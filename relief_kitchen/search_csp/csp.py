"""A small, general CSP solver (CS 188 lecture "Constraint Satisfaction Problems").

A CSP is a record: variable domains (lists, kept in a preferred value order), constraints, and a
static tie-break key per variable. A constraint is also a record. Its behaviour is a plain
function `check(assignment) -> bool`, which receives a *partial* assignment and must return True
whenever it cannot decide yet. That lets one test serve backtracking, forward checking and AC-3.

Every constraint carries a `category` (ingredients, equipment, staff, time, transport, ...). The
solver ignores it; the diagnosis module uses it to say *why* an order is infeasible.
Category "structure" marks facts that are never relaxed, for example task precedence.

Solving pipeline:
    1. node consistency      - apply unary constraints once
    2. AC-3                  - arc consistency on binary constraints
    3. backtracking search   - MRV with a degree tie-break, LCV value order, forward checking

The search mutates its working copy of the domains, undoing each change from a trail on
backtrack. Copying all domains at every node would be far slower. The mutation stays inside
`solve`: the CSP record passed in is never changed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

CATEGORIES = ("ingredients", "equipment", "staff", "time", "transport", "dietary", "safety", "collision",
              "priority", "structure")

Check = Callable[[dict], bool]  # partial assignment -> still consistent?
Revise = Callable[[str, str, dict], list]  # (xi, xj, domains) -> pruned domain of xi


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
# building CSPs
# ---------------------------------------------------------------------------------------------
def constraint(scope: Iterable[str], predicate: Callable[..., bool], category: str, description: str,
               revise: Revise | None = None, **meta) -> Constraint:
    """Constraint from a predicate over the scope's values, checked once all of them are assigned."""
    assert category in CATEGORIES, category
    scope = tuple(scope)

    def check(a: dict) -> bool:
        try:
            values = [a[v] for v in scope]
        except KeyError:
            return True
        return predicate(*values)

    return Constraint(scope, check, category, description, meta, revise)


def subset(csp: CSP, keep: Callable[[Constraint], bool]) -> CSP:
    """Same variables, only the constraints for which `keep` is true (used to relax a CSP)."""
    return replace(csp, constraints=[c for c in csp.constraints if keep(c)])


def violated(csp: CSP, a: dict) -> list[Constraint]:
    """Constraints broken by a complete assignment (an empty list means a valid solution)."""
    return [c for c in csp.constraints if not c.check(a)]


# ---------------------------------------------------------------------------------------------
# solving
# ---------------------------------------------------------------------------------------------
BUDGET = "budget"  # sentinel returned by `backtrack` when the node limit is reached


def solve(csp: CSP, *, node_limit: int = 50_000, ac3_limit: int = 6_000, lcv_limit: int = 2_000,
          value_order: Callable[[str, list, dict], list] | None = None,
          var_key: Callable[[str], tuple] | None = None, hints: dict | None = None) -> SolveResult:
    """Node consistency, AC-3, then backtracking search with forward checking.

    Optional problem knowledge:
      value_order(var, values, assignment) -> values   replaces the default LCV ordering
      var_key(var) -> tuple                            compared before MRV, e.g. "decide menus first"
      hints {var: value}                               value to try first (warm start)
    """
    t0 = time.perf_counter()
    ctx = {
        "csp": csp, "stats": SolveStats(), "node_limit": node_limit, "ac3_limit": ac3_limit,
        "lcv_limit": lcv_limit, "value_order": value_order, "var_key": var_key, "hints": hints or {},
        "by_var": _constraints_by_var(csp),
    }
    ctx["neighbors"] = {v: {u for c in cs for u in c.scope if u != v} for v, cs in ctx["by_var"].items()}
    domains = {v: list(d) for v, d in csp.domains.items()}  # working copy, mutated below

    wipe = node_consistency(ctx, domains) or ac3(ctx, domains)
    if wipe is not None:
        status, sol = "infeasible", None
    else:
        sol = backtrack(ctx, {}, domains)
        status = BUDGET if sol is BUDGET else ("solved" if sol is not None else "infeasible")
        sol = sol if status == "solved" else None
    ctx["stats"].seconds = time.perf_counter() - t0
    return SolveResult(status, sol, ctx["stats"], wipe, status == "solved")


def _constraints_by_var(csp: CSP) -> dict[str, list[Constraint]]:
    by_var: dict[str, list[Constraint]] = {v: [] for v in csp.domains}
    for c in csp.constraints:
        for v in c.scope:
            by_var[v].append(c)
    return by_var


