"""Infeasibility diagnosis: *why* can't an order be scheduled?

1. Direct checks, one per category (dietary, ingredients, equipment, staff, transport, time), with
   no search. A failed check is a definite cause: the order is impossible on its own ("isolated").
2. Relax one category at a time. If every check passes but the CSP still fails, drop that category's
   constraints for this order only and re-solve. Any category whose removal makes the order fit is
   reported as a cause. If the order fits alone, it is competing with accepted orders ("contention").
"""

from __future__ import annotations

from ..support.diagnosis_checks import CATEGORY_ORDER, direct_checks, make_diagnosis, relaxed_sentence
from ..support.env.entities import Order
from ..support.env.scenario import Scenario, clock
from ..support.model_helpers import solve_model
from ..support.records import Cause, Diagnosis
from .kitchen_csp import build_model


def diagnose_order(sc: Scenario, order: Order, accepted: list[Order], hints: dict | None = None,
                   node_limit: int = 1_500) -> Diagnosis:
    dest = sc.roads.places[order.destination].label
    # Step 1. direct checks
    causes = direct_checks(sc, order, accepted, hints or {})
    if causes:
        return make_diagnosis(order, dest, "isolated", causes)

    # Step 2. contention if the order fits on its own; otherwise relax within the order alone
    alone = build_model(sc, [order])
    contention = bool(accepted) and solve_model(alone, node_limit=node_limit).ok
    model = build_model(sc, accepted + [order]) if contention else alone
    for cat in CATEGORY_ORDER:
        def keep(c, _cat=cat):  # drop only this order's constraints of this category
            return not (c.category == _cat and order.id in c.meta.get("orders", ()))

        if any(not keep(c) for c in model.csp.constraints) and \
                solve_model(model, hints=hints if contention else None, node_limit=node_limit, keep=keep).ok:
            causes.append(Cause(cat, relaxed_sentence(sc, order, cat, contention)))
    if not causes:  # no single category is to blame: everything is simply too tight
        causes.append(Cause("time", f"no schedule meets the {clock(sc, order.deadline)} deadline with the "
                                    "resources left"))
    return make_diagnosis(order, dest, "contention" if contention else "isolated", causes)
