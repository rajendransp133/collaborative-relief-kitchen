"""Module 1 end to end: accept orders one by one with the CSP, diagnose the ones that don't fit,
then replan after every disruption event."""

from __future__ import annotations

import time

from ..support.diagnosis_checks import summary
from ..support.env.entities import Order
from ..support.env.scenario import Scenario, apply_event, load_scenario
from ..support.extras import enrich
from ..support.model_helpers import decode, solve_model
from ..support.records import Diagnosis, M1Result
from .diagnosis import diagnose_order
from .kitchen_csp import build_model
from .routing import depot_routes


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
        res = solve_model(model, hints=hints)
        if res.ok:
            accepted.append(order)
            hints, best = res.solution, (model, res)
            log.append(f"accept {order.id}: {res.stats.nodes} nodes, {res.stats.backtracks} backtracks, "
                       f"{res.stats.seconds * 1000:.0f} ms")
        else:
            d = diagnose_order(sc, order, accepted, hints)
            diagnoses[order.id] = d
            log.append(f"reject {order.id} ({res.status}): {summary(d)}")

    alloc = decode(*best) if best else None
    return M1Result(sc, label, accepted, alloc, diagnoses, depot_routes(sc.roads), log=log,
                    seconds=time.perf_counter() - t0, **enrich(sc, alloc, accepted))


def run_timeline(path: str) -> list[M1Result]:
    """Solve the scenario as given, then again after each disruption event (events accumulate)."""
    sc = load_scenario(path)
    results = [solve_scenario(sc, label="initial plan")]
    for ev in sc.events:
        sc, text = apply_event(sc, ev)
        results.append(solve_scenario(sc, label=f"after: {text}"))
    return results
