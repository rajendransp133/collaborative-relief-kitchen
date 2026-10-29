"""Building and checking CSPs (helpers around `algorithms.csp`).

Every constraint carries a `category` (ingredients, equipment, staff, time, transport, ...). The
solver ignores it; the diagnosis uses it to say *why* an order is infeasible. Category "structure"
marks facts that are never relaxed, for example task precedence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from .records import CSP, Constraint, Revise

CATEGORIES = ("ingredients", "equipment", "staff", "time", "transport", "dietary", "safety", "collision",
              "priority", "structure")


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


def constraints_by_var(csp: CSP) -> dict[str, list[Constraint]]:
    by_var: dict[str, list[Constraint]] = {v: [] for v in csp.domains}
    for c in csp.constraints:
        for v in c.scope:
            by_var[v].append(c)
    return by_var
