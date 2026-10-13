"""A small, general CSP solver (CS 188 lecture "Constraint Satisfaction Problems").

Variables have finite domains, kept as lists in a preferred value order. A constraint is an object
with a `scope` and a `holds(assignment)` test. `holds` receives a *partial* assignment and must
return True whenever it cannot decide yet. That lets one test serve backtracking,
forward checking and AC-3.

Every constraint also carries a `category` (ingredients, equipment, staff, time, transport, ...).
The solver ignores it; the diagnosis module uses it to say *why* an order is infeasible.
Category "structure" marks facts that are never relaxed, for example task precedence.

Solving pipeline:
    1. node consistency      - apply unary constraints once
    2. AC-3                  - arc consistency on binary constraints
    3. backtracking search   - MRV with a degree tie-break, LCV value order, forward checking
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

CATEGORIES = ("ingredients", "equipment", "staff", "time", "transport", "dietary", "safety", "collision",
              "priority", "structure")


class Constraint:
    def __init__(self, scope: Iterable[str], category: str, description: str, **meta):
        assert category in CATEGORIES, category
        self.scope = tuple(scope)
        self.category = category
        self.description = description
        self.meta = meta  # free-form tags, e.g. orders=..., kind=...

    def holds(self, a: dict) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def revise(self, xi: str, xj: str, domains: dict[str, list]) -> list | None:
        """Optional fast AC-3 revise for binary constraints: return the pruned domain of xi.

        Returning None makes AC-3 fall back to the generic O(|Di| * |Dj|) revise."""
        return None

    def __repr__(self) -> str:
        return f"<{self.category}: {self.description}>"


class FnConstraint(Constraint):
    """Constraint given as a predicate over the scope's values; checked once all are assigned."""

    def __init__(self, scope, fn: Callable[..., bool], category: str, description: str, **meta):
        super().__init__(scope, category, description, **meta)
        self.fn = fn

    def holds(self, a: dict) -> bool:
        try:
            vals = [a[v] for v in self.scope]
        except KeyError:
            return True
        return self.fn(*vals)


class CSP:
    def __init__(self):
        self.domains: dict[str, list] = {}
        self.constraints: list[Constraint] = []
        self.priority: dict[str, tuple] = {}  # static tie-break for variable ordering

    def add_variable(self, name: str, domain: Iterable, priority: tuple = ()):
        self.domains[name] = list(domain)
        self.priority[name] = priority

    def add(self, c: Constraint) -> Constraint:
        self.constraints.append(c)
        return c

    def subset(self, keep: Callable[[Constraint], bool]) -> "CSP":
        """Same variables, only the constraints for which `keep` is true (used to relax a CSP)."""
        out = CSP()
        out.domains = {v: list(d) for v, d in self.domains.items()}
        out.priority = dict(self.priority)
        out.constraints = [c for c in self.constraints if keep(c)]
        return out

    def violated(self, a: dict) -> list[Constraint]:
        """Constraints broken by a complete assignment (empty list = valid solution)."""
        return [c for c in self.constraints if not c.holds(a)]


@dataclass
class SolveStats:
    nodes: int = 0  # values tried during search
    backtracks: int = 0
    pruned: int = 0  # values removed by consistency checks
    seconds: float = 0.0


@dataclass
class SolveResult:
    status: str  # "solved" | "infeasible" | "budget" (node limit reached, treated as infeasible)
    solution: dict | None
    stats: SolveStats
    wipeout: Constraint | None = None  # constraint that emptied a domain before search, if any

    @property
    def ok(self) -> bool:
        return self.status == "solved"


class _Budget(Exception):
    pass