def node_consistency(ctx, domains) -> Constraint | None:
    """Filter domains with unary constraints. Returns the constraint that emptied a domain, if any."""
    for c in ctx["csp"].constraints:
        if len(c.scope) == 1:
            v = c.scope[0]
            before = len(domains[v])
            domains[v] = [x for x in domains[v] if c.check({v: x})]
            ctx["stats"].pruned += before - len(domains[v])
            if not domains[v]:
                return c
    return None


def ac3(ctx, domains) -> Constraint | None:
    """Standard AC-3 over binary constraints. Returns the constraint that wiped out a domain, or None."""
    arcs_into: dict[str, list] = {}  # var -> arcs (xk, var, c), re-queued when var's domain shrinks
    queue = []
    for c in ctx["csp"].constraints:
        if len(c.scope) == 2:
            x, y = c.scope
            for arc in ((x, y, c), (y, x, c)):
                queue.append(arc)
                arcs_into.setdefault(arc[1], []).append(arc)
    queued = {(a, b, id(c)) for a, b, c in queue}
    while queue:
        xi, xj, c = queue.pop()
        queued.discard((xi, xj, id(c)))
        if c.revise is not None:
            new = c.revise(xi, xj, domains)
        elif len(domains[xi]) * len(domains[xj]) > ctx["ac3_limit"]:
            continue  # too large for the generic O(|Di| * |Dj|) revise
        else:
            new = [x for x in domains[xi] if any(c.check({xi: x, xj: y}) for y in domains[xj])]
        if len(new) < len(domains[xi]):
            ctx["stats"].pruned += len(domains[xi]) - len(new)
            domains[xi] = new
            if not new:
                return c
            for arc in arcs_into.get(xi, []):
                key = (arc[0], arc[1], id(arc[2]))
                if arc[0] != xj and key not in queued:
                    queued.add(key)
                    queue.append(arc)
    return None


def select_var(ctx, assign, domains):
    """MRV, ties broken by degree (most constraints on other variables), then a static key."""
    def key(v):
        k = (len(domains[v]), -len(ctx["neighbors"][v]), ctx["csp"].priority.get(v, ()), v)
        return (ctx["var_key"](v),) + k if ctx["var_key"] else k

    return min((v for v in domains if v not in assign), key=key)


def order_values(ctx, var, domains, assign):
    values = domains[var]
    if ctx["value_order"] is not None:
        values = ctx["value_order"](var, values, assign)
    elif len(values) * max(1, len(ctx["neighbors"][var])) <= ctx["lcv_limit"]:
        values = sorted(values, key=lambda x: ruled_out(ctx, var, x, domains, assign))
    hint = ctx["hints"].get(var)
    if hint is not None and hint in values:
        values = [hint] + [x for x in values if x != hint]
    return values


def ruled_out(ctx, var, val, domains, assign) -> int:
    """LCV score: how many values of unassigned neighbours `var = val` would rule out."""
    trial = {**assign, var: val}
    return sum(not c.check({**trial, y: yv})
               for c in ctx["by_var"][var] for y in c.scope if y not in trial for yv in domains[y])


def consistent(ctx, var, val, assign) -> bool:
    trial = {**assign, var: val}
    return all(c.check(trial) for c in ctx["by_var"][var])


def forward_check(ctx, var, assign, domains, trail) -> bool:
    """Remove neighbour values that conflict with `var`'s new value. Returns False on a wipe-out.

    Each replaced domain is pushed onto `trail` so backtracking can restore it."""
    for c in ctx["by_var"][var]:
        for y in c.scope:
            if y in assign:
                continue
            kept = []
            for yv in domains[y]:
                assign[y] = yv
                if c.check(assign):
                    kept.append(yv)
                del assign[y]
            if len(kept) < len(domains[y]):
                trail.append((y, domains[y]))
                ctx["stats"].pruned += len(domains[y]) - len(kept)
                domains[y] = kept
                if not kept:
                    return False
    return True


def backtrack(ctx, assign, domains):
    """Depth-first search over assignments. Returns a solution dict, None, or BUDGET."""
    if len(assign) == len(domains):
        return dict(assign)
    stats = ctx["stats"]
    var = select_var(ctx, assign, domains)
    for val in order_values(ctx, var, domains, assign):
        stats.nodes += 1
        if stats.nodes > ctx["node_limit"]:
            return BUDGET
        if not consistent(ctx, var, val, assign):
            continue
        assign[var] = val
        trail: list = [(var, domains[var])]
        domains[var] = [val]
        if forward_check(ctx, var, assign, domains, trail):
            result = backtrack(ctx, assign, domains)
            if result is not None:
                return result  # a solution, or BUDGET bubbling up
        for y, old in reversed(trail):
            domains[y] = old
        del assign[var]
    stats.backtracks += 1
    return None
