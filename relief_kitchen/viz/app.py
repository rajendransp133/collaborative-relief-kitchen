"""Pygame visualiser: three Module 1 pages over the same plan, plus Module 2 and Module 3 pages.

    python -m relief_kitchen.viz --scenario configs/scenarios/road_closure.yaml

    Scenarios  every scenario file as a card: click one to load it, then open a page
    Kitchen    floor plan: agents on collision-free paths, food batches carried station to station,
               live shelf stock, what every station is doing; hover for details, click to pin them
    Delivery   road network, A* routes, vehicles in transit, deliveries and vehicle use
    Overview   small maps, the CSP schedule (Gantt) and the orders with their diagnosis
    Planning   (M2) the partial-order plan, its schedule and how POP built it
    Uncertainty (M3) Bayesian belief in disruptions over the timeline, plan risk, contingencies

Style: one `ViewState` record (see `state.py`) holds everything; plain functions update it
(`handle_event`, `tick`) or read it to paint a page (`draw`). Each page lives in its own module.
"""

from __future__ import annotations

import argparse
import os
import sys

import pygame

from ..support.env.scenario import Event
from .page_delivery import draw_delivery_page, place_tooltip, road_tooltip, vehicle_tooltip
from .page_kitchen import agent_tooltip, batch_tooltip, draw_kitchen_page, station_tooltip
from .page_overview import draw_overview_page, task_tooltip
from .page_scenarios import draw_scenarios_page
from .page_planning import draw_planning_page, step_tooltip
from .page_uncertainty import belief_tooltip, draw_uncertainty_page
from .state import (PAGES, ViewState, add_event, current, cycle_selection, end_minute, load, new_state, random_road,
                    random_stove, tick)
from .theme import ORDER_COLORS, PAPER, set_scale, to_logical
from .widgets import H, W, busy_note, draw_footer, draw_header, draw_help, draw_tooltip, hovered

PAGE_DRAW = {"scenarios": draw_scenarios_page, "kitchen": draw_kitchen_page, "delivery": draw_delivery_page, "overview": draw_overview_page,
             "planning": draw_planning_page, "uncertainty": draw_uncertainty_page}
TOOLTIPS = {"station": station_tooltip, "agent": agent_tooltip, "batch": batch_tooltip, "place": place_tooltip,
            "road": road_tooltip, "vehicle": vehicle_tooltip, "task": task_tooltip, "pstep": step_tooltip,
            "belief": belief_tooltip}


def handle_event(st: ViewState, ev) -> bool:
    """Update the state for one pygame event. Returns False when the window should close."""
    if ev.type == pygame.QUIT:
        return False
    if ev.type == pygame.MOUSEMOTION:
        st.mouse = to_logical(ev.pos)
    if ev.type == pygame.KEYDOWN:
        k = ev.key
        if k in (pygame.K_ESCAPE, pygame.K_q):
            return False
        keys = {pygame.K_c: "scenarios", pygame.K_k: "kitchen", pygame.K_v: "delivery", pygame.K_o: "overview", pygame.K_l: "planning",
                pygame.K_u: "uncertainty"}
        if k in keys:
            st.page = keys[k]
        elif k == pygame.K_SPACE:
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
        elif k == pygame.K_F11:
            toggle_fullscreen()
    if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
        pos = to_logical(ev.pos)
        hit = False
        for rect, action, value in st.clicks:
            if rect.collidepoint(pos):
                hit = True
                if action == "page":
                    st.page = value
                elif action == "step":
                    st.step = value
                elif action == "order":
                    st.selected = value
                elif action == "load" and value != st.path and not st.busy:
                    load(st, value)
                    st.minute = 0
                elif action == "ktab":
                    st.kitchen_tab = value
                elif action == "play":
                    st.playing = not st.playing
                elif action == "speed":
                    st.speed = value
                elif action == "reset":
                    st.minute = 0
                elif action == "unpin":
                    st.pinned = None
                elif action == "fail" and not st.busy:
                    add_event(st, lambda sc, sid=value: Event("fail_station", {"station": sid}, f"Station {sid} failed"))
        if not hit and st.page == "kitchen":
            st.mouse = pos
            target = hovered(st)
            if target and target[0] in ("station", "agent", "batch"):
                st.pinned = None if target == st.pinned else target  # a second click unpins
        if st.scrub.collidepoint(pos):
            frac = (pos[0] - st.scrub.x) / max(1, st.scrub.width)
            st.minute = max(0.0, min(end_minute(st), frac * st.t_span))
    return True