class Solver:
    """Backtracking search with forward checking.

    Hooks for problem-specific knowledge (all optional):
      value_order(var, values, assignment) -> values   replaces the default LCV ordering
      var_key(var) -> tuple                            checked before MRV, e.g. "decide menus first"
      hints {var: value}                               value to try first (warm start)
    """

    def __init__(self, csp: CSP, *, node_limit: int = 50_000, ac3_limit: int = 6_000, lcv_limit: int = 2_000,
                 value_order: Callable[[str, list, dict], list] | None = None,
                 var_key: Callable[[str], tuple] | None = None, hints: dict | None = None):
        self.csp = csp
        self.node_limit = node_limit
        self.ac3_limit = ac3_limit  # skip the generic revise when |Di| * |Dj| is larger than this
        self.lcv_limit = lcv_limit  # LCV costs |D| * neighbours checks; only use it when that is small
        self.value_order = value_order
        self.var_key = var_key
        self.hints = hints or {}
        self.stats = SolveStats()
        self.by_var: dict[str, list[Constraint]] = {v: [] for v in csp.domains}
        for c in csp.constraints:
            for v in c.scope:
                self.by_var[v].append(c)
        self.neighbors = {v: {u for c in cs for u in c.scope if u != v} for v, cs in self.by_var.items()}

    # ---- preprocessing -------------------------------------------------------------------------
    def node_consistency(self, domains) -> Constraint | None:
        for c in self.csp.constraints:
            if len(c.scope) == 1:
                v = c.scope[0]
                before = len(domains[v])
                domains[v] = [x for x in domains[v] if c.holds({v: x})]
                self.stats.pruned += before - len(domains[v])
                if not domains[v]:
                    return c
        return None

    def ac3(self, domains) -> Constraint | None:
        """Standard AC-3. Returns the constraint that wiped out a domain, or None."""
        arcs_into: dict[str, list] = {}  # var -> arcs (xk, var, c), re-queued when var's domain shrinks
        queue = []
        for c in self.csp.constraints:
            if len(c.scope) == 2:
                x, y = c.scope
                for arc in ((x, y, c), (y, x, c)):
                    queue.append(arc)
                    arcs_into.setdefault(arc[1], []).append(arc)
        queued = {(a, b, id(c)) for a, b, c in queue}
        while queue:
            xi, xj, c = queue.pop()
            queued.discard((xi, xj, id(c)))
            new = c.revise(xi, xj, domains)
            if new is None:
                if len(domains[xi]) * len(domains[xj]) > self.ac3_limit:
                    continue
                new = [x for x in domains[xi] if any(c.holds({xi: x, xj: y}) for y in domains[xj])]
            if len(new) < len(domains[xi]):
                self.stats.pruned += len(domains[xi]) - len(new)
                domains[xi] = new
                if not new:
                    return c
                for arc in arcs_into.get(xi, []):
                    key = (arc[0], arc[1], id(arc[2]))
                    if arc[0] != xj and key not in queued:
                        queued.add(key)
                        queue.append(arc)
        return None

    # ---- search --------------------------------------------------------------------------------
    def select_var(self, assign, domains):
        """MRV, ties broken by degree (most constraints on other variables), then a static key."""
        best, best_key = None, None
        for v in domains:
            if v in assign:
                continue
            key = (len(domains[v]), -len(self.neighbors[v]), self.csp.priority.get(v, ()), v)
            if self.var_key is not None:
                key = (self.var_key(v),) + key
            if best_key is None or key < best_key:
                best, best_key = v, key
        return best

    def order_values(self, var, domains, assign):
        values = domains[var]
        if self.value_order is not None:
            values = self.value_order(var, values, assign)
        elif len(values) * max(1, len(self.neighbors[var])) <= self.lcv_limit:
            values = sorted(values, key=lambda x: self._ruled_out(var, x, domains, assign))
        hint = self.hints.get(var)
        if hint is not None and hint in values:
            values = [hint] + [x for x in values if x != hint]
        return values

    def _ruled_out(self, var, val, domains, assign) -> int:
        """LCV score: how many values of unassigned neighbours `var = val` would rule out."""
        assign[var] = val
        count = 0
        for c in self.by_var[var]:
            for y in c.scope:
                if y in assign:
                    continue
                for yv in domains[y]:
                    assign[y] = yv
                    count += not c.holds(assign)
                    del assign[y]
        del assign[var]
        return count

    def consistent(self, var, val, assign) -> bool:
        assign[var] = val
        ok = all(c.holds(assign) for c in self.by_var[var])
        del assign[var]
        return ok

    def forward_check(self, var, assign, domains, trail) -> bool:
        """Remove neighbour values that conflict with `var`'s new value. False on a wipe-out.

        Removed domains are pushed onto `trail` so backtracking can restore them."""
        for c in self.by_var[var]:
            for y in c.scope:
                if y in assign:
                    continue
                kept = []
                for yv in domains[y]:
                    assign[y] = yv
                    if c.holds(assign):
                        kept.append(yv)
                    del assign[y]
                if len(kept) < len(domains[y]):
                    trail.append((y, domains[y]))
                    self.stats.pruned += len(domains[y]) - len(kept)
                    domains[y] = kept
                    if not kept:
                        return False
        return True

    def backtrack(self, assign, domains):
        if len(assign) == len(domains):
            return dict(assign)
        var = self.select_var(assign, domains)
        for val in self.order_values(var, domains, assign):
            self.stats.nodes += 1
            if self.stats.nodes > self.node_limit:
                raise _Budget
            if not self.consistent(var, val, assign):
                continue
            assign[var] = val
            trail: list = [(var, domains[var])]
            domains[var] = [val]
            if self.forward_check(var, assign, domains, trail):
                result = self.backtrack(assign, domains)
                if result is not None:
                    return result
            for y, old in reversed(trail):
                domains[y] = old
            del assign[var]
        self.stats.backtracks += 1
        return None

    def solve(self) -> SolveResult:
        t0 = time.perf_counter()
        domains = {v: list(d) for v, d in self.csp.domains.items()}
        wipe = self.node_consistency(domains) or self.ac3(domains)
        if wipe is not None:
            result = SolveResult("infeasible", None, self.stats, wipeout=wipe)
        else:
            try:
                sol = self.backtrack({}, domains)
                result = SolveResult("solved" if sol is not None else "infeasible", sol, self.stats)
            except _Budget:
                result = SolveResult("budget", None, self.stats)
        self.stats.seconds = time.perf_counter() - t0
        return result


def solve(csp: CSP, **kw) -> SolveResult:
    return Solver(csp, **kw).solve()
