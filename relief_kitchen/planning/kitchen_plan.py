"""Build the kitchen's POP problem from a scenario and solve it (used by the CLI and the visualiser)."""

from __future__ import annotations

from .partial_order import Operator, Plan, pop
from .scheduler import schedule


def build_operators(stages) -> list[Operator]:
    """Convert scenario Stage records into POP Operator objects."""
    ops = []
    for stage in stages:
        pre = frozenset(f"{dep}_done" for dep in stage.after)
        add = frozenset([f"{stage.name}_done"])
        ops.append(Operator(stage.name, pre, add))
    # Give fetch a precondition so POP has something to resolve from the initial state
    fetch_op = next((o for o in ops if o.name == "fetch"), None)
    if fetch_op is not None:
        ops[ops.index(fetch_op)] = Operator("fetch", frozenset(["ingredients_available"]), fetch_op.add,
                                            fetch_op.delete)
    return ops


def problem(sc) -> tuple[frozenset[str], frozenset[str], list[Operator]]:
    """(initial state, goal, operators) for a scenario."""
    init = frozenset(["ingredients_available"])
    goal = frozenset([f"{sc.stages[-1].name}_done"])
    return init, goal, build_operators(sc.stages)


def plan_for(sc, trace: list | None = None) -> tuple[Plan, dict[str, int]]:
    """Run POP on the scenario's stages, then the greedy scheduler. Returns (plan, start times)."""
    init, goal, ops = problem(sc)
    plan = pop(init, goal, ops, trace=trace)
    return plan, schedule(plan)
