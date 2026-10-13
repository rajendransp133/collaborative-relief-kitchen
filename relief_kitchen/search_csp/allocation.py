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

Style: records (`KitchenModel`, `Allocation`, ...) plus functions. Each constraint is a
`Constraint` record built by a small factory (`precedence`, `disjoint`, `stock_limit`) that closes
over the data it needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..env.entities import Order, Recipe, agent_available, recipe_satisfies, recipe_station
from ..env.kitchen_grid import HANDLING_MINUTES, WALK_SECONDS, shared_access_pairs, stations_of
from ..env.scenario import Scenario, clock, total_stock
from .csp import CSP, Constraint, SolveResult, constraint, solve, subset
from .astar import bfs_distances
from .locate import rank_stations
from .routing import Route, depot_routes
from .task_graph import TaskGraph, build_task_graph, graph_tasks, topological_order

UNLOAD_MINUTES = 10


def start_of(val) -> int:
    """Start slot of a task value (agent, station, start) or dispatch value (vehicle, departure)."""
    return val[-1]


# ---------------------------------------------------------------------------------------------
# constraint factories (each returns a Constraint record whose behaviour is a closure)
# ---------------------------------------------------------------------------------------------
def precedence(pred: str, succ: str, dur: int, order: str) -> Constraint:
    """`succ` starts no earlier than `pred` ends - one edge of the task DAG (never relaxed)."""

    def revise(xi, xj, domains):
        # Bounds version of AC-3's revise: succ needs start >= (earliest pred start + dur), and pred
        # needs start <= (latest succ start - dur). Domains are built sorted by start time and
        # filtering keeps that order, so min/max are the first/last elements.
        dom = domains[xi]
        if not dom:
            return dom
        if xi == succ:
            lo = start_of(domains[pred][0]) + dur if domains[pred] else 1 << 30
            return [v for v in dom if start_of(v) >= lo]
        hi = start_of(domains[succ][-1]) - dur if domains[succ] else -1
        return [v for v in dom if start_of(v) <= hi]

    return constraint((pred, succ), lambda p, s: start_of(s) >= start_of(p) + dur, "structure",
                      f"{succ} after {pred}", revise=revise, orders={order}, kind="precedence")


def disjoint(t1: str, t2: str, d1: int, d2: int, clash, category: str, kind: str, orders, description: str):
    """Two tasks using the same resource (agent, station, access cell) must not overlap in time.

    `clash(v1, v2)` says whether the two chosen values compete for one resource."""

    def no_overlap(v1, v2):
        if not clash(v1, v2):
            return True
        s1, s2 = start_of(v1), start_of(v2)
        return s1 + d1 <= s2 or s2 + d2 <= s1

    def revise(xi, xj, domains):
        # While xj still has several values, every xi value keeps some support, so the
        # quadratic AC-3 scan can only prune once xj is down to one value.
        if len(domains[xj]) != 1:
            return domains[xi]
        other = domains[xj][0]
        return [v for v in domains[xi] if (no_overlap(v, other) if xi == t1 else no_overlap(other, v))]

    return constraint((t1, t2), no_overlap, category, description, revise=revise, orders=set(orders), kind=kind)


def stock_limit(variant_vars: dict[str, Order], recipes: dict[str, Recipe], stock: dict[str, float]) -> Constraint:
    """Global constraint: ingredients used by all chosen menus must fit in storage.

    Usage only grows as more menus are chosen, so the check is also valid on partial assignments
    (which is why it does not use `constraint`, which waits for the whole scope)."""

    def check(a):
        use: dict[str, float] = {}
        for var, order in variant_vars.items():
            if var in a:
                for ing, q in recipes[a[var]].per_meal.items():
                    use[ing] = use.get(ing, 0.0) + q * order.meals
        return all(kg <= stock.get(ing, 0.0) + 1e-6 for ing, kg in use.items())

    return Constraint(tuple(variant_vars), check, "ingredients", "ingredient stock",
                      {"orders": {o.id for o in variant_vars.values()}, "kind": "stock"})


# ---------------------------------------------------------------------------------------------
# records: the model and the decoded solution
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
    carry_in: int = 0  # first minutes: fetching the batch from the previous station
    work: int = 0  # then the actual cooking / prep / packing
    carry_out: int = 0  # last stage only: final minutes carrying meals to the dispatch door
    recipe: str = ""


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


@dataclass(frozen=True)
class KitchenModel:
    scenario: Scenario
    orders: list[Order]
    csp: CSP
    graphs: dict[str, TaskGraph]
    dur: dict[str, int]  # task id -> duration in slots
    routes: dict[str, Route | None]  # depot -> place over open roads (None = unreachable)
    relaxed_routes: dict[str, Route | None]  # same, ignoring closures (to time a hypothetical trip)


