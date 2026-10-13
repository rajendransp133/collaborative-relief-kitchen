"""Infeasibility diagnosis.

When an order cannot be scheduled, QuickXplain (Junker, 2004) searches the order's relaxable
constraint groups (deadline, route, stock, skills, station occupancy, ...) for a *minimal* subset
that, together with the fixed background (task-graph precedence, the planning horizon and the
already-accepted orders), is still unsatisfiable. Each group maps to a category - ingredients,
equipment, staff, time, transport (plus dietary, safety, collision and priority) - and to a concrete
sentence built from the scenario, so the report says *why*, e.g.

    O4 (Stadium Shelter C, 80 meals): transport + time
      - transport: no open road from Kitchen to Stadium Shelter C (closed: R12, R13)
      - time: ...
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..env.entities import Order
from ..env.scenario import Scenario
from .allocation import KitchenModel, build_model, compatible_variants, solve_model
from .routing import astar_route

CATEGORY_ORDER = ["ingredients", "equipment", "staff", "time", "transport", "dietary", "safety", "collision", "priority"]


@dataclass
class Cause:
    kind: str
    category: str
    detail: str


@dataclass
class Diagnosis:
    order: str
    destination: str
    meals: int
    mode: str  # isolated (infeasible on its own) | contention (conflicts with higher-priority orders)
    causes: list[Cause]
    checks: int  # consistency checks QuickXplain needed
    exact: bool = True  # False if a search budget was hit during the explanation
    alternatives: list[str] = field(default_factory=list)

    @property
    def categories(self) -> list[str]:
        seen = {c.category for c in self.causes}
        return [c for c in CATEGORY_ORDER if c in seen]

    def summary(self) -> str:
        cats = " + ".join(self.categories) or "unknown"
        return f"{self.order} ({self.destination}, {self.meals} meals): {cats}"


# ---------------------------------------------------------------------------------------------
# QuickXplain
# ---------------------------------------------------------------------------------------------
def quickxplain(candidates: list[str], consistent) -> list[str] | None:
    """Minimal subset of `candidates` that is inconsistent with the background.

    `consistent(set_of_candidates)` tests background + those candidates. Returns None when all
    candidates together are consistent (no conflict), [] when the background alone is inconsistent.
    """
    if consistent(frozenset(candidates)):
        return None

    def qx(base: frozenset, delta: bool, cands: list[str]) -> list[str]:
        if delta and not consistent(base):
            return []
        if len(cands) == 1:
            return list(cands)
        k = len(cands) // 2
        c1, c2 = cands[:k], cands[k:]
        d2 = qx(base | frozenset(c1), bool(c1), c2)
        d1 = qx(base | frozenset(d2), bool(d2), c1)
        return d1 + d2

    return qx(frozenset(), True, list(candidates))


# order matters: QuickXplain adds earlier candidates to the background first, so when several
# minimal conflicts exist it reports the one built from the earliest kinds. Hard blockers (diet,
# failed equipment, closed roads) come first; soft, "could wait" ones such as the deadline last.
KIND_PREFERENCE = [
    "precedence", "dietary", "located", "station-type", "skill", "working", "capacity", "route",
    "vehicle-capacity", "vehicle-available", "release", "stock", "shift", "workspace", "allergen", "holding",
    "occupancy", "agent-booking", "vehicle-booking", "priority", "deadline",
]


class _Unknown(Exception):
    """A consistency check ran out of search budget."""


def diagnose_order(sc: Scenario, order: Order, accepted: list[Order], hints: dict | None = None,
                   node_limit: int = 2_500, alternatives: bool = True) -> Diagnosis:
    """Explain why `order` cannot be added to the already accepted orders.

    1. Solve the order alone. If that fails the order is infeasible in itself ("isolated");
       otherwise it conflicts with higher-priority work ("contention").
    2. QuickXplain over the order's relaxable constraint kinds gives a minimal conflict.
    3. If a check exhausts its search budget, fall back to correction sets: the kinds whose
       relaxation alone makes the order schedulable (cheap, because finding a schedule is easy).
    4. In contention mode, a capacity analysis names the saturated resource (staff, stations,
       vehicles) from the accepted schedule.
    """
    iso = build_model(sc, [order])
    iso_res = solve_model(iso, node_limit=node_limit)
    if iso_res.ok and accepted:
        model, mode = build_model(sc, accepted + [order]), "contention"
    else:
        model, mode, hints = iso, "isolated", None

    def key(c):
        if c.relaxable and order.id in c.meta.get("orders", ()):
            return c.meta.get("kind", c.group)
        return None  # background

    kinds = sorted({k for c in model.csp.constraints if (k := key(c)) is not None},
                   key=lambda k: KIND_PREFERENCE.index(k) if k in KIND_PREFERENCE else len(KIND_PREFERENCE))
    cache: dict[frozenset, bool | None] = {}

    def check(groups: frozenset, limit: int) -> bool | None:
        if groups not in cache:
            res = solve_model(model, hints=hints, node_limit=limit,
                              constraints=lambda c: key(c) is None or key(c) in groups)
            cache[groups] = None if res.status == "budget" else res.ok
        return cache[groups]

    def consistent(groups: frozenset) -> bool:
        r = check(groups, node_limit)
        if r is None:
            raise _Unknown
        return r

    exact = True
    try:
        conflict = quickxplain(kinds, consistent)
        if conflict is None:
            conflict = []
    except _Unknown:
        exact = False
        everything = frozenset(kinds)
        conflict = [k for k in kinds if check(everything - {k}, 1_000)]  # single-kind corrections
    causes = [Cause(k, _category(model, k), explain(k, sc, model, order, accepted, hints)) for k in conflict]
    if mode == "contention":
        for c in bottlenecks(sc, model, order, accepted, hints):
            if (c.kind, c.category) not in {(x.kind, x.category) for x in causes}:
                causes.append(c)
    if not causes:
        causes = [Cause("horizon", "time", "cannot be finished within the planning day")]
    diag = Diagnosis(order.id, sc.roads.places[order.destination].label, order.meals, mode, causes,
                     len(cache), exact=exact)
    if alternatives:
        diag.alternatives = suggest_alternatives(sc, order, accepted, hints, diag)
    return diag


def bottlenecks(sc: Scenario, model: KitchenModel, order: Order, accepted: list[Order],
                hints: dict | None) -> list[Cause]:
    """Capacity left for `order` before its latest possible finish, per resource pool."""
    if not hints:
        return []
    S = sc.slot_minutes
    g = model.graphs[order.id]
    route = model.routes.get(order.destination)
    if route is None:
        return []
    fastest = max(v.speed for v in sc.vehicles.values())
    latest_depart = order.deadline - route.minutes / fastest
    # latest end of each task = latest departure minus the longest chain still to come after it
    tail: dict[str, int] = {}
    for n in reversed(g.topological_order()):
        succ = [m for m in g.nodes.values() if n in m.preds]
        tail[n] = max([tail[m.id] + g.nodes[m.id].minutes for m in succ if m.id != g.dispatch] + [0])
    earliest = g.earliest_starts(order.release)
    out = []
    booked_tasks = [(k, v) for k, v in hints.items() if not k.endswith((".variant", ".dispatch"))]

    def pool_report(label, category, kind, members, task_ids):
        t1 = min(earliest[t] for t in task_ids)
        t2 = max(latest_depart - tail[t] for t in task_ids)
        if t2 <= t1:
            return
        cap = len(members) * (t2 - t1)
        booked = 0.0
        for k, v in booked_tasks:
            if (v[0] if kind == "agent-booking" else v[1]) in members:
                s0, s1 = v[2] * S, (v[2] + model.dur[k]) * S
                booked += max(0.0, min(s1, t2) - max(s0, t1))
        need = sum(g.nodes[t].minutes for t in task_ids)
        if booked + need > 0.85 * cap:
            pct = 100 * booked / cap
            out.append(Cause(kind, category,
                             f"{label} ({', '.join(sorted(members))}) are {pct:.0f}% booked between "
                             f"{sc.clock(t1)} and {sc.clock(t2)}; {order.id} needs {need} more minutes "
                             f"of {cap - booked:.0f} free"))

    skills = sorted({n.skill for n in g.tasks()})
    for skill in skills:
        members = {a.id for a in sc.agents.values() if skill in a.skills}
        pool_report(f"staff who can '{skill}'", "staff", "agent-booking", members,
                    [n.id for n in g.tasks() if n.skill == skill])
    for stype in sorted({t for n in g.tasks() for t in n.station_types}):
        members = {s.id for s in sc.kitchen.stations_of(stype, working_only=True)}
        if members:
            pool_report(f"{stype} stations", "equipment", "occupancy", members,
                        [n.id for n in g.tasks() if stype in n.station_types])
    # vehicles big enough for the order: are any free for a trip that leaves in time?
    big = [v for v in sc.vehicles.values() if v.capacity >= order.meals]
    if big:
        trip = 2 * route.minutes
        free = []
        for v in big:
            busy = []
            for o in accepted:
                hv = hints.get(f"{o.id}.dispatch")
                if hv and hv[0] == v.id:
                    r = model.routes.get(o.destination)
                    busy.append((hv[1] * S, hv[1] * S + 2 * (r.minutes if r else 0) / v.speed + 10))
            lo = order.release + g.critical_path_minutes()
            hi = order.deadline - route.minutes / v.speed
            t = lo
            while t <= hi:
                if all(t + trip / v.speed <= b0 or t >= b1 for b0, b1 in busy):
                    free.append(v.id)
                    break
                t += S
        if not free:
            out.append(Cause("vehicle-booking", "transport",
                             f"every vehicle that can carry {order.meals} meals ({', '.join(v.id for v in big)}) "
                             f"is on another trip when {order.id} would have to leave"))
    return out


def _category(model: KitchenModel, kind: str) -> str:
    for c in model.csp.constraints:
        if c.meta.get("kind") == kind:
            return c.category
    return "time"


# ---------------------------------------------------------------------------------------------
# human-readable causes
# ---------------------------------------------------------------------------------------------
def _reserved_usage(sc: Scenario, accepted: list[Order], hints: dict | None) -> dict[str, float]:
    use: dict[str, float] = {}
    for o in accepted:
        rid = (hints or {}).get(f"{o.id}.variant")
        if rid:
            for ing, q in sc.recipes[rid].per_meal.items():
                use[ing] = use.get(ing, 0.0) + q * o.meals
    return use


def explain(kind: str, sc: Scenario, model: KitchenModel, order: Order, accepted: list[Order],
            hints: dict | None) -> str:
    dest = sc.roads.places[order.destination].label
    grid = sc.kitchen
    g = model.graphs[order.id]
    compat = compatible_variants(sc, order)
    diet = ", ".join(sorted(order.diet)) or "no restriction"
    if kind == "dietary":
        if not compat:
            return f"no recipe satisfies the diet [{diet}]"
        return f"diet [{diet}] limits the menu to {', '.join(r.name for r in compat)}"
    if kind == "stock":
        stock = sc.stock()
        reserved = _reserved_usage(sc, accepted, hints)
        parts = []
        for r in compat or sc.recipes.values():
            short = []
            for ing, q in r.per_meal.items():
                need = q * order.meals
                left = stock.get(ing, 0.0) - reserved.get(ing, 0.0)
                if need > left + 1e-6:
                    short.append(f"{ing} {need:.1f} kg needed, {max(left, 0):.1f} kg left")
            if short:
                parts.append(f"{r.name}: " + "; ".join(short))
        return "not enough stock for any diet-safe menu - " + " | ".join(parts) if parts else "ingredient stock is exhausted by other orders"
    if kind == "located":
        mains = sorted({r.main_ingredient for r in compat})
        return f"no storage shelf holds {', '.join(mains)}"
    if kind == "skill":
        needed = sorted({n.skill for n in g.tasks()})
        missing = [s for s in needed if not any(s in a.skills for a in sc.agents.values())]
        if missing:
            return f"no agent has the skill(s) {', '.join(missing)}"
        scarce = []
        for s_ in needed:
            who = sorted(a.id for a in sc.agents.values() if s_ in a.skills)
            if len(who) < len(sc.agents) / 2:
                scarce.append(f"only {', '.join(who)} can '{s_}'")
        return "; ".join(scarce) or f"tasks need skills {', '.join(needed)}"
    if kind == "shift":
        parts = []
        for skill in sorted({n.skill for n in g.tasks()}):
            who = [a for a in sc.agents.values() if skill in a.skills]
            if who and all(a.shift_end <= order.release or a.shift_end <= 0 for a in who):
                parts.append(f"everyone who can '{skill}' is off shift "
                             f"({', '.join(f'{a.id} until {sc.clock(max(a.shift_end, 0))}' for a in who)})")
        when = f"order released at {sc.clock(order.release)}" if order.release else ""
        return "; ".join(parts + ([when] if when else [])) or "staff shifts do not cover the work"
    if kind == "working":
        types = sorted({t for n in g.tasks() for t in n.station_types})
        dead = [f"{t}: {', '.join(s.id for s in grid.stations_of(t))} failed" for t in types
                if grid.stations_of(t) and not grid.stations_of(t, working_only=True)]
        return "; ".join(dead) or "required equipment has failed"
    if kind == "capacity":
        parts = []
        for n in g.tasks():
            for t in n.station_types:
                ok = [s for s in grid.stations_of(t, working_only=True)]
                if ok and max(s.max_batch for s in ok) < n.meals:
                    parts.append(f"{n.meals}-meal batch exceeds every working {t} (max {max(s.max_batch for s in ok)})")
        return "; ".join(sorted(set(parts))) or "batches exceed equipment capacity"
    if kind == "station-type":
        return f"the diet-safe menu needs {', '.join(sorted({t for n in g.tasks() for t in n.station_types}))}"
    if kind == "release":
        return f"order only arrives at {sc.clock(order.release)}"
    if kind == "route":
        relaxed = astar_route(sc.roads, sc.roads.depot, order.destination, include_closed=True)
        closed = sorted(set(relaxed.roads) & set(sc.roads.closed_roads())) if relaxed else []
        all_closed = sorted(sc.roads.closed_roads())
        return (f"no open road from Kitchen to {dest} (closed: {', '.join(all_closed or closed)})")
    if kind == "vehicle-capacity":
        cap = max(v.capacity for v in sc.vehicles.values())
        return f"largest vehicle carries {cap} meals, order needs {order.meals} in one trip"
    if kind == "vehicle-available":
        return "no vehicle is available in time"
    if kind == "deadline":
        route = model.routes.get(order.destination) or model.relaxed_routes.get(order.destination)
        fastest = max(v.speed for v in sc.vehicles.values())
        drive = route.minutes / fastest if route else float("inf")
        cp = g.critical_path_minutes()
        earliest = order.release + cp + drive
        return (f"deadline {sc.clock(order.deadline)}, but the earliest arrival is {sc.clock(earliest)} "
                f"({cp} min of kitchen work + {drive:.0f} min drive)"
                if earliest > order.deadline else
                f"deadline {sc.clock(order.deadline)} leaves no slack once shared resources are booked")
    if kind == "holding":
        return f"food would wait more than {sc.max_hold} min between cooking and serving"
    if kind == "agent-booking":
        return "skilled staff are fully booked by higher-priority orders"
    if kind == "occupancy":
        return "stoves / counters are fully booked by higher-priority orders"
    if kind == "workspace":
        return "stations sharing one access cell cannot be worked at the same time"
    if kind == "allergen":
        return "allergen-free batches need stations cleaned after allergenic cooking"
    if kind == "vehicle-booking":
        return "all suitable vehicles are busy with other trips"
    if kind == "priority":
        return "higher-priority orders must leave first on a shared vehicle"
    return kind


# ---------------------------------------------------------------------------------------------
# alternatives: smallest change that makes the order feasible
# ---------------------------------------------------------------------------------------------
def _feasible(sc: Scenario, accepted: list[Order], order: Order, hints, node_limit=1_500) -> bool:
    return solve_model(build_model(sc, accepted + [order]), hints=hints, node_limit=node_limit).ok


def suggest_alternatives(sc: Scenario, order: Order, accepted: list[Order], hints, diag: Diagnosis) -> list[str]:
    out = []
    kinds = {c.kind for c in diag.causes}
    if kinds & {"route", "dietary", "located", "skill", "station-type"}:
        return out  # hard blockers: changing quantity or time does not help
    # 1) fewer meals now (largest feasible quantity, binary search in steps of 10)
    lo, hi = 0, order.meals // 10
    while lo < hi:
        mid = (lo + hi + 1) // 2
        trial = Order(order.id, order.destination, mid * 10, set(order.diet), order.deadline, order.priority,
                      order.release)
        if _feasible(sc, accepted, trial, hints):
            lo = mid
        else:
            hi = mid - 1
    if lo > 0:
        out.append(f"deliver {lo * 10} of {order.meals} meals by {sc.clock(order.deadline)}")
    # 2) all meals, later (earliest feasible deadline in 30-minute steps)
    for extra in range(30, 181, 30):
        if order.deadline + extra > sc.horizon:
            break
        trial = Order(order.id, order.destination, order.meals, set(order.diet), order.deadline + extra,
                      order.priority, order.release)
        if _feasible(sc, accepted, trial, hints):
            out.append(f"deliver all {order.meals} meals by {sc.clock(order.deadline + extra)}")
            break
    return out
