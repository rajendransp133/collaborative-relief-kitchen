"""Locate ingredients and equipment by breadth-first search from an agent's position.

One BFS gives the walking distance to every floor cell. Stations are then ranked by the
distance to their access cell, so "nearest working stove" or "nearest shelf with rice" is a
simple filter-and-sort.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..env.entities import Cell, Station
from ..env.kitchen_grid import KitchenGrid
from .astar import astar, bfs_distances


@dataclass
class Located:
    station: Station
    distance: int  # steps from the origin to the station's access cell
    path: list[Cell]


def rank_stations(grid: KitchenGrid, origin: Cell, stype: str,
                  ingredient: str | None = None) -> list[tuple[Station, int]]:
    """Working, reachable stations of type `stype`, nearest first.

    With `ingredient`, only shelves that still hold some of it are kept."""
    dist = bfs_distances(grid, origin)
    out = [(st, dist[st.access]) for st in grid.stations_of(stype, working_only=True)
           if st.access in dist and (ingredient is None or st.stock.get(ingredient, 0.0) > 0)]
    out.sort(key=lambda x: (x[1], x[0].id))
    return out


def nearest_station(grid: KitchenGrid, origin: Cell, stype: str, ingredient: str | None = None) -> Located | None:
    ranked = rank_stations(grid, origin, stype, ingredient)
    if not ranked:
        return None
    st, d = ranked[0]
    return Located(st, d, astar(grid, origin, st.access) or [])


def locate_ingredients(grid: KitchenGrid, origin: Cell, needs: dict[str, float]) -> dict[str, list[tuple[str, float, int]]]:
    """Pick list: for each ingredient, take from the nearest shelves until the need is covered.

    Returns ingredient -> [(shelf id, kg taken, walking distance)]. The list falls short when the
    stock cannot cover the need; the CSP's stock constraint prevents that for accepted orders."""
    dist = bfs_distances(grid, origin)
    plan: dict[str, list[tuple[str, float, int]]] = {}
    for ing, kg in needs.items():
        remaining, picks = kg, []
        for st, d in sorted(((s, dist[s.access]) for s in grid.stations_of("storage", working_only=True)
                             if s.stock.get(ing, 0) > 0 and s.access in dist), key=lambda x: (x[1], x[0].id)):
            if remaining <= 1e-9:
                break
            take = min(remaining, st.stock[ing])
            picks.append((st.id, round(take, 2), d))
            remaining -= take
        plan[ing] = picks
    return plan
