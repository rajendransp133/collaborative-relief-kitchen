"""Contingency suggestion: recommend backup actions when a variable is high-risk."""

from __future__ import annotations

from .belief import Belief

THRESHOLD = 0.4   # probability above which we flag the variable

CONTINGENCIES: dict[str, list[str]] = {
    "stove_ok": [
        "Reroute batch to steamer (T1) if recipe supports it",
        "Split batch across remaining working stoves",
        "Notify kitchen supervisor and delay affected order",
    ],
    "road_ok": [
        "Switch to alternate delivery route (re-run routing module)",
        "Dispatch vehicle earlier to absorb extra travel time",
        "Use faster vehicle (V3) if batch capacity allows",
    ],
    "supply_ok": [
        "Check secondary shelf stock (S3)",
        "Substitute recipe (e.g. rice_dal → millet_khichdi)",
        "Flag shortage to coordinator for emergency resupply",
    ],
}


def suggest_contingency(belief: Belief) -> list[str]:
    """Return a list of recommendation lines for all high-risk variables."""
    suggestions: list[str] = []
    for var, prob in belief.probs.items():
        if prob >= THRESHOLD:
            actions = CONTINGENCIES.get(var, ["Manual intervention required"])
            suggestions.append(f"[{var}  risk={prob:.2f}]")
            suggestions.extend(f"  -> {a}" for a in actions)
    return suggestions
