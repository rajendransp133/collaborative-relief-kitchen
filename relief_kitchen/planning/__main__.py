"""Demo runner for Module M2 — Partial-Order Planning.

    python -m relief_kitchen.planning
    python -m relief_kitchen.planning --scenario configs/scenarios/base.yaml
"""

from __future__ import annotations

import argparse

from relief_kitchen.support.env.scenario import load_scenario
from .partial_order import Operator, pop
from .scheduler import STEP_DURATION, schedule


def _build_operators(stages) -> list[Operator]:
    """Convert scenario Stage records into POP Operator objects."""
    ops = []
    for stage in stages:
        pre = frozenset(f"{dep}_done" for dep in stage.after)
        add = frozenset([f"{stage.name}_done"])
        ops.append(Operator(stage.name, pre, add))
    return ops


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Module M2: Partial-Order Planning")
    ap.add_argument("--scenario", default="configs/scenarios/base.yaml")
    args = ap.parse_args(argv)

    sc = load_scenario(args.scenario)
    operators = _build_operators(sc.stages)

    # Give fetch a precondition so POP has something to resolve from init state
    fetch_op = next(o for o in operators if o.name == "fetch")
    operators[operators.index(fetch_op)] = Operator(
        "fetch",
        frozenset(["ingredients_available"]),
        fetch_op.add,
        fetch_op.delete,
    )

    init = frozenset(["ingredients_available"])
    last_stage = sc.stages[-1].name
    goal = frozenset([f"{last_stage}_done"])

    print(f"\n=== Module M2: Partial-Order Planning ===")
    print(f"Scenario : {sc.name}")
    print(f"Stages   : {' -> '.join(s.name for s in sc.stages)}")
    print(f"Goal     : {goal}\n")

    plan = pop(init, goal, operators)
    times = schedule(plan)

    # Print execution schedule
    print(f"{'Step':<22} {'Start':>6}  {'Duration':>10}  {'Finish':>8}")
    print("-" * 52)
    for step in plan.sorted_steps():
        if step.id in ("Start", "Finish"):
            continue
        op = step.id.split("_")[0]
        dur = STEP_DURATION.get(op, 10)
        t = times.get(step.id, 0)
        print(f"  {step.id:<20} {t:>6}  {dur:>8} min  {t+dur:>6}")

    # Print causal links
    print(f"\nCausal links ({len(plan.links)}):")
    for lk in plan.links:
        print(f"  {lk.producer:>20} --[{lk.condition}]--> {lk.consumer}")

    # Print ordering constraints
    non_trivial = [(a, b) for a, b in sorted(plan.orderings)
                   if not (a == "Start" or b == "Finish")]
    if non_trivial:
        print(f"\nOrdering constraints (non-trivial, {len(non_trivial)}):")
        for a, b in non_trivial:
            print(f"  {a} < {b}")


if __name__ == "__main__":
    main()
