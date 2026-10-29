"""After the CSP: collision-free motion, pick lists, nearest stations and shelf withdrawals for the
accepted orders (what the visualiser and the report show)."""

from __future__ import annotations

from .env.entities import Order
from .env.kitchen_grid import stations_of
from .env.scenario import Scenario
from .kitchen_flow import stock_withdrawals
from .locate import locate_ingredients, nearest_station
from .motion import plan_kitchen_motion
from .records import Allocation


def enrich(sc: Scenario, alloc: Allocation | None, accepted: list[Order]) -> dict:
    """Keyword arguments for `M1Result`: motion, ingredient_plan, nearest and withdrawals."""
    if alloc is None:
        return dict(motion=None, ingredient_plan={}, nearest={}, withdrawals=[])
    # pick lists: nearest shelves first, measured by BFS from the dispatch door
    door = stations_of(sc.kitchen, "dispatch")
    origin = door[0].access if door else next(iter(sc.agents.values())).home
    ingredient_plan = {}
    for o in accepted:
        r = sc.recipes[alloc.variants[o.id]]
        ingredient_plan[o.id] = locate_ingredients(sc.kitchen, origin, {i: q * o.meals for i, q in r.per_meal.items()})
    centre = list(sc.agents.values())[len(sc.agents) // 2].home
    nearest = {}
    for stype in ("storage", "prep", "stove", "packaging"):
        hit = nearest_station(sc.kitchen, centre, stype)
        nearest[stype] = f"{hit.station.id} ({hit.distance} steps)" if hit else "none working"
    return dict(motion=plan_kitchen_motion(sc, alloc), ingredient_plan=ingredient_plan, nearest=nearest,
                withdrawals=stock_withdrawals(sc, alloc))
