"""Delivery routing on the weighted road graph: uniform-cost search (Dijkstra) and A*.

Edge cost = travel minutes. Closed roads are simply skipped, so after a closure we only re-run the
search ("reroute"). `include_closed=True` ignores closures; diagnosis uses it to time a trip that
is currently impossible.
"""

from __future__ import annotations

import heapq

from ..support.env.road_network import RoadNetwork, road_neighbors, straight_line
from ..support.records import Route


def _search(net: RoadNetwork, origin: str, dest: str, use_heuristic: bool, include_closed: bool) -> Route | None:
    """Best-first graph search ordered by g + h; with h = 0 this is uniform-cost search."""
    scale = 0.0
    if use_heuristic:
        # h = straight-line distance x (fewest minutes per distance unit over all roads).
        # No road beats that rate, so h never overestimates: admissible.
        ratios = [r.minutes / max(straight_line(net, r.a, r.b), 1e-9) for r in net.roads.values()]
        scale = min(ratios) if ratios else 0.0
    h = (lambda n: scale * straight_line(net, n, dest)) if use_heuristic else (lambda n: 0.0)
    g = {origin: 0.0}
    parent: dict[str, tuple[str, str]] = {}
    heap = [(h(origin), 0.0, origin)]
    expanded = 0
    while heap:
        _, cost, node = heapq.heappop(heap)
        if cost > g[node] + 1e-9:  # stale heap entry: a cheaper path was found later
            continue
        expanded += 1
        if node == dest:
            nodes, roads = [dest], []
            while nodes[-1] in parent:
                prev, rid = parent[nodes[-1]]
                nodes.append(prev)
                roads.append(rid)
            return Route(origin, dest, nodes[::-1], roads[::-1], cost, expanded)
        for nb, minutes, rid in road_neighbors(net, node, include_closed=include_closed):
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
