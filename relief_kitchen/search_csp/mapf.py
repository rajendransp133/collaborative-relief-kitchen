"""Multi-agent path finding (MAPF) on the kitchen grid with prioritised planning.

Agents are planned one at a time with space-time A* (`astar.space_time_astar`). Each agent's timed
path is written into a reservation table, and later agents treat reserved (cell, t) pairs and
reserved moves as obstacles. Two kinds of collision are ruled out:

    vertex conflict  two agents in the same cell at the same time step
    edge conflict    two agents swap cells between t and t+1

The method is simple and fast, but not complete: a bad agent order can leave a later agent with no
path. Agents that stay put are planned first, which avoids most such cases in a kitchen.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..env.entities import Cell
from ..env.kitchen_grid import KitchenGrid
from .astar import space_time_astar


def at(path: list[Cell], t: int) -> Cell:
    """Position at time t; an agent waits at its last cell once its path ends."""
    return path[t] if t < len(path) else path[-1]


def find_conflicts(paths: dict[str, list[Cell]]) -> list[tuple]:
    """First conflict per pair: ('vertex', a, b, cell, t) or ('edge', a, b, cell_a, cell_b, t)."""
    out = []
    ids = list(paths)
    horizon = max((len(p) for p in paths.values()), default=0)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            pa, pb = paths[a], paths[b]
            for t in range(horizon):
                if at(pa, t) == at(pb, t):
                    out.append(("vertex", a, b, at(pa, t), t))
                    break
                if t + 1 < horizon and at(pa, t) == at(pb, t + 1) and at(pb, t) == at(pa, t + 1):
                    out.append(("edge", a, b, at(pa, t), at(pa, t + 1), t))
                    break
    return out


def verify_collision_free(paths: dict[str, list[Cell]]) -> bool:
    return not find_conflicts(paths)


@dataclass
class MAPFResult:
    paths: dict[str, list[Cell]]
    ok: bool = True
    note: str = ""


def prioritized_planning(grid: KitchenGrid, starts: dict[str, Cell], goals: dict[str, Cell],
                         order: list[str] | None = None, max_t: int = 120) -> MAPFResult:
    order = sorted(order or list(starts), key=lambda a: starts[a] != goals[a])  # stable: stay-put first
    vertex: set[tuple[Cell, int]] = set()  # reserved (cell, t)
    edges: set[tuple[Cell, Cell, int]] = set()  # reserved moves (from, to, t)
    parked: dict[Cell, int] = {}  # cell -> time from which a planned agent sits there for good
    paths: dict[str, list[Cell]] = {}
    for aid in order:
        goal = goals[aid]

        def vertex_blocked(cell, t):
            return (cell, t) in vertex or (cell in parked and t >= parked[cell])

        def edge_blocked(a, b, t):
            return (b, a, t) in edges  # moving a->b while someone moves b->a is a swap

        # only stop at the goal once nobody else passes through it later
        busy = max((t for (c, t) in vertex if c == goal), default=-1) + 1
        path = space_time_astar(grid, starts[aid], goal, vertex_blocked, edge_blocked, goal_busy_until=busy,
                                max_t=max_t)
        if path is None:
            return MAPFResult(paths, ok=False, note=f"no path for {aid}")
        paths[aid] = path
        for t, c in enumerate(path):
            vertex.add((c, t))
            if t + 1 < len(path):
                edges.add((c, path[t + 1], t))
        parked[path[-1]] = len(path) - 1
    return MAPFResult(paths)
