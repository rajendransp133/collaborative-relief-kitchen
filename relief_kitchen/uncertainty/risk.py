"""Risk estimation for a relief kitchen plan.

Two methods:
  1. Analytical  — fast weighted sum over plan steps
  2. Monte Carlo — sample N disruption worlds, count plan failures
"""

from __future__ import annotations

import random

from .belief import Belief

# Which belief variable can disrupt each stage, and how critical it is (0-1)
STEP_RISK: dict[str, tuple[str | None, float]] = {
    "fetch":   ("supply_ok", 0.8),
    "prep":    (None,        0.0),
    "cook":    ("stove_ok",  0.9),
    "pack":    (None,        0.0),
    "deliver": ("road_ok",   0.7),
}


def estimate_risk(steps: list[str], belief: Belief) -> float:
    """Analytical risk: probability that at least one critical step fails.

    Uses 1 - product(1 - p_i) approximation (independent failures).
    """
    p_all_ok = 1.0
    for step in steps:
        var, weight = STEP_RISK.get(step, (None, 0.0))
        if var is not None:
            p_step_fails = weight * belief.probs.get(var, 0.0)
            p_all_ok *= (1.0 - p_step_fails)
    return round(1.0 - p_all_ok, 4)


def monte_carlo_risk(steps: list[str], belief: Belief, n: int = 500) -> float:
    """Sample n worlds; return fraction where at least one critical step fails."""
    failures = 0
    for _ in range(n):
        # Sample a concrete world state
        world = {var: (random.random() < prob) for var, prob in belief.probs.items()}
        for step in steps:
            var, _ = STEP_RISK.get(step, (None, 0.0))
            if var is not None and world.get(var, False):
                failures += 1
                break   # plan fails — no need to check further steps
    return round(failures / n, 4)
