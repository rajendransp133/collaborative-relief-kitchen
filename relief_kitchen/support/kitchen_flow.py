"""What happens in the kitchen over time, derived from the CSP schedule (pure functions).

The allocation only says "task X: agent A at station S from t0 to t1". This module turns that into
the facts the visualiser and the report show:

* stock withdrawals: each fetch takes its batch's ingredients from the shelves, so per-shelf
  stock goes down during the day;
* batch journeys: where each batch of food is at any minute - on a shelf, carried by an agent,
  being prepped or cooked on a station, waiting, at the door, or in a vehicle;
* station and agent activity at a given minute (used for hover tooltips).

Every task starts with a carry-in: its agent walks to the previous station of the same batch,
picks it up and brings it over. The last stage ends with a carry-out to the dispatch door.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..algorithms.grid_search import bfs_distances
from .env.kitchen_grid import stations_of
from .env.scenario import Scenario
from .records import Allocation, ScheduledTask

STAGE_VERB = {"fetch": "Collecting ingredients", "prep": "Washing and cutting", "cook": "Cooking",
              "pack": "Packing"}


@dataclass(frozen=True)
class Withdrawal:
    minute: int
    shelf: str
    ingredient: str
    kg: float
    task: str


@dataclass(frozen=True)
class Leg:
    """One piece of a batch's journey."""

    start: float
    end: float
    kind: str  # walking, collecting, carried, working, waiting, to_door, at_door, in_vehicle, delivered
    where: str  # station or vehicle id (for "carried": destination station)
    who: str = ""  # agent or vehicle
    task: str = ""
    origin: str = ""  # for "carried": station the batch was picked up from


# ---------------------------------------------------------------------------------------------
# small helpers over the allocation
# ---------------------------------------------------------------------------------------------
def batch_key(t: ScheduledTask) -> tuple[str, int]:
    return (t.order, t.batch)


def tasks_by_batch(alloc: Allocation) -> dict[tuple[str, int], list[ScheduledTask]]:
    out: dict[tuple[str, int], list[ScheduledTask]] = {}
    for t in sorted(alloc.tasks, key=lambda t: t.start):
        out.setdefault(batch_key(t), []).append(t)
    return out


def previous_task(alloc: Allocation, task: ScheduledTask) -> ScheduledTask | None:
    """The task of the same batch that ran just before (its station is where the carry-in starts)."""
    chain = tasks_by_batch(alloc)[batch_key(task)]
    i = chain.index(task)
    return chain[i - 1] if i > 0 else None


def door_station(sc: Scenario) -> str | None:
    doors = stations_of(sc.kitchen, "dispatch")
    return doors[0].id if doors else None


# ---------------------------------------------------------------------------------------------
# stock
# ---------------------------------------------------------------------------------------------
def stock_withdrawals(sc: Scenario, alloc: Allocation) -> list[Withdrawal]:
    """Ingredients taken at the start of each fetch's collecting work: the CSP-assigned shelf
    first, then the nearest other shelves until the batch's need is covered."""
    left = {st.id: dict(st.stock) for st in stations_of(sc.kitchen, "storage")}
    out: list[Withdrawal] = []
    for t in sorted((t for t in alloc.tasks if sc.kitchen.stations[t.station].type == "storage"),
                    key=lambda t: t.start):
        recipe = sc.recipes[t.recipe]
        home = sc.kitchen.stations[t.station]
        dist = bfs_distances(sc.kitchen, home.access)
        shelves = sorted(left, key=lambda sid: (sid != t.station, dist.get(sc.kitchen.stations[sid].access, 999), sid))
        for ing, per_meal in recipe.per_meal.items():
            need = per_meal * t.meals
            for sid in shelves:
                if need <= 1e-9:
                    break
                take = min(need, left[sid].get(ing, 0.0))
                if take > 1e-9:
                    left[sid][ing] -= take
                    need -= take
                    out.append(Withdrawal(t.start + t.carry_in, sid, ing, round(take, 3), t.id))
    return out


def stock_at(sc: Scenario, withdrawals: list[Withdrawal], minute: float) -> dict[str, dict[str, float]]:
    """Per-shelf stock (kg) at `minute`."""
    stock = {st.id: dict(st.stock) for st in stations_of(sc.kitchen, "storage")}
    for w in withdrawals:
        if w.minute <= minute:
            stock[w.shelf][w.ingredient] = max(0.0, stock[w.shelf].get(w.ingredient, 0.0) - w.kg)
    return stock


