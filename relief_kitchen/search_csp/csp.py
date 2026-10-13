"""A small, general CSP engine.

* Variables have finite domains (lists, kept in a preferred value order).
* Constraints are objects with a scope, a `holds(assignment)` test that must return True whenever
  it cannot yet decide (partial assignments), and diagnosis metadata: a `category` (ingredients,
  equipment, staff, time, transport, dietary, safety, collision, priority), a `group` key used by
  the infeasibility explainer, and a human-readable `description`.
* The solver runs node consistency, AC-3 on binary constraints, then backtracking search with
  MRV + degree variable ordering, LCV (or a problem-specific) value ordering and forward checking.
  Constraints that offer a fast `revise` (bounds) are also kept arc consistent during search, and
  an optional `node_check` hook adds global reasoning (the kitchen uses energetic resource bounds).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

CATEGORIES = ("ingredients", "equipment", "staff", "time", "transport", "dietary", "safety", "collision", "priority")


class Constraint:
    def __init__(self, scope: Iterable[str], category: str, group: str, description: str, relaxable: bool = True,
                 **meta):
        self.scope = tuple(scope)
        self.meta = meta
        assert category in CATEGORIES or category == "structure", category
        self.category = category
        self.group = group
        self.description = description
        self.relaxable = relaxable

    def holds(self, a: dict) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def revise(self, xi: str, xj: str, domains: dict[str, list]) -> list | None:
        """Optional fast arc revision: return the pruned domain of xi, or None to fall back.

        Constraints that set `propagate_in_search = True` are also revised during search."""
        return None

    def __repr__(self) -> str:
        return f"<{self.category}:{self.group} {self.description}>"


class FnConstraint(Constraint):
    """Constraint given by a predicate over its scope's values; checked once all are assigned."""

    def __init__(self, scope, fn: Callable[..., bool], category: str, group: str, description: str,
                 relaxable: bool = True, **meta):
        super().__init__(scope, category, group, description, relaxable, **meta)
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
        self.priority: dict[str, tuple] = {}  # static tie-break key for variable ordering

    def add_variable(self, name: str, domain: Iterable, priority: tuple = ()):
        self.domains[name] = list(domain)
        self.priority[name] = priority

    def add(self, c: Constraint) -> Constraint:
        self.constraints.append(c)
        return c

    def subset(self, keep: Callable[[Constraint], bool]) -> "CSP":
        out = CSP()
        out.domains = {v: list(d) for v, d in self.domains.items()}
        out.priority = dict(self.priority)
        out.constraints = [c for c in self.constraints if keep(c)]
        return out

    def is_solution(self, a: dict) -> list[Constraint]:
        """Return the constraints that a complete assignment violates (empty if it is a solution)."""
        return [c for c in self.constraints if not c.holds(a)]


@dataclass
class SolveStats:
    nodes: int = 0
    backtracks: int = 0
    ac3_revisions: int = 0
    pruned: int = 0
    seconds: float = 0.0


@dataclass
class SolveResult:
    status: str  # solved | infeasible | budget
    solution: dict | None
    stats: SolveStats
    wipeout: Constraint | None = None  # constraint that emptied a domain before search (if any)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "solved"


class _Budget(Exception):
    pass


