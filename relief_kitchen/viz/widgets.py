"""Shared drawing pieces: header with page tabs, time scrubber, footer, help card and tooltips."""

from __future__ import annotations

import pygame

from ..support.env.scenario import clock
from .state import PAGES, ViewState, current, end_minute
from .theme import (ACCENT, FAINT, HAIRLINE, HIGHLIGHT, INK, LOGICAL_H, LOGICAL_W, MUTED, PAPER, SURFACE, disc,
                    draw_line, draw_rect, fit, hline, shadow, text, veil, wrap)

W, H = LOGICAL_W, LOGICAL_H  # logical canvas; theme.set_scale maps it onto the real window
M = 24  # outer margin
CONTENT_TOP = 136
CONTENT_BOTTOM = H - 70

PAGE_TITLES = {"kitchen": "Kitchen", "delivery": "Delivery", "overview": "Overview"}


# ---------------------------------------------------------------------------------------------
# header: title, clock, page tabs, timeline steps
# ---------------------------------------------------------------------------------------------
def draw_header(st: ViewState, s):
    r = current(st)
    t = text(s, "Relief Kitchen", (M, 14), 20, INK, True)
    text(s, "Module 1  ·  Search & Constraint Satisfaction", (t.right + 14, 20), 13, MUTED)
    if r is not None:
        text(s, r.scenario.name, (M, 42), 13, INK)
        text(s, clock(r.scenario, st.minute), (W - M, 8), 28, INK, True, anchor="topright")
        state = "playing" if st.playing else "paused"
        text(s, f"{state}  ·  {st.speed:g} min/s", (W - M, 46), 11, MUTED, anchor="topright")

    st.clicks = []
    x = M
    for page in PAGES:
        active = page == st.page
        rect = text(s, PAGE_TITLES[page], (x, 70), 15, INK if active else MUTED, active)
        if active:
            draw_line(s, ACCENT, (rect.x, 95), (rect.right, 95), 3)
        st.clicks.append((rect.inflate(16, 18), "page", page))
        x = rect.right + 34
    hline(s, M, W - M, 97)

    if r is None:
        return
    if st.busy:
        text(s, st.busy + " …", (W - M, 74), 12, ACCENT, True, anchor="topright")
    else:
        parts = []
        if r.allocation:
            stats = r.allocation.result.stats
            parts.append(f"CSP {stats.nodes} nodes · {stats.backtracks} backtracks · {stats.seconds * 1000:.0f} ms")
        if r.motion:
            parts.append(f"{r.motion.collisions} collisions")
        parts.append(f"{len(r.accepted)} accepted · {len(r.diagnoses)} rejected")
        text(s, "     |     ".join(parts), (W - M, 76), 11, MUTED, anchor="topright")

    # timeline steps (initial plan, then one per disruption)
    x = text(s, "PLAN", (M, 108), 10, FAINT, True).right + 14
    for i, step in enumerate(st.steps):
        active = i == st.step
        label = fit(f"{i}  {step.label}", 12, 340, active)
        rect = text(s, label, (x, 106), 12, INK if active else MUTED, active)
        if active:
            draw_line(s, ACCENT, (rect.x, 123), (rect.right, 123), 2)
        st.clicks.append((rect.inflate(8, 10), "step", i))
        x = rect.right + 24
    hline(s, M, W - M, 125)


# ---------------------------------------------------------------------------------------------
# footer: time scrubber and key hints
# ---------------------------------------------------------------------------------------------
def draw_footer(st: ViewState, s):
    r = current(st)
    if r is not None:
        span = max(60.0, end_minute(st))
        st.t_span = span
        track = pygame.Rect(M + 44, H - 54, W - 2 * M - 44, 4)
        st.scrub = track.inflate(0, 18)
        text(s, "TIME", (M, H - 60), 10, FAINT, True)
        draw_rect(s, HAIRLINE, track, border_radius=2)
        done = track.width * min(1.0, st.minute / span)
        draw_rect(s, ACCENT, (track.x, track.y, done, track.height), border_radius=2)
        for m in range(0, int(span) + 1, 60):
            x = track.x + track.width * m / span
            draw_line(s, FAINT, (x, track.bottom + 2), (x, track.bottom + 5))
            text(s, clock(r.scenario, m), (x, track.bottom + 6), 9, FAINT, anchor="midtop")
        knob = (track.x + done, track.centery)
        disc(s, ACCENT, knob, 6)
        disc(s, SURFACE, knob, 2)
    hline(s, M, W - M, H - 30)
    x = M
    for key, what in (("Space", "play"), ("← →", "time"), ("↑ ↓", "speed"), ("K V O", "pages"),
                      ("Tab", "next step"), ("1–9", "scenario"), ("R", "close a road"), ("F", "fail a stove"),
                      ("S", "screenshot"), ("F11", "fullscreen"), ("H", "help")):
        k = text(s, key, (x, H - 22), 11, INK, True)
        x = text(s, what, (k.right + 6, H - 22), 11, MUTED).right + 18
    if st.message:
        text(s, st.message, (W - M, H - 22), 11, MUTED, anchor="topright")


