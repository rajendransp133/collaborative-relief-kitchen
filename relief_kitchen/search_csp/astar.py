"""A* on the kitchen grid, plus space-time A* used by the multi-agent path finders."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable

from ..env.entities import Cell
from ..env.kitchen_grid import KitchenGrid


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def reconstruct(parents: dict, node) -> list:
    path = [node]
    while node in parents:
        node = parents[node]
        path.append(node)
    path.reverse()
    return path


def astar(grid: KitchenGrid, start: Cell, goal: Cell, stats: dict | None = None) -> list[Cell] | None:
    """Shortest 4-connected path from start to goal (both inclusive), or None if unreachable."""
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
        for n in grid.neighbors(cell):
            ng = cost + 1
            if ng < g.get(n, 1 << 30):
                g[n] = ng
                parents[n] = cell
                heapq.heappush(open_heap, (ng + manhattan(n, goal), ng, n))
    if stats is not None:
        stats["expanded"] = expanded
    return None


def bfs_distances(grid: KitchenGrid, source: Cell) -> dict[Cell, int]:
    """Uninformed breadth-first search: distance from source to every reachable floor cell."""
    dist = {source: 0}
    frontier = [source]
    while frontier:
        nxt = []
        for cell in frontier:
            for n in grid.neighbors(cell):
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
    """
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
        moves: Iterable[Cell] = [cell, *grid.neighbors(cell)]
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