# ---------------------------------------------------------------------------------------------
# batch journeys
# ---------------------------------------------------------------------------------------------
def batch_journey(sc: Scenario, alloc: Allocation, key: tuple[str, int],
                  arrivals: dict[tuple[str, str], float] | None = None) -> list[Leg]:
    """Ordered legs of one batch from the shelf to the vehicle.

    `arrivals` (from the motion planner) gives the minute an agent actually reached its pickup,
    work or door cell, so food tokens move exactly with the animated agents. Without it the
    middle of the carry-in is used as the pickup time."""
    arrivals = arrivals or {}
    chain = tasks_by_batch(alloc)[key]
    delivery = next(d for d in alloc.deliveries if d.order == key[0])
    door = door_station(sc) or chain[-1].station
    legs: list[Leg] = []
    prev: ScheduledTask | None = None
    for t in chain:
        work_start = t.start + t.carry_in
        work_end = t.end - t.carry_out
        if prev is None:
            # the fetch agent walks to the shelf, then collects the ingredients there
            legs.append(Leg(work_start, work_end, "collecting", t.station, t.agent, t.id))
        else:
            pickup = min(arrivals.get((t.id, "pickup"), t.start + t.carry_in / 2), work_start)
            arrive = min(max(arrivals.get((t.id, "work"), work_start), pickup), work_start)
            legs.append(Leg(prev.end, pickup, "waiting", prev.station, "", t.id))
            legs.append(Leg(pickup, arrive, "carried", t.station, t.agent, t.id, prev.station))
            legs.append(Leg(arrive, work_end, "working", t.station, t.agent, t.id))
        if t.carry_out:
            at_door = min(max(arrivals.get((t.id, "door"), t.end), work_end), t.end)
            legs.append(Leg(work_end, at_door, "to_door", door, t.agent, t.id, t.station))
            legs.append(Leg(at_door, t.end, "at_door", door, "", t.id))
        prev = t
    legs.append(Leg(prev.end, delivery.depart, "at_door", door, "", prev.id))
    legs.append(Leg(delivery.depart, delivery.arrive, "in_vehicle", delivery.vehicle, delivery.vehicle))
    legs.append(Leg(delivery.arrive, 1e9, "delivered", delivery.destination, delivery.vehicle))
    return [leg for leg in legs if leg.end > leg.start]


def leg_at(legs: list[Leg], minute: float) -> Leg | None:
    """The leg in progress at `minute` (None before the batch exists)."""
    return next((leg for leg in legs if leg.start <= minute < leg.end), None)


def batch_status(leg: Leg | None, task_stage: str = "") -> str:
    """Short human-readable status of a batch."""
    if leg is None:
        return "not started"
    return {
        "collecting": "ingredients being collected",
        "carried": f"carried to {leg.where} by {leg.who}",
        "working": f"{STAGE_VERB.get(task_stage, 'in work').lower()} at {leg.where}",
        "waiting": f"waiting at {leg.where}",
        "to_door": f"carried to the door by {leg.who}",
        "at_door": "packed, waiting at the door",
        "in_vehicle": f"on vehicle {leg.where}",
        "delivered": f"delivered to {leg.where}",
    }.get(leg.kind, leg.kind)


# ---------------------------------------------------------------------------------------------
# activity at a minute (tooltips)
# ---------------------------------------------------------------------------------------------
def task_phase(t: ScheduledTask, minute: float) -> str:
    """'carry-in', 'work' or 'carry-out' for a task in progress."""
    if minute < t.start + t.carry_in:
        return "carry-in"
    if minute >= t.end - t.carry_out:
        return "carry-out"
    return "work"


def station_activity(alloc: Allocation, station: str, minute: float):
    """(current task or None, upcoming tasks) at a station."""
    here = sorted((t for t in alloc.tasks if t.station == station), key=lambda t: t.start)
    now = next((t for t in here if t.start <= minute < t.end), None)
    return now, [t for t in here if t.start > minute]


def agent_activity(alloc: Allocation, agent: str, minute: float):
    """(current task or None, phase, next task or None) for an agent."""
    mine = sorted((t for t in alloc.tasks if t.agent == agent), key=lambda t: t.start)
    now = next((t for t in mine if t.start <= minute < t.end), None)
    nxt = next((t for t in mine if t.start > minute), None)
    return now, (task_phase(now, minute) if now else "idle"), nxt
