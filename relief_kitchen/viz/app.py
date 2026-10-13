"""Pygame visualiser for Module 1.

    python -m relief_kitchen.viz --scenario configs/scenarios/road_closure.yaml

Panels: kitchen floor with agents moving on collision-free MAPF paths, road network with vehicles
on their A* routes, a Gantt chart of the CSP schedule, and an orders panel with the infeasibility
diagnosis. Keys are listed in the footer (press H for the overlay).
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import threading
from pathlib import Path

import pygame

from ..env.scenario import Event, load_scenario
from ..search_csp.allocation import UNLOAD_MINUTES
from ..search_csp.pipeline import M1Result, solve_scenario

# ---------------------------------------------------------------------------------------------
# look and feel
# ---------------------------------------------------------------------------------------------
BG = (15, 18, 26)
PANEL = (24, 29, 42)
PANEL_EDGE = (44, 52, 72)
TEXT = (230, 233, 240)
MUTED = (140, 149, 168)
FLOOR = (36, 43, 60)
FLOOR_LINE = (46, 54, 74)
WALL = (14, 17, 25)
ACCENT = (255, 212, 59)

ORDER_COLORS = [(232, 93, 117), (79, 163, 247), (245, 185, 66), (123, 211, 137), (180, 140, 242),
                (77, 208, 200), (242, 140, 196), (255, 146, 76)]
CATEGORY_COLORS = {
    "ingredients": (245, 185, 66), "equipment": (240, 135, 93), "staff": (79, 163, 247),
    "time": (180, 140, 242), "transport": (232, 93, 117), "dietary": (123, 211, 137),
    "safety": (77, 208, 200), "collision": (190, 190, 190), "priority": (242, 140, 196),
}
STATION_COLORS = {
    "storage": (141, 110, 99), "prep": (92, 124, 250), "stove": (255, 107, 107), "steamer": (247, 131, 172),
    "packaging": (32, 201, 151), "dispatch": (255, 212, 59),
}
STATION_ICON = {"storage": "S", "prep": "P", "stove": "C", "steamer": "T", "packaging": "K", "dispatch": "D"}
AGENT_COLORS = [(255, 255, 255), (255, 236, 179), (200, 230, 255), (210, 255, 210), (255, 210, 240)]

W, H = 1440, 860


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    if key not in _FONTS:
        name = pygame.font.match_font("segoeui,dejavusans,liberationsans,arial,freesans", bold=bold)
        _FONTS[key] = pygame.font.Font(name, size) if name else pygame.font.Font(None, int(size * 1.3))
    return _FONTS[key]


_FONTS: dict = {}


def blit_text(surf, text, pos, size=14, color=TEXT, bold=False, anchor="topleft"):
    img = font(size, bold).render(str(text), True, color)
    rect = img.get_rect(**{anchor: pos})
    surf.blit(img, rect)
    return rect


def wrap(text: str, size: int, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    f = font(size)
    for w in words:
        trial = f"{cur} {w}".strip()
        if f.size(trial)[0] <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def chip(surf, text, pos, color, size=12, fill_alpha=60):
    f = font(size, True)
    tw, th = f.size(text)
    rect = pygame.Rect(pos[0], pos[1], tw + 12, th + 6)
    bg = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(bg, (*color, fill_alpha), bg.get_rect(), border_radius=rect.height // 2)
    surf.blit(bg, rect)
    pygame.draw.rect(surf, color, rect, 1, border_radius=rect.height // 2)
    surf.blit(f.render(text, True, color), (rect.x + 6, rect.y + 3))
    return rect


def panel(surf, rect, title=None):
    pygame.draw.rect(surf, PANEL, rect, border_radius=10)
    pygame.draw.rect(surf, PANEL_EDGE, rect, 1, border_radius=10)
    if title:
        blit_text(surf, title, (rect.x + 14, rect.y + 9), 15, TEXT, bold=True)


def dashed_line(surf, color, a, b, width=2, dash=8):
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    if length == 0:
        return
    n = int(length // dash)
    for i in range(0, n, 2):
        s, e = i / n, min((i + 1) / n, 1)
        pygame.draw.line(surf, color, (ax + (bx - ax) * s, ay + (by - ay) * s), (ax + (bx - ax) * e, ay + (by - ay) * e),
                         width)


# ---------------------------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------------------------
class App:
    def __init__(self, scenario_path: str):
        self.scenario_files = sorted(str(p) for p in Path(scenario_path).parent.glob("*.yaml"))
        self.speed = 4.0  # simulated minutes per real second
        self.playing = True
        self.minute = 0.0
        self.selected: str | None = None
        self.show_help = False
        self.message = ""
        self.busy: str | None = None
        self.steps: list[M1Result] = []
        self.step = 0
        self._pending: list[M1Result] | None = None
        self.load(scenario_path)

    # ---- solving (background thread so the window stays responsive) --------------------------
    def _run(self, label, fn):
        self.busy = label

        def work():
            try:
                fn()
            except Exception as exc:  # pragma: no cover - shown in the UI
                self.message = f"error: {exc}"
            self.busy = None

        threading.Thread(target=work, daemon=True).start()

    def load(self, path: str):
        self.path = path

        def fn():
            sc = load_scenario(path)
            steps = [solve_scenario(sc, label="Initial plan")]
            self._pending = steps
            for ev in sc.events:
                sc = sc.copy()
                text = sc.apply(ev)
                steps.append(solve_scenario(sc, label=text))
                self._pending = list(steps)

        self.steps, self.step = [], 0
        self._run(f"Solving {Path(path).name} ...", fn)

    def add_event(self, make_event):
        if not self.steps:
            return
        base = self.steps[-1].scenario

        def fn():
            sc = base.copy()
            ev = make_event(sc)
            if ev is None:
                self.message = "nothing left to disrupt"
                return
            text = sc.apply(ev)
            res = solve_scenario(sc, label=text + " (live)")
            self._pending = self.steps + [res]
            self._jump_to_last = True

        self._run("Re-solving after disruption ...", fn)

    @property
    def cur(self) -> M1Result | None:
        return self.steps[self.step] if self.steps else None

    def end_minute(self) -> float:
        r = self.cur
        if not r or not r.allocation:
            return 360
        ends = [d.back for d in r.allocation.deliveries] + [t.end for t in r.allocation.tasks]
        return max(ends) + 10

    # ---- events ----------------------------------------------------------------------------
    def handle(self, ev) -> bool:
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYDOWN:
            k = ev.key
            if k in (pygame.K_ESCAPE, pygame.K_q):
                return False
            if k == pygame.K_SPACE:
                self.playing = not self.playing
            elif k == pygame.K_RIGHT:
                self.minute = min(self.end_minute(), self.minute + 10)
            elif k == pygame.K_LEFT:
                self.minute = max(0, self.minute - 10)
            elif k == pygame.K_UP:
                self.speed = min(64, self.speed * 2)
            elif k == pygame.K_DOWN:
                self.speed = max(0.5, self.speed / 2)
            elif k == pygame.K_HOME:
                self.minute = 0
            elif k in (pygame.K_TAB, pygame.K_n) and self.steps:
                self.step = (self.step + 1) % len(self.steps)
            elif k == pygame.K_p and self.steps:
                self.step = (self.step - 1) % len(self.steps)
            elif pygame.K_1 <= k <= pygame.K_9:
                i = k - pygame.K_1
                if i < len(self.scenario_files) and not self.busy:
                    self.load(self.scenario_files[i])
                    self.minute = 0
            elif k == pygame.K_r and not self.busy:
                self.add_event(self._random_road)
            elif k == pygame.K_f and not self.busy:
                self.add_event(self._random_stove)
            elif k == pygame.K_d:
                self._cycle_selection()
            elif k == pygame.K_h:
                self.show_help = not self.show_help
            elif k == pygame.K_s:
                self.screenshot()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, oid in getattr(self, "_order_rows", []):
                if rect.collidepoint(ev.pos):
                    self.selected = oid
            for rect, i in getattr(self, "_tabs", []):
                if rect.collidepoint(ev.pos):
                    self.step = i
            if hasattr(self, "_timeline") and self._timeline.collidepoint(ev.pos):
                frac = (ev.pos[0] - self._timeline.x) / self._timeline.width
                self.minute = max(0.0, min(self.end_minute(), frac * self._t_span))
        return True

    def _random_road(self, sc):
        used = {rid for r in [self.cur] if r and r.allocation for d in r.allocation.deliveries if d.route
                for rid in d.route.roads}
        options = [rid for rid, road in sc.roads.roads.items() if road.open and rid in used] or \
                  [rid for rid, road in sc.roads.roads.items() if road.open]
        if not options:
            return None
        rid = random.choice(options)
        road = sc.roads.roads[rid]
        return Event("close_road", {"road": rid}, f"Road {rid} ({road.a} - {road.b}) closed")

    def _random_stove(self, sc):
        options = [s.id for s in sc.kitchen.stations.values() if s.type in ("stove", "steamer") and not s.failed]
        if not options:
            return None
        sid = random.choice(options)
        return Event("fail_station", {"station": sid}, f"Station {sid} failed")

    def _cycle_selection(self):
        r = self.cur
        if not r:
            return
        ids = [o.id for o in r.scenario.orders]
        if not ids:
            return
        self.selected = ids[(ids.index(self.selected) + 1) % len(ids)] if self.selected in ids else ids[0]

    def screenshot(self, path: str | None = None):
        path = path or f"relief_m1_{Path(self.path).stem}_{self.step}.png"
        pygame.image.save(self.screen, path)
        self.message = f"saved {path}"

    # ---- main loop -------------------------------------------------------------------------
    def tick(self, dt: float):
        if self._pending is not None:
            jump = getattr(self, "_jump_to_last", False)
            self.steps, self._pending = self._pending, None
            if jump:
                self.step = len(self.steps) - 1
                self._jump_to_last = False
            self.step = min(self.step, len(self.steps) - 1)
            if self.selected is None and self.cur and self.cur.diagnoses:
                self.selected = next(iter(self.cur.diagnoses))
        if self.playing and self.cur:
            self.minute += dt * self.speed
            if self.minute > self.end_minute():
                self.minute = 0.0

    def draw(self, screen):
        self.screen = screen
        screen.fill(BG)
        r = self.cur
        self._draw_header(screen, r)
        if r is None:
            blit_text(screen, self.busy or "loading ...", (W // 2, H // 2), 22, MUTED, anchor="center")
            return
        self.order_color = {o.id: ORDER_COLORS[i % len(ORDER_COLORS)] for i, o in enumerate(r.scenario.orders)}
        self._draw_kitchen(screen, r, pygame.Rect(16, 96, 640, 400))
        self._draw_roads(screen, r, pygame.Rect(672, 96, 752, 400))
        self._draw_gantt(screen, r, pygame.Rect(16, 508, 900, 316))
        self._draw_orders(screen, r, pygame.Rect(928, 508, 496, 316))
        self._draw_footer(screen)
        if self.busy:
            self._overlay(screen, self.busy)
        if self.show_help:
            self._draw_help(screen)

    # ---- header ----------------------------------------------------------------------------
    def _draw_header(self, s, r):
        blit_text(s, "Relief Kitchen  -  Module 1: Search & Constraint Satisfaction", (16, 10), 20, TEXT, True)
        if r is None:
            return
        sc = r.scenario
        blit_text(s, sc.name, (16, 38), 14, ACCENT, True)
        clock = sc.clock(self.minute)
        blit_text(s, clock, (W - 16, 6), 30, TEXT, True, anchor="topright")
        blit_text(s, f"{'playing' if self.playing else 'paused'}  x{self.speed:g} min/s", (W - 16, 44), 12, MUTED,
                  anchor="topright")
        x = 16 + font(14, True).size(sc.name)[0] + 16
        st = r.allocation.result.stats if r.allocation else None
        if st:
            x = chip(s, f"CSP {st.nodes} nodes  {st.backtracks} backtracks  {st.seconds * 1000:.0f} ms", (x, 38),
                     (79, 163, 247)).right + 8
        if r.motion:
            col = (123, 211, 137) if r.motion.collisions == 0 else (232, 93, 117)
            x = chip(s, f"MAPF collisions {r.motion.collisions}", (x, 38), col).right + 8
        acc, rej = len(r.accepted), len(r.diagnoses)
        x = chip(s, f"{acc} accepted  {rej} infeasible", (x, 38), (123, 211, 137) if not rej else (245, 185, 66)).right + 8
        # timeline tabs
        self._tabs = []
        tx = 16
        for i, step in enumerate(self.steps):
            label = f"{i}. {step.label}"
            f = font(12, i == self.step)
            w = min(f.size(label)[0] + 16, 330)
            rect = pygame.Rect(tx, 66, w, 22)
            pygame.draw.rect(s, PANEL_EDGE if i == self.step else PANEL, rect, border_radius=6)
            if i == self.step:
                pygame.draw.rect(s, ACCENT, rect, 1, border_radius=6)
            while f.size(label)[0] > w - 14 and len(label) > 4:
                label = label[:-2]
            s.blit(f.render(label, True, TEXT if i == self.step else MUTED), (rect.x + 8, rect.y + 3))
            self._tabs.append((rect, i))
            tx = rect.right + 6
        if self.busy and self.steps:
            blit_text(s, "solving next step ...", (tx + 6, 69), 12, ACCENT)

    # ---- kitchen ---------------------------------------------------------------------------
    def _draw_kitchen(self, s, r, rect):
        panel(s, rect, "Kitchen floor  (grid graph, prioritised MAPF)")
        sc, grid = r.scenario, r.scenario.kitchen
        area = rect.inflate(-28, -60).move(0, 14)
        cell = min(area.width // grid.width, area.height // grid.height)
        ox = area.x + (area.width - cell * grid.width) // 2
        oy = area.y + (area.height - cell * grid.height) // 2
        to_px = lambda rc: (ox + rc[1] * cell + cell / 2, oy + rc[0] * cell + cell / 2)  # noqa: E731
        busy_now = {}
        if r.allocation:
            for t in r.allocation.tasks:
                if t.start <= self.minute < t.end:
                    busy_now[t.station] = t
        for rr in range(grid.height):
            for cc in range(grid.width):
                ch = grid.rows[rr][cc]
                cr = pygame.Rect(ox + cc * cell, oy + rr * cell, cell, cell)
                if ch == "#":
                    pygame.draw.rect(s, WALL, cr)
                else:
                    pygame.draw.rect(s, FLOOR, cr)
                    pygame.draw.rect(s, FLOOR_LINE, cr, 1)
                if (rr, cc) in grid.blocked:
                    pygame.draw.line(s, (232, 93, 117), cr.topleft, cr.bottomright, 2)
        # access cells of busy stations
        for sid, t in busy_now.items():
            acc = grid.stations[sid].access
            if acc:
                cr = pygame.Rect(ox + acc[1] * cell, oy + acc[0] * cell, cell, cell)
                glow = pygame.Surface(cr.size, pygame.SRCALPHA)
                glow.fill((*self.order_color.get(t.order, ACCENT), 45))
                s.blit(glow, cr)
        for st in grid.stations.values():
            r0, c0 = st.cell
            cr = pygame.Rect(ox + c0 * cell + 2, oy + r0 * cell + 2, cell - 4, cell - 4)
            col = STATION_COLORS.get(st.type, MUTED)
            if st.failed:
                col = (90, 90, 96)
            pygame.draw.rect(s, col, cr, border_radius=6)
            t = busy_now.get(st.id)
            if t:
                oc = self.order_color.get(t.order, ACCENT)
                pygame.draw.rect(s, oc, cr.inflate(4, 4), 3, border_radius=8)
                frac = (self.minute - t.start) / max(1, t.end - t.start)
                pygame.draw.rect(s, (20, 20, 20), (cr.x + 3, cr.bottom - 7, cr.width - 6, 4))
                pygame.draw.rect(s, oc, (cr.x + 3, cr.bottom - 7, (cr.width - 6) * frac, 4))
            blit_text(s, st.id, cr.center, 12, (15, 15, 20), True, anchor="center")
            if st.failed:
                pygame.draw.line(s, (232, 93, 117), cr.topleft, cr.bottomright, 3)
                pygame.draw.line(s, (232, 93, 117), cr.topright, cr.bottomleft, 3)
            if st.type == "storage" and st.stock:
                items = [f"{k[:3]} {v:g}" for k, v in st.stock.items() if v > 0][:3]
                for i, txt in enumerate(items):
                    blit_text(s, txt, (cr.right + 3, cr.y + i * 11 - 2), 9, MUTED)
        # agents
        if r.motion:
            for i, ag in enumerate(sorted(sc.agents.values(), key=lambda a: a.id)):
                trail = r.motion.trail(ag.id, self.minute, linger=1.5)
                if len(trail) > 1:
                    pts = [to_px(c) for c in trail]
                    pygame.draw.lines(s, (*AGENT_COLORS[i % len(AGENT_COLORS)][:3],), False, pts, 1)
            for i, ag in enumerate(sorted(sc.agents.values(), key=lambda a: a.id)):
                pos = r.motion.position(ag.id, self.minute)
                px, py = to_px(pos)
                task = None
                if r.allocation:
                    task = next((t for t in r.allocation.tasks if t.agent == ag.id and t.start <= self.minute < t.end),
                                None)
                ring = self.order_color.get(task.order) if task else MUTED
                rad = cell * 0.36
                if ag.kind == "robot":
                    rr_ = pygame.Rect(0, 0, rad * 2, rad * 2)
                    rr_.center = (px, py)
                    pygame.draw.rect(s, (60, 66, 84), rr_, border_radius=5)
                    pygame.draw.rect(s, ring, rr_, 3, border_radius=5)
                else:
                    pygame.draw.circle(s, (230, 230, 236), (px, py), rad)
                    pygame.draw.circle(s, ring, (px, py), rad, 3)
                blit_text(s, ag.id[:2], (px, py), 11, (15, 15, 20) if ag.kind != "robot" else TEXT, True,
                          anchor="center")
        # legend
        lx = rect.x + 14
        ly = rect.bottom - 22
        for stype in ("storage", "prep", "stove", "steamer", "packaging", "dispatch"):
            pygame.draw.rect(s, STATION_COLORS[stype], (lx, ly + 3, 10, 10), border_radius=2)
            lx = blit_text(s, stype, (lx + 14, ly), 11, MUTED).right + 12
        lx = blit_text(s, "( ) human  [ ] robot", (lx + 6, ly), 11, MUTED).right

    # ---- road network ----------------------------------------------------------------------
    def _draw_roads(self, s, r, rect):
        panel(s, rect, "Delivery network  (weighted road graph, A* routing)")
        net = r.scenario.roads
        area = rect.inflate(-150, -110).move(0, 4)
        xs = [p.x for p in net.places.values()]
        ys = [p.y for p in net.places.values()]
        sx = area.width / max(1e-9, max(xs) - min(xs))
        sy = area.height / max(1e-9, max(ys) - min(ys))
        to_px = lambda pid: (area.x + (net.places[pid].x - min(xs)) * sx,  # noqa: E731
                             area.y + (net.places[pid].y - min(ys)) * sy)
        used_by: dict[str, list[str]] = {}
        if r.allocation:
            for d in r.allocation.deliveries:
                if d.route:
                    for rid in d.route.roads:
                        used_by.setdefault(rid, []).append(d.order)
        for road in net.roads.values():
            a, b = to_px(road.a), to_px(road.b)
            if road.open:
                pygame.draw.line(s, (70, 80, 104), a, b, 5)
            else:
                dashed_line(s, (232, 93, 117), a, b, 4)
                mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                pygame.draw.line(s, (232, 93, 117), (mx - 7, my - 7), (mx + 7, my + 7), 3)
                pygame.draw.line(s, (232, 93, 117), (mx - 7, my + 7), (mx + 7, my - 7), 3)
            # orders using this road, drawn as offset coloured strands
            orders = used_by.get(road.id, [])
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy) or 1
            nx, ny = -dy / n, dx / n
            for i, oid in enumerate(orders):
                off = (i - (len(orders) - 1) / 2) * 4
                pygame.draw.line(s, self.order_color.get(oid, ACCENT), (a[0] + nx * off, a[1] + ny * off),
                                 (b[0] + nx * off, b[1] + ny * off), 3)
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            blit_text(s, f"{road.id} {road.minutes:g}'", (mx + nx * 12, my + ny * 12), 10, MUTED, anchor="center")
        for p in net.places.values():
            x, y = to_px(p.id)
            if p.kind == "junction":
                pygame.draw.circle(s, (110, 120, 145), (x, y), 5)
                blit_text(s, p.id, (x + 8, y - 6), 10, MUTED)
                continue
            if p.kind == "depot":
                rr = pygame.Rect(0, 0, 26, 26)
                rr.center = (x, y)
                pygame.draw.rect(s, ACCENT, rr, border_radius=5)
                blit_text(s, "K", rr.center, 14, (20, 20, 20), True, anchor="center")
            elif p.kind == "hospital":
                pygame.draw.circle(s, (240, 240, 245), (x, y), 14)
                pygame.draw.rect(s, (232, 93, 117), (x - 3, y - 9, 6, 18))
                pygame.draw.rect(s, (232, 93, 117), (x - 9, y - 3, 18, 6))
            else:
                pygame.draw.circle(s, (123, 211, 137), (x, y), 12)
                pygame.draw.polygon(s, (20, 40, 26), [(x - 7, y + 4), (x, y - 6), (x + 7, y + 4)])
            reachable = r.routes.get(p.id) is not None or p.kind == "depot"
            label = p.label + ("" if reachable else "  (cut off)")
            col = TEXT if reachable else (232, 93, 117)
            anchor = "midright" if x > rect.centerx + 120 else "midleft"
            off = -18 if anchor == "midright" else 18
            blit_text(s, label, (x + off, y - 14), 12, col, True, anchor=anchor)
            if p.people:
                blit_text(s, f"{p.people} people", (x + off, y + 2), 10, MUTED, anchor=anchor)
        # vehicles
        if r.allocation:
            parked = 0
            for d in r.allocation.deliveries:
                pos = self._vehicle_pos(r, d, to_px)
                if pos is None:
                    continue
                (x, y), moving = pos
                if not moving:
                    x, y = to_px(net.depot)
                    x, y = x - 30, y + 22 + parked * 0
                    parked += 1
                    continue
                vr = pygame.Rect(0, 0, 30, 18)
                vr.center = (x, y)
                pygame.draw.rect(s, self.order_color.get(d.order, ACCENT), vr, border_radius=4)
                pygame.draw.rect(s, (15, 15, 20), vr, 1, border_radius=4)
                blit_text(s, d.vehicle, vr.center, 11, (15, 15, 20), True, anchor="center")
        # ETA table
        y = rect.bottom - 22
        x = rect.x + 14
        if r.allocation:
            for d in r.allocation.deliveries:
                txt = f"{d.order} {d.vehicle}: {r.scenario.clock(d.depart)} > {r.scenario.clock(d.arrive)}"
                pygame.draw.rect(s, self.order_color.get(d.order, ACCENT), (x, y + 3, 10, 10), border_radius=2)
                x = blit_text(s, txt, (x + 14, y), 11, MUTED).right + 14

    def _vehicle_pos(self, r, d, to_px):
        if not d.route:
            return None
        t = self.minute
        if t < d.depart or t > d.back:
            return (0, 0), False
        nodes = d.route.nodes
        net = r.scenario.roads
        legs = [net.road_between(a, b).minutes for a, b in zip(nodes, nodes[1:])]
        total = sum(legs) or 1
        if t <= d.arrive:
            frac = (t - d.depart) / max(1e-9, d.arrive - d.depart)
        elif t <= d.arrive + UNLOAD_MINUTES:
            frac = 1.0
        else:
            frac = 1 - (t - d.arrive - UNLOAD_MINUTES) / max(1e-9, d.back - d.arrive - UNLOAD_MINUTES)
        dist = frac * total
        for (a, b), leg in zip(zip(nodes, nodes[1:]), legs):
            if dist <= leg:
                pa, pb = to_px(a), to_px(b)
                f = dist / leg
                return (pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f), True
            dist -= leg
        return to_px(nodes[-1]), True

    # ---- gantt -----------------------------------------------------------------------------
    def _draw_gantt(self, s, r, rect):
        panel(s, rect, "CSP schedule  (agents, stations and vehicles over time)")
        sc = r.scenario
        if not r.allocation:
            blit_text(s, "no feasible order", rect.center, 16, MUTED, anchor="center")
            return
        al = r.allocation
        agents = sorted(sc.agents)
        vehicles = sorted(sc.vehicles)
        rows = [("agent", a) for a in agents] + [("vehicle", v) for v in vehicles]
        left = rect.x + 78
        right = rect.right - 14
        top = rect.y + 52
        bottom = rect.bottom - 30
        span = max(60.0, math.ceil(self.end_minute() / 60) * 60)
        self._t_span = span
        rh = (bottom - top) / len(rows)
        tx = lambda m: left + (right - left) * m / span  # noqa: E731
        self._timeline = pygame.Rect(left, rect.y + 30, right - left, bottom - rect.y - 30)
        # hour grid
        for m in range(0, int(span) + 1, 30):
            x = tx(m)
            pygame.draw.line(s, PANEL_EDGE, (x, top - 4), (x, bottom), 1)
            if m % 60 == 0:
                blit_text(s, sc.clock(m), (x, top - 18), 11, MUTED, anchor="midtop")
        # deadlines
        for o in sc.orders:
            if o.deadline <= span:
                x = tx(o.deadline)
                col = self.order_color.get(o.id, ACCENT)
                pygame.draw.polygon(s, col, [(x - 5, bottom + 2), (x + 5, bottom + 2), (x, bottom - 6)])
                blit_text(s, o.id, (x, bottom + 4), 10, col, anchor="midtop")
        for i, (kind, rid) in enumerate(rows):
            y = top + i * rh
            if i == len(agents):
                pygame.draw.line(s, PANEL_EDGE, (rect.x + 10, y), (rect.right - 10, y), 1)
            label = rid if kind == "agent" else f"{rid} ({sc.vehicles[rid].capacity})"
            blit_text(s, label, (rect.x + 14, y + rh / 2), 12, TEXT if kind == "agent" else MUTED, anchor="midleft")
        for t in al.tasks:
            i = agents.index(t.agent)
            y = top + i * rh + 3
            bar = pygame.Rect(tx(t.start) + 1, y, max(2, tx(t.end) - tx(t.start) - 2), rh - 6)
            col = self.order_color.get(t.order, ACCENT)
            pygame.draw.rect(s, col, bar, border_radius=4)
            if self.selected == t.order:
                pygame.draw.rect(s, TEXT, bar, 2, border_radius=4)
            lab = f"{t.order}.{t.stage[:4]} {t.station}"
            if font(10).size(lab)[0] < bar.width - 4:
                blit_text(s, lab, (bar.x + 4, bar.centery), 10, (15, 15, 20), anchor="midleft")
            elif font(10).size(t.stage[0].upper())[0] < bar.width - 2:
                blit_text(s, t.stage[0].upper(), bar.center, 10, (15, 15, 20), anchor="center")
        for d in al.deliveries:
            i = len(agents) + vehicles.index(d.vehicle)
            y = top + i * rh + 3
            col = self.order_color.get(d.order, ACCENT)
            out = pygame.Rect(tx(d.depart), y, max(2, tx(d.arrive) - tx(d.depart)), rh - 6)
            back = pygame.Rect(tx(d.arrive), y + 4, max(2, tx(d.back) - tx(d.arrive)), rh - 14)
            pygame.draw.rect(s, col, out, border_radius=4)
            pygame.draw.rect(s, col, back, 1, border_radius=4)
            lab = f"{d.order} > {r.scenario.roads.places[d.destination].label}"
            if font(10).size(lab)[0] < out.width - 4:
                blit_text(s, lab, (out.x + 4, out.centery), 10, (15, 15, 20), anchor="midleft")
            else:
                blit_text(s, d.order, (out.x + 3, out.centery), 10, (15, 15, 20), anchor="midleft")
        # now line
        x = tx(self.minute)
        pygame.draw.line(s, ACCENT, (x, top - 6), (x, bottom), 2)

    # ---- orders and diagnosis --------------------------------------------------------------
    def _draw_orders(self, s, r, rect):
        panel(s, rect, "Orders  &  infeasibility diagnosis")
        sc = r.scenario
        y = rect.y + 34
        self._order_rows = []
        deliveries = {d.order: d for d in r.allocation.deliveries} if r.allocation else {}
        for o in sorted(sc.orders, key=lambda o: (-o.priority, o.deadline)):
            row = pygame.Rect(rect.x + 8, y, rect.width - 16, 24)
            if self.selected == o.id:
                pygame.draw.rect(s, PANEL_EDGE, row, border_radius=6)
            col = self.order_color.get(o.id, ACCENT)
            pygame.draw.rect(s, col, (row.x + 6, row.y + 6, 12, 12), border_radius=3)
            dest = sc.roads.places[o.destination].label
            blit_text(s, f"{o.id}  {o.meals:>3} meals > {dest}", (row.x + 24, row.y + 4), 12, TEXT, True)
            x = row.right - 6
            if o.id in deliveries:
                d = deliveries[o.id]
                ok = d.arrive <= o.deadline
                txt = f"{sc.clock(d.arrive)} (by {sc.clock(o.deadline)})"
                rr = blit_text(s, txt, (x, row.y + 5), 11, (123, 211, 137) if ok else (232, 93, 117),
                               anchor="topright")
                blit_text(s, "OK", (rr.x - 8, row.y + 4), 12, (123, 211, 137), True, anchor="topright")
            elif o.id in r.diagnoses:
                cats = r.diagnoses[o.id].categories
                widths = [font(10, True).size(c)[0] + 16 for c in cats]
                cx = x - sum(widths)
                for c, w_ in zip(cats, widths):
                    chip(s, c, (cx, row.y + 3), CATEGORY_COLORS.get(c, MUTED), 10)
                    cx += w_
            self._order_rows.append((row, o.id))
            y += 26
        y += 6
        pygame.draw.line(s, PANEL_EDGE, (rect.x + 12, y), (rect.right - 12, y))
        y += 8
        sel = self.selected if self.selected in {o.id for o in sc.orders} else None
        if sel is None:
            blit_text(s, "click an order (or press D) for details", (rect.x + 14, y), 12, MUTED)
            return
        o = next(o for o in sc.orders if o.id == sel)
        width = rect.width - 30
        diet = ", ".join(sorted(o.diet)) or "no restriction"
        blit_text(s, f"{o.id}: diet [{diet}], priority {o.priority}, deadline {sc.clock(o.deadline)}",
                  (rect.x + 14, y), 12, TEXT, True)
        y += 20
        lines: list[tuple[str, tuple, bool]] = []
        if sel in r.diagnoses:
            d = r.diagnoses[sel]
            mode = ("cannot be met on its own" if d.mode == "isolated"
                    else "conflicts with higher-priority orders")
            lines.append((f"INFEASIBLE - {mode}", (232, 93, 117), True))
            for c in d.causes:
                lines.append((f"[{c.category}] {c.detail}", CATEGORY_COLORS.get(c.category, MUTED), False))
        elif sel in deliveries:
            dlv = deliveries[sel]
            rec = sc.recipes[dlv.recipe]
            lines.append((f"menu: {rec.name}  (allergens: {', '.join(sorted(rec.allergens)) or 'none'})", TEXT, False))
            route = " > ".join(dlv.route.nodes) if dlv.route else "-"
            lines.append((f"vehicle {dlv.vehicle}: leaves {sc.clock(dlv.depart)}, arrives {sc.clock(dlv.arrive)}, "
                          f"back {sc.clock(dlv.back)}", TEXT, False))
            lines.append((f"route: {route}  ({dlv.route.minutes:.0f} min)" if dlv.route else "route: -", MUTED, False))
            batches = sorted({t.batch for t in r.allocation.tasks if t.order == sel})
            lines.append((f"{len(batches)} batch(es); stations "
                          f"{', '.join(sorted({t.station for t in r.allocation.tasks if t.order == sel}))}", MUTED, False))
            plan = r.ingredient_plan.get(sel, {})
            picks = "; ".join(f"{ing} " + "+".join(f"{kg:g}kg@{sh}" for sh, kg, _ in p) for ing, p in plan.items())
            if picks:
                lines.append((f"pick list: {picks}", MUTED, False))
        for text, col, bold in lines:
            for ln in wrap(text, 12, width):
                if y > rect.bottom - 18:
                    return
                blit_text(s, ln, (rect.x + 14, y), 12, col, bold)
                y += 16
            y += 2

    # ---- footer / overlays ------------------------------------------------------------------
    def _draw_footer(self, s):
        keys = ("SPACE play/pause   <- -> time   up/down speed   TAB next step   1-9 scenario   "
                "R close a road   F fail a stove   D select order   S screenshot   H help")
        blit_text(s, keys, (16, H - 26), 12, MUTED)
        if self.message:
            blit_text(s, self.message, (W - 16, H - 26), 12, ACCENT, anchor="topright")

    def _overlay(self, s, text):
        if self.cur is None:
            return
        box = pygame.Rect(0, 0, 420, 70)
        box.center = (W // 2, H // 2)
        shade = pygame.Surface(box.size, pygame.SRCALPHA)
        shade.fill((10, 12, 18, 220))
        s.blit(shade, box)
        pygame.draw.rect(s, ACCENT, box, 2, border_radius=10)
        blit_text(s, text, box.center, 16, TEXT, True, anchor="center")

    def _draw_help(self, s):
        box = pygame.Rect(0, 0, 720, 420)
        box.center = (W // 2, H // 2)
        shade = pygame.Surface(box.size, pygame.SRCALPHA)
        shade.fill((10, 12, 18, 235))
        s.blit(shade, box)
        pygame.draw.rect(s, ACCENT, box, 2, border_radius=10)
        text = [
            ("What you are looking at", True),
            ("Kitchen: agents move on a 4-connected grid graph. Every time the CSP schedule changes their", False),
            ("goals, prioritised planning (space-time A* per agent) finds collision-free timed paths.", False),
            ("Roads: A* routes from the kitchen; closed roads are dashed red and routes are recomputed.", False),
            ("Schedule: the CSP assigns each batch task an agent, station and start slot, and each order a", False),
            ("menu variant, vehicle and departure, under dietary, stock, skill, shift, capacity, deadline,", False),
            ("food-safety, workspace and priority constraints.", False),
            ("Diagnosis: per-category checks (stock, equipment, staff, roads, time), then relaxing one", False),
            ("constraint category at a time - ingredients / equipment / staff / time / transport.", False),
            ("", False),
            ("Keys", True),
            ("SPACE play/pause    LEFT/RIGHT -/+ 10 min    UP/DOWN speed    HOME restart", False),
            ("TAB / P next / previous timeline step (initial plan, then after each scenario event)", False),
            ("1-9 load scenario file    R close a used road    F fail a stove", False),
            ("D or click: select order    S screenshot    H toggle this help    Q / ESC quit", False),
        ]
        y = box.y + 18
        for line, bold in text:
            blit_text(s, line, (box.x + 22, y), 14 if bold else 13, ACCENT if bold else TEXT, bold)
            y += 24 if bold else 21


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
    pygame.display.set_caption("Relief Kitchen - Module 1")
    screen = pygame.display.set_mode((W, H))
    app = App(args.scenario)
    clock = pygame.time.Clock()

    if args.screenshot:
        while app.busy or app._pending is not None:
            app.tick(0)
            pygame.time.wait(50)
        app.tick(0)
        app.step = args.step % len(app.steps)
        sc = app.cur.scenario
        h, m = map(int, args.at.split(":"))
        app.minute = h * 60 + m - sc.start_clock
        app.playing = False
        if args.select:
            app.selected = args.select
        app.draw(screen)
        pygame.image.save(screen, args.screenshot)
        print(f"saved {args.screenshot}")
        pygame.quit()
        return

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for ev in pygame.event.get():
            running = app.handle(ev) and running
        app.tick(dt)
        app.draw(screen)
        pygame.display.flip()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
