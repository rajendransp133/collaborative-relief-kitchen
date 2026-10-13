"""Task-dependency graph (a DAG) for each order.

An order is split into batches of at most `batch_size` meals. Every batch runs the scenario's stage
DAG (fetch -> prep -> cook -> pack by default); all packed batches feed one dispatch node, which is
followed by the drive to the destination.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..env.entities import Order, Recipe, Stage


@dataclass
class TaskNode:
    id: str
    order: str
    batch: int
    stage: str
    meals: int
    skill: str
    station_types: set[str]
    minutes: int
    preds: list[str] = field(default_factory=list)


@dataclass
class TaskGraph:
    order: Order
    nodes: dict[str, TaskNode]
    dispatch: str  # id of the dispatch node
    travel_minutes: float | None = None

    def edges(self) -> list[tuple[str, str]]:
        return [(p, n.id) for n in self.nodes.values() for p in n.preds]

    def topological_order(self) -> list[str]:
        indeg = {n: len(self.nodes[n].preds) for n in self.nodes}
        succ: dict[str, list[str]] = {n: [] for n in self.nodes}
        for u, v in self.edges():
            succ[u].append(v)
        ready = sorted(n for n, d in indeg.items() if d == 0)
        out = []
        while ready:
            n = ready.pop(0)
            out.append(n)
            for m in succ[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if len(out) != len(self.nodes):
            raise ValueError("task graph has a cycle")
        return out

    def earliest_starts(self, release: int = 0) -> dict[str, int]:
        """ASAP start times ignoring resource contention (a lower bound)."""
        est: dict[str, int] = {}
        for n in self.topological_order():
            node = self.nodes[n]
            est[n] = max([release] + [est[p] + self.nodes[p].minutes for p in node.preds])
        return est

    def critical_path_minutes(self) -> int:
        """Minutes from release to dispatch along the longest dependency chain."""
        est = self.earliest_starts(0)
        return est[self.dispatch]

    def tasks(self) -> list[TaskNode]:
        return [n for n in self.nodes.values() if n.id != self.dispatch]


def batch_sizes(meals: int, batch_size: int) -> list[int]:
    n = max(1, math.ceil(meals / batch_size))
    base, extra = divmod(meals, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def build_task_graph(order: Order, stages: list[Stage], variants: list[Recipe], batch_size: int) -> TaskGraph:
    """Variants are the order's diet-compatible recipes; a stage's station types are the union over
    variants and its duration the maximum, so the graph is valid whichever variant the CSP picks."""
    nodes: dict[str, TaskNode] = {}
    sizes = batch_sizes(order.meals, batch_size)
    packs = []
    for b, meals in enumerate(sizes):
        for st in stages:
            types = {r.stage_station(st) for r in variants} or {st.station_type}
            minutes = max([r.stage_minutes(st) for r in variants] or [st.minutes])
            tid = f"{order.id}.b{b + 1}.{st.name}"
            nodes[tid] = TaskNode(tid, order.id, b + 1, st.name, meals, st.skill, types, minutes,
                                  preds=[f"{order.id}.b{b + 1}.{p}" for p in st.after])
        sinks = {s.name for s in stages} - {p for s in stages for p in s.after}
        packs += [f"{order.id}.b{b + 1}.{s}" for s in sorted(sinks)]
    did = f"{order.id}.dispatch"
    nodes[did] = TaskNode(did, order.id, 0, "dispatch", order.meals, "drive", {"vehicle"}, 0, preds=packs)
    return TaskGraph(order, nodes, did)
