"""Shared chrome: top nav bar, tab bar, step bar, time scrubber, tooltip, help modal."""

from __future__ import annotations

import pygame

from ..env.scenario import clock
from .state import PAGES, ViewState, current, end_minute
from .theme import (ACCENT, BAND, ERROR, FAINT, HAIRLINE, HIGHLIGHT, INK, MUTED,
                    PAPER, SURFACE, card, disc, fit, font, hline, text, text_width, wrap)

W, H = 1440, 860
M = 24

# Header zones (must sum to CONTENT_TOP)
_NAV_H  = 64   # app bar: logo, title, clock
_TAB_H  = 44   # page tab bar
_STEP_H = 28   # plan-step breadcrumb strip
CONTENT_TOP    = _NAV_H + _TAB_H + _STEP_H   # = 136
CONTENT_BOTTOM = H - 64

PAGE_TITLES = {"kitchen": "Kitchen", "delivery": "Delivery", "overview": "Overview"}


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
def draw_header(st: ViewState, s):
    r = current(st)

    # ── App bar ──────────────────────────────────────────────────────────────
    pygame.draw.rect(s, SURFACE, (0, 0, W, _NAV_H))

    # Logo mark (blue rounded square)
    logo_rect = pygame.Rect(M, (_NAV_H - 28) // 2, 28, 28)
    pygame.draw.rect(s, ACCENT, logo_rect, border_radius=6)
    text(s, "RK", logo_rect.center, 11, SURFACE, True, anchor="center")

    # App title + subtitle
    title_r = text(s, "Relief Kitchen", (logo_rect.right + 12, _NAV_H // 2), 17, INK, True, anchor="midleft")
    text(s, "Module 1  ·  Search & Constraint Satisfaction",
         (title_r.right + 16, _NAV_H // 2 + 1), 11, MUTED, anchor="midleft")

    # Scenario name tag
    if r is not None:
        sc_name = r.scenario.name
        tw = text_width(sc_name, 11) + 18
        t_rect = pygame.Rect(title_r.right + 16 + text_width("Module 1  ·  Search & Constraint Satisfaction", 11) + 18,
                             _NAV_H // 2 - 11, tw, 22)
        pygame.draw.rect(s, HIGHLIGHT, t_rect, border_radius=4)
        pygame.draw.rect(s, ACCENT, t_rect, 1, border_radius=4)
        text(s, sc_name, t_rect.center, 11, ACCENT, anchor="center")

    # Clock + playback (right side)
    if r is not None:
        clk_r = text(s, clock(r.scenario, st.minute), (W - M, 10), 26, INK, True, anchor="topright")
        state_label = "playing" if st.playing else "paused"
        text(s, f"{state_label}  ·  {st.speed:g} min/s", (W - M, clk_r.bottom + 3), 11, FAINT, anchor="topright")

    # Bottom border
    pygame.draw.line(s, HAIRLINE, (0, _NAV_H), (W, _NAV_H), 1)

    # ── Tab bar ───────────────────────────────────────────────────────────────
    tab_top = _NAV_H
    pygame.draw.rect(s, SURFACE, (0, tab_top, W, _TAB_H))

    st.clicks = []
    x = M
    for page in PAGES:
        active = page == st.page
        label = PAGE_TITLES[page]
        col = ACCENT if active else MUTED
        tab_r = text(s, label, (x, tab_top + _TAB_H // 2), 14, col, active, anchor="midleft")
        if active:
            ind = pygame.Rect(tab_r.x - 2, tab_top + _TAB_H - 3, tab_r.width + 4, 3)
            pygame.draw.rect(s, ACCENT, ind, border_radius=2)
        st.clicks.append((tab_r.inflate(20, 24), "page", page))
        x = tab_r.right + 38

    # Stats (right-aligned in tab bar)
    if r is not None:
        if st.busy:
            text(s, st.busy + " …", (W - M, tab_top + _TAB_H // 2), 12, ACCENT, True, anchor="midright")
        else:
            parts = []
            if r.allocation:
                stats = r.allocation.result.stats
                parts.append(f"CSP {stats.nodes} nodes · {stats.backtracks} bt · {stats.seconds * 1000:.0f} ms")
            if r.motion:
                parts.append(f"{r.motion.collisions} collision(s)")
            parts.append(f"{len(r.accepted)} accepted · {len(r.diagnoses)} rejected")
            text(s, "   ·   ".join(parts), (W - M, tab_top + _TAB_H // 2), 11, FAINT, anchor="midright")

    pygame.draw.line(s, HAIRLINE, (0, tab_top + _TAB_H), (W, tab_top + _TAB_H), 1)

    # ── Step bar ──────────────────────────────────────────────────────────────
    step_top = tab_top + _TAB_H
    pygame.draw.rect(s, BAND, (0, step_top, W, _STEP_H))

    if r is None:
        return

    text(s, "PLAN", (M, step_top + _STEP_H // 2), 10, FAINT, True, anchor="midleft")
    x = M + text_width("PLAN", 10, True) + 14
    for i, step in enumerate(st.steps):
        active = i == st.step
        label = fit(step.label, 11, 280, active)
        cy = step_top + _STEP_H // 2
        if active:
            tw = text_width(label, 11, True) + 18
            pill = pygame.Rect(x, cy - 10, tw, 20)
            pygame.draw.rect(s, ACCENT, pill, border_radius=10)
            text(s, label, pill.center, 11, SURFACE, True, anchor="center")
            st.clicks.append((pill, "step", i))
            x = pill.right + 14
        else:
            r_ = text(s, label, (x, cy), 11, MUTED, anchor="midleft")
            st.clicks.append((r_.inflate(12, 12), "step", i))
            x = r_.right + 18

    pygame.draw.line(s, HAIRLINE, (0, step_top + _STEP_H - 1), (W, step_top + _STEP_H - 1), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Footer — time scrubber + key hints
# ─────────────────────────────────────────────────────────────────────────────
def draw_footer(st: ViewState, s):
    r = current(st)
    footer_top = H - 64
    pygame.draw.rect(s, SURFACE, (0, footer_top, W, 64))
    pygame.draw.line(s, HAIRLINE, (0, footer_top), (W, footer_top), 1)

    if r is not None:
        span = max(60.0, end_minute(st))
        st.t_span = span
        track = pygame.Rect(M + 48, footer_top + 16, W - 2 * M - 48, 4)
        st.scrub = track.inflate(0, 20)

        text(s, "TIME", (M, track.centery), 10, FAINT, True, anchor="midleft")

        # Track background
        pygame.draw.rect(s, HAIRLINE, track, border_radius=2)
        # Filled portion
        done = track.width * min(1.0, st.minute / span)
        pygame.draw.rect(s, ACCENT, (track.x, track.y, done, track.height), border_radius=2)

        # Hour ticks
        for m in range(0, int(span) + 1, 60):
            x = track.x + track.width * m / span
            pygame.draw.line(s, FAINT, (x, track.bottom + 3), (x, track.bottom + 6))
            text(s, clock(r.scenario, m), (x, track.bottom + 8), 9, FAINT, anchor="midtop")

        # Knob — Ant Design slider thumb style
        knob_x = int(track.x + done)
        knob_y = track.centery
        disc(s, SURFACE, (knob_x, knob_y), 7)
        pygame.draw.circle(s, ACCENT, (knob_x, knob_y), 7, 2)

    # Key hints
    hint_y = footer_top + 44
    x = M
    hints = [
        ("Space", "play"), ("← →", "time"), ("↑ ↓", "speed"),
        ("K V O", "pages"), ("Tab", "step"), ("1–9", "scenario"),
        ("R", "road off"), ("F", "stove fail"), ("S", "screenshot"), ("H", "help"),
    ]
    for key, what in hints:
        key_r = text(s, key, (x, hint_y), 11, INK, True)
        x = text(s, what, (key_r.right + 5, hint_y), 11, MUTED).right + 16
    if st.message:
        text(s, st.message, (W - M, hint_y), 11, FAINT, anchor="topleft" if x < W - 300 else "topright")


# ─────────────────────────────────────────────────────────────────────────────
# Tooltip — Ant Design Popover style
# ─────────────────────────────────────────────────────────────────────────────
def draw_tooltip(s, lines, mouse, width=360):
    pad, inner = 16, width - 32
    rendered = []
    for ln in lines:
        kind = ln[0]
        if kind == "title":
            rendered.append((kind, ln, 24))
        elif kind in ("sub", "text"):
            for w_ in wrap(ln[1], 12 if kind == "text" else 11, inner):
                rendered.append((kind, (kind, w_) + tuple(ln[2:]), 18 if kind == "text" else 16))
        elif kind == "kv":
            for i, w_ in enumerate(wrap(ln[2], 12, inner - 96)):
                rendered.append(("kv", ("kv", ln[1] if i == 0 else "", w_) + tuple(ln[3:]), 18))
        elif kind == "bar":
            rendered.append((kind, ln, 14))
        elif kind == "rule":
            rendered.append((kind, ln, 12))
        elif kind == "head":
            rendered.append((kind, ln, 20))
    height = sum(h for *_, h in rendered) + 2 * pad
    box = pygame.Rect(mouse[0] + 16, mouse[1] + 12, width, height)
    if box.right > W - 8:
        box.right = mouse[0] - 12
    if box.bottom > H - 8:
        box.bottom = H - 8

    # Shadow
    sh = pygame.Surface((box.width + 16, box.height + 16), pygame.SRCALPHA)
    pygame.draw.rect(sh, (0, 0, 0, 12),
                     pygame.Rect(4, 6, box.width + 8, box.height + 8), border_radius=10)
    pygame.draw.rect(sh, (0, 0, 0, 8),
                     pygame.Rect(2, 3, box.width + 12, box.height + 12), border_radius=12)
    s.blit(sh, (box.x - 8, box.y - 8))

    pygame.draw.rect(s, SURFACE, box, border_radius=8)
    pygame.draw.rect(s, HAIRLINE, box, 1, border_radius=8)

    x, y = box.x + pad, box.y + pad
    for kind, ln, h in rendered:
        if kind == "title":
            text(s, ln[1], (x, y), 15, INK, True)
        elif kind == "sub":
            text(s, ln[1], (x, y), 11, MUTED)
        elif kind == "text":
            text(s, ln[1], (x, y), 12, ln[2] if len(ln) > 2 else INK)
        elif kind == "head":
            text(s, ln[1].upper(), (x, y + 5), 10, FAINT, True)
            pygame.draw.line(s, HAIRLINE, (x, y + h - 2), (box.right - pad, y + h - 2))
        elif kind == "kv":
            text(s, ln[1], (x, y + 1), 11, FAINT)
            text(s, ln[2], (x + 96, y), 12, ln[3] if len(ln) > 3 else INK)
        elif kind == "bar":
            bar = pygame.Rect(x, y + 4, inner, 6)
            pygame.draw.rect(s, HIGHLIGHT, bar, border_radius=3)
            filled = pygame.Rect(bar.x, bar.y, int(bar.width * max(0.0, min(1.0, ln[1]))), 6)
            pygame.draw.rect(s, ln[2], filled, border_radius=3)
        elif kind == "rule":
            pygame.draw.line(s, HAIRLINE, (x, y + 5), (box.right - pad, y + 5))
        y += h


def hovered(st: ViewState):
    for rect, kind, payload in reversed(st.hover):
        if rect.collidepoint(st.mouse):
            return kind, payload
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Meter — Ant Design Progress bar
# ─────────────────────────────────────────────────────────────────────────────
def meter(s, rect: pygame.Rect, frac: float, colour, back=HIGHLIGHT):
    pygame.draw.rect(s, back, rect, border_radius=rect.height // 2)
    filled = pygame.Rect(rect.x, rect.y, int(rect.width * max(0.0, min(1.0, frac))), rect.height)
    pygame.draw.rect(s, colour, filled, border_radius=rect.height // 2)


# ─────────────────────────────────────────────────────────────────────────────
# Help modal — Ant Design Modal style
# ─────────────────────────────────────────────────────────────────────────────
def draw_help(st: ViewState, s):
    # Backdrop
    veil = pygame.Surface((W, H), pygame.SRCALPHA)
    veil.fill((0, 0, 0, 100))
    s.blit(veil, (0, 0))

    modal = pygame.Rect(0, 0, 760, 460)
    modal.center = (W // 2, H // 2)

    # Modal shadow
    sh = pygame.Surface((modal.width + 40, modal.height + 40), pygame.SRCALPHA)
    pygame.draw.rect(sh, (0, 0, 0, 30), pygame.Rect(8, 12, modal.width + 24, modal.height + 24), border_radius=14)
    s.blit(sh, (modal.x - 20, modal.y - 20))

    pygame.draw.rect(s, SURFACE, modal, border_radius=8)
    pygame.draw.rect(s, HAIRLINE, modal, 1, border_radius=8)

    # Modal header
    header = pygame.Rect(modal.x, modal.y, modal.width, 54)
    pygame.draw.rect(s, SURFACE, header, border_top_left_radius=8, border_top_right_radius=8)
    pygame.draw.line(s, HAIRLINE, (modal.x, header.bottom), (modal.right, header.bottom))
    text(s, "Keyboard Shortcuts & How to Read", (modal.x + 24, modal.y + 14), 16, INK, True)

    x, y = modal.x + 24, header.bottom + 20
    notes = [
        ("Kitchen", "Agents navigate a 4-connected grid with collision-free paths (prioritised A*). "
         "Food batches are coloured squares. Hover anything for details."),
        ("Delivery", "A* routes on a weighted road graph. Closed roads shown dashed red."),
        ("Overview", "CSP Gantt chart — light bar ends = carry-in / carry-out time. Click an order for details."),
        ("Colours", "HACCP kitchen coding: brown storage, green prep, red/amber cooking, "
         "blue packing, cyan dispatch."),
    ]
    for title, body in notes:
        text(s, title, (x, y), 13, ACCENT, True)
        y += 20
        for ln in wrap(body, 12, modal.width - 48):
            text(s, ln, (x + 12, y), 12, INK)
            y += 17
        y += 6

    pygame.draw.line(s, HAIRLINE, (x, y + 4), (modal.right - 24, y + 4))
    y += 18

    keys = [
        ("Space", "play / pause"), ("← →", "move 10 min"), ("↑ ↓", "speed"),
        ("K / V / O", "pages"), ("Tab / P", "next / prev step"),
        ("1–9", "load scenario"), ("R", "close a road (live)"),
        ("F", "fail a stove (live)"), ("D", "select order"),
        ("S", "screenshot"), ("H", "close help"), ("Q / Esc", "quit"),
    ]
    for i, (k, what) in enumerate(keys):
        cx = x + (i % 2) * 350
        cy = y + (i // 2) * 22
        kw = text_width(k, 12, True)
        k_rect = pygame.Rect(cx, cy, kw + 12, 20)
        pygame.draw.rect(s, BAND, k_rect, border_radius=4)
        pygame.draw.rect(s, HAIRLINE, k_rect, 1, border_radius=4)
        text(s, k, k_rect.center, 12, INK, True, anchor="center")
        text(s, what, (k_rect.right + 10, cy), 12, MUTED)


# ─────────────────────────────────────────────────────────────────────────────
# Busy spinner note
# ─────────────────────────────────────────────────────────────────────────────
def busy_note(st: ViewState, s):
    if st.busy and current(st) is None:
        cx, cy = W // 2, H // 2
        box = pygame.Rect(cx - 160, cy - 36, 320, 72)
        card(s, box, radius=8)
        disc(s, ACCENT, (cx - 100, cy), 8)
        text(s, st.busy + " …", (cx - 80, cy), 14, INK, anchor="midleft")
