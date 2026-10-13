"""Load a YAML scenario into plain Python objects and apply disruption events to it."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .entities import Agent, Order, Recipe, Stage, Vehicle
from .kitchen_grid import KitchenGrid
from .road_network import Place, Road, RoadNetwork


def parse_clock(value, start_clock: int) -> int:
    """'11:30' -> minutes after the start clock; plain numbers are already minutes."""
    if isinstance(value, (int, float)):
        return int(value)
    h, m = str(value).split(":")
    return int(h) * 60 + int(m) - start_clock


@dataclass
class Event:
    kind: str  # close_road, fail_station, repair_station, set_stock, add_order, demand_surge, agent_off
    params: dict
    label: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    start_clock: int  # minutes after midnight
    slot_minutes: int
    horizon: int  # minutes
    batch_size: int
    max_hold: int  # food safety: max minutes between end of cooking and arrival
    kitchen: KitchenGrid
    roads: RoadNetwork
    agents: dict[str, Agent]
    stages: list[Stage]
    recipes: dict[str, Recipe]
    orders: list[Order]
    vehicles: dict[str, Vehicle]
    events: list[Event] = field(default_factory=list)
    path: str = ""

    def clock(self, minutes: float) -> str:
        t = int(round(self.start_clock + minutes))
        return f"{t // 60:02d}:{t % 60:02d}"

    def copy(self) -> "Scenario":
        return copy.deepcopy(self)

    def stock(self) -> dict[str, float]:
        total: dict[str, float] = {}
        for st in self.kitchen.stations_of("storage"):
            for ing, kg in st.stock.items():
                total[ing] = total.get(ing, 0.0) + kg
        return total

    # ---- disruptions ---------------------------------------------------------------------------
    def apply(self, ev: Event) -> str:
        p = ev.params
        if ev.kind == "close_road":
            self.roads.close_road(p["road"])
            return ev.label or f"Road {p['road']} closed"
        if ev.kind == "open_road":
            self.roads.open_road(p["road"])
            return ev.label or f"Road {p['road']} reopened"
        if ev.kind == "fail_station":
            self.kitchen.stations[p["station"]].failed = True
            return ev.label or f"Station {p['station']} failed"
        if ev.kind == "repair_station":
            self.kitchen.stations[p["station"]].failed = False
            return ev.label or f"Station {p['station']} repaired"
        if ev.kind == "set_stock":
            self.kitchen.stations[p["shelf"]].stock[p["ingredient"]] = float(p["kg"])
            return ev.label or f"{p['ingredient']} on {p['shelf']} is {p['kg']} kg"
        if ev.kind == "demand_surge":
            order = next(o for o in self.orders if o.id == p["order"])
            order.meals += int(p["extra"])
            return ev.label or f"Order {order.id} +{p['extra']} meals"
        if ev.kind == "add_order":
            o = p["order"]
            self.orders.append(
                Order(
                    id=o["id"],
                    destination=o["destination"],
                    meals=int(o["meals"]),
                    diet=set(o.get("diet", [])),
                    deadline=parse_clock(o["deadline"], self.start_clock),
                    priority=int(o.get("priority", 1)),
                    release=parse_clock(o.get("release", 0), self.start_clock),
                )
            )
            return ev.label or f"New order {o['id']}"
        if ev.kind == "agent_off":
            self.agents[p["agent"]].shift_end = 0
            return ev.label or f"Agent {p['agent']} unavailable"
        if ev.kind == "block_cell":
            self.kitchen.blocked.add(tuple(p["cell"]))
            return ev.label or f"Kitchen cell {p['cell']} blocked"
        raise ValueError(f"unknown event kind {ev.kind!r}")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def read_scenario_dict(path: str | Path) -> dict:
    """Read YAML; `extends: other.yaml` deep-merges this file over another (lists are replaced)."""
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    parent = data.pop("extends", None)
    if parent:
        data = _merge(read_scenario_dict(path.parent / parent), data)
    return data


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    data = read_scenario_dict(path)
    start = parse_clock(data.get("start", "08:00"), 0)
    clk = lambda v: parse_clock(v, start)  # noqa: E731

    k = data["kitchen"]
    kitchen = KitchenGrid(k["map"], {sid: tuple(c) for sid, c in k.get("access", {}).items()})
    for sid, cfg in k.get("stations", {}).items():
        st = kitchen.stations[sid]
        st.max_batch = int(cfg.get("max_batch", st.max_batch))
        st.failed = bool(cfg.get("failed", False))
        st.stock = {ing: float(kg) for ing, kg in cfg.get("stock", {}).items()}

    places = [
        Place(id=pid, kind=p["kind"], x=float(p["xy"][0]), y=float(p["xy"][1]), label=p.get("label", pid),
              people=int(p.get("people", 0)))
        for pid, p in data["network"]["places"].items()
    ]
    roads = [
        Road(id=rid, a=r[0], b=r[1], minutes=float(r[2]), open=(len(r) < 4 or r[3] != "closed"))
        for rid, r in data["network"]["roads"].items()
    ]

    agents = {
        aid: Agent(id=aid, kind=a.get("kind", "human"), skills=set(a["skills"]), home=tuple(a["home"]),
                   shift_start=clk(a.get("shift", ["00:00", "23:59"])[0]) if "shift" in a else 0,
                   shift_end=clk(a["shift"][1]) if "shift" in a else 10_000)
        for aid, a in data["agents"].items()
    }
    stages = [
        Stage(name=s["name"], skill=s["skill"], station_type=s["station"], minutes=int(s["minutes"]),
              after=list(s.get("after", [])))
        for s in data["stages"]
    ]
    recipes = {
        rid: Recipe(id=rid, name=r.get("name", rid), tags=set(r.get("tags", [])),
                    allergens=set(r.get("allergens", [])), per_meal={i: float(q) for i, q in r["per_meal"].items()},
                    main_ingredient=r.get("main", next(iter(r["per_meal"]))), overrides=r.get("overrides", {}))
        for rid, r in data["recipes"].items()
    }
    orders = [
        Order(id=o["id"], destination=o["destination"], meals=int(o["meals"]), diet=set(o.get("diet", [])),
              deadline=clk(o["deadline"]), priority=int(o.get("priority", 1)), release=clk(o.get("release", 0)))
        for o in data["orders"]
    ]
    vehicles = {
        vid: Vehicle(id=vid, capacity=int(v["capacity"]), speed=float(v.get("speed", 1.0)),
                     available_from=clk(v.get("available_from", 0)))
        for vid, v in data["vehicles"].items()
    }
    events = [Event(kind=e["kind"], params={k2: v for k2, v in e.items() if k2 not in ("kind", "label")},
                    label=e.get("label", "")) for e in data.get("events", [])]
    return Scenario(
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        start_clock=start,
        slot_minutes=int(data.get("slot_minutes", 10)),
        horizon=clk(data.get("end", "16:00")),
        batch_size=int(data.get("batch_size", 50)),
        max_hold=int(data.get("food_safety", {}).get("max_hold_minutes", 150)),
        kitchen=kitchen,
        roads=RoadNetwork(places, roads),
        agents=agents,
        stages=stages,
        recipes=recipes,
        orders=orders,
        vehicles=vehicles,
        events=events,
        path=str(path),
    )
