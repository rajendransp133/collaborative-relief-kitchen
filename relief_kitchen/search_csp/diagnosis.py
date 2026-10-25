"""Infeasibility diagnosis: *why* can't an order be scheduled?

Two simple steps.

1. Direct checks, one per category, with no search. Each tests a necessary condition:
     dietary      some recipe satisfies the diet
     ingredients  some diet-safe recipe fits the stock left after the accepted orders
     equipment    that recipe's stages each have a working station big enough
     staff        every needed skill has an agent on shift after the order arrives
     transport    an open road reaches the destination and a vehicle is big enough
     time         release + critical path of the task DAG + fastest drive <= deadline
   A failed check is a definite cause ("isolated": the order is impossible on its own).

2. Relax one category at a time. If every check passes but the CSP still fails, the order is
   competing with the already-accepted orders (or the combination is too tight). For each category,
   drop that category's constraints for this order only and re-solve. Any category whose removal
   makes the order fit is reported as a cause.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..env.entities import Order
from ..env.entities import recipe_station
from ..env.kitchen_grid import stations_of
from ..env.road_network import closed_roads
from ..env.scenario import Scenario, clock, total_stock
from .allocation import build_model, compatible_variants, effective_batch_size, solve_model, transfer_budgets
from .routing import astar_route
from .task_graph import build_task_graph, critical_path_minutes

CATEGORY_ORDER = ["ingredients", "equipment", "staff", "time", "transport", "dietary", "safety", "collision", "priority"]


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


def make_diagnosis(order: Order, destination: str, mode: str, causes: list[Cause]) -> Diagnosis:
    seen = {c.category for c in causes}
    return Diagnosis(order.id, destination, order.meals, mode, causes, [c for c in CATEGORY_ORDER if c in seen])


def summary(d: Diagnosis) -> str:
    return f"{d.order} ({d.destination}, {d.meals} meals): {' + '.join(d.categories) or 'unknown'}"


def diagnose_order(sc: Scenario, order: Order, accepted: list[Order], hints: dict | None = None,
                   node_limit: int = 1_500) -> Diagnosis:
    dest = sc.roads.places[order.destination].label
    causes = direct_checks(sc, order, accepted, hints or {})
    if causes:
        return make_diagnosis(order, dest, "isolated", causes)

    # Step 2. Contention if the order fits on its own; otherwise relax within the order alone.
    alone = build_model(sc, [order])
    contention = bool(accepted) and solve_model(alone, node_limit=node_limit).ok
    model = build_model(sc, accepted + [order]) if contention else alone
    for cat in CATEGORY_ORDER:
        def keep(c, _cat=cat):
            return not (c.category == _cat and order.id in c.meta.get("orders", ()))

        if any(not keep(c) for c in model.csp.constraints) and \
                solve_model(model, hints=hints if contention else None, node_limit=node_limit, keep=keep).ok:
            causes.append(Cause(cat, _relaxed_sentence(sc, order, cat, contention)))
    if not causes:  # no single category is to blame: everything is simply too tight
        causes.append(Cause("time", f"no schedule meets the {clock(sc, order.deadline)} deadline with the "
                                    "resources left"))
    return make_diagnosis(order, dest, "contention" if contention else "isolated", causes)


# ---------------------------------------------------------------------------------------------
# step 1: direct checks
# ---------------------------------------------------------------------------------------------
def direct_checks(sc: Scenario, order: Order, accepted: list[Order], hints: dict) -> list[Cause]:
    causes: list[Cause] = []
    diet = ", ".join(sorted(order.diet)) or "no restriction"
    recipes = compatible_variants(sc, order)
    if not recipes:
        return [Cause("dietary", f"no recipe satisfies the diet [{diet}]")]

    # ingredients: stock minus what the accepted orders' chosen menus already use
    left = total_stock(sc)
    for o in accepted:
        rid = hints.get(f"{o.id}.variant")
        for ing, q in (sc.recipes[rid].per_meal.items() if rid else []):
            left[ing] = left.get(ing, 0.0) - q * o.meals
    shelved = {ing for st in stations_of(sc.kitchen, "storage") for ing, kg in st.stock.items() if kg > 0}
    stocked, shortages = [], []
    for r in recipes:
        short = [f"{ing} {q * order.meals:.1f} kg needed, {max(left.get(ing, 0.0), 0):.1f} kg left"
                 for ing, q in r.per_meal.items() if q * order.meals > left.get(ing, 0.0) + 1e-6]
        if r.main_ingredient not in shelved:
            short.insert(0, f"no shelf holds {r.main_ingredient}")
        if short:
            shortages.append(f"{r.name} ({'; '.join(short)})")
        else:
            stocked.append(r)
    if not stocked:
        causes.append(Cause("ingredients", "no diet-safe menu can be cooked: " + ", ".join(shortages)))

    # equipment: each stage of the recipe needs a working station of the right type and size
    grid, broken = sc.kitchen, []
    for r in stocked or recipes:
        batch = effective_batch_size(sc, [r])
        for stage in sc.stages:
            stype = recipe_station(r, stage)
            working = stations_of(grid, stype, working_only=True)
            if not working:
                failed = [s.id for s in stations_of(grid, stype)]
                broken.append(f"{r.name} needs a {stype}" + (f" ({', '.join(failed)} failed)" if failed else ""))
            elif max(s.max_batch for s in working) < min(batch, order.meals):
                broken.append(f"{r.name}: no working {stype} takes a {batch}-meal batch")
    if broken and len(broken) >= len(stocked or recipes):
        causes.append(Cause("equipment", "; ".join(broken)))

    # staff: every skill must have someone on shift between the order's release and its deadline
    for stage in sc.stages:
        able = [a for a in sc.agents.values() if stage.skill in a.skills]
        if not able:
            causes.append(Cause("staff", f"no agent has the skill '{stage.skill}'"))
        elif not any(a.shift_end > order.release and a.shift_start < order.deadline for a in able):
            shifts = ", ".join(f"{a.id} until {clock(sc, max(a.shift_end, 0))}" for a in able)
            causes.append(Cause("staff", f"everyone who can '{stage.skill}' is off shift after the order arrives at "
                                         f"{clock(sc, order.release)} ({shifts})"))

    # transport
    route = astar_route(sc.roads, sc.roads.depot, order.destination)
    if route is None:
        closed = ", ".join(closed_roads(sc.roads))
        causes.append(Cause("transport", f"no open road from the kitchen to "
                                         f"{sc.roads.places[order.destination].label} (closed: {closed})"))
    biggest = max(v.capacity for v in sc.vehicles.values())
    if biggest < order.meals:
        causes.append(Cause("transport", f"largest vehicle carries {biggest} meals, order needs {order.meals}"))

    # time: lower bound on arrival = release + longest task chain + fastest possible drive
    drive_route = route or astar_route(sc.roads, sc.roads.depot, order.destination, include_closed=True)
    if drive_route is not None:
        g = build_task_graph(order, sc.stages, recipes, effective_batch_size(sc, recipes), transfer_budgets(sc))
        chain = critical_path_minutes(g)
        drive = drive_route.minutes / max(v.speed for v in sc.vehicles.values())
        earliest = order.release + chain + drive
        if earliest > order.deadline:
            causes.append(Cause("time", f"deadline {clock(sc, order.deadline)}, but the earliest possible arrival is "
                                        f"{clock(sc, earliest)} ({chain} min of kitchen work + {drive:.0f} min drive)"))
    return causes


# ---------------------------------------------------------------------------------------------
# step 2: wording for a category whose relaxation lets the order through
# ---------------------------------------------------------------------------------------------
def _relaxed_sentence(sc: Scenario, order: Order, category: str, contention: bool) -> str:
    who = " by higher-priority orders" if contention else ""
    return {
        "staff": f"staff with the needed skills are fully booked{who}",
        "equipment": f"stoves, counters or packing tables are fully booked{who}",
        "transport": f"every vehicle big enough is busy{who}",
        "time": f"the {clock(sc, order.deadline)} deadline is too tight" + (" once higher-priority orders are scheduled"
                                                                            if contention else ""),
        "ingredients": f"the remaining stock is taken{who}",
        "safety": f"food would wait more than {sc.max_hold} min between cooking and serving",
        "collision": "stations sharing one access cell cannot be worked at the same time",
        "priority": "higher-priority orders must leave first on a shared vehicle",
        "dietary": "the diet-safe menus do not fit",
    }[category]
