"""Simplified multi-agent kitchen environment for MARL training.

State  per agent: (zone, load, urgency) encoded as int 0-26
Actions          : 0=idle  1=fetch  2=prep  3=cook  4=pack  5=deliver
Reward           : +1.0 delivered on time  |  -0.5 missed deadline  |  -0.1 idle
"""

from __future__ import annotations

import random

from .q_agent import N_ACTIONS, encode_state

N_AGENTS     = 3
EPISODE_LEN  = 30      # time-steps per episode

# Action -> zone the agent moves to (None = stay in current zone)
ACTION_ZONE = {0: None, 1: 0, 2: 0, 3: 1, 4: 2, 5: 2}


class KitchenEnv:
    def __init__(self):
        self.n_agents = N_AGENTS

    def reset(self) -> list[int]:
        """Reset to start of episode; return initial encoded states."""
        self.t          = 0
        self.meals_done = 0
        self.missed     = 0
        self.zones  = [0] * N_AGENTS   # all start in prep area
        self.loads  = [0] * N_AGENTS   # all start empty
        return [encode_state(self.zones[i], self.loads[i], 0) for i in range(N_AGENTS)]

    def step(self, actions: list[int]) -> tuple[list[int], list[float], bool]:
        """Execute one joint action step.

        Returns: (next_states, rewards, episode_done)
        """
        self.t += 1
        rewards = []

        for i, action in enumerate(actions):
            new_zone = ACTION_ZONE.get(action)
            if new_zone is not None:
                self.zones[i] = new_zone

            if action == 0:                    # idle — small penalty
                reward = -0.1
            elif action in (1, 2, 3, 4):       # working stage — small positive
                self.loads[i] = 1
                reward = 0.1
            elif action == 5:                  # deliver
                if self.loads[i] == 1:
                    on_time = random.random() > 0.2   # 80% chance on-time
                    if on_time:
                        self.meals_done += 1
                        reward = 1.0
                    else:
                        self.missed += 1
                        reward = -0.5
                    self.loads[i] = 0          # batch consumed
                else:
                    reward = -0.2              # deliver without batch → penalty
            else:
                reward = 0.0
            rewards.append(reward)

        urgency = min(2, self.t // 10)         # urgency increases as episode progresses
        next_states = [encode_state(self.zones[i], self.loads[i], urgency)
                       for i in range(N_AGENTS)]
        done = self.t >= EPISODE_LEN
        return next_states, rewards, done
