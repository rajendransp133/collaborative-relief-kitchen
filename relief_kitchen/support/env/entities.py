"""Entities: plain records shared by every module, plus the few functions that read them.

Records hold data only (no methods); behaviour lives in module-level functions.
Times are minutes after the scenario's start clock (e.g. 0 = 08:00); quantities are kilograms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

Cell = Tuple[int, int]  # (row, col) on the kitchen grid


@dataclass
class Agent:
    id: str
    kind: str  # "human" or "robot"
    skills: set[str]
    home: Cell
    shift_start: int = 0
    shift_end: int = 10_000


@dataclass
class Station:
    id: str
    type: str  # storage, prep, stove, packaging, dispatch
    cell: Cell
    access: Cell | None = None  # floor cell an agent stands on to use it
    max_batch: int = 10_000  # equipment capacity (meals per batch)
    failed: bool = False
    stock: dict[str, float] = field(default_factory=dict)  # only for storage shelves


@dataclass
class Stage:
    """One step of the per-batch task DAG (fetch -> prep -> cook -> pack)."""

    name: str
    skill: str
    station_type: str
    minutes: int
    after: list[str] = field(default_factory=list)


@dataclass
class Recipe:
    id: str
    name: str
    tags: set[str]  # vegetarian, diabetic, soft, ...
    allergens: set[str]  # nuts, gluten, dairy, ...
    per_meal: dict[str, float]  # ingredient -> kg per meal
    main_ingredient: str
    overrides: dict[str, dict] = field(default_factory=dict)  # stage -> {station, minutes}


@dataclass
class Order:
    id: str
    destination: str
    meals: int
    diet: set[str]
    deadline: int
    priority: int = 1  # higher is more urgent (hospital = 3)
    release: int = 0  # earliest time cooking may start


@dataclass
class Vehicle:
    id: str
    capacity: int
    speed: float = 1.0  # multiplier on road travel time (2.0 = twice as fast)
    available_from: int = 0


# ---------------------------------------------------------------------------------------------
# functions over entities
# ---------------------------------------------------------------------------------------------
def agent_available(agent: Agent, start: int, end: int) -> bool:
    """Does [start, end) fall inside the agent's shift?"""
    return agent.shift_start <= start and end <= agent.shift_end


def recipe_satisfies(recipe: Recipe, diet: set[str]) -> bool:
    """`diet` holds tags like "diabetic" or allergen-free tags like "nut_free"."""
    for need in diet:
        if need.endswith("_free"):
            if need[: -len("_free")] in recipe.allergens:
                return False
        elif need not in recipe.tags:
            return False
    return True


def recipe_station(recipe: Recipe, stage: Stage) -> str:
    """Station type the recipe needs for a stage (a recipe may override a stage's station)."""
    return recipe.overrides.get(stage.name, {}).get("station", stage.station_type)


def recipe_minutes(recipe: Recipe, stage: Stage) -> int:
    return recipe.overrides.get(stage.name, {}).get("minutes", stage.minutes)
