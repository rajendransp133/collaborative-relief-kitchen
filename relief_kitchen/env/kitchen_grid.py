"""Kitchen floor as an occupancy grid graph.

The map is ASCII art:

    #  wall            .  floor
    S  storage shelf   P  preparation counter
    C  stove           T  steamer
    K  packaging table D  dispatch door

Station cells are not walkable. An agent works a station from its *access cell*, a neighbouring
floor cell. Floor cells form a 4-connected graph, which the path finders search.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .entities import Cell, Station

STATION_CHARS = {"S": "storage", "P": "prep", "C": "stove", "T": "steamer", "K": "packaging", "D": "dispatch"}
ID_PREFIX = {"storage": "S", "prep": "P", "stove": "C", "steamer": "T", "packaging": "K", "dispatch": "D"}


@dataclass
class KitchenGrid:
    rows: list[str]
    width: int
    height: int
    stations: dict[str, Station]
    blocked: set[Cell] = field(default_factory=set)  # floor cells blocked at run time (spills, debris)


def parse_kitchen(rows: list[str], access_overrides: dict[str, Cell] | None = None) -> KitchenGrid:
    """Build the grid record from ASCII rows. Stations get ids in reading order (S1, S2, ...)."""
    width = max(len(r) for r in rows)
    rows = [r.ljust(width, "#") for r in rows]
    stations: dict[str, Station] = {}
    counters: dict[str, int] = {}
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch in STATION_CHARS:
                stype = STATION_CHARS[ch]
                counters[stype] = counters.get(stype, 0) + 1
                sid = f"{ID_PREFIX[stype]}{counters[stype]}"
                stations[sid] = Station(id=sid, type=stype, cell=(r, c))
    grid = KitchenGrid(rows, width, len(rows), stations)
    overrides = access_overrides or {}
    for sid, st in stations.items():
        st.access = tuple(overrides[sid]) if sid in overrides else _default_access(grid, st.cell)
    return grid


def _default_access(grid: KitchenGrid, cell: Cell) -> Cell | None:
    r, c = cell
    for dr, dc in ((1, 0), (-1, 0), (0, -1), (0, 1)):  # prefer the cell in front (below)
        if is_floor(grid, (r + dr, c + dc)):
            return (r + dr, c + dc)
    return None


# ---- graph -------------------------------------------------------------------------------------
def is_floor(grid: KitchenGrid, cell: Cell) -> bool:
    r, c = cell
    return 0 <= r < grid.height and 0 <= c < grid.width and grid.rows[r][c] == "."


def walkable(grid: KitchenGrid, cell: Cell) -> bool:
    return is_floor(grid, cell) and cell not in grid.blocked


def neighbors(grid: KitchenGrid, cell: Cell) -> list[Cell]:
    r, c = cell
    return [n for n in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)) if walkable(grid, n)]


# ---- stations ----------------------------------------------------------------------------------
def stations_of(grid: KitchenGrid, stype: str, working_only: bool = False) -> list[Station]:
    return [s for s in grid.stations.values() if s.type == stype and not (working_only and s.failed)]


def shared_access_pairs(grid: KitchenGrid) -> set[frozenset[str]]:
    """Pairs of stations worked from the same floor cell: they cannot be used at the same time."""
    by_cell: dict[Cell, list[str]] = {}
    for s in grid.stations.values():
        by_cell.setdefault(s.access, []).append(s.id)
    return {frozenset((a, b)) for ids in by_cell.values() for i, a in enumerate(ids) for b in ids[i + 1:]}
