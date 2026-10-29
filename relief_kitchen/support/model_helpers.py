"""Helpers for the kitchen CSP in `algorithms/kitchen_csp.py`: small lookups, time budgets, search
heuristics, solving a model and decoding its solution into tasks and deliveries."""

from __future__ import annotations

import math

from ..algorithms.csp import solve
from ..algorithms.grid_search import bfs_distances
from .csp_build import subset
from .env.entities import Order, Recipe, recipe_satisfies, recipe_station
from .env.kitchen_grid import HANDLING_MINUTES, WALK_SECONDS, stations_of
from .env.scenario import Scenario
from .locate import rank_stations
from .records import Allocation, Delivery, KitchenModel, ScheduledTask, SolveResult
from .task_graph import graph_tasks

UNLOAD_MINUTES = 10


def start_of(val) -> int:
    """Start slot of a task value (agent, station, start) or dispatch value (vehicle, departure)."""
    return val[-1]


def travel_minutes(sc: Scenario, routes, relaxed_routes, order: Order, vehicle_id: str) -> float:
    """One-way drive time for `order` in a vehicle (relaxed route when the real one is cut)."""
    r = routes.get(order.destination) or relaxed_routes.get(order.destination)
    return (r.minutes if r else 10_000) / sc.vehicles[vehicle_id].speed


def model_travel(m: KitchenModel, order: Order, vehicle_id: str) -> float:
    return travel_minutes(m.scenario, m.routes, m.relaxed_routes, order, vehicle_id)


def compatible_variants(sc: Scenario, order: Order) -> list[Recipe]:
    return [r for r in sc.recipes.values() if recipe_satisfies(r, order.diet)]


def cook_stage(sc: Scenario) -> str:
    for s in sc.stages:
        if s.station_type == "stove" or s.skill == "cook":
            return s.name
    return sc.stages[-1].name


def stage_station_types(sc: Scenario, stage) -> set[str]:
    """Every station type a stage can use, over all recipes (the stage's own, plus any recipe override)."""
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
# solving and decoding
# ---------------------------------------------------------------------------------------------
def solve_model(m: KitchenModel, hints: dict | None = None, node_limit: int = 3_000, keep=None) -> SolveResult:
    """Solve the model's CSP; `keep(constraint)` optionally drops constraints (used by diagnosis)."""
    csp = m.csp if keep is None else subset(m.csp, keep)
    return solve(csp, node_limit=node_limit, value_order=value_order(m), var_key=phase_key, hints=hints)


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


# ---------------------------------------------------------------------------------------------
# search heuristics
# ---------------------------------------------------------------------------------------------
def phase_key(var: str) -> tuple:
    """Phase before MRV: choose menus, then kitchen tasks, then vehicles (a list-scheduling order)."""
    if var.endswith(".variant"):
        return (0,)
    if var.endswith(".dispatch"):
        return (2,)
    return (1,)


def value_order(m: KitchenModel):
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
