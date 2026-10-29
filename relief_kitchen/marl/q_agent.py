"""Module M4 — Tabular Q-Learning agent.

State encoding: (zone, load, urgency) each 0-2  →  integer 0..26
  zone    : 0=prep_area, 1=cooking_area, 2=dispatch
  load    : 0=empty, 1=has_batch, 2=waiting_for_resource
  urgency : 0=low, 1=medium, 2=high  (grows as deadlines approach)

Actions: idle, fetch, prep, cook, pack, deliver

Q-update (Bellman equation):
  Q(s,a) ← Q(s,a) + α * [r + γ * max_a' Q(s',a') - Q(s,a)]
"""

from __future__ import annotations

import random
from collections import defaultdict

ACTIONS = ["idle", "fetch", "prep", "cook", "pack", "deliver"]
N_ACTIONS = len(ACTIONS)


def encode_state(zone: int, load: int, urgency: int) -> int:
    """Pack three 0-2 indices into a single integer (0..26)."""
    return zone * 9 + load * 3 + urgency


class QAgent:
    def __init__(self, agent_id: str, alpha: float = 0.1, gamma: float = 0.9, epsilon: float = 0.3):
        self.id      = agent_id
        self.alpha   = alpha      # learning rate
        self.gamma   = gamma      # discount factor (future reward weight)
        self.epsilon = epsilon    # exploration probability
        self.q: dict[tuple[int, int], float] = defaultdict(float)

    def act(self, state: int) -> int:
        """ε-greedy policy: explore randomly, otherwise exploit best Q-value."""
        if random.random() < self.epsilon:
            return random.randrange(N_ACTIONS)
        return max(range(N_ACTIONS), key=lambda a: self.q[(state, a)])

    def update(self, state: int, action: int, reward: float, next_state: int) -> None:
        """Temporal-difference update (Q-learning)."""
        best_next = max(self.q[(next_state, a)] for a in range(N_ACTIONS))
        td_error  = reward + self.gamma * best_next - self.q[(state, action)]
        self.q[(state, action)] += self.alpha * td_error

    def decay_epsilon(self, rate: float = 0.99) -> None:
        """Reduce exploration over time (anneal to minimum 0.01)."""
        self.epsilon = max(0.01, self.epsilon * rate)

    def top_actions(self, top_n: int = 3) -> list[tuple[str, float]]:
        """Average Q-value per action across all states (for reporting)."""
        totals: dict[int, float] = defaultdict(float)
        counts: dict[int, int]   = defaultdict(int)
        for (_, a), v in self.q.items():
            totals[a] += v
            counts[a] += 1
        avg = {a: (totals[a] / counts[a]) for a in range(N_ACTIONS) if counts[a] > 0}
        ranked = sorted(avg.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [(ACTIONS[a], round(v, 3)) for a, v in ranked]
