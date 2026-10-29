"""Bayesian belief state for the relief kitchen.

Each variable tracks the probability that a resource is *disrupted*.
Bayes update rule:
    P(fail | obs_disrupted) = P(obs | fail) * P(fail)
                              ──────────────────────────────────────
                              P(obs|fail)*P(fail) + P(obs|ok)*P(ok)
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Likelihood model — how probable is the disruption signal given true state
P_OBS_GIVEN_FAIL = 0.90   # P(see disruption | resource really failed)
P_OBS_GIVEN_OK   = 0.05   # P(see disruption | resource is actually fine)  ← false alarm


@dataclass
class Belief:
    """Maps resource names -> probability of being in a failed/disrupted state."""
    probs: dict[str, float] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "Belief":
        return cls(probs={
            "stove_ok":  0.05,   # 5% prior chance stove is disrupted
            "road_ok":   0.05,
            "supply_ok": 0.05,
        })

    def observe_disruption(self, variable: str) -> None:
        """Raise failure probability after observing a disruption signal."""
        p = self.probs.get(variable, 0.05)
        numerator   = P_OBS_GIVEN_FAIL * p
        denominator = numerator + P_OBS_GIVEN_OK * (1.0 - p)
        self.probs[variable] = numerator / denominator

    def observe_normal(self, variable: str) -> None:
        """Lower failure probability after observing a normal (all-good) signal."""
        p = self.probs.get(variable, 0.05)
        p_obs_fail = 1.0 - P_OBS_GIVEN_FAIL
        p_obs_ok   = 1.0 - P_OBS_GIVEN_OK
        numerator   = p_obs_fail * p
        denominator = numerator + p_obs_ok * (1.0 - p)
        self.probs[variable] = numerator / denominator

    def __str__(self) -> str:
        lines = ["Belief state (P(disrupted)):"]
        for k, v in self.probs.items():
            bar = "#" * int(v * 20)
            lines.append(f"  {k:<15} {v:.3f}  [{bar:<20}]")
        return "\n".join(lines)
