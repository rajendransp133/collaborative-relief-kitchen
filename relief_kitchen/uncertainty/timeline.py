"""Belief and risk over a scenario's timeline (initial plan, then one step per disruption).

Each step compares the scenario with the previous one, turns what changed into disruption
observations, and applies the Bayes update from `belief.py`. Used by the visualiser.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .belief import Belief
from .contingency import suggest_contingency
from .risk import estimate_risk, monte_carlo_risk

STAGE_NAMES = ["fetch", "prep", "cook", "pack", "deliver"]

# Map scenario event kinds to belief variables
EVENT_TO_VAR = {
    "fail_station": "stove_ok",
    "close_road":   "road_ok",
    "set_stock":    "supply_ok",
}


@dataclass
class BeliefStep:
    probs: dict[str, float]
    updates: list[tuple[str, float, float]] = field(default_factory=list)  # (variable, prior, posterior)
    mc: float = 0.0  # Monte Carlo risk (seeded)
    analytical: float = 0.0
    contingencies: list[str] = field(default_factory=list)


def observed_disruptions(prev, sc) -> list[str]:
    """Belief variables with a disruption signal between two scenario states."""
    out = []
    if any(st.failed and not prev.kitchen.stations[sid].failed
           for sid, st in sc.kitchen.stations.items() if st.type == "stove" and sid in prev.kitchen.stations):
        out.append("stove_ok")
    if any(not road.open and prev.roads.roads[rid].open for rid, road in sc.roads.roads.items() if rid in prev.roads.roads):
        out.append("road_ok")
    if any(kg < prev.kitchen.stations[sid].stock.get(ing, 0.0) - 1e-9
           for sid, st in sc.kitchen.stations.items() if sid in prev.kitchen.stations
           for ing, kg in st.stock.items()):
        out.append("supply_ok")
    return out


def belief_timeline(scenarios: list, n: int = 500, seed: int = 0) -> list[BeliefStep]:
    """One BeliefStep per scenario state; step 0 is the prior."""
    belief = Belief.default()
    steps = []
    for i, sc in enumerate(scenarios):
        updates = []
        for var in (observed_disruptions(scenarios[i - 1], sc) if i else []):
            prior = belief.probs.get(var, 0.05)
            belief.observe_disruption(var)
            updates.append((var, prior, belief.probs[var]))
        steps.append(BeliefStep(dict(belief.probs), updates,
                                monte_carlo_risk(STAGE_NAMES, belief, n, rng=random.Random(seed)),
                                estimate_risk(STAGE_NAMES, belief), suggest_contingency(belief)))
    return steps
