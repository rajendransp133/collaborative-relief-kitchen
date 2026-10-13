"""Task and resource allocation for the relief kitchen, formulated as a CSP.

Variables (time is discretised into slots of `slot_minutes`):

    <order>.variant            which recipe (meal variant) the order gets
    <order>.b<k>.<stage>       (agent, station, start slot) for each batch task
    <order>.dispatch           (vehicle, departure slot)

Every constraint carries a category (ingredients, equipment, staff, time, transport, dietary,
safety, collision, priority), a `kind`, and the orders it concerns, so the diagnosis module can
explain which of them make an order infeasible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..env.entities import Order, Recipe
from ..env.scenario import Scenario
from .csp import CSP, Constraint, FnConstraint, SolveResult, solve
from .locate import rank_stations
from .routing import Route, depot_routes
from .task_graph import TaskGraph, TaskNode, build_task_graph

UNLOAD_MINUTES = 10


# ---------------------------------------------------------------------------------------------
# constraint classes that need more than a predicate
# ---------------------------------------------------------------------------------------------
def start_of(val) -> int:
    return val[-1]


class Precedence(Constraint):
    """succ starts no earlier than pred ends (structural: part of the task DAG)."""

    propagate_in_search = True  # cheap bounds revision, kept consistent at every node

    def __init__(self, pred: str, succ: str, dur: int, order: str, kind: str = "precedence"):
        super().__init__((pred, succ), "structure", f"{order}:{kind}", f"{succ} after {pred}",
                         relaxable=False, orders={order}, kind=kind)
        self.pred, self.succ, self.dur = pred, succ, dur

    def holds(self, a):
        if self.pred in a and self.succ in a:
            return start_of(a[self.succ]) >= start_of(a[self.pred]) + self.dur
        return True

    def revise(self, xi, xj, domains):
        # domains are sorted by start time (built that way, pruning keeps the order)
        if xi == self.succ:
            lo = start_of(domains[self.pred][0]) + self.dur if domains[self.pred] else 1 << 30
            dom = domains[xi]
            return dom if not dom or start_of(dom[0]) >= lo else [v for v in dom if start_of(v) >= lo]
        hi = start_of(domains[self.succ][-1]) - self.dur if domains[self.succ] else -1
        dom = domains[xi]
        return dom if not dom or start_of(dom[-1]) <= hi else [v for v in dom if start_of(v) <= hi]


class Disjoint(Constraint):
    """Two tasks may not overlap in time when they share a resource (agent, station or access cell).

    `clash(v1, v2)` says whether the two values compete for the same resource."""

    def __init__(self, t1: str, t2: str, d1: int, d2: int, clash, category, kind, orders, description, gap=0):
        super().__init__((t1, t2), category, kind, description, orders=set(orders), kind=kind)
        self.t1, self.t2, self.d1, self.d2, self.clash, self.gap = t1, t2, d1, d2, clash, gap

    def holds(self, a):
        if self.t1 not in a or self.t2 not in a:
            return True
        v1, v2 = a[self.t1], a[self.t2]
        if not self.clash(v1, v2):
            return True
        s1, s2 = start_of(v1), start_of(v2)
        return s1 + self.d1 + self.gap <= s2 or s2 + self.d2 + self.gap <= s1

    def revise(self, xi, xj, domains):
        # a resource clash only removes support once the other task is fixed; until then every
        # value keeps a support, so skip the quadratic scan
        if len(domains[xj]) != 1:
            return domains[xi]
        a = {xj: domains[xj][0]}
        out = []
        for v in domains[xi]:
            a[xi] = v
            if self.holds(a):
                out.append(v)
        return out


class StockConstraint(Constraint):
    """Global: ingredient use of all chosen variants must fit in storage (checkable on partials)."""

    def __init__(self, variant_vars: dict[str, Order], recipes: dict[str, Recipe], stock: dict[str, float]):
        super().__init__(tuple(variant_vars), "ingredients", "stock", "ingredient stock",
                         orders={o.id for o in variant_vars.values()}, kind="stock")
        self.variant_vars, self.recipes, self.stock = variant_vars, recipes, stock

    def usage(self, a) -> dict[str, float]:
        use: dict[str, float] = {}
        for var, order in self.variant_vars.items():
            if var in a:
                for ing, q in self.recipes[a[var]].per_meal.items():
                    use[ing] = use.get(ing, 0.0) + q * order.meals
        return use

    def holds(self, a):
        return all(kg <= self.stock.get(ing, 0.0) + 1e-6 for ing, kg in self.usage(a).items())


# ---------------------------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------------------------
@dataclass
class ScheduledTask:
    id: str
    order: str
    batch: int
    stage: str
    meals: int
    agent: str
    station: str
    start: int  # minutes
    end: int


@dataclass
class Delivery:
    order: str
    destination: str
    vehicle: str
    depart: int
    arrive: int
    back: int
    route: Route | None
    meals: int
    recipe: str


@dataclass
class Allocation:
    variants: dict[str, str]
    tasks: list[ScheduledTask]
    deliveries: list[Delivery]
    result: SolveResult


@dataclass
class KitchenModel:
    scenario: Scenario
    orders: list[Order]
    csp: CSP
    graphs: dict[str, TaskGraph]
    dur: dict[str, int]
    routes: dict[str, Route | None]
    relaxed_routes: dict[str, Route | None]
    variants: dict[str, list[Recipe]] = field(default_factory=dict)

    @property
    def slot(self) -> int:
        return self.scenario.slot_minutes

    def travel(self, order: Order, vehicle_id: str) -> float:
        r = self.routes.get(order.destination) or self.relaxed_routes.get(order.destination)
        minutes = r.minutes if r else 10_000
        return minutes / self.scenario.vehicles[vehicle_id].speed

    def solve(self, hints: dict | None = None, node_limit: int = 6_000) -> SolveResult:
        return solve_model(self, hints=hints, node_limit=node_limit)

    def decode(self, result: SolveResult) -> Allocation:
        S, a = self.slot, result.solution
        variants = {o.id: a[f"{o.id}.variant"] for o in self.orders}
        tasks = []
        for o in self.orders:
            for node in self.graphs[o.id].tasks():
                agent, station, s = a[node.id]
                tasks.append(ScheduledTask(node.id, o.id, node.batch, node.stage, node.meals, agent, station,
                                           s * S, (s + self.dur[node.id]) * S))
        deliveries = []
        for o in self.orders:
            v, d = a[f"{o.id}.dispatch"]
            travel = self.travel(o, v)
            deliveries.append(Delivery(o.id, o.destination, v, d * S, d * S + travel,
                                       d * S + 2 * travel + UNLOAD_MINUTES, self.routes.get(o.destination),
                                       o.meals, variants[o.id]))
        tasks.sort(key=lambda t: (t.start, t.order, t.batch))
        return Allocation(variants, tasks, deliveries, result)


def compatible_variants(sc: Scenario, order: Order) -> list[Recipe]:
    return [r for r in sc.recipes.values() if r.satisfies(order.diet)]


def effective_batch_size(sc: Scenario, variants: list[Recipe]) -> int:
    """Batch size capped by the biggest working cooking station the order could use, so that when
    the large stoves fail the work is split into smaller batches for the remaining ones."""
    stage = next((s for s in sc.stages if s.name == _cook_stage(sc)), None)
    if stage is None:
        return sc.batch_size
    types = {r.stage_station(stage) for r in variants} or {stage.station_type}
    caps = [st.max_batch for t in types for st in sc.kitchen.stations_of(t, working_only=True)]
    return min(sc.batch_size, max(caps)) if caps else sc.batch_size


def build_model(sc: Scenario, orders: list[Order]) -> KitchenModel:
    S = sc.slot_minutes
    H = sc.horizon // S
    routes = depot_routes(sc.roads)
    relaxed = depot_routes(sc.roads, include_closed=True)
    csp = CSP()
    graphs: dict[str, TaskGraph] = {}
    dur: dict[str, int] = {}
    variants: dict[str, list[Recipe]] = {}
    grid = sc.kitchen
    stations = grid.stations
    rank = {o.id: i for i, o in enumerate(sorted(orders, key=lambda o: (-o.priority, o.deadline)))}

    for o in orders:
        compat = compatible_variants(sc, o)
        variants[o.id] = compat
        # variants that break the diet are still in the domain; the dietary constraint removes them
        g = build_task_graph(o, sc.stages, compat or list(sc.recipes.values()), effective_batch_size(sc, compat))
        graphs[o.id] = g
        csp.add_variable(f"{o.id}.variant", list(sc.recipes), priority=(rank[o.id],))
        topo = {n: i for i, n in enumerate(g.topological_order())}
        for node in g.tasks():
            d = max(1, math.ceil(node.minutes / S))
            dur[node.id] = d
            domain = [(ag, st.id, s) for s in range(0, H - d + 1)
                      for st in sorted(stations.values(), key=lambda x: x.id) if st.type in node.station_types
                      for ag in sorted(sc.agents)]
            csp.add_variable(node.id, domain, priority=(rank[o.id], topo[node.id]))
        csp.add_variable(g.dispatch, [(v, s) for s in range(H) for v in sorted(sc.vehicles)],
                         priority=(rank[o.id], len(topo)))
        dur[g.dispatch] = 0

    model = KitchenModel(sc, orders, csp, graphs, dur, routes, relaxed, variants)
    _add_order_constraints(model)
    _add_pair_constraints(model)
    csp.add(StockConstraint({f"{o.id}.variant": o for o in orders}, sc.recipes, sc.stock()))
    return model


def _add_order_constraints(m: KitchenModel) -> None:
    sc, csp, S = m.scenario, m.csp, m.slot
    stations = sc.kitchen.stations
    clock = sc.clock
    for o in m.orders:
        oid, var = o.id, f"{o.id}.variant"
        g = m.graphs[oid]
        meta = dict(orders={oid})

        # dietary requirements (hard)
        diet = ", ".join(sorted(o.diet)) or "none"
        csp.add(FnConstraint((var,), lambda r, _d=frozenset(o.diet): sc.recipes[r].satisfies(set(_d)),
                             "dietary", f"{oid}:dietary", f"meal must satisfy diet [{diet}]", kind="dietary", **meta))

        for node in g.tasks():
            t, d = node.id, m.dur[node.id]
            csp.add(FnConstraint((t,), lambda v, _s=node.skill: _s in sc.agents[v[0]].skills, "staff",
                                 f"{oid}:skill", f"{t} needs an agent with skill '{node.skill}'", kind="skill",
                                 skill=node.skill, **meta))
            csp.add(FnConstraint((t,), lambda v, _d=d: sc.agents[v[0]].available(v[2] * S, (v[2] + _d) * S), "staff",
                                 f"{oid}:shift", f"{t} must fall inside the agent's shift", kind="shift",
                                 skill=node.skill, **meta))
            csp.add(FnConstraint((t,), lambda v: not stations[v[1]].failed, "equipment", f"{oid}:working",
                                 f"{t} needs a working {'/'.join(sorted(node.station_types))}", kind="working",
                                 station_types=node.station_types, **meta))
            csp.add(FnConstraint((t,), lambda v, _m=node.meals: stations[v[1]].max_batch >= _m, "equipment",
                                 f"{oid}:capacity", f"{t} ({node.meals} meals) needs enough station capacity",
                                 kind="capacity", meals=node.meals, station_types=node.station_types, **meta))
            if not node.preds:
                csp.add(FnConstraint((t,), lambda v, _r=o.release: v[2] * S >= _r, "structure", f"{oid}:release",
                                     f"{t} cannot start before the order arrives at {clock(o.release)}",
                                     relaxable=False, kind="release", **meta))
            # recipe-specific station type (e.g. idli needs a steamer)
            stage = _stage(sc, node)
            if any(r.stage_station(stage) != stage.station_type for r in sc.recipes.values()):
                csp.add(FnConstraint((t, var), lambda v, r, _n=node: stations[v[1]].type == sc.recipes[r].stage_station(
                    _stage(sc, _n)), "equipment", f"{oid}:station-type", f"{t} station must suit the recipe",
                    kind="station-type", **meta))
            if node.stage == sc.stages[0].name:
                # the first stage picks up the main ingredient: shelf must hold it (ingredient search)
                csp.add(FnConstraint((t, var), lambda v, r: stations[v[1]].type != "storage"
                                     or stations[v[1]].stock.get(sc.recipes[r].main_ingredient, 0) > 0,
                                     "ingredients", f"{oid}:located", f"{t} shelf must stock the main ingredient",
                                     kind="located", **meta))
            for p in node.preds:
                csp.add(Precedence(p, t, m.dur[p], oid))

        # symmetry breaking: equal-sized batches are interchangeable, so batch k starts each stage
        # no later than batch k+1 (prunes k! equivalent schedules when proving infeasibility)
        by_stage: dict[str, list[TaskNode]] = {}
        for node in g.tasks():
            by_stage.setdefault(node.stage, []).append(node)
        for nodes in by_stage.values():
            nodes.sort(key=lambda n: n.batch)
            for n1, n2 in zip(nodes, nodes[1:]):
                if n1.meals == n2.meals:
                    csp.add(Precedence(n1.id, n2.id, 0, oid, kind="symmetry"))

        disp = g.dispatch
        for p in g.nodes[disp].preds:
            csp.add(Precedence(p, disp, m.dur[p], oid))
        dest = sc.roads.places[o.destination].label
        csp.add(FnConstraint((disp,), lambda v, _o=o: m.routes.get(_o.destination) is not None, "transport",
                             f"{oid}:route", f"an open road route to {dest}", kind="route", **meta))
        csp.add(FnConstraint((disp,), lambda v, _o=o: sc.vehicles[v[0]].capacity >= _o.meals, "transport",
                             f"{oid}:vehicle-capacity", f"vehicle must carry {o.meals} meals",
                             kind="vehicle-capacity", **meta))
        csp.add(FnConstraint((disp,), lambda v: v[1] * S >= sc.vehicles[v[0]].available_from, "transport",
                             f"{oid}:vehicle-available", "vehicle must be available", kind="vehicle-available", **meta))
        csp.add(FnConstraint((disp,), lambda v, _o=o: v[1] * S + m.travel(_o, v[0]) <= _o.deadline, "time",
                             f"{oid}:deadline", f"arrive at {dest} by {clock(o.deadline)}", kind="deadline", **meta))
        csp.add(FnConstraint((disp,), lambda v, _o=o: v[1] * S + 2 * m.travel(_o, v[0]) <= sc.horizon + 120,
                             "structure", f"{oid}:horizon", "trip must end in the planning day", relaxable=False,
                             kind="horizon", **meta))
        # food safety: cooked food may wait at most max_hold minutes before it is served
        cook_stage = _cook_stage(sc)
        for node in g.tasks():
            if node.stage == cook_stage:
                csp.add(FnConstraint((node.id, disp), lambda c, v, _o=o, _d=m.dur[node.id]:
                                     v[1] * S + m.travel(_o, v[0]) - (c[2] + _d) * S <= sc.max_hold, "safety",
                                     f"{oid}:holding", f"{node.id} served within {sc.max_hold} min of cooking",
                                     kind="holding", **meta))


def _stage(sc: Scenario, node: TaskNode):
    return next(s for s in sc.stages if s.name == node.stage)


def _cook_stage(sc: Scenario) -> str:
    for s in sc.stages:
        if s.station_type in ("stove", "steamer") or s.skill == "cook":
            return s.name
    return sc.stages[-1].name


def _add_pair_constraints(m: KitchenModel) -> None:
    sc, csp = m.scenario, m.csp
    shared = sc.kitchen.shared_access_pairs()
    tasks = [(o, n) for o in m.orders for n in m.graphs[o.id].tasks()]
    cook_like = {"prep", "stove", "steamer"}
    clean = math.ceil(sc.clean_minutes / sc.slot_minutes)
    for i, (o1, n1) in enumerate(tasks):
        for o2, n2 in tasks[i + 1:]:
            d1, d2 = m.dur[n1.id], m.dur[n2.id]
            orders = {o1.id, o2.id}
            csp.add(Disjoint(n1.id, n2.id, d1, d2, lambda a, b: a[0] == b[0], "staff", "agent-booking", orders,
                             "an agent does one task at a time"))
            if n1.station_types & n2.station_types:
                csp.add(Disjoint(n1.id, n2.id, d1, d2, lambda a, b: a[1] == b[1], "equipment", "occupancy", orders,
                                 "one batch per station at a time"))
            if shared:
                csp.add(Disjoint(n1.id, n2.id, d1, d2, lambda a, b: frozenset((a[1], b[1])) in shared, "collision",
                                 "workspace", orders, "stations sharing an access cell are not used together"))
            # allergen separation: an allergen-free batch never follows an allergenic one on the same
            # station without a cleaning gap
            if o1.id != o2.id and (n1.station_types & n2.station_types & cook_like):
                for free, other, nf, no in ((o1, o2, n1, n2), (o2, o1, n2, n1)):
                    banned = {d[: -len("_free")] for d in free.diet if d.endswith("_free")}
                    risky = [r.id for r in m.variants.get(other.id, []) if r.allergens & banned]
                    if not banned or not risky:
                        continue
                    csp.add(_AllergenGap(nf.id, no.id, m.dur[nf.id], m.dur[no.id], f"{other.id}.variant",
                                         banned, sc, clean, {free.id, other.id}))
    # vehicles: one trip at a time, and a higher-priority order leaves first when sharing a vehicle
    for i, o1 in enumerate(m.orders):
        for o2 in m.orders[i + 1:]:
            v1, v2 = f"{o1.id}.dispatch", f"{o2.id}.dispatch"
            csp.add(FnConstraint((v1, v2), lambda a, b, _o1=o1, _o2=o2: a[0] != b[0] or _trips_apart(m, _o1, a, _o2, b),
                                 "transport", "vehicle-booking", "a vehicle makes one trip at a time",
                                 orders={o1.id, o2.id}, kind="vehicle-booking"))
            if o1.priority != o2.priority:
                hi, lo = (o1, o2) if o1.priority > o2.priority else (o2, o1)
                csp.add(FnConstraint((f"{hi.id}.dispatch", f"{lo.id}.dispatch"),
                                     lambda a, b: a[0] != b[0] or a[1] <= b[1], "priority", "priority",
                                     f"{hi.id} (priority {hi.priority}) leaves before {lo.id} on a shared vehicle",
                                     orders={hi.id, lo.id}, kind="priority"))


def _trips_apart(m: KitchenModel, o1: Order, a, o2: Order, b) -> bool:
    S = m.slot
    s1, s2 = a[1] * S, b[1] * S
    e1 = s1 + 2 * m.travel(o1, a[0]) + UNLOAD_MINUTES
    e2 = s2 + 2 * m.travel(o2, b[0]) + UNLOAD_MINUTES
    return e1 <= s2 or e2 <= s1


class _AllergenGap(Constraint):
    def __init__(self, free_task, other_task, d_free, d_other, other_variant, banned, sc, clean, orders):
        super().__init__((free_task, other_task, other_variant), "safety", "allergen",
                         f"{free_task} is allergen-free ({', '.join(sorted(banned))}); station must be cleaned after "
                         f"{other_task}", orders=orders, kind="allergen")
        self.f, self.o, self.df, self.do, self.var = free_task, other_task, d_free, d_other, other_variant
        self.banned, self.sc, self.clean = banned, sc, clean

    def holds(self, a):
        if self.f not in a or self.o not in a or self.var not in a:
            return True
        vf, vo = a[self.f], a[self.o]
        if vf[1] != vo[1] or not (self.sc.recipes[a[self.var]].allergens & self.banned):
            return True
        # the allergenic batch must come after, or finish `clean` slots before the allergen-free one
        return vf[2] + self.df <= vo[2] or vo[2] + self.do + self.clean <= vf[2]


# ---------------------------------------------------------------------------------------------
# solving
# ---------------------------------------------------------------------------------------------
def _value_order_factory(m: KitchenModel, dispatch_late: bool = True):
    sc = m.scenario
    grid = sc.kitchen
    # station preference: nearest working station to the agents' common area (ingredient/equipment
    # search with BFS), so batches go to nearby shelves and stoves first
    homes = [a.home for a in sc.agents.values()]
    centre = homes[len(homes) // 2] if homes else (1, 1)
    pref: dict[str, int] = {}
    for stype in {s.type for s in grid.stations.values()}:
        for i, (st, _d) in enumerate(rank_stations(grid, centre, stype)):
            pref[st.id] = i

    def order(var, values, assign):
        if var.endswith(".variant"):
            return values
        if var.endswith(".dispatch"):
            o = next(o for o in m.orders if o.id == var.split(".")[0])
            # vehicles are fixed before the kitchen tasks: try the latest departure that still meets
            # the deadline first (leaves the kitchen the most room, so little backtracking), smallest
            # fitting vehicle first; the left-shift pass afterwards moves departures earlier
            fit = (lambda v: sc.vehicles[v[0]].capacity - o.meals if sc.vehicles[v[0]].capacity >= o.meals
                   else 10_000)
            if dispatch_late:
                return sorted(values, key=lambda v: (-v[1], fit(v), v[0]))
            return sorted(values, key=lambda v: (v[1], fit(v), v[0]))
        busy = {}
        for k, v in assign.items():
            if not k.endswith((".variant", ".dispatch")):
                busy[v[0]] = busy.get(v[0], 0) + m.dur[k]
        return sorted(values, key=lambda v: (v[2], pref.get(v[1], 99), busy.get(v[0], 0), v[0]))

    return order


class EnergyCheck:
    """Energetic reasoning for cumulative resources (a global necessary condition).

    For each resource pool - the agents able to do a skill, the stations of a type - and each time
    window [t1, t2) built from the tasks' earliest starts and latest ends, the work that *must* fall
    inside the window cannot exceed pool size x window length. The check runs at the root and after
    each menu/vehicle decision, when deadlines have just been propagated back through the DAG; it
    is what lets the solver prove "the cooks cannot finish in time" without enumerating schedules.
    The constraint behind it is still the pairwise one (agent-booking / occupancy), so diagnosis
    reports those kinds.
    """

    def __init__(self, m: KitchenModel, constraints=None):
        self.m = m
        self.tasks = [n for o in m.orders for n in m.graphs[o.id].tasks()]
        self.dur = m.dur
        # only orders whose pairwise resource constraints are enforced take part (diagnosis relaxes
        # them per order); None means every order
        self.enforced: dict[str, set[str]] | None = None
        if constraints is not None:
            self.enforced = {"agent-booking": set(), "occupancy": set()}
            for c in constraints:
                k = c.meta.get("kind")
                if k in self.enforced:
                    self.enforced[k] |= c.meta["orders"]
        self.calls = 0

    def _member(self, kind: str, order: str) -> bool:
        return self.enforced is None or order in self.enforced[kind]

    def pools(self, domains):
        by_skill: dict[str, list[str]] = {}
        by_type: dict[str, list[str]] = {}
        for n in self.tasks:
            if n.id not in domains:
                continue
            if self._member("agent-booking", n.order):
                by_skill.setdefault(n.skill, []).append(n.id)
            if self._member("occupancy", n.order):
                for t in n.station_types:
                    by_type.setdefault(t, []).append(n.id)
        out = []
        for ids in by_skill.values():
            out.append((ids, len({v[0] for i in ids for v in domains[i]})))
        for ids in by_type.values():
            out.append((ids, len({v[1] for i in ids for v in domains[i]})))
        return out

    def __call__(self, var, assign, domains) -> bool:
        if var is not None and not var.endswith((".variant", ".dispatch")):
            return True
        self.calls += 1
        bounds: dict[str, tuple[int, int]] = {}
        for ids, cap in self.pools(domains):
            if cap == 0:
                return False
            est, lct, d = {}, {}, {}
            for i in ids:
                if i not in bounds:
                    dom = domains[i]
                    if not dom:
                        return False
                    # domains are generated in start order and pruning keeps that order
                    bounds[i] = (dom[0][2], dom[-1][2])
                d[i] = self.dur[i]
                est[i] = bounds[i][0]
                lct[i] = bounds[i][1] + d[i]
            starts = sorted(set(est.values()))
            ends = sorted(set(lct.values()))
            for t1 in starts:
                for t2 in ends:
                    if t2 <= t1:
                        continue
                    need = 0
                    for i in ids:
                        # minimum overlap of task i with [t1, t2) whether shifted left or right
                        ov = min(d[i], t2 - t1, est[i] + d[i] - t1, t2 - (lct[i] - d[i]))
                        if ov > 0:
                            need += ov
                    if need > cap * (t2 - t1):
                        return False
        return True


def _var_key(var: str) -> tuple:
    # decide the menu first, then vehicles and departures, then the kitchen tasks (MRV with degree
    # tie-break chooses inside each phase); transport conflicts are found before task search
    if var.endswith(".variant"):
        return (0,)
    if var.endswith(".dispatch"):
        return (1,)
    return (2,)


def _var_key_tasks_first(var: str) -> tuple:
    # list-scheduling order used by the improvement pass: menu, kitchen tasks, then vehicles
    if var.endswith(".variant"):
        return (0,)
    if var.endswith(".dispatch"):
        return (2,)
    return (1,)


def solve_model(m: KitchenModel, hints: dict | None = None, node_limit: int = 6_000,
                constraints=None, left_shift: bool = True) -> SolveResult:
    csp = m.csp if constraints is None else m.csp.subset(constraints)
    res = solve(csp, node_limit=node_limit, value_order=_value_order_factory(m), hints=hints,
                var_key=_var_key, lcv=False,
                node_check=EnergyCheck(m, None if constraints is None else csp.constraints))
    if res.ok and left_shift:
        res = _left_shift(m, csp, res)
    return res


def _left_shift(m: KitchenModel, csp: CSP, res: SolveResult) -> SolveResult:
    """Improve a solution without giving up feasibility (the CSP itself has no objective).

    1. With menus fixed and every departure capped at its current time, re-solve as a list
       schedule (tasks earliest-first, then vehicles); bounded search, skipped if it fails.
    2. With menus and kitchen tasks fixed, move each departure as early as the schedule allows.
    """
    best = res
    capped = csp.subset(lambda c: True)
    for v, val in res.solution.items():
        if v.endswith(".variant"):
            capped.domains[v] = [val]
        elif v.endswith(".dispatch"):
            capped.domains[v] = [x for x in capped.domains[v] if x[1] <= val[1]]
    tight = solve(capped, node_limit=1_500, value_order=_value_order_factory(m, dispatch_late=False),
                  var_key=_var_key_tasks_first, lcv=False, node_check=EnergyCheck(m, csp.constraints))
    if tight.ok:
        best = tight
    fixed = csp.subset(lambda c: True)
    for v, val in best.solution.items():
        if not v.endswith(".dispatch"):
            fixed.domains[v] = [val]
    again = solve(fixed, node_limit=2_000, value_order=_value_order_factory(m, dispatch_late=False),
                  var_key=_var_key, lcv=False)
    if again.ok:
        best = again
    if best is not res:
        best.stats.nodes += res.stats.nodes
        best.stats.backtracks += res.stats.backtracks
        best.stats.seconds += res.stats.seconds
    return best
