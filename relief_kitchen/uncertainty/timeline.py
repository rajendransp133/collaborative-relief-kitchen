"""Belief and risk over a scenario's timeline (initial plan, then one step per disruption).

Each step compares the scenario with the previous one. Stove failures and road closures are
reports that may be wrong, so they go through the Bayes update in `belief.py`. A stock count is a
fact, not a report: it is checked against M1's plan instead (`stock_check`). Used by the visualiser
and the CLI.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .belief import Belief
from .contingency import suggest_contingency
from .risk import estimate_risk, monte_carlo_risk

STAGE_NAMES = ["fetch", "prep", "cook", "pack", "deliver"]
PRIOR = 0.05


@dataclass
class StockCheck:
    changes: list[tuple[str, str, float, float]] = field(default_factory=list)  # (shelf, ingredient, kg before, kg after)
    short_orders: list[str] = field(default_factory=list)  # orders M1 rejects for lack of ingredients


@dataclass
class BeliefStep:
    probs: dict[str, float]
    updates: list[tuple[str, float, float]] = field(default_factory=list)  # (variable, prior, posterior)
    stock: StockCheck = field(default_factory=StockCheck)
    mc: float = 0.0  # Monte Carlo risk (seeded)
    analytical: float = 0.0
    contingencies: list[str] = field(default_factory=list)


def observed_disruptions(prev, sc) -> list[str]:
    """Belief variables with a (possibly false) disruption report between two scenario states."""
    out = []
    if any(st.failed and not prev.kitchen.stations[sid].failed
           for sid, st in sc.kitchen.stations.items() if st.type == "stove" and sid in prev.kitchen.stations):
        out.append("stove_ok")
    if any(not road.open and prev.roads.roads[rid].open for rid, road in sc.roads.roads.items() if rid in prev.roads.roads):
        out.append("road_ok")
    return out


def stock_changes(prev, sc) -> list[tuple[str, str, float, float]]:
    """Every shelf ingredient whose counted stock differs between two scenario states."""
    return [(sid, ing, before, kg)
            for sid, st in sc.kitchen.stations.items() if sid in prev.kitchen.stations
            for ing, kg in st.stock.items()
            if abs(kg - (before := prev.kitchen.stations[sid].stock.get(ing, 0.0))) > 1e-9]


def stock_check(result, prev=None) -> StockCheck:
    """What changed on the shelves, and which orders M1 could not cook from what is left."""
    short = [oid for oid, d in result.diagnoses.items() if "ingredients" in d.categories]
    return StockCheck(stock_changes(prev.scenario, result.scenario) if prev else [], short)


def belief_timeline(results: list, n: int = 500, seed: int = 0) -> list[BeliefStep]:
    """One BeliefStep per M1 result (initial plan, then one per event); step 0 is the prior.

    Supply is not a guess: it is 1.0 while M1 rejects an order for lack of ingredients, else the prior."""
    belief = Belief.default()
    steps = []
    for i, res in enumerate(results):
        updates = []
        for var in (observed_disruptions(results[i - 1].scenario, res.scenario) if i else []):
            prior = belief.probs.get(var, PRIOR)
            belief.observe_disruption(var)
            updates.append((var, prior, belief.probs[var]))
        stock = stock_check(res, results[i - 1] if i else None)
        belief.probs["supply_ok"] = 1.0 if stock.short_orders else PRIOR
        steps.append(BeliefStep(dict(belief.probs), updates, stock,
                                monte_carlo_risk(STAGE_NAMES, belief, n, rng=random.Random(seed)),
                                estimate_risk(STAGE_NAMES, belief), suggest_contingency(belief)))
    return steps