# ---------------------------------------------------------------------------------------------
# window: sharp on high-DPI screens, resizable, F11 for fullscreen
# ---------------------------------------------------------------------------------------------
_window_size = (W, H)  # size to return to when leaving fullscreen


def enable_dpi_awareness():
    """Stop Windows from bitmap-stretching (blurring) the window on scaled displays."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def open_window():
    """A resizable window filling most of the desktop, with the canvas's aspect ratio."""
    global _window_size
    dw, dh = pygame.display.get_desktop_sizes()[0]
    f = min(dw * 0.92 / W, dh * 0.85 / H)
    _window_size = (round(W * f), round(H * f))
    return pygame.display.set_mode(_window_size, pygame.RESIZABLE)


def toggle_fullscreen():
    global _window_size
    screen = pygame.display.get_surface()
    if screen.get_flags() & pygame.FULLSCREEN:
        pygame.display.set_mode(_window_size, pygame.RESIZABLE)
    else:
        _window_size = screen.get_size()
        pygame.display.set_mode((0, 0), pygame.FULLSCREEN)  # (0, 0) = the desktop's own resolution


def screenshot(st: ViewState, path: str | None = None):
    path = path or f"relief_{st.page}_{st.step}.png"
    pygame.image.save(st.screen, path)
    st.message = f"Saved {path}"


def draw(st: ViewState, screen):
    """Paint the current page, then the tooltip for whatever is under the mouse."""
    st.screen = screen
    st.hover = []
    set_scale(*screen.get_size())
    screen.fill(PAPER)
    draw_header(st, screen)
    r = current(st)
    if st.page == "scenarios":
        draw_scenarios_page(st, screen, r)
        draw_footer(st, screen)
        if st.show_help:
            draw_help(st, screen)
        return
    if r is None:
        busy_note(st, screen)
        return
    st.order_color = {o.id: ORDER_COLORS[i % len(ORDER_COLORS)] for i, o in enumerate(r.scenario.orders)}
    PAGE_DRAW[st.page](st, screen, r)
    draw_footer(st, screen)
    target = hovered(st)
    if target and target[0] in TOOLTIPS and (target[0] != "task" or r.allocation):
        draw_tooltip(screen, TOOLTIPS[target[0]](st, r, target[1]), st.mouse)
    if st.show_help:
        draw_help(st, screen)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Relief kitchen visualiser (Modules 1-3)")
    ap.add_argument("--scenario", default="configs/scenarios/road_closure.yaml")
    ap.add_argument("--page", choices=PAGES, default="scenarios")
    ap.add_argument("--screenshot", help="render one frame to this PNG and exit (works headless)")
    ap.add_argument("--at", default="09:20", help="clock time for --screenshot")
    ap.add_argument("--step", type=int, default=-1, help="timeline step for --screenshot (-1 = last)")
    ap.add_argument("--select", help="order to select for --screenshot")
    ap.add_argument("--hover", help="mouse position x,y for --screenshot (shows that tooltip)")
    ap.add_argument("--pin", help="kitchen item to pin for --screenshot: station:C2, agent:Anu or batch:O1:1")
    ap.add_argument("--tab", choices=("batches", "stock"), help="kitchen list tab for --screenshot")
    ap.add_argument("--scale", type=float, default=2.0, help="resolution multiplier for --screenshot")
    args = ap.parse_args(argv)

    if args.screenshot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    else:
        enable_dpi_awareness()
    pygame.init()
    pygame.display.set_caption("Relief Kitchen")
    if args.screenshot:
        screen = pygame.display.set_mode((round(W * args.scale), round(H * args.scale)))
    else:
        screen = open_window()
    st = new_state(args.scenario, args.page)
    frame_clock = pygame.time.Clock()

    if args.screenshot:
        while st.busy or st.pending is not None:
            tick(st, 0)
            pygame.time.wait(50)
        set_scale(*screen.get_size())
        tick(st, 0)
        st.step = args.step % len(st.steps)
        h, m = map(int, args.at.split(":"))
        st.minute = h * 60 + m - current(st).scenario.start_clock
        st.playing = False
        if args.select:
            st.selected = args.select
        if args.pin:
            kind, _, rest = args.pin.partition(":")
            if kind == "batch":
                order, _, batch = rest.partition(":")
                st.pinned = (kind, (order, int(batch)))
            else:
                st.pinned = (kind, rest)
        if args.tab:
            st.kitchen_tab = args.tab
        if args.hover:
            draw(st, screen)  # first pass records the hover targets
            st.mouse = tuple(int(v) for v in args.hover.split(","))
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
        draw(st, pygame.display.get_surface())  # the surface changes on resize / F11
        pygame.display.flip()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
