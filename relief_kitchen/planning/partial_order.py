"""Module M2 — Partial-Order Planning (POP).

Algorithm (textbook):
  Given: initial state facts, goal conditions, and operators
  Plan  = steps + ordering constraints + causal links
  Loop:
    1. Find an open precondition (a step whose precondition is not yet satisfied)
    2. Find or add a step that achieves it → add causal link + ordering
    3. Detect and resolve threats (a step whose delete-effect negates the link)
  Until: no open preconditions → plan is complete
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Operator:
    """A kitchen stage template (fetch, prep, cook, pack …)."""
    name: str
    pre: frozenset[str]      # preconditions that must hold before execution
    add: frozenset[str]      # facts that become true after execution
    delete: frozenset[str] = frozenset()   # facts that become false


@dataclass
class Step:
    id: str
    operator: Operator

    def achieves(self, cond: str) -> bool:
        return cond in self.operator.add

    def threatens(self, cond: str) -> bool:
        return cond in self.operator.delete


@dataclass
class CausalLink:
    producer: str    # id of the step that produces `condition`
    condition: str
    consumer: str    # id of the step that needs `condition`


@dataclass
class Plan:
    steps: dict[str, Step] = field(default_factory=dict)
    orderings: set[tuple[str, str]] = field(default_factory=set)
    links: list[CausalLink] = field(default_factory=list)

    def open_preconditions(self) -> list[tuple[str, str]]:
        """Return [(step_id, condition)] for every unachieved precondition."""
        agenda = []
        for sid, step in self.steps.items():
            if sid == "Start":
                continue
            achieved = {lk.condition for lk in self.links if lk.consumer == sid}
            for cond in step.operator.pre:
                if cond not in achieved:
                    agenda.append((sid, cond))
        return agenda

    def before(self, a: str, b: str) -> bool:
        """Is step a ordered before step b (directly or transitively)?"""
        seen, stack = set(), [a]
        while stack:
            cur = stack.pop()
            if cur == b:
                return True
            if cur not in seen:
                seen.add(cur)
                stack.extend(y for (x, y) in self.orderings if x == cur)
        return False

    def sorted_steps(self) -> list[Step]:
        """Topological sort — Start first, Finish last."""
        from collections import defaultdict, deque
        deg: dict[str, int] = defaultdict(int)
        nxt: dict[str, list] = defaultdict(list)
        for a, b in self.orderings:
            nxt[a].append(b)
            deg[b] += 1
        q = deque(sid for sid in self.steps if deg[sid] == 0)
        result = []
        while q:
            sid = q.popleft()
            result.append(self.steps[sid])
            for child in nxt[sid]:
                deg[child] -= 1
                if deg[child] == 0:
                    q.append(child)
        return result


_counter = 0


def pop(init: frozenset[str], goal: frozenset[str], operators: list[Operator]) -> Plan:
    """Run Partial-Order Planning; return a complete Plan."""
    global _counter
    _counter = 0

    start = Step("Start", Operator("Start", frozenset(), init))
    finish = Step("Finish", Operator("Finish", goal, frozenset()))
    plan = Plan(
        steps={"Start": start, "Finish": finish},
        orderings={("Start", "Finish")},
    )

    while True:
        agenda = plan.open_preconditions()
        if not agenda:
            break                          # no open preconditions → done

        consumer_id, need = agenda[0]

        # --- step 2: find an existing achiever or instantiate a new one ---
        achiever: Optional[Step] = None
        for sid, step in plan.steps.items():
            if sid != consumer_id and step.achieves(need):
                if not plan.before(consumer_id, sid):   # ordering wouldn't cycle
                    achiever = step
                    break

        if achiever is None:               # no existing step → add a new one
            op = next((o for o in operators if need in o.add), None)
            if op is None:
                raise ValueError(f"No operator achieves condition: {need!r}")
            _counter += 1
            achiever = Step(f"{op.name}_{_counter}", op)
            plan.steps[achiever.id] = achiever
            plan.orderings |= {("Start", achiever.id), (achiever.id, "Finish")}

        plan.links.append(CausalLink(achiever.id, need, consumer_id))
        plan.orderings.add((achiever.id, consumer_id))

        # --- step 3: resolve threats on the new causal link ---
        for sid, step in list(plan.steps.items()):
            if sid in (achiever.id, consumer_id):
                continue
            if step.threatens(need):
                if not plan.before(consumer_id, sid):   # demote: put threat after consumer
                    plan.orderings.add((consumer_id, sid))
                elif not plan.before(sid, achiever.id): # promote: put threat before achiever
                    plan.orderings.add((sid, achiever.id))

    return plan
