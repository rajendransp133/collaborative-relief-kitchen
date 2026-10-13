"""Kitchen floor as an occupancy grid graph.

The map is ASCII art:

    #  wall            .  floor
    S  storage shelf   P  preparation counter
    C  stove           T  steamer
    K  packaging table D  dispatch door

Station cells are not walkable; an agent works a station from its *access cell*, a neighbouring
floor cell. Floor cells form a 4-connected graph that the path finders search.
"""

from __future__ import annotations

from .entities import Cell, Station

STATION_CHARS = {
    "S": "storage",
    "P": "prep",
    "C": "stove",
    "T": "steamer",
    "K": "packaging",
    "D": "dispatch",
}
ID_PREFIX = {"storage": "S", "prep": "P", "stove": "C", "steamer": "T", "packaging": "K", "dispatch": "D"}
ZONES = {
    "storage": "Storage",
    "prep": "Preparation",
    "stove": "Cooking",
    "steamer": "Cooking",
    "packaging": "Packaging",
    "dispatch": "Dispatch",
}


class KitchenGrid:
    def __init__(self, rows: list[str], access_overrides: dict[str, Cell] | None = None):
        width = max(len(r) for r in rows)
        self.rows = [r.ljust(width, "#") for r in rows]
        self.height = len(self.rows)
        self.width = width
        self.stations: dict[str, Station] = {}
        self.blocked: set[Cell] = set()  # temporarily blocked floor cells (spills, debris)
        counters: dict[str, int] = {}
        for r, line in enumerate(self.rows):
            for c, ch in enumerate(line):
                if ch in STATION_CHARS:
                    stype = STATION_CHARS[ch]
                    counters[stype] = counters.get(stype, 0) + 1
                    sid = f"{ID_PREFIX[stype]}{counters[stype]}"
                    self.stations[sid] = Station(id=sid, type=stype, cell=(r, c))
        access_overrides = access_overrides or {}
        for sid, st in self.stations.items():
            st.access = tuple(access_overrides[sid]) if sid in access_overrides else self._default_access(st.cell)

    # ---- graph -------------------------------------------------------------------------------
    def is_floor(self, cell: Cell) -> bool:
        r, c = cell
        return 0 <= r < self.height and 0 <= c < self.width and self.rows[r][c] == "."

    def walkable(self, cell: Cell) -> bool:
        return self.is_floor(cell) and cell not in self.blocked

    def neighbors(self, cell: Cell) -> list[Cell]:
        r, c = cell
        out = []
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (r + dr, c + dc)
            if self.walkable(n):
                out.append(n)
        return out

    def floor_cells(self) -> list[Cell]:
        return [(r, c) for r in range(self.height) for c in range(self.width) if self.walkable((r, c))]

    def _default_access(self, cell: Cell) -> Cell | None:
        r, c = cell
        for dr, dc in ((1, 0), (-1, 0), (0, -1), (0, 1)):
            n = (r + dr, c + dc)
            if self.is_floor(n):
                return n
        return None

    # ---- stations ----------------------------------------------------------------------------
    def stations_of(self, stype: str, working_only: bool = False) -> list[Station]:
        return [s for s in self.stations.values() if s.type == stype and not (working_only and s.failed)]

    def shared_access_pairs(self) -> set[frozenset[str]]:
        """Pairs of stations worked from the same floor cell: they cannot be used at once."""
        by_cell: dict[Cell, list[str]] = {}
        for s in self.stations.values():
            by_cell.setdefault(s.access, []).append(s.id)
        pairs = set()
        for ids in by_cell.values():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pairs.add(frozenset((ids[i], ids[j])))
        return pairs
