"""Delivery network: a weighted, undirected road graph whose roads can be closed."""

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


@dataclass
class RoadNetwork:
    places: dict[str, Place]
    roads: dict[str, Road]
    depot: str


def make_network(places: list[Place], roads: list[Road]) -> RoadNetwork:
    return RoadNetwork({p.id: p for p in places}, {r.id: r for r in roads},
                       next(p.id for p in places if p.kind == "depot"))


def road_neighbors(net: RoadNetwork, node: str, include_closed: bool = False):
    """Yield (neighbour, minutes, road id) over open roads (all roads if include_closed)."""
    for r in net.roads.values():
        if not r.open and not include_closed:
            continue
        if r.a == node:
            yield r.b, r.minutes, r.id      #yields the b, minutes, id of the road one by one
        elif r.b == node:
            yield r.a, r.minutes, r.id      #yields the a, minutes, id of the road one by one


def road_between(net: RoadNetwork, a: str, b: str) -> Road | None:
    return next((r for r in net.roads.values() if {r.a, r.b} == {a, b}), None)  #return 1 match or none


def closed_roads(net: RoadNetwork) -> list[str]:
    return [r.id for r in net.roads.values() if not r.open]


def straight_line(net: RoadNetwork, a: str, b: str) -> float:
    pa, pb = net.places[a], net.places[b]
    return ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2) ** 0.5
