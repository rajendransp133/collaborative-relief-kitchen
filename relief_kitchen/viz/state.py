"""Visualiser state: one `ViewState` record plus the functions that change it.

Nothing here draws. Solving runs in a background thread, so the window stays responsive while
the CSP works; the thread hands its results over through `st.pending`.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pygame

from ..support.env.scenario import Event, apply_event, load_scenario
from ..algorithms.planner import solve_scenario
from ..support.records import M1Result

PAGES = ("kitchen", "delivery", "overview")


@dataclass
class ViewState:
    """Everything the window shows or remembers."""

    scenario_files: list[str]
    path: str = ""
    page: str = "kitchen"
    speed: float = 4.0  # simulated minutes per real second
    playing: bool = True
    minute: float = 0.0
    selected: str | None = None  # order id highlighted on the overview page
    show_help: bool = False
    message: str = ""
    busy: str | None = None  # label of the running background solve, if any
    steps: list[M1Result] = field(default_factory=list)  # timeline: initial plan, then one per event
    step: int = 0
    pending: list[M1Result] | None = None  # results handed over by the solver thread
    jump_to_last: bool = False
    order_color: dict = field(default_factory=dict)
    mouse: tuple[int, int] = (-1, -1)
    # hit areas recorded while drawing (used for clicks and hover tooltips)
    hover: list = field(default_factory=list)  # [(rect, kind, payload)]
    clicks: list = field(default_factory=list)  # [(rect, action, value)]
    scrub: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    t_span: float = 360.0
    screen: pygame.Surface | None = None


def new_state(scenario_path: str, page: str = "kitchen") -> ViewState:
    st = ViewState(sorted(str(p) for p in Path(scenario_path).parent.glob("*.yaml")), page=page)
    load(st, scenario_path)
    return st


def run_in_background(st: ViewState, label, fn):
    """Run `fn` on a worker thread; `st.busy` shows `label` until it finishes."""
    st.busy = label

    def work():
        try:
            fn()
        except Exception as exc:  # pragma: no cover - shown in the UI
            st.message = f"error: {exc}"
        st.busy = None

    threading.Thread(target=work, daemon=True).start()


def load(st: ViewState, path: str):
    """Solve a scenario file: the initial plan, then one re-solve per scripted event."""
    st.path = path

    def fn():
        sc = load_scenario(path)
        steps = [solve_scenario(sc, label="Initial plan")]
        st.pending = steps
        for ev in sc.events:
            sc, label = apply_event(sc, ev)
            steps.append(solve_scenario(sc, label=label))
            st.pending = list(steps)

    st.steps, st.step, st.selected = [], 0, None
    run_in_background(st, f"Solving {Path(path).stem.replace('_', ' ')}", fn)


def add_event(st: ViewState, make_event):
    """Apply a live disruption (built by `make_event(scenario)`) to the last step and re-solve."""
    if not st.steps:
        return
    base = st.steps[-1].scenario

    def fn():
        ev = make_event(base)
        if ev is None:
            st.message = "Nothing left to disrupt"
            return
        sc, label = apply_event(base, ev)
        res = solve_scenario(sc, label=label + " (live)")
        st.pending = st.steps + [res]
        st.jump_to_last = True

    run_in_background(st, "Re-solving after disruption", fn)


def current(st: ViewState) -> M1Result | None:
    return st.steps[st.step] if st.steps else None


def end_minute(st: ViewState) -> float:
    r = current(st)
    if not r or not r.allocation:
        return 360
    ends = [d.back for d in r.allocation.deliveries] + [t.end for t in r.allocation.tasks]
    return max(ends) + 10


def sorted_orders(r: M1Result):
    return sorted(r.scenario.orders, key=lambda o: (-o.priority, o.deadline))


def random_road(r: M1Result | None, sc):
    """Close a random open road, preferring roads that a current delivery uses."""
    used = {rid for d in (r.allocation.deliveries if r and r.allocation else []) if d.route for rid in d.route.roads}
    options = [rid for rid, road in sc.roads.roads.items() if road.open and rid in used] or \
              [rid for rid, road in sc.roads.roads.items() if road.open]
    if not options:
        return None
    rid = random.choice(options)
    road = sc.roads.roads[rid]
    return Event("close_road", {"road": rid}, f"Road {rid} ({road.a} – {road.b}) closed")


def random_stove(sc):
    options = [s.id for s in sc.kitchen.stations.values() if s.type in ("stove", "steamer") and not s.failed]
    if not options:
        return None
    sid = random.choice(options)
    return Event("fail_station", {"station": sid}, f"Station {sid} failed")


def cycle_selection(st: ViewState):
    if not current(st):
        return
    ids = [o.id for o in sorted_orders(current(st))]
    st.selected = ids[(ids.index(st.selected) + 1) % len(ids)] if st.selected in ids else ids[0]


def tick(st: ViewState, dt: float):
    """Advance the clock and pick up results the solver thread handed over."""
    if st.pending is not None:
        st.steps, st.pending = st.pending, None
        if st.jump_to_last:
            st.step, st.jump_to_last = len(st.steps) - 1, False
        st.step = min(st.step, len(st.steps) - 1)
        if st.selected is None and current(st) and current(st).diagnoses:
            st.selected = next(iter(current(st).diagnoses))
    if st.playing and current(st):
        st.minute += dt * st.speed
        if st.minute > end_minute(st):
            st.minute = 0.0
