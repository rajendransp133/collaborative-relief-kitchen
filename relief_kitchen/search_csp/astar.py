"""Grid search on the kitchen floor (CS 188 "Search" lectures).

* `astar`          - A* with the Manhattan heuristic (admissible: each move costs 1, no diagonals).
* `bfs_distances`  - breadth-first search from one cell to every reachable cell.
* `space_time_astar` - A* whose states are (cell, time). "Wait" is an extra action, and some
  (cell, t) states or moves are forbidden because other agents reserved them. Used by `mapf`.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable

from ..env.entities import Cell
from ..env.kitchen_grid import KitchenGrid, neighbors


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def reconstruct(parents: dict, node) -> list:
    """Follow parent pointers back from `node` and return the path from the start."""
    path = [node]
    while node in parents:
        node = parents[node]
        path.append(node)
    path.reverse()
    return path


def astar(grid: KitchenGrid, start: Cell, goal: Cell, stats: dict | None = None) -> list[Cell] | None:
    """Shortest 4-connected path from start to goal (both ends included), or None if unreachable.

    Graph search with lazy deletion: stale heap entries (cost > best known g) are skipped."""
    if start == goal:
        return [start]
    open_heap = [(manhattan(start, goal), 0, start)]
    g = {start: 0}
    parents: dict[Cell, Cell] = {}
    expanded = 0
    while open_heap:
        _, cost, cell = heapq.heappop(open_heap)
        if cost > g[cell]:
            continue
        expanded += 1
        if cell == goal:
            if stats is not None:
                stats["expanded"] = expanded
            return reconstruct(parents, cell)
        for n in neighbors(grid, cell):
            ng = cost + 1
            if ng < g.get(n, 1 << 30):
                g[n] = ng
                parents[n] = cell
                heapq.heappush(open_heap, (ng + manhattan(n, goal), ng, n))
    if stats is not None:
        stats["expanded"] = expanded
    return None


def bfs_distances(grid: KitchenGrid, source: Cell) -> dict[Cell, int]:
    """BFS: number of steps from `source` to every reachable floor cell (also an exact heuristic)."""
    dist = {source: 0}
    frontier = [source]
    while frontier:
        nxt = []
        for cell in frontier:
            for n in neighbors(grid, cell):
                if n not in dist:
                    dist[n] = dist[cell] + 1
                    nxt.append(n)
        frontier = nxt
    return dist


def space_time_astar(
    grid: KitchenGrid,
    start: Cell,
    goal: Cell,
    vertex_blocked: Callable[[Cell, int], bool],
    edge_blocked: Callable[[Cell, Cell, int], bool],
    goal_busy_until: int = 0,
    max_t: int = 200,
    heuristic: dict[Cell, int] | None = None,
) -> list[Cell] | None:
    """Timed path (one cell per time step, waiting allowed) that respects the given constraints.

    The path ends at `goal` at some t >= goal_busy_until, after which the agent stays there; the
    caller makes sure nothing is constrained at the goal afterwards.

    State = (cell, t). Every action costs one time step, so g(state) = t, and a state's first
    discovery is already optimal: marking states `seen` on push is safe.
    """
    # true BFS distances to the goal: a perfect heuristic for the static map, admissible with waits
    h = heuristic if heuristic is not None else bfs_distances(grid, goal)
    if start not in h:
        return None
    start_state = (start, 0)
    open_heap = [(h[start], 0, 0, start)]
    parents: dict[tuple[Cell, int], tuple[Cell, int]] = {}
    seen = {start_state}
    while open_heap:
        _, _tie, t, cell = heapq.heappop(open_heap)
        if cell == goal and t >= goal_busy_until:
            return [c for c, _ in reconstruct(parents, (cell, t))]
        if t >= max_t:
            continue
        moves: Iterable[Cell] = [cell, *neighbors(grid, cell)]
        for n in moves:
            nt = t + 1
            if n not in h or (n, nt) in seen:
                continue
            if vertex_blocked(n, nt) or edge_blocked(cell, n, t):
                continue
            seen.add((n, nt))
            parents[(n, nt)] = (cell, t)
            # tie-break on fewer waits (prefer progress)
            heapq.heappush(open_heap, (nt + h[n], 0 if n != cell else 1, nt, n))
    return None