# ---------------------------------------------------------------------------------------------
# tooltips
# ---------------------------------------------------------------------------------------------
# A tooltip is a list of lines:
#   ("title", text)  ("sub", text)  ("text", text[, colour])  ("kv", key, value[, colour])
#   ("bar", fraction, colour)  ("rule",)  ("head", text)
def draw_tooltip(s, lines, mouse, width=360):
    pad, inner = 14, width - 28
    rendered = []  # (kind, payload, height)
    for ln in lines:
        kind = ln[0]
        if kind == "title":
            rendered.append((kind, ln, 22))
        elif kind in ("sub", "text"):
            for w_ in wrap(ln[1], 12 if kind == "text" else 11, inner):
                rendered.append((kind, (kind, w_) + tuple(ln[2:]), 17 if kind == "text" else 15))
        elif kind == "kv":
            for i, w_ in enumerate(wrap(ln[2], 12, inner - 86)):
                rendered.append(("kv", ("kv", ln[1] if i == 0 else "", w_) + tuple(ln[3:]), 17))
        elif kind == "bar":
            rendered.append((kind, ln, 12))
        elif kind == "rule":
            rendered.append((kind, ln, 11))
        elif kind == "head":
            rendered.append((kind, ln, 18))
    height = sum(h for *_, h in rendered) + 2 * pad - 4
    box = pygame.Rect(mouse[0] + 18, mouse[1] + 14, width, height)
    if box.right > W - 8:
        box.right = mouse[0] - 14
    if box.bottom > H - 8:
        box.bottom = H - 8
    shadow(s, (box.x - 2, box.y + 2, box.width + 8, box.height + 8))
    draw_rect(s, SURFACE, box, border_radius=6)
    draw_rect(s, HAIRLINE, box, 1, border_radius=6)
    x, y = box.x + pad, box.y + pad
    for kind, ln, h in rendered:
        if kind == "title":
            text(s, ln[1], (x, y), 14, INK, True)
        elif kind == "sub":
            text(s, ln[1], (x, y), 11, MUTED)
        elif kind == "text":
            text(s, ln[1], (x, y), 12, ln[2] if len(ln) > 2 else INK)
        elif kind == "head":
            text(s, ln[1].upper(), (x, y + 4), 10, FAINT, True)
        elif kind == "kv":
            text(s, ln[1], (x, y + 1), 11, MUTED)
            text(s, ln[2], (x + 86, y), 12, ln[3] if len(ln) > 3 else INK)
        elif kind == "bar":
            bar = pygame.Rect(x, y + 3, inner, 5)
            draw_rect(s, HIGHLIGHT, bar, border_radius=2)
            draw_rect(s, ln[2], (bar.x, bar.y, bar.width * max(0.0, min(1.0, ln[1])), 5), border_radius=2)
        elif kind == "rule":
            hline(s, x, box.right - pad, y + 5)
        y += h


def hovered(st: ViewState):
    """Top-most hover target under the mouse, as (kind, payload), or None."""
    for rect, kind, payload in reversed(st.hover):
        if rect.collidepoint(st.mouse):
            return kind, payload
    return None


# ---------------------------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------------------------
def meter(s, rect: pygame.Rect, frac: float, colour, back=HIGHLIGHT):
    draw_rect(s, back, rect, border_radius=2)
    draw_rect(s, colour, (rect.x, rect.y, rect.width * max(0.0, min(1.0, frac)), rect.height),
                     border_radius=2)


def draw_help(st: ViewState, s):
    veil(s, PAPER, 215)
    card = pygame.Rect(0, 0, 720, 460)
    card.center = (W // 2, H // 2)
    draw_rect(s, SURFACE, card, border_radius=6)
    draw_rect(s, HAIRLINE, card, 1, border_radius=6)
    x, y = card.x + 32, card.y + 28
    text(s, "How to read this", (x, y), 16, INK, True)
    y += 34
    notes = [
        "Kitchen page: agents walk on a 4-connected grid with collision-free paths (prioritised planning, "
        "space-time A*). Every step starts with a hand-off: the agent fetches the batch from the previous "
        "station and carries it over. Coloured squares are batches of food. Hover anything for details.",
        "Delivery page: A* routes from the kitchen. Closed roads are dashed red and routes are recomputed.",
        "Overview page: the CSP schedule (agents and vehicles over time) and the orders, with the reason "
        "for every rejected order - ingredients, equipment, staff, time or transport.",
        "Station colours follow HACCP colour coding: brown stores, green prep, warm cooking, yellow "
        "ready-to-eat packing, purple allergen-free.",
    ]
    for note in notes:
        for ln in wrap(note, 12, card.width - 64):
            text(s, ln, (x, y), 12, INK)
            y += 17
        y += 6
    hline(s, x, card.right - 32, y + 4)
    y += 18
    keys = [("Space", "play / pause"), ("← →", "move 10 minutes"), ("↑ ↓", "change speed"),
            ("K / V / O", "kitchen / delivery / overview"), ("Tab / P", "next / previous plan step"),
            ("1–9", "load scenario"), ("R", "close a road (live)"), ("F", "fail a stove (live)"),
            ("D", "select order"), ("S", "screenshot"), ("F11", "fullscreen / window"), ("H", "close help"),
            ("Q / Esc", "quit")]
    for i, (k, what) in enumerate(keys):
        cx = x + (i % 2) * 330
        cy = y + (i // 2) * 21
        text(s, k, (cx, cy), 12, INK, True)
        text(s, what, (cx + 86, cy), 12, MUTED)


def busy_note(st: ViewState, s):
    if st.busy and current(st) is None:
        text(s, st.busy + " …", (W // 2, H // 2), 15, MUTED, anchor="center")

