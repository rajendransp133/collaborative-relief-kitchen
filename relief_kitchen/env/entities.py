"""Plain data classes shared by every module.

Times are minutes after the scenario's start clock (e.g. 0 = 08:00); quantities are kilograms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Cell = tuple[int, int]  # (row, col) on the kitchen grid


@dataclass
class Agent:
    id: str
    kind: str  # "human" or "robot"
    skills: set[str]
    home: Cell
    shift_start: int = 0
    shift_end: int = 10_000

    def available(self, start: int, end: int) -> bool:
        return self.shift_start <= start and end <= self.shift_end


@dataclass
class Station:
    id: str
    type: str  # storage, prep, stove, steamer, packaging, dispatch
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

    def satisfies(self, diet: set[str]) -> bool:
        """`diet` holds tags like "diabetic" or allergen-free tags like "nut_free"."""
        for need in diet:
            if need.endswith("_free"):
                if need[: -len("_free")] in self.allergens:
                    return False
            elif need not in self.tags:
                return False
        return True

    def stage_station(self, stage: Stage) -> str:
        return self.overrides.get(stage.name, {}).get("station", stage.station_type)

    def stage_minutes(self, stage: Stage) -> int:
        return self.overrides.get(stage.name, {}).get("minutes", stage.minutes)


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
