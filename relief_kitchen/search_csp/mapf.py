"""Multi-agent path finding on the kitchen grid.

Two solvers share the same space-time A* low level:

* prioritised planning - agents are planned one after another; earlier agents' timed paths are
  reserved so later agents route around them (fast, not complete);
* Conflict-Based Search (Sharon et al., 2015) - a best-first search over a constraint tree that
  resolves the first vertex or edge (swap) conflict by branching on which agent must avoid it
  (optimal for the sum of path costs).
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field

from ..env.entities import Cell
from ..env.kitchen_grid import KitchenGrid
from .astar import bfs_distances, space_time_astar


def at(path: list[Cell], t: int) -> Cell:
    return path[t] if t < len(path) else path[-1]


def find_conflicts(paths: dict[str, list[Cell]]) -> list[tuple]:
    """All conflicts: ('vertex', a, b, cell, t) or ('edge', a, b, cell_a, cell_b, t)."""
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


def sum_of_costs(paths: dict[str, list[Cell]], goals: dict[str, Cell]) -> int:
    total = 0
    for a, p in paths.items():
        last = len(p) - 1
        while last > 0 and p[last - 1] == goals[a]:
            last -= 1
        total += last
    return total


@dataclass
class MAPFResult:
    paths: dict[str, list[Cell]]
    solver: str
    expanded: int = 0  # high-level nodes for CBS, agents planned for prioritised
    cost: int = 0
    ok: bool = True
    note: str = ""


# ---------------------------------------------------------------------------------------------
# Prioritised planning
# ---------------------------------------------------------------------------------------------
def prioritized_planning(grid: KitchenGrid, starts: dict[str, Cell], goals: dict[str, Cell],
                         order: list[str] | None = None, max_t: int = 120) -> MAPFResult:
    order = order or list(starts)
    # agents that stay put go first: later agents then route around them
    order = sorted(order, key=lambda a: starts[a] != goals[a])
    vertex: set[tuple[Cell, int]] = set()
    edges: set[tuple[Cell, Cell, int]] = set()
    parked: dict[Cell, int] = {}  # cell -> time from which a planned agent sits there forever
    paths: dict[str, list[Cell]] = {}
    for aid in order:
        goal = goals[aid]

        def vb(cell, t):
            if (cell, t) in vertex:
                return True
            since = parked.get(cell)
            return since is not None and t >= since

        def eb(a, b, t):
            return (b, a, t) in edges

        busy = max((t for (c, t) in vertex if c == goal), default=-1) + 1
        path = space_time_astar(grid, starts[aid], goal, vb, eb, goal_busy_until=busy, max_t=max_t)
        if path is None:
            return MAPFResult(paths=paths, solver="prioritized", ok=False, note=f"no path for {aid}")
        paths[aid] = path
        for t, c in enumerate(path):
            vertex.add((c, t))
            if t + 1 < len(path):
                edges.add((c, path[t + 1], t))
        parked[path[-1]] = len(path) - 1
    return MAPFResult(paths=paths, solver="prioritized", expanded=len(order), cost=sum_of_costs(paths, goals))


# ---------------------------------------------------------------------------------------------
# Conflict-Based Search
# ---------------------------------------------------------------------------------------------
@dataclass(order=True)
class _CTNode:
    cost: int
    n_conflicts: int
    tie: int
    constraints: dict = field(compare=False)  # agent -> {"v": set[(cell,t)], "e": set[(a,b,t)]}
    paths: dict = field(compare=False)


def _low_level(grid, start, goal, cons, h, max_t):
    v, e = cons["v"], cons["e"]
    busy = max((t for (c, t) in v if c == goal), default=-1) + 1
    return space_time_astar(grid, start, goal, lambda c, t: (c, t) in v, lambda a, b, t: (a, b, t) in e,
                            goal_busy_until=busy, max_t=max_t, heuristic=h)


def conflict_based_search(grid: KitchenGrid, starts: dict[str, Cell], goals: dict[str, Cell],
                          max_nodes: int = 2000, max_t: int = 120) -> MAPFResult:
    heuristics = {a: bfs_distances(grid, goals[a]) for a in starts}
    tie = itertools.count()
    root_cons = {a: {"v": set(), "e": set()} for a in starts}
    root_paths = {}
    for a in starts:
        p = _low_level(grid, starts[a], goals[a], root_cons[a], heuristics[a], max_t)
        if p is None:
            return MAPFResult(paths={}, solver="cbs", ok=False, note=f"{a} cannot reach its goal")
        root_paths[a] = p
    root = _CTNode(sum_of_costs(root_paths, goals), len(find_conflicts(root_paths)), next(tie), root_cons, root_paths)
    open_list = [root]
    expanded = 0
    while open_list and expanded < max_nodes:
        node = heapq.heappop(open_list)
        expanded += 1
        conflicts = find_conflicts(node.paths)
        if not conflicts:
            return MAPFResult(paths=node.paths, solver="cbs", expanded=expanded, cost=node.cost)
        c = conflicts[0]
        for agent_idx in (1, 2):
            agent = c[agent_idx]
            cons = {a: {"v": set(x["v"]), "e": set(x["e"])} for a, x in node.constraints.items()}
            if c[0] == "vertex":
                cons[agent]["v"].add((c[3], c[4]))
            else:
                _, a1, _a2, ca, cb, t = c
                # a1 moves ca->cb and a2 moves cb->ca between t and t+1
                cons[agent]["e"].add((ca, cb, t) if agent == a1 else (cb, ca, t))
            new_path = _low_level(grid, starts[agent], goals[agent], cons[agent], heuristics[agent], max_t)
            if new_path is None:
                continue
            paths = dict(node.paths)
            paths[agent] = new_path
            heapq.heappush(open_list, _CTNode(sum_of_costs(paths, goals), len(find_conflicts(paths)), next(tie),
                                              cons, paths))
    # budget exhausted: fall back so the simulation can continue
    fb = prioritized_planning(grid, starts, goals, max_t=max_t)
    fb.note = "CBS budget exhausted, used prioritised planning"
    return fb


def solve_mapf(grid: KitchenGrid, starts: dict[str, Cell], goals: dict[str, Cell], method: str = "cbs",
               order: list[str] | None = None) -> MAPFResult:
    if method == "cbs":
        return conflict_based_search(grid, starts, goals)
    return prioritized_planning(grid, starts, goals, order=order)