# ---------------------------------------------------------------------------------------------
# functions over the model
# ---------------------------------------------------------------------------------------------
def travel_minutes(sc: Scenario, routes, relaxed_routes, order: Order, vehicle_id: str) -> float:
    """One-way drive time for `order` in a vehicle (relaxed route when the real one is cut)."""
    r = routes.get(order.destination) or relaxed_routes.get(order.destination)
    return (r.minutes if r else 10_000) / sc.vehicles[vehicle_id].speed


def model_travel(m: KitchenModel, order: Order, vehicle_id: str) -> float:
    return travel_minutes(m.scenario, m.routes, m.relaxed_routes, order, vehicle_id)


def solve_model(m: KitchenModel, hints: dict | None = None, node_limit: int = 3_000, keep=None) -> SolveResult:
    """Solve the model's CSP; `keep(constraint)` optionally drops constraints (used by diagnosis)."""
    csp = m.csp if keep is None else subset(m.csp, keep)
    return solve(csp, node_limit=node_limit, value_order=_value_order(m), var_key=_var_key, hints=hints)


def decode(m: KitchenModel, result: SolveResult) -> Allocation:
    """Turn a CSP solution (slots and tuples) into tasks and deliveries in minutes."""
    S, a = m.scenario.slot_minutes, result.solution
    variants = {o.id: a[f"{o.id}.variant"] for o in m.orders}
    tasks = sorted((ScheduledTask(node.id, o.id, node.batch, node.stage, node.meals, *a[node.id][:2],
                                  a[node.id][2] * S, (a[node.id][2] + m.dur[node.id]) * S,
                                  node.transfer_minutes, node.work_minutes, node.carry_out_minutes, variants[o.id])
                    for o in m.orders for node in graph_tasks(m.graphs[o.id])),
                   key=lambda t: (t.start, t.order, t.batch))
    deliveries = []
    for o in m.orders:
        v, d = a[f"{o.id}.dispatch"]
        travel = model_travel(m, o, v)
        deliveries.append(Delivery(o.id, o.destination, v, d * S, d * S + travel, d * S + 2 * travel + UNLOAD_MINUTES,
                                   m.routes.get(o.destination), o.meals, variants[o.id]))
    return Allocation(variants, tasks, deliveries, result)


def compatible_variants(sc: Scenario, order: Order) -> list[Recipe]:
    return [r for r in sc.recipes.values() if recipe_satisfies(r, order.diet)]


def cook_stage(sc: Scenario) -> str:
    for s in sc.stages:
        if s.station_type in ("stove", "steamer") or s.skill == "cook":
            return s.name
    return sc.stages[-1].name


def stage_station_types(sc: Scenario, stage) -> set[str]:
    """Every station type a stage can use, over all recipes (e.g. cook: stove or steamer)."""
    return {stage.station_type} | {recipe_station(r, stage) for r in sc.recipes.values()}


def transfer_budgets(sc: Scenario) -> dict[str, int]:
    """Carry-in time per stage, in minutes: the worst case of
    walk(agent home -> previous station) + walk(previous station -> this station) + handling.

    The first stage walks from home to the shelf; "dispatch" is the walk from packing to the door.
    Walk times come from BFS distances on the floor grid (WALK_SECONDS per step)."""
    grid = sc.kitchen
    homes = [a.home for a in sc.agents.values()]
    cells = lambda types: [st.access for st in grid.stations.values() if st.type in types]  # noqa: E731
    dist_from = {}

    def walk(a, b) -> float:
        if a not in dist_from:
            dist_from[a] = bfs_distances(grid, a)
        return dist_from[a].get(b, 0) * WALK_SECONDS / 60

    budgets: dict[str, int] = {}
    for stage in sc.stages:
        here = cells(stage_station_types(sc, stage))
        prev_types = set().union(*(stage_station_types(sc, p) for p in sc.stages if p.name in stage.after))
        if not prev_types:
            worst = max(walk(h, c) for h in homes for c in here)
        else:
            worst = max(walk(h, p) + walk(p, c) for h in homes for p in cells(prev_types) for c in here)
        budgets[stage.name] = math.ceil(worst + HANDLING_MINUTES)
    last = sc.stages[-1]
    door = cells({"dispatch"})
    if door:
        budgets["dispatch"] = math.ceil(max(walk(k, d) for k in cells(stage_station_types(sc, last)) for d in door)
                                        + HANDLING_MINUTES)
    return budgets


