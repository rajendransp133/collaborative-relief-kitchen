"""Locate ingredients and equipment: breadth-first search outward from an agent's cell."""

from __future__ import annotations

from dataclasses import dataclass

from ..env.entities import Cell, Station
from ..env.kitchen_grid import KitchenGrid
from .astar import astar, bfs_distances


@dataclass
class Located:
    station: Station
    distance: int
    path: list[Cell]


def nearest_station(grid: KitchenGrid, origin: Cell, stype: str, *, ingredient: str | None = None,
                    min_kg: float = 0.0, max_batch: int = 0, exclude: set[str] | None = None) -> Located | None:
    """Closest working station of `stype` reachable from origin.

    For storage shelves `ingredient`/`min_kg` filter on stock; for equipment `max_batch` filters on
    capacity. Failed stations, unreachable ones and `exclude` are skipped.
    """
    ranked = rank_stations(grid, origin, stype, ingredient=ingredient, min_kg=min_kg, max_batch=max_batch,
                           exclude=exclude)
    if not ranked:
        return None
    st, d = ranked[0]
    return Located(st, d, astar(grid, origin, st.access) or [])


def rank_stations(grid: KitchenGrid, origin: Cell, stype: str, *, ingredient: str | None = None,
                  min_kg: float = 0.0, max_batch: int = 0, exclude: set[str] | None = None) -> list[tuple[Station, int]]:
    dist = bfs_distances(grid, origin)
    out = []
    for st in grid.stations_of(stype, working_only=True):
        if exclude and st.id in exclude:
            continue
        if ingredient is not None and st.stock.get(ingredient, 0.0) < max(min_kg, 1e-9):
            continue
        if st.max_batch < max_batch:
            continue
        if st.access not in dist:
            continue
        out.append((st, dist[st.access]))
    out.sort(key=lambda x: (x[1], x[0].id))
    return out


def locate_ingredients(grid: KitchenGrid, origin: Cell, needs: dict[str, float]) -> dict[str, list[tuple[str, float, int]]]:
    """Plan where to pick each ingredient: nearest shelves first until the quantity is covered.

    Returns ingredient -> [(shelf id, kg taken, walking distance)]; an entry is missing or short when
    the stock cannot cover the need.
    """
    dist = bfs_distances(grid, origin)
    plan: dict[str, list[tuple[str, float, int]]] = {}
    for ing, kg in needs.items():
        shelves = [s for s in grid.stations_of("storage", working_only=True)
                   if s.stock.get(ing, 0) > 0 and s.access in dist]
        shelves.sort(key=lambda s: (dist[s.access], s.id))
        remaining = kg
        picks = []
        for s in shelves:
            if remaining <= 1e-9:
                break
            take = min(remaining, s.stock[ing])
            picks.append((s.id, round(take, 2), dist[s.access]))
            remaining -= take
        plan[ing] = picks
    return plan
