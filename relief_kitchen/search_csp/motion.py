"""Turn the CSP schedule into collision-free movement on the kitchen floor.

At every slot boundary each agent's goal is the access cell of the station it works during that
slot (or its home cell when idle). Whenever goals change, a multi-agent path finder (CBS or
prioritised planning) moves everyone at once without vertex or swap collisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..env.entities import Cell
from ..env.scenario import Scenario
from .allocation import Allocation
from .mapf import MAPFResult, find_conflicts, solve_mapf


@dataclass
class Segment:
    slot: int
    result: MAPFResult


@dataclass
class KitchenMotion:
    method: str
    slot_minutes: int
    homes: dict[str, Cell]
    segments: list[Segment] = field(default_factory=list)
    collisions: int = 0
    failures: int = 0
    steps: int = 0  # total agent moves

    def position(self, agent: str, minute: float, step_seconds: float = 20.0) -> tuple[float, float]:
        """Interpolated (row, col) of an agent at a simulation minute (for animation)."""
        pos = self.homes[agent]
        for seg in self.segments:
            start = seg.slot * self.slot_minutes
            if start > minute:
                break
            path = seg.result.paths.get(agent)
            if not path:
                continue
            k = (minute - start) * 60.0 / step_seconds
            if k >= len(path) - 1:
                pos = path[-1]
                continue
            i = int(k)
            f = k - i
            a, b = path[i], path[i + 1]
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        return pos

    def trail(self, agent: str, minute: float, step_seconds: float = 20.0, linger: float = 1.0) -> list[Cell]:
        """Path of the agent's current move (shown while walking and `linger` minutes after)."""
        cur = None
        for seg in self.segments:
            start = seg.slot * self.slot_minutes
            if start > minute:
                break
            path = seg.result.paths.get(agent)
            if path and len(set(path)) > 1 and minute <= start + len(path) * step_seconds / 60 + linger:
                cur = path
        return cur or []


def plan_kitchen_motion(sc: Scenario, alloc: Allocation, method: str = "cbs") -> KitchenMotion:
    grid = sc.kitchen
    S = sc.slot_minutes
    homes = {a.id: a.home for a in sc.agents.values()}
    motion = KitchenMotion(method, S, homes)
    pos = dict(homes)
    last = max((t.end for t in alloc.tasks), default=0) // S + 1
    for slot in range(last + 1):
        minute = slot * S
        goal = dict(homes)
        for t in alloc.tasks:
            if t.start <= minute < t.end:
                goal[t.agent] = grid.stations[t.station].access
        if goal == pos:
            continue
        order = sorted(goal, key=lambda a: -sum(1 for t in alloc.tasks if t.agent == a and t.start == minute))
        res = solve_mapf(grid, pos, goal, method=method, order=order)
        if not res.ok:
            motion.failures += 1
            continue
        motion.collisions += len(find_conflicts(res.paths))
        motion.steps += sum(len(p) - 1 for p in res.paths.values())
        motion.segments.append(Segment(slot, res))
        pos = {a: p[-1] for a, p in res.paths.items()}
    return motion
