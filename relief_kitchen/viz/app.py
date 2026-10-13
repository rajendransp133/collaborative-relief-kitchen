"""Pygame visualiser for Module 1.

    python -m relief_kitchen.viz --scenario configs/scenarios/road_closure.yaml

Four views of the same plan:
    kitchen    agents moving on collision-free MAPF paths, busy stations
    network    roads, closures, A* routes and vehicles in transit
    schedule   the CSP solution as a Gantt chart (agents and vehicles over time)
    orders     accepted orders with arrival times, rejected ones with their diagnosis

Solving runs in a background thread so the window stays responsive. Press H for help.

Style: one `ViewState` record holds everything the window shows. Plain functions update it
(`handle_event`, `tick`) or read it to paint the screen (`draw` and its `draw_*` helpers).
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pygame

from ..env.road_network import road_between
from ..env.scenario import Event, apply_event, clock, load_scenario, total_stock
from ..search_csp.allocation import UNLOAD_MINUTES
from ..search_csp.motion import agent_position, agent_trail
from ..search_csp.pipeline import M1Result, solve_scenario
from .theme import (ACCENT, BAND, ERROR, FAILED_STYLE, FAINT, GRID, HAIRLINE, HIGHLIGHT, INK, MUTED, ORDER_COLORS,
                    PAPER, ROAD, STATION_STYLE, SURFACE, WALL, dashed, disc, fit, hline, ring, section, text,
                    text_width, wrap)

W, H = 1440, 860
M = 24  # outer margin

# layout (x0, y0, x1, y1) of the four views
KITCHEN = pygame.Rect(M, 116, 640, 372)
NETWORK = pygame.Rect(696, 116, W - M - 696, 372)
SCHEDULE = pygame.Rect(M, 516, 904, 300)
ORDERS = pygame.Rect(960, 516, W - M - 960, 300)


@dataclass
class ViewState:
    """Everything the window shows or remembers. Changed only by the functions below."""

    scenario_files: list[str]
    path: str = ""
    speed: float = 4.0  # simulated minutes per real second
    playing: bool = True
    minute: float = 0.0
    selected: str | None = None
    show_help: bool = False
    message: str = ""
    busy: str | None = None  # label of the running background solve, if any
    steps: list[M1Result] = field(default_factory=list)  # timeline: initial plan, then one per event
    step: int = 0
    pending: list[M1Result] | None = None  # results handed over by the solver thread
    jump_to_last: bool = False
    order_color: dict = field(default_factory=dict)
    # hit areas recorded while drawing, used by mouse handling
    tabs: list = field(default_factory=list)
    order_rows: list = field(default_factory=list)
    timeline: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    t_span: float = 360.0
    screen: pygame.Surface | None = None


def new_state(scenario_path: str) -> ViewState:
    st = ViewState(sorted(str(p) for p in Path(scenario_path).parent.glob("*.yaml")))
    load(st, scenario_path)
    return st


# ---- solving (background thread so the window stays responsive) --------------------------
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


# ---- input -----------------------------------------------------------------------------
def handle_event(st: ViewState, ev) -> bool:
    """Update the state for one pygame event. Returns False when the window should close."""
    if ev.type == pygame.QUIT:
        return False
    if ev.type == pygame.KEYDOWN:
        k = ev.key
        if k in (pygame.K_ESCAPE, pygame.K_q):
            return False
        if k == pygame.K_SPACE:
            st.playing = not st.playing
        elif k == pygame.K_RIGHT:
            st.minute = min(end_minute(st), st.minute + 10)
        elif k == pygame.K_LEFT:
            st.minute = max(0, st.minute - 10)
        elif k == pygame.K_UP:
            st.speed = min(64, st.speed * 2)
        elif k == pygame.K_DOWN:
            st.speed = max(0.5, st.speed / 2)
        elif k == pygame.K_HOME:
            st.minute = 0
        elif k in (pygame.K_TAB, pygame.K_n) and st.steps:
            st.step = (st.step + 1) % len(st.steps)
        elif k == pygame.K_p and st.steps:
            st.step = (st.step - 1) % len(st.steps)
        elif pygame.K_1 <= k <= pygame.K_9:
            i = k - pygame.K_1
            if i < len(st.scenario_files) and not st.busy:
                load(st, st.scenario_files[i])
                st.minute = 0
        elif k == pygame.K_r and not st.busy:
            add_event(st, lambda sc: random_road(current(st), sc))
        elif k == pygame.K_f and not st.busy:
            add_event(st, random_stove)
        elif k == pygame.K_d:
            cycle_selection(st)
        elif k == pygame.K_h:
            st.show_help = not st.show_help
        elif k == pygame.K_s:
            screenshot(st)
    if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
        for rect, oid in st.order_rows:
            if rect.collidepoint(ev.pos):
                st.selected = oid
        for rect, i in st.tabs:
            if rect.collidepoint(ev.pos):
                st.step = i
        if st.timeline.collidepoint(ev.pos):
            frac = (ev.pos[0] - st.timeline.x) / st.timeline.width
            st.minute = max(0.0, min(end_minute(st), frac * st.t_span))
    return True


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


def screenshot(st: ViewState, path: str | None = None):
    path = path or f"relief_m1_{Path(st.path).stem}_{st.step}.png"
    pygame.image.save(st.screen, path)
    st.message = f"Saved {path}"


# ---- main loop -------------------------------------------------------------------------
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


def draw(st: ViewState, screen):
    """Paint the whole window from the state (reads `st`; only records hit areas on it)."""
    st.screen = screen
    screen.fill(PAPER)
    r = current(st)
    draw_header(st, screen, r)
    if r is None:
        text(screen, (st.busy or "Loading") + " …", (W // 2, H // 2), 15, MUTED, anchor="center")
        return
    st.order_color = {o.id: ORDER_COLORS[i % len(ORDER_COLORS)] for i, o in enumerate(r.scenario.orders)}
    hline(screen, M, W - M, 500)
    pygame.draw.line(screen, HAIRLINE, (672, 116), (672, 484))
    pygame.draw.line(screen, HAIRLINE, (936, 516), (936, 816))
    draw_kitchen(st, screen, r, KITCHEN)
    draw_network(st, screen, r, NETWORK)
    draw_schedule(st, screen, r, SCHEDULE)
    draw_orders(st, screen, r, ORDERS)
    draw_footer(st, screen)
    if st.show_help:
        draw_help(st, screen)


# ---- header ----------------------------------------------------------------------------
def draw_header(st: ViewState, s, r):
    t = text(s, "Relief Kitchen", (M, 18), 20, INK, True)
    text(s, "Module 1  ·  Search & Constraint Satisfaction", (t.right + 14, 24), 13, MUTED)
    if r is None:
        return
    sc = r.scenario
    text(s, sc.name, (M, 46), 13, INK)
    text(s, clock(sc, st.minute), (W - M, 12), 28, INK, True, anchor="topright")
    state = "playing" if st.playing else "paused"
    text(s, f"{state}  ·  {st.speed:g} min/s", (W - M, 50), 11, MUTED, anchor="topright")

    # timeline steps as underlined text tabs
    st.tabs = []
    x = M
    for i, step in enumerate(st.steps):
        active = i == st.step
        label = fit(f"{i}  {step.label}", 12, 320, active)
        rect = text(s, label, (x, 78), 12, INK if active else MUTED, active)
        if active:
            pygame.draw.line(s, ACCENT, (rect.x, 99), (rect.right, 99), 2)
        st.tabs.append((rect.inflate(8, 12), i))
        x = rect.right + 28
    hline(s, M, W - M, 100)

    # one quiet stats line on the right (or the solving indicator)
    if st.busy:
        text(s, st.busy + " …", (W - M, 79), 12, ACCENT, True, anchor="topright")
        return
    parts = []
    if r.allocation:
        stats = r.allocation.result.stats
        parts.append(f"CSP {stats.nodes} nodes · {stats.backtracks} backtracks · {stats.seconds * 1000:.0f} ms")
    if r.motion:
        parts.append(f"{r.motion.collisions} collisions")
    parts.append(f"{len(r.accepted)} accepted · {len(r.diagnoses)} rejected")
    text(s, "     |     ".join(parts), (W - M, 80), 11, MUTED, anchor="topright")


# ---- kitchen ---------------------------------------------------------------------------
def draw_kitchen(st: ViewState, s, r, rect):
    section(s, rect.x, rect.y, "Kitchen", "grid graph  ·  prioritised multi-agent paths")
    sc, grid = r.scenario, r.scenario.kitchen
    area = pygame.Rect(rect.x, rect.y + 26, rect.width, rect.height - 80)
    cell = min(area.width // grid.width, area.height // grid.height)
    ox = area.x + (area.width - cell * grid.width) // 2
    oy = area.y
    to_px = lambda rc: (ox + rc[1] * cell + cell / 2, oy + rc[0] * cell + cell / 2)  # noqa: E731

    busy = {}
    if r.allocation:
        busy = {t.station: t for t in r.allocation.tasks if t.start <= st.minute < t.end}

    # floor and walls
    pygame.draw.rect(s, SURFACE, (ox, oy, cell * grid.width, cell * grid.height))
    for rr in range(grid.height):
        for cc in range(grid.width):
            cr = pygame.Rect(ox + cc * cell, oy + rr * cell, cell, cell)
            if grid.rows[rr][cc] == "#":
                pygame.draw.rect(s, WALL, cr)
            else:
                pygame.draw.rect(s, GRID, cr, 1)
            if (rr, cc) in grid.blocked:
                pygame.draw.line(s, ERROR, cr.topleft, cr.bottomright, 2)
    pygame.draw.rect(s, HAIRLINE, (ox, oy, cell * grid.width, cell * grid.height), 1)

    # stations
    for stn in grid.stations.values():
        cr = pygame.Rect(ox + stn.cell[1] * cell + 3, oy + stn.cell[0] * cell + 3, cell - 6, cell - 6)
        fill, edge = FAILED_STYLE if stn.failed else STATION_STYLE.get(stn.type, FAILED_STYLE)
        task = busy.get(stn.id)
        if task:
            edge = st.order_color.get(task.order, ACCENT)
        pygame.draw.rect(s, fill, cr, border_radius=4)
        pygame.draw.rect(s, edge, cr, 2 if task else 1, border_radius=4)
        text(s, stn.id, (cr.centerx, cr.centery - (2 if task else 0)), 11, MUTED if stn.failed else INK, True,
             anchor="center")
        if stn.failed:
            pad = 6
            pygame.draw.line(s, ERROR, (cr.x + pad, cr.y + pad), (cr.right - pad, cr.bottom - pad), 2)
            pygame.draw.line(s, ERROR, (cr.right - pad, cr.y + pad), (cr.x + pad, cr.bottom - pad), 2)
        if task:
            frac = (st.minute - task.start) / max(1, task.end - task.start)
            bar = pygame.Rect(cr.x + 4, cr.bottom - 6, cr.width - 8, 2)
            pygame.draw.rect(s, HIGHLIGHT, bar)
            pygame.draw.rect(s, edge, (bar.x, bar.y, bar.width * frac, 2))

    # agents: dotted trail of the current move, then the agent itself
    if r.motion:
        agents = sorted(sc.agents.values(), key=lambda a: a.id)
        for ag in agents:
            for c in agent_trail(r.motion, ag.id, st.minute, linger=1.5)[1:-1]:
                disc(s, FAINT, to_px(c), 1.5)
        for ag in agents:
            px, py = to_px(agent_position(r.motion, ag.id, st.minute))
            task = None
            if r.allocation:
                task = next((t for t in r.allocation.tasks
                             if t.agent == ag.id and t.start <= st.minute < t.end), None)
            col = st.order_color.get(task.order, INK) if task else INK
            rad = cell * 0.34
            if ag.kind == "robot":
                box = pygame.Rect(0, 0, rad * 2, rad * 2)
                box.center = (px, py)
                pygame.draw.rect(s, col, box, border_radius=4)
            else:
                disc(s, col, (px, py), rad)
            text(s, ag.id[:2], (px, py), 10, SURFACE, True, anchor="center")

    # legend and stock
    y = oy + cell * grid.height + 14
    x = rect.x
    for stype, label in (("storage", "Storage"), ("prep", "Prep"), ("stove", "Stove"), ("steamer", "Steamer"),
                         ("packaging", "Packing"), ("dispatch", "Dispatch")):
        fill, edge = STATION_STYLE[stype]
        sw = pygame.Rect(x, y + 3, 10, 10)
        pygame.draw.rect(s, fill, sw, border_radius=2)
        pygame.draw.rect(s, edge, sw, 1, border_radius=2)
        x = text(s, label, (x + 15, y), 11, MUTED).right + 16
    disc(s, INK, (x + 5, y + 8), 5)
    x = text(s, "Human", (x + 15, y), 11, MUTED).right + 14
    pygame.draw.rect(s, INK, (x, y + 3, 10, 10), border_radius=2)
    text(s, "Robot", (x + 15, y), 11, MUTED)
    stock = ",  ".join(f"{k} {v:g} kg" for k, v in sorted(total_stock(sc).items()))
    text(s, fit("Stock   " + stock, 11, rect.width), (rect.x, y + 20), 11, MUTED)


# ---- delivery network ------------------------------------------------------------------
def draw_network(st: ViewState, s, r, rect):
    section(s, rect.x, rect.y, "Delivery network", "weighted road graph  ·  A* routes")
    net = r.scenario.roads
    area = pygame.Rect(rect.x + 30, rect.y + 52, rect.width - 170, rect.height - 104)
    xs = [p.x for p in net.places.values()]
    ys = [p.y for p in net.places.values()]
    sx = area.width / max(1e-9, max(xs) - min(xs))
    sy = area.height / max(1e-9, max(ys) - min(ys))

    def to_px(pid):
        p = net.places[pid]
        return (area.x + (p.x - min(xs)) * sx, area.y + (p.y - min(ys)) * sy)

    used_by: dict[str, list[str]] = {}
    if r.allocation:
        for d in r.allocation.deliveries:
            for rid in (d.route.roads if d.route else []):
                used_by.setdefault(rid, []).append(d.order)

    for road in net.roads.values():
        a, b = to_px(road.a), to_px(road.b)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1
        nx, ny = -dy / n, dx / n
        if road.open:
            pygame.draw.line(s, ROAD, a, b, 2)
            text(s, f"{road.minutes:g}′", (mx + nx * 11, my + ny * 11), 10, FAINT, anchor="center")
        else:
            dashed(s, ERROR, a, b, 2)
            text(s, f"{road.id} closed", (mx - nx * 14, my - ny * 14), 10, ERROR, True, anchor="center")
        orders = used_by.get(road.id, [])
        for i, oid in enumerate(orders):
            off = (i - (len(orders) - 1) / 2) * 4
            pygame.draw.line(s, st.order_color.get(oid, ACCENT), (a[0] + nx * off, a[1] + ny * off),
                             (b[0] + nx * off, b[1] + ny * off), 3)

    for p in net.places.values():
        x, y = to_px(p.id)
        if p.kind == "junction":
            disc(s, HAIRLINE, (x, y), 3.5)
            continue
        if p.kind == "depot":
            pygame.draw.rect(s, INK, (x - 7, y - 7, 14, 14), border_radius=2)
        elif p.kind == "hospital":
            disc(s, INK, (x, y), 9)
            pygame.draw.rect(s, SURFACE, (x - 1.5, y - 5, 3, 10))
            pygame.draw.rect(s, SURFACE, (x - 5, y - 1.5, 10, 3))
        else:
            ring(s, INK, (x, y), 8, PAPER)
        reachable = p.kind == "depot" or r.routes.get(p.id) is not None
        right = x > area.centerx
        anchor = "topleft"
        lx = x + 14
        if p.kind == "depot":
            lx, anchor = x, "midtop"
            text(s, p.label, (lx, y + 12), 12, INK, True, anchor=anchor)
            continue
        if not right:
            lx = x + 14
        text(s, p.label, (lx, y - 15), 12, INK if reachable else ERROR, True, anchor=anchor)
        sub = f"{p.people} people" if reachable else "unreachable"
        text(s, sub, (lx, y + 1), 11, MUTED if reachable else ERROR, anchor=anchor)

    # vehicles in transit
    if r.allocation:
        for d in r.allocation.deliveries:
            pos = vehicle_pos(st, r, d, to_px)
            if pos is None:
                continue
            box = pygame.Rect(0, 0, 26, 16)
            box.center = pos
            pygame.draw.rect(s, st.order_color.get(d.order, ACCENT), box, border_radius=3)
            text(s, d.vehicle, box.center, 10, SURFACE, True, anchor="center")

    # arrival list
    y = rect.bottom - 18
    x = rect.x
    if r.allocation:
        for d in r.allocation.deliveries:
            disc(s, st.order_color.get(d.order, ACCENT), (x + 4, y + 8), 4)
            label = f"{d.order}  {d.vehicle}  {clock(r.scenario, d.depart)} → {clock(r.scenario, d.arrive)}"
            x = text(s, label, (x + 13, y), 11, MUTED).right + 22


def vehicle_pos(st: ViewState, r, d, to_px):
    """Pixel position of a vehicle on its route at the current minute (None when at the depot)."""
    t = st.minute
    if not d.route or t < d.depart or t > d.back:
        return None
    nodes, net = d.route.nodes, r.scenario.roads
    legs = [road_between(net, a, b).minutes for a, b in zip(nodes, nodes[1:])]
    if t <= d.arrive:
        frac = (t - d.depart) / max(1e-9, d.arrive - d.depart)
    elif t <= d.arrive + UNLOAD_MINUTES:
        frac = 1.0
    else:
        frac = 1 - (t - d.arrive - UNLOAD_MINUTES) / max(1e-9, d.back - d.arrive - UNLOAD_MINUTES)
    dist = frac * (sum(legs) or 1)
    for (a, b), leg in zip(zip(nodes, nodes[1:]), legs):
        if dist <= leg:
            pa, pb = to_px(a), to_px(b)
            f = dist / leg
            return (pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f)
        dist -= leg
    return to_px(nodes[-1])


# ---- schedule --------------------------------------------------------------------------
def draw_schedule(st: ViewState, s, r, rect):
    section(s, rect.x, rect.y, "Schedule", "CSP solution  ·  agents and vehicles over time")
    sc = r.scenario
    if not r.allocation:
        text(s, "No order could be scheduled.", (rect.x, rect.y + 40), 13, MUTED)
        return
    al = r.allocation
    agents, vehicles = sorted(sc.agents), sorted(sc.vehicles)
    rows = [("agent", a) for a in agents] + [("vehicle", v) for v in vehicles]
    left, right = rect.x + 84, rect.right - 8
    top, bottom = rect.y + 52, rect.bottom - 30
    span = max(60.0, math.ceil(end_minute(st) / 60) * 60)
    st.t_span = span
    rh = (bottom - top) / len(rows)
    tx = lambda m: left + (right - left) * m / span  # noqa: E731
    st.timeline = pygame.Rect(left, rect.y + 30, right - left, bottom - rect.y - 30)

    pygame.draw.rect(s, SURFACE, (left, top, right - left, bottom - top))
    for i, (kind, rid) in enumerate(rows):
        y = top + i * rh
        if i % 2:
            pygame.draw.rect(s, BAND, (left, y, right - left, rh))
        label = rid if kind == "agent" else f"{rid}  ·  {sc.vehicles[rid].capacity}"
        text(s, label, (rect.x, y + rh / 2), 12, INK if kind == "agent" else MUTED, anchor="midleft")
    now_x = tx(st.minute)
    for m in range(0, int(span) + 1, 30):
        x = tx(m)
        pygame.draw.line(s, HAIRLINE if m % 60 == 0 else GRID, (x, top), (x, bottom))
        if m % 60 == 0 and abs(x - now_x) > 34:  # keep clear of the "now" tag
            text(s, clock(sc, m), (x, top - 18), 11, MUTED, anchor="midtop")
    hline(s, left, right, top)
    hline(s, left, right, bottom)
    sep = top + len(agents) * rh
    hline(s, rect.x, right, sep)

    for t in al.tasks:
        y = top + agents.index(t.agent) * rh
        bar = pygame.Rect(tx(t.start) + 1, y + 5, max(2, tx(t.end) - tx(t.start) - 2), rh - 10)
        col = st.order_color.get(t.order, ACCENT)
        pygame.draw.rect(s, col, bar, border_radius=3)
        if st.selected == t.order:
            pygame.draw.rect(s, INK, bar.inflate(2, 2), 1, border_radius=4)
        for label in (f"{t.order} {t.stage}", t.stage[0].upper()):
            if text_width(label, 10) < bar.width - 6:
                text(s, label, (bar.x + 4, bar.centery), 10, SURFACE, anchor="midleft")
                break

    for d in al.deliveries:
        y = top + (len(agents) + vehicles.index(d.vehicle)) * rh
        col = st.order_color.get(d.order, ACCENT)
        out = pygame.Rect(tx(d.depart), y + 5, max(2, tx(d.arrive) - tx(d.depart)), rh - 10)
        pygame.draw.rect(s, col, out, border_radius=3)
        pygame.draw.line(s, col, (out.right, y + rh / 2), (tx(d.back), y + rh / 2), 2)
        pygame.draw.line(s, col, (tx(d.back), y + rh / 2 - 4), (tx(d.back), y + rh / 2 + 4), 2)
        label = f"{d.order} → {sc.roads.places[d.destination].label}"
        for lab in (label, d.order):
            if text_width(lab, 10) < out.width - 6:
                text(s, lab, (out.x + 4, out.centery), 10, SURFACE, anchor="midleft")
                break

    # deadlines below the axis
    for o in sc.orders:
        if o.deadline <= span:
            x = tx(o.deadline)
            col = st.order_color.get(o.id, ACCENT)
            pygame.draw.line(s, col, (x, bottom + 2), (x, bottom + 8), 2)
            text(s, o.id, (x, bottom + 10), 10, MUTED, anchor="midtop")
    text(s, "due", (rect.x, bottom + 10), 10, FAINT)

    # now
    x = tx(st.minute)
    pygame.draw.line(s, ACCENT, (x, top), (x, bottom), 2)
    tag = text(s, clock(sc, st.minute), (x, top - 4), 10, SURFACE, True, anchor="midbottom")
    pygame.draw.rect(s, ACCENT, tag.inflate(8, 2), border_radius=3)
    text(s, clock(sc, st.minute), (x, top - 4), 10, SURFACE, True, anchor="midbottom")


# ---- orders ----------------------------------------------------------------------------
def sorted_orders(r):
    return sorted(r.scenario.orders, key=lambda o: (-o.priority, o.deadline))


def draw_orders(st: ViewState, s, r, rect):
    section(s, rect.x, rect.y, "Orders", "click a row for details")
    sc = r.scenario
    deliveries = {d.order: d for d in r.allocation.deliveries} if r.allocation else {}
    x0, x1 = rect.x, rect.right
    y = rect.y + 30
    for label, x, anchor in (("ORDER", x0 + 16, "topleft"), ("DESTINATION", x0 + 58, "topleft"),
                             ("MEALS", x0 + 252, "topright"), ("STATUS", x1, "topright")):
        text(s, label, (x, y), 10, FAINT, True, anchor=anchor)
    y += 18
    hline(s, x0, x1, y)
    st.order_rows = []
    for o in sorted_orders(r):
        row = pygame.Rect(x0, y, rect.width, 24)
        if st.selected == o.id:
            pygame.draw.rect(s, HIGHLIGHT, row)
        disc(s, st.order_color.get(o.id, ACCENT), (x0 + 6, row.centery), 4)
        text(s, o.id, (x0 + 16, row.centery), 12, INK, True, anchor="midleft")
        dest = fit(sc.roads.places[o.destination].label, 12, 150)
        text(s, dest, (x0 + 58, row.centery), 12, INK, anchor="midleft")
        text(s, str(o.meals), (x0 + 252, row.centery), 12, INK, anchor="midright")
        if o.id in deliveries:
            d = deliveries[o.id]
            late = d.arrive > o.deadline
            due = text(s, f"due {clock(sc, o.deadline)}", (x1, row.centery), 11, FAINT, anchor="midright")
            text(s, f"{'late ' if late else ''}arr {clock(sc, d.arrive)}", (due.x - 10, row.centery), 12,
                 ERROR if late else INK, anchor="midright")
        elif o.id in r.diagnoses:
            cats = ", ".join(r.diagnoses[o.id].categories)
            text(s, fit(f"rejected — {cats}", 12, 170), (x1, row.centery), 12, ERROR, anchor="midright")
        hline(s, x0, x1, row.bottom, HAIRLINE)
        st.order_rows.append((row, o.id))
        y = row.bottom

    # details of the selected order
    y += 16
    sel = next((o for o in sc.orders if o.id == st.selected), None)
    if sel is None:
        text(s, "Select an order (click or press D).", (x0, y), 12, MUTED)
        return
    width = rect.width
    diet = ", ".join(sorted(sel.diet)) or "no restriction"
    t = text(s, f"{sel.id}  ·  {sc.roads.places[sel.destination].label}", (x0, y), 13, INK, True)
    text(s, f"{diet}  ·  priority {sel.priority}  ·  due {clock(sc, sel.deadline)}", (t.right + 12, y + 2), 11,
         MUTED)
    y += 22
    lines: list[tuple[str, str]] = []  # (label, body)
    if sel.id in r.diagnoses:
        d = r.diagnoses[sel.id]
        head = "Cannot be met on its own." if d.mode == "isolated" else "Does not fit next to more urgent orders."
        text(s, head, (x0, y), 12, ERROR, True)
        y += 19
        lines = [(c.category.upper(), c.detail) for c in d.causes]
    elif sel.id in deliveries:
        dl = deliveries[sel.id]
        rec = sc.recipes[dl.recipe]
        lines.append(("MENU", f"{rec.name} (allergens: {', '.join(sorted(rec.allergens)) or 'none'})"))
        lines.append(("VEHICLE", f"{dl.vehicle}: leaves {clock(sc, dl.depart)}, arrives {clock(sc, dl.arrive)}, "
                                 f"back {clock(sc, dl.back)}"))
        if dl.route:
            lines.append(("ROUTE", f"{' – '.join(dl.route.nodes)}  ({dl.route.minutes:.0f} min)"))
        plan = r.ingredient_plan.get(sel.id, {})
        picks = ", ".join(f"{ing} {sum(kg for _, kg, _ in p):g} kg ({'+'.join(sh for sh, _, _ in p)})"
                          for ing, p in plan.items())
        if picks:
            lines.append(("PICK", picks))
    for label, body in lines:
        text(s, label, (x0, y + 2), 10, FAINT, True)
        for ln in wrap(body, 12, width - 88):
            if y > rect.bottom - 10:
                return
            text(s, ln, (x0 + 88, y), 12, INK)
            y += 16
        y += 3


# ---- footer / overlays ------------------------------------------------------------------
def draw_footer(st: ViewState, s):
    hline(s, M, W - M, H - 36)
    x = M
    for key, what in (("Space", "play"), ("← →", "time"), ("↑ ↓", "speed"), ("Tab", "next step"),
                      ("1–9", "scenario"), ("R", "close a road"), ("F", "fail a stove"), ("D", "select order"),
                      ("S", "screenshot"), ("H", "help")):
        k = text(s, key, (x, H - 26), 11, INK, True)
        x = text(s, what, (k.right + 6, H - 26), 11, MUTED).right + 20
    if st.message:
        text(s, st.message, (W - M, H - 26), 11, MUTED, anchor="topright")


def draw_help(st: ViewState, s):
    veil = pygame.Surface((W, H), pygame.SRCALPHA)
    veil.fill((*PAPER, 215))
    s.blit(veil, (0, 0))
    card = pygame.Rect(0, 0, 680, 400)
    card.center = (W // 2, H // 2)
    pygame.draw.rect(s, SURFACE, card, border_radius=6)
    pygame.draw.rect(s, HAIRLINE, card, 1, border_radius=6)
    x, y = card.x + 32, card.y + 28
    text(s, "How to read this", (x, y), 16, INK, True)
    y += 34
    notes = [
        "Kitchen: agents walk on a 4-connected grid. Whenever the schedule changes their goals, prioritised "
        "planning (space-time A* per agent) gives collision-free paths.",
        "Network: A* routes from the kitchen. Closed roads are dashed red; routes are recomputed.",
        "Schedule: the CSP gives every batch task an agent, station and start time, and every order a menu, "
        "vehicle and departure.",
        "Orders: rejected orders list the blocking category - ingredients, equipment, staff, time or transport.",
    ]
    for note in notes:
        for ln in wrap(note, 12, card.width - 64):
            text(s, ln, (x, y), 12, INK)
            y += 17
        y += 6
    y += 8
    hline(s, x, card.right - 32, y)
    y += 14
    keys = [("Space", "play / pause"), ("← →", "move 10 minutes"), ("↑ ↓", "change speed"),
            ("Home", "restart"), ("Tab / P", "next / previous step"), ("1–9", "load scenario"),
            ("R", "close a road (live)"), ("F", "fail a stove (live)"), ("D", "select order"),
            ("S", "screenshot"), ("H", "close help"), ("Q / Esc", "quit")]
    for i, (k, what) in enumerate(keys):
        cx = x + (i % 2) * 310
        cy = y + (i // 2) * 21
        text(s, k, (cx, cy), 12, INK, True)
        text(s, what, (cx + 76, cy), 12, MUTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Relief kitchen - Module 1 visualiser")
    ap.add_argument("--scenario", default="configs/scenarios/road_closure.yaml")
    ap.add_argument("--screenshot", help="render one frame to this PNG and exit (works headless)")
    ap.add_argument("--at", default="09:20", help="clock time for --screenshot")
    ap.add_argument("--step", type=int, default=-1, help="timeline step for --screenshot (-1 = last)")
    ap.add_argument("--select", help="order to select for --screenshot")
    args = ap.parse_args(argv)

    if args.screenshot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.display.set_caption("Relief Kitchen – Module 1")
    screen = pygame.display.set_mode((W, H))
    st = new_state(args.scenario)
    frame_clock = pygame.time.Clock()

    if args.screenshot:
        while st.busy or st.pending is not None:
            tick(st, 0)
            pygame.time.wait(50)
        tick(st, 0)
        st.step = args.step % len(st.steps)
        h, m = map(int, args.at.split(":"))
        st.minute = h * 60 + m - current(st).scenario.start_clock
        st.playing = False
        if args.select:
            st.selected = args.select
        draw(st, screen)
        pygame.image.save(screen, args.screenshot)
        print(f"saved {args.screenshot}")
        pygame.quit()
        return

    running = True
    while running:
        dt = frame_clock.tick(60) / 1000.0
        for ev in pygame.event.get():
            running = handle_event(st, ev) and running
        tick(st, dt)
        draw(st, screen)
        pygame.display.flip()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
