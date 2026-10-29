"""Records (plain dataclasses) used by the algorithms in `relief_kitchen.algorithms`.

Kept here so the algorithm files open straight on the logic.
"""

from __future__ import annotations

from typing import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .env.entities import Cell, Order
    from .env.scenario import Scenario
    from .kitchen_flow import Withdrawal
    from .motion import KitchenMotion
    from .task_graph import TaskGraph

Check = Callable[[dict], bool]  # partial assignment -> still consistent?
Revise = Callable[[str, str, dict], list]  # (xi, xj, domains) -> pruned domain of xi


# ---------------------------------------------------------------------------------------------
# CSP
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Constraint:
    scope: tuple[str, ...]
    check: Check
    category: str
    description: str
    meta: dict = field(default_factory=dict)  # free-form tags, e.g. orders=..., kind=...
    revise: Revise | None = None  # optional fast AC-3 revise for binary constraints


@dataclass(frozen=True)
class CSP:
    domains: dict[str, list]
    constraints: list[Constraint]
    priority: dict[str, tuple]  # static tie-break for variable ordering


@dataclass
class SolveStats:
    nodes: int = 0  # values tried during search
    backtracks: int = 0
    pruned: int = 0  # values removed by consistency checks
    seconds: float = 0.0


@dataclass(frozen=True)
class SolveResult:
    status: str  # "solved" | "infeasible" | "budget" (node limit reached, treated as infeasible)
    solution: dict | None
    stats: SolveStats
    wipeout: Constraint | None = None  # constraint that emptied a domain before search, if any
    ok: bool = False  # status == "solved"


# ---------------------------------------------------------------------------------------------
# routes and multi-agent paths
# ---------------------------------------------------------------------------------------------
@dataclass
class Route:
    origin: str
    destination: str
    nodes: list[str]
    roads: list[str]
    minutes: float
    expanded: int = 0


@dataclass
class MAPFResult:
    paths: dict[str, list[Cell]]
    ok: bool = True
    note: str = ""


# ---------------------------------------------------------------------------------------------
# the kitchen model and its decoded solution
# ---------------------------------------------------------------------------------------------
@dataclass
class ScheduledTask:
    id: str
    order: str
    batch: int
    stage: str
    meals: int
    agent: str
    station: str
    start: int  # minutes after the scenario start
    end: int
    carry_in: int = 0  # first minutes: fetching the batch from the previous station
    work: int = 0  # then the actual cooking / prep / packing
    carry_out: int = 0  # last stage only: final minutes carrying meals to the dispatch door
    recipe: str = ""


@dataclass
class Delivery:
    order: str
    destination: str
    vehicle: str
    depart: int
    arrive: int
    back: int  # vehicle is free again at the depot
    route: Route | None
    meals: int
    recipe: str


@dataclass
class Allocation:
    variants: dict[str, str]
    tasks: list[ScheduledTask]
    deliveries: list[Delivery]
    result: SolveResult


@dataclass(frozen=True)
class KitchenModel:
    scenario: Scenario
    orders: list[Order]
    csp: CSP
    graphs: dict[str, TaskGraph]
    dur: dict[str, int]  # task id -> duration in slots
    routes: dict[str, Route | None]  # depot -> place over open roads (None = unreachable)
    relaxed_routes: dict[str, Route | None]  # same, ignoring closures (to time a hypothetical trip)


# ---------------------------------------------------------------------------------------------
# diagnosis and the end-to-end result
# ---------------------------------------------------------------------------------------------
@dataclass
class Cause:
    category: str
    detail: str


@dataclass(frozen=True)
class Diagnosis:
    order: str
    destination: str
    meals: int
    mode: str  # "isolated": impossible on its own | "contention": clashes with accepted orders
    causes: list[Cause]
    categories: list[str]  # distinct cause categories, in CATEGORY_ORDER


@dataclass
class M1Result:
    scenario: Scenario
    label: str
    accepted: list[Order]
    allocation: Allocation | None
    diagnoses: dict[str, Diagnosis]  # rejected order id -> why
    routes: dict[str, Route | None]
    motion: KitchenMotion | None
    ingredient_plan: dict[str, dict[str, list]] = field(default_factory=dict)
    nearest: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    seconds: float = 0.0
    withdrawals: list[Withdrawal] = field(default_factory=list)  # stock taken from shelves over the day
