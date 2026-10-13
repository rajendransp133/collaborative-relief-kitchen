"""Delivery network: a weighted, undirected road graph whose edges can be closed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Place:
    id: str
    kind: str  # depot, shelter, hospital, junction
    x: float
    y: float
    label: str = ""
    people: int = 0


@dataclass
class Road:
    id: str
    a: str
    b: str
    minutes: float
    open: bool = True


class RoadNetwork:
    def __init__(self, places: list[Place], roads: list[Road]):
        self.places = {p.id: p for p in places}
        self.roads = {r.id: r for r in roads}
        self.depot = next(p.id for p in places if p.kind == "depot")

    def neighbors(self, node: str, include_closed: bool = False):
        """Yield (neighbor, minutes, road_id)."""
        for r in self.roads.values():
            if not r.open and not include_closed:
                continue
            if r.a == node:
                yield r.b, r.minutes, r.id
            elif r.b == node:
                yield r.a, r.minutes, r.id

    def road_between(self, a: str, b: str) -> Road | None:
        for r in self.roads.values():
            if {r.a, r.b} == {a, b}:
                return r
        return None

    def close_road(self, road_id: str) -> None:
        self.roads[road_id].open = False

    def open_road(self, road_id: str) -> None:
        self.roads[road_id].open = True

    def closed_roads(self) -> list[str]:
        return [r.id for r in self.roads.values() if not r.open]

    def straight_line(self, a: str, b: str) -> float:
        pa, pb = self.places[a], self.places[b]
        return ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2) ** 0.5
