"""Demo runner for Module M3 — Uncertainty & Risk.

    python -m relief_kitchen.uncertainty
    python -m relief_kitchen.uncertainty --scenario configs/scenarios/stove_failure.yaml

Solves the scenario with M1 (initial plan, then once per event) and prints the belief, the Bayes
updates, the stock check and the risk at every step.
"""

from __future__ import annotations

import argparse

from relief_kitchen.algorithms.planner import run_timeline
from .belief import Belief
from .timeline import belief_timeline


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Module M3: Uncertainty & Risk")
    ap.add_argument("--scenario", default="configs/scenarios/stove_failure.yaml")
    args = ap.parse_args(argv)

    results = run_timeline(args.scenario)
    steps = belief_timeline(results)

    print(f"\n=== Module M3: Uncertainty & Risk ===")
    print(f"Scenario: {results[0].scenario.name}")

    for i, (res, step) in enumerate(zip(results, steps)):
        print(f"\n--- Step {i}: {res.label} ---")
        for var, prior, post in step.updates:
            print(f"  Bayes update  {var}: {prior:.3f} -> {post:.3f}")
        for shelf, ing, before, after in step.stock.changes:
            print(f"  Stock count   {shelf} {ing}: {before:g} -> {after:g} kg (a fact, not a guess)")
        if step.stock.short_orders:
            print(f"  Stock check   short for {', '.join(step.stock.short_orders)} -> supply_ok = 1.0")
        elif step.stock.changes:
            print("  Stock check   M1 still cooks every order from what is left -> supply_ok stays at the prior")
        if i and not step.updates and not step.stock.changes:
            print("  No stove, road or stock change at this step; the belief is unchanged.")
        print(Belief(step.probs))
        was = f"  (was {steps[i - 1].mc:.3f})" if i else ""
        print(f"\n  Monte-Carlo risk : {step.mc:.3f}{was}")
        was = f"  (was {steps[i - 1].analytical:.3f})" if i else ""
        print(f"  Analytical risk  : {step.analytical:.3f}{was}")
        if step.contingencies:
            print("\n  Contingency recommendations:")
            for line in step.contingencies:
                print(f"    {line}")


if __name__ == "__main__":
    main()