def effective_batch_size(sc: Scenario, variants: list[Recipe]) -> int:
    """Cap the batch size at the biggest *working* cooking station: if the large stoves fail, the
    order is split into smaller batches that the remaining stoves can take."""
    stage = next(s for s in sc.stages if s.name == cook_stage(sc))
    types = {recipe_station(r, stage) for r in variants} or {stage.station_type}
    caps = [st.max_batch for t in types for st in stations_of(sc.kitchen, t, working_only=True)]
    return min(sc.batch_size, max(caps)) if caps else sc.batch_size


# ---------------------------------------------------------------------------------------------
# building the model
# ---------------------------------------------------------------------------------------------
def build_model(sc: Scenario, orders: list[Order]) -> KitchenModel:
    S = sc.slot_minutes
    H = sc.horizon // S  # number of slots in the day
    stations = sorted(sc.kitchen.stations.values(), key=lambda x: x.id)
    routes, relaxed = depot_routes(sc.roads), depot_routes(sc.roads, include_closed=True)
    rank = {o.id: i for i, o in enumerate(sorted(orders, key=lambda o: (-o.priority, o.deadline)))}
    transfers = transfer_budgets(sc)
    domains: dict[str, list] = {}
    priority: dict[str, tuple] = {}
    graphs: dict[str, TaskGraph] = {}
    dur: dict[str, int] = {}

    for o in orders:
        compat = compatible_variants(sc, o)
        g = build_task_graph(o, sc.stages, compat or list(sc.recipes.values()), effective_batch_size(sc, compat),
                             transfers)
        graphs[o.id] = g
        # every recipe is in the domain; the dietary constraint (node consistency) removes the unsafe ones
        domains[f"{o.id}.variant"], priority[f"{o.id}.variant"] = list(sc.recipes), (rank[o.id],)
        topo = {n: i for i, n in enumerate(topological_order(g))}
        for node in graph_tasks(g):
            d = max(1, math.ceil(node.minutes / S))
            dur[node.id] = d
            # start-major order: domains stay sorted by start time (precedence's revise relies on it)
            domains[node.id] = [(ag, st.id, s) for s in range(0, H - d + 1) for st in stations
                                if st.type in node.station_types for ag in sorted(sc.agents)]
            priority[node.id] = (rank[o.id], topo[node.id])
        domains[g.dispatch] = [(v, s) for s in range(H) for v in sorted(sc.vehicles)]
        priority[g.dispatch] = (rank[o.id], len(topo))
        dur[g.dispatch] = 0

    def travel(order, vehicle_id):
        return travel_minutes(sc, routes, relaxed, order, vehicle_id)

    constraints = (order_constraints(sc, orders, graphs, dur, routes, travel)
                   + pair_constraints(sc, orders, graphs, dur, travel)
                   + [stock_limit({f"{o.id}.variant": o for o in orders}, sc.recipes, total_stock(sc))])
    return KitchenModel(sc, orders, CSP(domains, constraints, priority), graphs, dur, routes, relaxed)


