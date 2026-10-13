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
    diagnoses: dict[str, Diagnosis]
    routes: dict[str, Route | None]
    motion: KitchenMotion | None
    ingredient_plan: dict[str, dict[str, list]] = field(default_factory=dict)
    nearest: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    seconds: float = 0.0
    nodes: int = 0

    @property
    def rejected(self) -> list[str]:
        return list(self.diagnoses)


def solve_scenario(sc: Scenario, mapf_method: str = "cbs", label: str = "plan", diagnose: bool = True) -> M1Result:
    """Accept orders greedily by (priority, deadline); each acceptance re-solves the joint CSP
    warm-started from the previous solution, and every rejected order is diagnosed."""
    t0 = time.perf_counter()
    queue = sorted(sc.orders, key=lambda o: (-o.priority, o.deadline, o.id))
    accepted: list[Order] = []
    hints: dict = {}
    best = None
    diagnoses: dict[str, Diagnosis] = {}
    log: list[str] = []
    nodes = 0
    for order in queue:
        model = build_model(sc, accepted + [order])
        res = model.solve(hints=hints)
        nodes += res.stats.nodes
        if res.ok:
            accepted.append(order)
            hints = res.solution
            best = (model, res)
            log.append(f"accept {order.id}: {res.stats.nodes} nodes, {res.stats.backtracks} backtracks, "
                       f"{res.stats.seconds * 1000:.0f} ms")
        else:
            log.append(f"reject {order.id}: CSP {res.status}" +
                       (f" (domain wiped out by: {res.wipeout.description})" if res.wipeout else ""))
            if diagnose:
                d = diagnose_order(sc, order, accepted, hints)
                diagnoses[order.id] = d
                log.append(f"  diagnosis: {d.summary()} [{d.checks} QuickXplain checks]")

    alloc = best[0].decode(best[1]) if best else None
    motion = plan_kitchen_motion(sc, alloc, mapf_method) if alloc else None
    ingredient_plan, nearest = {}, {}
    if alloc:
        door = sc.kitchen.stations_of("dispatch")
        origin = door[0].access if door else next(iter(sc.agents.values())).home
        for o in accepted:
            r = sc.recipes[alloc.variants[o.id]]
            ingredient_plan[o.id] = locate_ingredients(sc.kitchen, origin,
                                                       {i: q * o.meals for i, q in r.per_meal.items()})
        centre = list(sc.agents.values())[len(sc.agents) // 2].home
        for stype in ("storage", "prep", "stove", "steamer", "packaging"):
            hit = nearest_station(sc.kitchen, centre, stype)
            nearest[stype] = f"{hit.station.id} ({hit.distance} steps)" if hit else "none working"
    return M1Result(sc, label, accepted, alloc, diagnoses, depot_routes(sc.roads), motion, ingredient_plan,
                    nearest, log, time.perf_counter() - t0, nodes)


def run_timeline(path: str, mapf_method: str = "cbs") -> list[M1Result]:
    """Solve the scenario as given, then once more after each disruption event (cumulative)."""
    sc = load_scenario(path)
    results = [solve_scenario(sc, mapf_method, label="initial plan")]
    for ev in sc.events:
        sc = sc.copy()
        text = sc.apply(ev)
        results.append(solve_scenario(sc, mapf_method, label=f"after: {text}"))
    return results
