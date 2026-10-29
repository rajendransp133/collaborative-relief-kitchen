"""Demo runner for Module M3 — Uncertainty & Risk.

    python -m relief_kitchen.uncertainty
    python -m relief_kitchen.uncertainty --scenario configs/scenarios/stove_failure.yaml
"""

from __future__ import annotations

import argparse

from relief_kitchen.support.env.scenario import apply_event, load_scenario
from .belief import Belief
from .contingency import suggest_contingency
from .risk import estimate_risk, monte_carlo_risk
from .timeline import EVENT_TO_VAR, STAGE_NAMES


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Module M3: Uncertainty & Risk")
    ap.add_argument("--scenario", default="configs/scenarios/stove_failure.yaml")
    args = ap.parse_args(argv)

    sc = load_scenario(args.scenario)
    belief = Belief.default()

    print(f"\n=== Module M3: Uncertainty & Risk ===")
    print(f"Scenario: {sc.name}\n")

    print("--- Initial belief state (before any disruption) ---")
    print(belief)
    r_mc = monte_carlo_risk(STAGE_NAMES, belief)
    r_an = estimate_risk(STAGE_NAMES, belief)
    print(f"\n  Monte-Carlo risk : {r_mc:.3f}")
    print(f"  Analytical risk  : {r_an:.3f}")

    # Apply the first scenario event as the observed disruption
    if sc.events:
        ev = sc.events[0]
        _, label = apply_event(sc, ev)
        print(f"\n>>> Disruption observed: {label}")
        var = EVENT_TO_VAR.get(ev.kind)
        if var:
            belief.observe_disruption(var)
        else:
            print("  (unknown event type — simulating stove failure)")
            belief.observe_disruption("stove_ok")
    else:
        print("\n>>> No events in scenario — simulating a stove failure signal")
        belief.observe_disruption("stove_ok")

    print("\n--- Updated belief state (after disruption) ---")
    print(belief)
    r_mc2 = monte_carlo_risk(STAGE_NAMES, belief)
    r_an2 = estimate_risk(STAGE_NAMES, belief)
    print(f"\n  Monte-Carlo risk : {r_mc2:.3f}  (was {r_mc:.3f})")
    print(f"  Analytical risk  : {r_an2:.3f}  (was {r_an:.3f})")

    suggestions = suggest_contingency(belief)
    if suggestions:
        print("\n--- Contingency recommendations ---")
        for line in suggestions:
            print(f"  {line}")
    else:
        print("\n(Risk below threshold — no contingency action needed)")


if __name__ == "__main__":
    main()
