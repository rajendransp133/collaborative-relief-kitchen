"""Module 1 end to end: routes -> CSP allocation (with diagnosis) -> collision-free kitchen motion."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..env.entities import Order
from ..env.scenario import Scenario, load_scenario
from .allocation import Allocation, build_model
from .diagnosis import Diagnosis, diagnose_order
from .locate import locate_ingredients, nearest_station
from .motion import KitchenMotion, plan_kitchen_motion
from .routing import Route, depot_routes


@dataclass
class M1Result:
    scenario: Scenario
    label: str
    accepted: list[Order]
    allocation: Allocation | None
    diagnoses: dict[str, Diagnosis]  # rejected order id -> why
    routes: dict[str, Route | None]
    motion: KitchenMotion | None
    ingredient_plan: dict[str, dict[str, list]] = field(default_factory=dict)
    nearest: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    seconds: float = 0.0


def solve_scenario(sc: Scenario, label: str = "plan") -> M1Result:
    """Accept orders greedily, most urgent first (priority, then deadline).

    Each new order is added to the joint CSP, which is re-solved with the previous solution as hints
    (a warm start: accepted orders keep their slots unless the newcomer forces a change). If the CSP
    fails, the order is rejected and diagnosed, and the remaining orders are still served.
    """
    t0 = time.perf_counter()
    accepted: list[Order] = []
    hints: dict = {}
    best = None
    diagnoses: dict[str, Diagnosis] = {}
    log: list[str] = []
    for order in sorted(sc.orders, key=lambda o: (-o.priority, o.deadline, o.id)):
        model = build_model(sc, accepted + [order])
        res = model.solve(hints=hints)
        if res.ok:
            accepted.append(order)
            hints, best = res.solution, (model, res)
            log.append(f"accept {order.id}: {res.stats.nodes} nodes, {res.stats.backtracks} backtracks, "
                       f"{res.stats.seconds * 1000:.0f} ms")
        else:
            d = diagnose_order(sc, order, accepted, hints)
            diagnoses[order.id] = d
            log.append(f"reject {order.id} ({res.status}): {d.summary()}")

    alloc = best[0].decode(best[1]) if best else None
    motion = plan_kitchen_motion(sc, alloc) if alloc else None
    ingredient_plan, nearest = {}, {}
    if alloc:
        # pick lists: nearest shelves first, measured by BFS from the dispatch door
        door = sc.kitchen.stations_of("dispatch")
        origin = door[0].access if door else next(iter(sc.agents.values())).home
        for o in accepted:
            r = sc.recipes[alloc.variants[o.id]]
            ingredient_plan[o.id] = locate_ingredients(sc.kitchen, origin, {i: q * o.meals for i, q in r.per_meal.items()})
        centre = list(sc.agents.values())[len(sc.agents) // 2].home
        for stype in ("storage", "prep", "stove", "steamer", "packaging"):
            hit = nearest_station(sc.kitchen, centre, stype)
            nearest[stype] = f"{hit.station.id} ({hit.distance} steps)" if hit else "none working"
    return M1Result(sc, label, accepted, alloc, diagnoses, depot_routes(sc.roads), motion, ingredient_plan,
                    nearest, log, time.perf_counter() - t0)


def run_timeline(path: str) -> list[M1Result]:
    """Solve the scenario as given, then again after each disruption event (events accumulate)."""
    sc = load_scenario(path)
    results = [solve_scenario(sc, label="initial plan")]
    for ev in sc.events:
        sc = sc.copy()
        text = sc.apply(ev)
        results.append(solve_scenario(sc, label=f"after: {text}"))
    return results