def order_constraints(sc: Scenario, orders, graphs, dur, routes, travel) -> list[Constraint]:
    """Constraints that involve a single order: unary rules plus links between its own variables."""
    S = sc.slot_minutes
    stations = sc.kitchen.stations
    first_stage, cook = sc.stages[0].name, cook_stage(sc)
    out: list[Constraint] = []
    for o in orders:
        var, g = f"{o.id}.variant", graphs[o.id]
        tag = dict(orders={o.id})

        out.append(constraint((var,), lambda r, _o=o: recipe_satisfies(sc.recipes[r], _o.diet), "dietary",
                              f"meal must satisfy diet [{', '.join(sorted(o.diet)) or 'none'}]", kind="dietary", **tag))

        for node in graph_tasks(g):
            t, d = node.id, dur[node.id]
            stage = next(s for s in sc.stages if s.name == node.stage)
            out.append(constraint((t,), lambda v, _s=node.skill: _s in sc.agents[v[0]].skills, "staff",
                                  f"{t} needs skill '{node.skill}'", kind="skill", **tag))
            out.append(constraint((t,), lambda v, _d=d: agent_available(sc.agents[v[0]], v[2] * S, (v[2] + _d) * S),
                                  "staff", f"{t} inside the agent's shift", kind="shift", **tag))
            out.append(constraint((t,), lambda v: not stations[v[1]].failed, "equipment",
                                  f"{t} needs a working station", kind="working", **tag))
            out.append(constraint((t,), lambda v, _m=node.meals: stations[v[1]].max_batch >= _m, "equipment",
                                  f"{t} needs capacity for {node.meals} meals", kind="capacity", **tag))
            if not node.preds:
                out.append(constraint((t,), lambda v, _r=o.release: v[2] * S >= _r, "structure",
                                      f"{t} not before the order arrives", kind="release", **tag))
            if any(recipe_station(r, stage) != stage.station_type for r in sc.recipes.values()):
                # some recipes need a different station for this stage (idli is steamed, not boiled)
                out.append(constraint((t, var), lambda v, r, _st=stage: stations[v[1]].type == recipe_station(
                    sc.recipes[r], _st), "equipment", f"{t} station must suit the recipe", kind="station-type", **tag))
            if node.stage == first_stage:
                # the fetch goes to a shelf that actually stocks the recipe's main ingredient
                out.append(constraint((t, var), lambda v, r: stations[v[1]].stock.get(sc.recipes[r].main_ingredient, 0) > 0,
                                      "ingredients", f"{t} shelf must stock the main ingredient", kind="located", **tag))
            if node.stage == cook:
                # food safety: cooked food is served within max_hold minutes
                out.append(constraint((t, g.dispatch), lambda c, v, _o=o, _d=d:
                                      v[1] * S + travel(_o, v[0]) - (c[2] + _d) * S <= sc.max_hold, "safety",
                                      f"{t} served within {sc.max_hold} min of cooking", kind="holding", **tag))
            out += [precedence(p, t, dur[p], o.id) for p in node.preds]

        disp = g.dispatch
        # the last stage ends with the packed meals at the dispatch door (carry-out in its duration)
        out += [precedence(p, disp, dur[p], o.id) for p in g.nodes[disp].preds]
        dest = sc.roads.places[o.destination].label
        out += [
            constraint((disp,), lambda v, _o=o: routes.get(_o.destination) is not None, "transport",
                       f"open road to {dest}", kind="route", **tag),
            constraint((disp,), lambda v, _o=o: sc.vehicles[v[0]].capacity >= _o.meals, "transport",
                       f"vehicle carries {o.meals} meals", kind="vehicle-capacity", **tag),
            constraint((disp,), lambda v: v[1] * S >= sc.vehicles[v[0]].available_from, "transport",
                       "vehicle is available", kind="vehicle-available", **tag),
            constraint((disp,), lambda v, _o=o: v[1] * S + travel(_o, v[0]) <= _o.deadline, "time",
                       f"arrive at {dest} by {clock(sc, o.deadline)}", kind="deadline", **tag),
            constraint((disp,), lambda v, _o=o: v[1] * S + 2 * travel(_o, v[0]) <= sc.horizon + 120,
                       "structure", "trip ends within the day", kind="horizon", **tag),
        ]
    return out


def pair_constraints(sc: Scenario, orders, graphs, dur, travel) -> list[Constraint]:
    """Shared-resource constraints between every pair of tasks / deliveries."""
    S = sc.slot_minutes
    shared = shared_access_pairs(sc.kitchen)
    tasks = [(o, n) for o in orders for n in graph_tasks(graphs[o.id])]
    out: list[Constraint] = []
    for i, (o1, n1) in enumerate(tasks):
        for o2, n2 in tasks[i + 1:]:
            d1, d2, both = dur[n1.id], dur[n2.id], {o1.id, o2.id}
            out.append(disjoint(n1.id, n2.id, d1, d2, lambda a, b: a[0] == b[0], "staff", "agent-booking", both,
                                "an agent does one task at a time"))
            if n1.station_types & n2.station_types:
                out.append(disjoint(n1.id, n2.id, d1, d2, lambda a, b: a[1] == b[1], "equipment", "occupancy",
                                    both, "one batch per station at a time"))
            if shared:
                out.append(disjoint(n1.id, n2.id, d1, d2, lambda a, b: frozenset((a[1], b[1])) in shared,
                                    "collision", "workspace", both,
                                    "stations sharing an access cell are not used together"))

    def trips_apart(o1, a, o2, b):
        e1 = a[1] * S + 2 * travel(o1, a[0]) + UNLOAD_MINUTES
        e2 = b[1] * S + 2 * travel(o2, b[0]) + UNLOAD_MINUTES
        return e1 <= b[1] * S or e2 <= a[1] * S

    for i, o1 in enumerate(orders):
        for o2 in orders[i + 1:]:
            out.append(constraint((f"{o1.id}.dispatch", f"{o2.id}.dispatch"),
                                  lambda a, b, _o1=o1, _o2=o2: a[0] != b[0] or trips_apart(_o1, a, _o2, b),
                                  "transport", "a vehicle makes one trip at a time",
                                  orders={o1.id, o2.id}, kind="vehicle-booking"))
            if o1.priority != o2.priority:
                hi, lo = (o1, o2) if o1.priority > o2.priority else (o2, o1)
                out.append(constraint((f"{hi.id}.dispatch", f"{lo.id}.dispatch"),
                                      lambda a, b: a[0] != b[0] or a[1] <= b[1], "priority",
                                      f"{hi.id} leaves before {lo.id} on a shared vehicle",
                                      orders={hi.id, lo.id}, kind="priority"))
    return out


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
