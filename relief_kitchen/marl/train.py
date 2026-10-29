"""Training loop for Module M4 — Cooperative Multi-Agent Q-Learning."""

from __future__ import annotations

from .env_wrapper import KitchenEnv, N_AGENTS
from .q_agent import QAgent


def train(n_episodes: int = 200, verbose: bool = True) -> list[QAgent]:
    """Train N_AGENTS independent Q-learning agents; return trained agents."""
    env    = KitchenEnv()
    agents = [QAgent(f"agent_{i}") for i in range(N_AGENTS)]

    for ep in range(n_episodes):
        states     = env.reset()
        ep_rewards = [0.0] * N_AGENTS
        done       = False

        while not done:
            # Each agent picks its action independently (ε-greedy)
            actions = [agents[i].act(states[i]) for i in range(N_AGENTS)]

            # Environment transitions
            next_states, rewards, done = env.step(actions)

            # Each agent updates its own Q-table
            for i in range(N_AGENTS):
                agents[i].update(states[i], actions[i], rewards[i], next_states[i])
                ep_rewards[i] += rewards[i]

            states = next_states

        # Decay exploration rate after each episode
        for agent in agents:
            agent.decay_epsilon()

        if verbose and (ep + 1) % 20 == 0:
            avg = sum(ep_rewards) / N_AGENTS
            print(f"  Episode {ep+1:>3}/{n_episodes}  "
                  f"avg_reward={avg:+.2f}  "
                  f"meals_delivered={env.meals_done}  "
                  f"epsilon={agents[0].epsilon:.3f}")

    return agents
