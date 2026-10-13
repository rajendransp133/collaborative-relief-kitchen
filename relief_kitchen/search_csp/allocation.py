"""Task and resource allocation for the relief kitchen, formulated as a CSP.

Time is cut into slots of `slot_minutes` (10 min). Variables per order O:

    O.variant          which recipe (meal variant) O gets           domain: recipe ids
    O.b<k>.<stage>     who does batch k's stage, where, and when    domain: (agent, station, start slot)
    O.dispatch         which vehicle leaves when                    domain: (vehicle, departure slot)

Packing agent, station and start into one tuple-valued variable keeps every resource
rule a *binary* constraint ("two tasks on the same station must not overlap"). That fits forward
checking and AC-3 directly.

Each constraint is tagged with a category, and with the orders it concerns in `meta["orders"]`.
The diagnosis module uses these tags to blame ingredients / equipment / staff / time / transport.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..env.entities import Order, Recipe
from ..env.scenario import Scenario
from .csp import CSP, Constraint, FnConstraint, SolveResult, solve
from .locate import rank_stations
from .routing import Route, depot_routes
from .task_graph import TaskGraph, build_task_graph

UNLOAD_MINUTES = 10


def start_of(val) -> int:
    """Start slot of a task value (agent, station, start) or dispatch value (vehicle, departure)."""
    return val[-1]


# ---------------------------------------------------------------------------------------------
# constraint classes that need more than a one-line predicate
# ---------------------------------------------------------------------------------------------
class Precedence(Constraint):
    """`succ` starts no earlier than `pred` ends - one edge of the task DAG (never relaxed)."""

    def __init__(self, pred: str, succ: str, dur: int, order: str):
        super().__init__((pred, succ), "structure", f"{succ} after {pred}", orders={order}, kind="precedence")
        self.pred, self.succ, self.dur = pred, succ, dur

    def holds(self, a):
        if self.pred in a and self.succ in a:
            return start_of(a[self.succ]) >= start_of(a[self.pred]) + self.dur
        return True

    def revise(self, xi, xj, domains):
        # Bounds version of AC-3's revise: succ needs start >= (earliest pred start + dur), and pred
        # needs start <= (latest succ start - dur). Domains are built sorted by start time and
        # filtering keeps that order, so min/max are the first/last elements.
        dom = domains[xi]
        if not dom:
            return dom
        if xi == self.succ:
            lo = start_of(domains[self.pred][0]) + self.dur if domains[self.pred] else 1 << 30
            return [v for v in dom if start_of(v) >= lo]
        hi = start_of(domains[self.succ][-1]) - self.dur if domains[self.succ] else -1
        return [v for v in dom if start_of(v) <= hi]


class Disjoint(Constraint):
    """Two tasks that use the same resource (agent, station, access cell) must not overlap in time.

    `clash(v1, v2)` says whether the two chosen values compete for one resource."""

    def __init__(self, t1: str, t2: str, d1: int, d2: int, clash, category, kind, orders, description):
        super().__init__((t1, t2), category, description, orders=set(orders), kind=kind)
        self.t1, self.t2, self.d1, self.d2, self.clash = t1, t2, d1, d2, clash

    def holds(self, a):
        if self.t1 not in a or self.t2 not in a:
            return True
        v1, v2 = a[self.t1], a[self.t2]
        if not self.clash(v1, v2):
            return True
        s1, s2 = start_of(v1), start_of(v2)
        return s1 + self.d1 <= s2 or s2 + self.d2 <= s1

    def revise(self, xi, xj, domains):
        # While xj still has several values, every xi value keeps some support, so the
        # quadratic AC-3 scan can only prune once xj is down to one value.
        if len(domains[xj]) != 1:
            return domains[xi]
        return [v for v in domains[xi] if self.holds({xi: v, xj: domains[xj][0]})]


class StockConstraint(Constraint):
    """Global constraint: ingredients used by all chosen menus must fit in storage.

    Usage only grows as more menus are chosen, so the check is also valid on partial assignments."""

    def __init__(self, variant_vars: dict[str, Order], recipes: dict[str, Recipe], stock: dict[str, float]):
        super().__init__(tuple(variant_vars), "ingredients", "ingredient stock",
                         orders={o.id for o in variant_vars.values()}, kind="stock")
        self.variant_vars, self.recipes, self.stock = variant_vars, recipes, stock

    def holds(self, a):
        use: dict[str, float] = {}
        for var, order in self.variant_vars.items():
            if var in a:
                for ing, q in self.recipes[a[var]].per_meal.items():
                    use[ing] = use.get(ing, 0.0) + q * order.meals
        return all(kg <= self.stock.get(ing, 0.0) + 1e-6 for ing, kg in use.items())


# ---------------------------------------------------------------------------------------------
# model and decoded solution
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
    start: int  # minutes after the scenario start
    end: int


@dataclass
class Delivery:
    order: str
    destination: str
    vehicle: str
    depart: int
    arrive: int
    back: int  # vehicle is free again at the depot
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
    dur: dict[str, int]  # task id -> duration in slots
    routes: dict[str, Route | None]  # depot -> place over open roads (None = unreachable)
    relaxed_routes: dict[str, Route | None]  # same, ignoring closures (to time a hypothetical trip)

    @property
    def slot(self) -> int:
        return self.scenario.slot_minutes

    def travel(self, order: Order, vehicle_id: str) -> float:
        r = self.routes.get(order.destination) or self.relaxed_routes.get(order.destination)
        minutes = r.minutes if r else 10_000
        return minutes / self.scenario.vehicles[vehicle_id].speed

    def solve(self, hints: dict | None = None, node_limit: int = 3_000, keep=None) -> SolveResult:
        """Solve the CSP; `keep(constraint)` optionally drops constraints (used by diagnosis)."""
        csp = self.csp if keep is None else self.csp.subset(keep)
        return solve(csp, node_limit=node_limit, value_order=_value_order(self), var_key=_var_key, hints=hints)

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


def cook_stage(sc: Scenario) -> str:
    for s in sc.stages:
        if s.station_type in ("stove", "steamer") or s.skill == "cook":
            return s.name
    return sc.stages[-1].name


def effective_batch_size(sc: Scenario, variants: list[Recipe]) -> int:
    """Cap the batch size at the biggest *working* cooking station: if the large stoves fail, the
    order is split into smaller batches that the remaining stoves can take."""
    stage = next(s for s in sc.stages if s.name == cook_stage(sc))
    types = {r.stage_station(stage) for r in variants} or {stage.station_type}
    caps = [st.max_batch for t in types for st in sc.kitchen.stations_of(t, working_only=True)]
    return min(sc.batch_size, max(caps)) if caps else sc.batch_size


def build_model(sc: Scenario, orders: list[Order]) -> KitchenModel:
    S = sc.slot_minutes
    H = sc.horizon // S  # number of slots in the day
    stations = sorted(sc.kitchen.stations.values(), key=lambda x: x.id)
    csp = CSP()
    graphs: dict[str, TaskGraph] = {}
    dur: dict[str, int] = {}
    rank = {o.id: i for i, o in enumerate(sorted(orders, key=lambda o: (-o.priority, o.deadline)))}

    for o in orders:
        compat = compatible_variants(sc, o)
        g = build_task_graph(o, sc.stages, compat or list(sc.recipes.values()), effective_batch_size(sc, compat))
        graphs[o.id] = g
        # every recipe is in the domain; the dietary constraint (node consistency) removes the unsafe ones
        csp.add_variable(f"{o.id}.variant", list(sc.recipes), priority=(rank[o.id],))
        topo = {n: i for i, n in enumerate(g.topological_order())}
        for node in g.tasks():
            d = max(1, math.ceil(node.minutes / S))
            dur[node.id] = d
            # start-major order: domains stay sorted by start time (Precedence.revise relies on it)
            domain = [(ag, st.id, s) for s in range(0, H - d + 1) for st in stations
                      if st.type in node.station_types for ag in sorted(sc.agents)]
            csp.add_variable(node.id, domain, priority=(rank[o.id], topo[node.id]))
        csp.add_variable(g.dispatch, [(v, s) for s in range(H) for v in sorted(sc.vehicles)],
                         priority=(rank[o.id], len(topo)))
        dur[g.dispatch] = 0

    model = KitchenModel(sc, orders, csp, graphs, dur, depot_routes(sc.roads),
                         depot_routes(sc.roads, include_closed=True))
    _add_order_constraints(model)
    _add_pair_constraints(model)
    csp.add(StockConstraint({f"{o.id}.variant": o for o in orders}, sc.recipes, sc.stock()))
    return model


def _add_order_constraints(m: KitchenModel) -> None:
    """Constraints that involve a single order: unary rules plus links between its own variables."""
    sc, csp, S = m.scenario, m.csp, m.slot
    stations = sc.kitchen.stations
    first_stage, cook = sc.stages[0].name, cook_stage(sc)
    for o in m.orders:
        var, g = f"{o.id}.variant", m.graphs[o.id]
        tag = dict(orders={o.id})

        csp.add(FnConstraint((var,), lambda r, _o=o: sc.recipes[r].satisfies(_o.diet), "dietary",
                             f"meal must satisfy diet [{', '.join(sorted(o.diet)) or 'none'}]", kind="dietary", **tag))

        for node in g.tasks():
            t, d = node.id, m.dur[node.id]
            stage = next(s for s in sc.stages if s.name == node.stage)
            csp.add(FnConstraint((t,), lambda v, _s=node.skill: _s in sc.agents[v[0]].skills, "staff",
                                 f"{t} needs skill '{node.skill}'", kind="skill", **tag))
            csp.add(FnConstraint((t,), lambda v, _d=d: sc.agents[v[0]].available(v[2] * S, (v[2] + _d) * S),
                                 "staff", f"{t} inside the agent's shift", kind="shift", **tag))
            csp.add(FnConstraint((t,), lambda v: not stations[v[1]].failed, "equipment",
                                 f"{t} needs a working station", kind="working", **tag))
            csp.add(FnConstraint((t,), lambda v, _m=node.meals: stations[v[1]].max_batch >= _m, "equipment",
                                 f"{t} needs capacity for {node.meals} meals", kind="capacity", **tag))
            if not node.preds:
                csp.add(FnConstraint((t,), lambda v, _r=o.release: v[2] * S >= _r, "structure",
                                     f"{t} not before the order arrives", kind="release", **tag))
            if any(r.stage_station(stage) != stage.station_type for r in sc.recipes.values()):
                # some recipes need a different station for this stage (idli is steamed, not boiled)
                csp.add(FnConstraint((t, var), lambda v, r, _st=stage: stations[v[1]].type == sc.recipes[r].stage_station(_st),
                                     "equipment", f"{t} station must suit the recipe", kind="station-type", **tag))
            if node.stage == first_stage:
                # the fetch goes to a shelf that actually stocks the recipe's main ingredient
                csp.add(FnConstraint((t, var), lambda v, r: stations[v[1]].stock.get(sc.recipes[r].main_ingredient, 0) > 0,
                                     "ingredients", f"{t} shelf must stock the main ingredient", kind="located", **tag))
            if node.stage == cook:
                # food safety: cooked food is served within max_hold minutes
                csp.add(FnConstraint((t, g.dispatch), lambda c, v, _o=o, _d=d:
                                     v[1] * S + m.travel(_o, v[0]) - (c[2] + _d) * S <= sc.max_hold, "safety",
                                     f"{t} served within {sc.max_hold} min of cooking", kind="holding", **tag))
            for p in node.preds:
                csp.add(Precedence(p, t, m.dur[p], o.id))

        disp = g.dispatch
        for p in g.nodes[disp].preds:
            csp.add(Precedence(p, disp, m.dur[p], o.id))
        dest = sc.roads.places[o.destination].label
        csp.add(FnConstraint((disp,), lambda v, _o=o: m.routes.get(_o.destination) is not None, "transport",
                             f"open road to {dest}", kind="route", **tag))
        csp.add(FnConstraint((disp,), lambda v, _o=o: sc.vehicles[v[0]].capacity >= _o.meals, "transport",
                             f"vehicle carries {o.meals} meals", kind="vehicle-capacity", **tag))
        csp.add(FnConstraint((disp,), lambda v: v[1] * S >= sc.vehicles[v[0]].available_from, "transport",
                             "vehicle is available", kind="vehicle-available", **tag))
        csp.add(FnConstraint((disp,), lambda v, _o=o: v[1] * S + m.travel(_o, v[0]) <= _o.deadline, "time",
                             f"arrive at {dest} by {sc.clock(o.deadline)}", kind="deadline", **tag))
        csp.add(FnConstraint((disp,), lambda v, _o=o: v[1] * S + 2 * m.travel(_o, v[0]) <= sc.horizon + 120,
                             "structure", "trip ends within the day", kind="horizon", **tag))


def _add_pair_constraints(m: KitchenModel) -> None:
    """Shared-resource constraints between every pair of tasks / deliveries."""
    sc, csp = m.scenario, m.csp
    shared = sc.kitchen.shared_access_pairs()
    tasks = [(o, n) for o in m.orders for n in m.graphs[o.id].tasks()]
    for i, (o1, n1) in enumerate(tasks):
        for o2, n2 in tasks[i + 1:]:
            d1, d2, orders = m.dur[n1.id], m.dur[n2.id], {o1.id, o2.id}
            csp.add(Disjoint(n1.id, n2.id, d1, d2, lambda a, b: a[0] == b[0], "staff", "agent-booking", orders,
                             "an agent does one task at a time"))
            if n1.station_types & n2.station_types:
                csp.add(Disjoint(n1.id, n2.id, d1, d2, lambda a, b: a[1] == b[1], "equipment", "occupancy", orders,
                                 "one batch per station at a time"))
            if shared:
                csp.add(Disjoint(n1.id, n2.id, d1, d2, lambda a, b: frozenset((a[1], b[1])) in shared, "collision",
                                 "workspace", orders, "stations sharing an access cell are not used together"))
    for i, o1 in enumerate(m.orders):
        for o2 in m.orders[i + 1:]:
            v1, v2 = f"{o1.id}.dispatch", f"{o2.id}.dispatch"
            csp.add(FnConstraint((v1, v2), lambda a, b, _o1=o1, _o2=o2: a[0] != b[0] or _trips_apart(m, _o1, a, _o2, b),
                                 "transport", "a vehicle makes one trip at a time",
                                 orders={o1.id, o2.id}, kind="vehicle-booking"))
            if o1.priority != o2.priority:
                hi, lo = (o1, o2) if o1.priority > o2.priority else (o2, o1)
                csp.add(FnConstraint((f"{hi.id}.dispatch", f"{lo.id}.dispatch"),
                                     lambda a, b: a[0] != b[0] or a[1] <= b[1], "priority",
                                     f"{hi.id} leaves before {lo.id} on a shared vehicle",
                                     orders={hi.id, lo.id}, kind="priority"))


def _trips_apart(m: KitchenModel, o1: Order, a, o2: Order, b) -> bool:
    S = m.slot
    s1, s2 = a[1] * S, b[1] * S
    e1 = s1 + 2 * m.travel(o1, a[0]) + UNLOAD_MINUTES
    e2 = s2 + 2 * m.travel(o2, b[0]) + UNLOAD_MINUTES
    return e1 <= s2 or e2 <= s1


# ---------------------------------------------------------------------------------------------
# search heuristics
# ---------------------------------------------------------------------------------------------
def _var_key(var: str) -> tuple:
    """Phase before MRV: choose menus, then kitchen tasks, then vehicles (a list-scheduling order)."""
    if var.endswith(".variant"):
        return (0,)
    if var.endswith(".dispatch"):
        return (2,)
    return (1,)


def _value_order(m: KitchenModel):
    """Value ordering in place of LCV (LCV over hundreds of (agent, station, slot) values is slow).

    Tasks: earliest start, then the station nearest the work area (BFS ranking from `locate`), then
    the least-busy agent. Vehicles: earliest departure, then the smallest vehicle that fits."""
    sc = m.scenario
    homes = [a.home for a in sc.agents.values()]
    centre = homes[len(homes) // 2]
    pref = {st.id: i for stype in {s.type for s in sc.kitchen.stations.values()}
            for i, (st, _d) in enumerate(rank_stations(sc.kitchen, centre, stype))}

    def order(var, values, assign):
        if var.endswith(".variant"):
            return values
        if var.endswith(".dispatch"):
            meals = next(o.meals for o in m.orders if var == f"{o.id}.dispatch")
            spare = lambda v: sc.vehicles[v[0]].capacity - meals  # noqa: E731
            return sorted(values, key=lambda v: (v[1], spare(v) if spare(v) >= 0 else 10_000, v[0]))
        busy: dict[str, int] = {}
        for k, v in assign.items():
            if not k.endswith((".variant", ".dispatch")):
                busy[v[0]] = busy.get(v[0], 0) + m.dur[k]
        return sorted(values, key=lambda v: (v[2], pref.get(v[1], 99), busy.get(v[0], 0), v[0]))

    return order
