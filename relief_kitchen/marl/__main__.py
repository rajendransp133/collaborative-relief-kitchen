"""Demo runner for Module M4 — Cooperative MARL.

    python -m relief_kitchen.marl
    python -m relief_kitchen.marl --episodes 300
"""

from __future__ import annotations

import argparse

from .train import train


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Module M4: Cooperative Multi-Agent Q-Learning")
    ap.add_argument("--episodes", type=int, default=200)
    args = ap.parse_args(argv)

    print(f"\n=== Module M4: Cooperative Multi-Agent Q-Learning ===")
    print(f"Agents  : 3 independent Q-learning agents")
    print(f"State   : (zone, load, urgency)  ->  27 possible states per agent")
    print(f"Actions : idle | fetch | prep | cook | pack | deliver")
    print(f"Reward  : +1 on-time delivery  |  -0.5 missed  |  -0.1 idle\n")
    print(f"Training for {args.episodes} episodes...\n")

    agents = train(n_episodes=args.episodes, verbose=True)

    print("\n--- Learned Policy Summary ---")
    for agent in agents:
        top = agent.top_actions(top_n=3)
        top_str = "  |  ".join(f"{a} Q={v:+.3f}" for a, v in top)
        print(f"  {agent.id}:  {top_str}")
        print(f"    final epsilon={agent.epsilon:.3f}   |Q-table|={len(agent.q)} entries")

    print("\nTraining complete.")


if __name__ == "__main__":
    main()
