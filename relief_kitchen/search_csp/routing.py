"""Delivery routing on the road graph: Dijkstra (uniform-cost search) and A*."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from ..env.road_network import RoadNetwork


@dataclass
class Route:
    origin: str
    destination: str
    nodes: list[str]
    roads: list[str]
    minutes: float
    expanded: int = 0

    def __bool__(self) -> bool:
        return bool(self.nodes)


def _search(net: RoadNetwork, origin: str, dest: str, use_heuristic: bool, include_closed: bool) -> Route | None:
    scale = 0.0
    if use_heuristic:
        # admissible: no road is faster per straight-line unit than the fastest one in the network
        ratios = [r.minutes / max(net.straight_line(r.a, r.b), 1e-9) for r in net.roads.values()]
        scale = min(ratios) if ratios else 0.0
    h = (lambda n: scale * net.straight_line(n, dest)) if use_heuristic else (lambda n: 0.0)
    g = {origin: 0.0}
    parent: dict[str, tuple[str, str]] = {}
    heap = [(h(origin), 0.0, origin)]
    expanded = 0
    while heap:
        _, cost, node = heapq.heappop(heap)
        if cost > g[node] + 1e-9:
            continue
        expanded += 1
        if node == dest:
            nodes, roads = [dest], []
            while nodes[-1] in parent:
                prev, rid = parent[nodes[-1]]
                nodes.append(prev)
                roads.append(rid)
            return Route(origin, dest, nodes[::-1], roads[::-1], cost, expanded)
        for nb, minutes, rid in net.neighbors(node, include_closed=include_closed):
            ng = cost + minutes
            if ng < g.get(nb, float("inf")) - 1e-9:
                g[nb] = ng
                parent[nb] = (node, rid)
                heapq.heappush(heap, (ng + h(nb), ng, nb))
    return None


def dijkstra(net: RoadNetwork, origin: str, dest: str, include_closed: bool = False) -> Route | None:
    return _search(net, origin, dest, use_heuristic=False, include_closed=include_closed)


def astar_route(net: RoadNetwork, origin: str, dest: str, include_closed: bool = False) -> Route | None:
    return _search(net, origin, dest, use_heuristic=True, include_closed=include_closed)


def depot_routes(net: RoadNetwork, include_closed: bool = False) -> dict[str, Route | None]:
    """Shortest route from the kitchen depot to every other place."""
    return {pid: astar_route(net, net.depot, pid, include_closed) for pid in net.places if pid != net.depot}


def reroute(net: RoadNetwork, old: Route, closed_road: str) -> Route | None:
    """Recompute a route after `closed_road` closes (returns the old one if unaffected)."""
    if closed_road not in old.roads:
        return old
    return astar_route(net, old.origin, old.destination)