class Solver:
    def __init__(self, csp: CSP, *, node_limit: int = 50_000, ac3: bool = True, ac3_limit: int = 6_000,
                 lcv: bool = True, lcv_limit: int = 2_000,
                 value_order: Callable[[str, list, dict], list] | None = None,
                 hints: dict | None = None, var_key: Callable[[str], tuple] | None = None,
                 propagate: bool = True,
                 node_check: Callable[[str | None, dict, dict], bool] | None = None):
        self.csp = csp
        self.node_check = node_check
        self.var_key = var_key
        self.propagate = propagate
        self.node_limit = node_limit
        self.use_ac3 = ac3
        self.ac3_limit = ac3_limit
        self.lcv = lcv
        self.lcv_limit = lcv_limit
        self.value_order = value_order
        self.hints = hints or {}
        self.stats = SolveStats()
        self.by_var: dict[str, list[Constraint]] = {v: [] for v in csp.domains}
        for c in csp.constraints:
            for v in c.scope:
                self.by_var[v].append(c)
        self.neighbors = {v: {u for c in cs for u in c.scope if u != v} for v, cs in self.by_var.items()}
        # constraints with a fast `revise` (e.g. precedence bounds) are kept arc consistent during
        # search as well (a light form of MAC on top of forward checking)
        self.fast_by_var: dict[str, list[Constraint]] = {v: [] for v in csp.domains}
        for c in csp.constraints:
            if len(c.scope) == 2 and getattr(c, "propagate_in_search", False):
                for v in c.scope:
                    self.fast_by_var[v].append(c)

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
        arcs_of: dict[str, list[tuple[str, str, Constraint]]] = {}
        queue: list[tuple[str, str, Constraint]] = []
        for c in self.csp.constraints:
            if len(c.scope) != 2:
                continue
            x, y = c.scope
            for arc in ((x, y, c), (y, x, c)):
                queue.append(arc)
                arcs_of.setdefault(arc[1], []).append(arc)
        queued = {(a, b, id(c)) for a, b, c in queue}
        while queue:
            xi, xj, c = queue.pop()
            queued.discard((xi, xj, id(c)))
            new = c.revise(xi, xj, domains)
            if new is None:
                if len(domains[xi]) * len(domains[xj]) > self.ac3_limit:
                    continue
                new = []
                probe = {}
                for x in domains[xi]:
                    probe[xi] = x
                    for y in domains[xj]:
                        probe[xj] = y
                        if c.holds(probe):
                            new.append(x)
                            break
            self.stats.ac3_revisions += 1
            if len(new) < len(domains[xi]):
                self.stats.pruned += len(domains[xi]) - len(new)
                domains[xi] = new
                if not new:
                    return c
                for arc in arcs_of.get(xi, []):
                    key = (arc[0], arc[1], id(arc[2]))
                    if arc[0] != xj and key not in queued:
                        queued.add(key)
                        queue.append(arc)
        return None

    # ---- search --------------------------------------------------------------------------------
    def select_var(self, assign, domains):
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
        elif self.lcv and len(values) * max(1, len(self.neighbors[var])) <= self.lcv_limit:
            values = sorted(values, key=lambda x: self._ruled_out(var, x, domains, assign))
        hint = self.hints.get(var)
        if hint is not None and hint in values:
            values = [hint] + [x for x in values if x != hint]
        return values

    def _ruled_out(self, var, val, domains, assign) -> int:
        """LCV score: how many neighbour values this choice would eliminate."""
        assign[var] = val
        count = 0
        for c in self.by_var[var]:
            for y in c.scope:
                if y in assign:
                    continue
                for yv in domains[y]:
                    assign[y] = yv
                    if not c.holds(assign):
                        count += 1
                    del assign[y]
        del assign[var]
        return count

    def consistent(self, var, val, assign) -> bool:
        assign[var] = val
        ok = all(c.holds(assign) for c in self.by_var[var])
        del assign[var]
        return ok

    def forward_check(self, var, assign, domains, trail) -> bool:
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
        if self.propagate:
            return self._propagate_fast([y for y, _ in trail] + [var], assign, domains, trail)
        return True

    def _propagate_fast(self, changed, assign, domains, trail) -> bool:
        queue = list(dict.fromkeys(changed))
        while queue:
            y = queue.pop()
            for c in self.fast_by_var[y]:
                z = c.scope[0] if c.scope[1] == y else c.scope[1]
                if z in assign:
                    continue
                new = c.revise(z, y, domains)
                if new is not None and len(new) < len(domains[z]):
                    trail.append((z, domains[z]))
                    self.stats.pruned += len(domains[z]) - len(new)
                    domains[z] = new
                    if not new:
                        return False
                    queue.append(z)
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
            trail: list = []
            saved = domains[var]
            domains[var] = [val]
            if self.forward_check(var, assign, domains, trail) and (
                    self.node_check is None or self.node_check(var, assign, domains)):
                result = self.backtrack(assign, domains)
                if result is not None:
                    return result
            for y, old in reversed(trail):
                domains[y] = old
            domains[var] = saved
            del assign[var]
        self.stats.backtracks += 1
        return None

    def solve(self) -> SolveResult:
        t0 = time.perf_counter()
        domains = {v: list(d) for v, d in self.csp.domains.items()}
        wipe = self.node_consistency(domains)
        if wipe is None and self.use_ac3:
            wipe = self.ac3(domains)
        if wipe is not None:
            self.stats.seconds = time.perf_counter() - t0
            return SolveResult("infeasible", None, self.stats, wipeout=wipe)
        if self.node_check is not None and not self.node_check(None, {}, domains):
            self.stats.seconds = time.perf_counter() - t0
            return SolveResult("infeasible", None, self.stats, notes=["global check failed at the root"])
        try:
            sol = self.backtrack({}, domains)
        except _Budget:
            self.stats.seconds = time.perf_counter() - t0
            return SolveResult("budget", None, self.stats)
        self.stats.seconds = time.perf_counter() - t0
        return SolveResult("solved" if sol is not None else "infeasible", sol, self.stats)


def solve(csp: CSP, **kw) -> SolveResult:
    return Solver(csp, **kw).solve()
