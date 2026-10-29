"""Greedy time-slot scheduler for a POP plan.

Assigns a start_time to each step respecting:
  1. All ordering constraints from the plan
  2. Resource capacity (one task per station type at a time)
"""

from __future__ import annotations

from .partial_order import Plan

STEP_DURATION: dict[str, int] = {
    "fetch":   10,
    "prep":    20,
    "cook":    30,
    "pack":    10,
    "deliver": 40,
    "Start":    0,
    "Finish":   0,
}


def _op_name(step_id: str) -> str:
    """Strip counter suffix: 'cook_2' -> 'cook'."""
    return step_id.split("_")[0]


def schedule(plan: Plan, earliest: int = 0) -> dict[str, int]:
    """Return {step_id: start_time} using an earliest-start greedy scheduler."""
    steps = plan.sorted_steps()          # topological order guarantees predecessors first
    start_time: dict[str, int] = {}
    station_free_at: dict[str, int] = {} # resource type -> time when next available

    for step in steps:
        op = _op_name(step.id)
        duration = STEP_DURATION.get(op, 10)

        # Must start after every predecessor finishes
        ready = earliest
        for (a, b) in plan.orderings:
            if b == step.id and a in start_time:
                pred_dur = STEP_DURATION.get(_op_name(a), 10)
                ready = max(ready, start_time[a] + pred_dur)

        # Must wait until the station/resource is free
        ready = max(ready, station_free_at.get(op, 0))

        start_time[step.id] = ready
        station_free_at[op] = ready + duration

    return start_time
