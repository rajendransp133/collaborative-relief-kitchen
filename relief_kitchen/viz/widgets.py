"""Shared drawing pieces: header with page tabs and plan steps, the playback footer, help card and tooltips."""

from __future__ import annotations

import pygame

from ..support.env.scenario import clock
from .state import PAGES, ViewState, current, end_minute
from .theme import (ACCENT, BORDER, DIVIDER, ERROR, HAIRLINE, HIGHLIGHT, INK, LOGICAL_H, LOGICAL_W, MUTED, PAPER,
                    SUBTLE, SURFACE, caps, card, chip, disc, draw_line, draw_rect, fit, hex_rgb, hline, pill,
                    pill_width, pt, shadow, text, text_width, veil, wrap)

W, H = LOGICAL_W, LOGICAL_H  # logical canvas; theme.set_scale maps it onto the real window
M = 24  # outer margin
HEADER_H = 100  # white header band (title row + page tabs); the plan-step pills sit just under it
FOOTER_TOP = H - 66  # white playback band
CONTENT_TOP = 146
CONTENT_BOTTOM = FOOTER_TOP - 10
GAP = 20  # between cards
PAD = 18  # inside a card
LEFT_W = 952  # the wide left column; the right column takes the rest
RIGHT_X = M + LEFT_W + GAP
RIGHT_W = W - M - RIGHT_X
SPEEDS = (1, 2, 4, 8, 16)  # simulated minutes per real second, the footer's speed buttons
SUBTITLE = "Group 14 · Collaborative Emergency Kitchen and Relief-Supply System"

PAGE_TITLES = {"scenarios": "Scenarios", "kitchen": "Kitchen", "delivery": "Delivery", "overview": "Overview", "planning": "Planning",
               "uncertainty": "Uncertainty"}
MODULE_TITLE = {"planning": "Module 2 · Partial-order planning",
                "uncertainty": "Module 3 · Reasoning under uncertainty"}


# ---------------------------------------------------------------------------------------------
# buttons
# ---------------------------------------------------------------------------------------------
BUTTON_STYLE = {  # kind -> (fill, border, text)
    "secondary": (SURFACE, BORDER, INK),
    "primary": (INK, INK, SURFACE),
    "danger": (SURFACE, hex_rgb("#E0A58C"), ERROR),
    "disabled": (PAPER, HAIRLINE, MUTED),
}


def panel(s, rect, title, note="", note_colour=MUTED) -> int:
    """White card with its title and an optional fact on the right; returns the y where content starts."""
    rect = pygame.Rect(rect)
    card(s, rect)
    t = text(s, title, (rect.x + PAD, rect.y + 16), 17, INK, weight="semibold")
    if note:
        text(s, fit(note, 13, rect.right - PAD - t.right - 16), (rect.right - PAD, rect.y + 19), 13, note_colour,
             anchor="topright")
    return rect.y + 52


def button(st: ViewState, s, rect, label, action, value=None, kind="secondary") -> pygame.Rect:
    """A flat 8px-radius button; registers its click unless disabled."""
    rect = pygame.Rect(rect)
    fill, edge, colour = BUTTON_STYLE[kind]
    draw_rect(s, fill, rect, border_radius=8)
    draw_rect(s, edge, rect, 1, border_radius=8)
    text(s, label, rect.center, 13, colour, anchor="center", weight="semibold")
    if kind != "disabled":
        st.clicks.append((rect, action, value))
    return rect


# ---------------------------------------------------------------------------------------------
# header: logo, title, scenario, clock, page tabs, stats, plan steps
# ---------------------------------------------------------------------------------------------
def draw_logo(s, x, y):
    """Dark tile with a cooking pot (drawn, so no image file is needed)."""
    draw_rect(s, INK, (x, y, 42, 42), border_radius=10)
    draw_rect(s, SURFACE, (x + 11, y + 21, 20, 11), 2, border_bottom_left_radius=4, border_bottom_right_radius=4)
    draw_line(s, SURFACE, (x + 7, y + 21), (x + 35, y + 21), 2)
    for sx in (x + 17, x + 25):
        draw_line(s, SURFACE, (sx, y + 11), (sx, y + 16), 2)


def draw_header(st: ViewState, s):
    r = current(st)
    st.clicks = []
    draw_rect(s, SURFACE, (0, 0, W, HEADER_H))
    hline(s, 0, W, HEADER_H, HAIRLINE)
    draw_logo(s, M, 12)
    t = text(s, "Relief Kitchen", (M + 56, 10), 22, INK, weight="semibold")
    text(s, MODULE_TITLE.get(st.page, "Module 1 · Search and constraint satisfaction"), (t.right + 12, 18), 13, MUTED)
    text(s, SUBTITLE, (M + 56, 38), 13, MUTED)

    if r is not None:
        clock_r = text(s, clock(r.scenario, st.minute), (W - M, 10), 36, INK, anchor="topright", mono=True,
                       weight="semibold")
        div_x = clock_r.x - 22
        draw_line(s, HAIRLINE, (div_x, 14), (div_x, 56))
        name = r.scenario.name
        bx = div_x - 22 - max(text_width(name, 14, weight="medium"), 70)
        caps(s, "Scenario", (bx, 15))
        nr = text(s, name, (bx, 31), 14, INK, weight="medium")
        st.clicks.append((pygame.Rect(bx - 8, 8, div_x - bx, 50), "page", "scenarios"))
        if st.page != "scenarios":
            draw_line(s, HAIRLINE, (nr.x, nr.bottom + 2), (nr.right, nr.bottom + 2))

    # page tabs
    x = M
    for page in PAGES:
        active = page == st.page
        rect = text(s, PAGE_TITLES[page], (x, 66), 15, INK if active else MUTED, weight="semibold" if active else None)
        if active:
            draw_line(s, INK, (rect.x - 4, HEADER_H - 2), (rect.right + 4, HEADER_H - 2), 2)
        st.clicks.append((pygame.Rect(rect.x - 14, 58, rect.width + 28, HEADER_H - 58), "page", page))
        x = rect.right + 30
        if page in ("scenarios", "overview"):  # Scenarios | Module 1 pages | Module 2 and 3 pages
            draw_line(s, HAIRLINE, (x - 15, 68), (x - 15, 86))
            x += 4

    if r is None:
        return
    # stats on the right of the tab row
    if st.busy:
        text(s, st.busy + " …", (W - M, 68), 13, ACCENT, anchor="topright", weight="semibold")
    else:
        parts = []
        if r.allocation:
            stats = r.allocation.result.stats
            parts.append(f"CSP {stats.nodes} nodes · {stats.backtracks} backtracks · {stats.seconds * 1000:.0f} ms")
        if r.motion:
            parts.append(f"{r.motion.collisions} collisions")
        parts.append(f"{len(r.accepted)} accepted · {len(r.diagnoses)} rejected")
        cx = W - M
        for part in reversed(parts):
            cx = chip(s, part, (cx, 64), anchor="topright").x - 8

    # plan steps: initial plan, then one per disruption
    x = caps(s, "Plan", (M, 117), 12).right + 12
    n = max(1, len(st.steps))
    room = (W - M - x - 8 * (n - 1)) / n  # width each pill may take
    for i, step in enumerate(st.steps):
        label = step.label
        if pill_width(label, str(i)) > room:
            label = fit(label, 13, max(40, room - pill_width("", str(i))))
        rect = pill(s, x, 111, label, str(i), active=i == st.step)
        st.clicks.append((rect.inflate(4, 8), "step", i))
        x = rect.right + 8


# ---------------------------------------------------------------------------------------------
# footer: play / pause, time of day, speed, reset
# ---------------------------------------------------------------------------------------------
def draw_footer(st: ViewState, s):
    r = current(st)
    draw_rect(s, SURFACE, (0, FOOTER_TOP, W, H - FOOTER_TOP))
    hline(s, 0, W, FOOTER_TOP, HAIRLINE)
    cy = FOOTER_TOP + 33

    # play / pause
    disc(s, INK, (M + 22, cy), 22)
    if st.playing:
        draw_rect(s, SURFACE, (M + 15, cy - 7, 5, 14), border_radius=1)
        draw_rect(s, SURFACE, (M + 24, cy - 7, 5, 14), border_radius=1)
    else:
        pygame.draw.polygon(s, SURFACE, [pt((M + 17, cy - 8)), pt((M + 17, cy + 8)), pt((M + 30, cy))])
    st.clicks.append((pygame.Rect(M, cy - 22, 44, 44), "play", None))

    # right-hand controls, laid out right to left
    note = text(s, st.message or "H  keys", (W - M, cy), 12, MUTED, anchor="midright")
    reset = button(st, s, (note.x - 24 - 104, cy - 18, 104, 36), "Reset day", "reset")
    labels = [f"{v}×" for v in SPEEDS]
    widths = [text_width(lb, 12, mono=True, weight="medium") + 22 for lb in labels]
    seg = pygame.Rect(0, cy - 19, round(sum(widths) + 4 * (len(widths) - 1) + 6), 38)
    seg.right = reset.x - 16
    draw_rect(s, PAPER, seg, border_radius=10)
    sx = seg.x + 3
    for v, lb, w in zip(SPEEDS, labels, widths):
        on = st.speed == v
        b = pygame.Rect(round(sx), seg.y + 3, round(w), 32)
        if on:
            draw_rect(s, SURFACE, b, border_radius=8)
        text(s, lb, b.center, 12, INK if on else MUTED, anchor="center", mono=True, weight="medium")
        st.clicks.append((b, "speed", v))
        sx += w + 4

    # time of day
    x0, x1 = M + 66, seg.x - 32
    if r is None:
        return
    span = max(60.0, end_minute(st))
    st.t_span = span
    track = pygame.Rect(x0, FOOTER_TOP + 24, x1 - x0, 4)
    st.scrub = track.inflate(0, 22)
    draw_rect(s, DIVIDER, track, border_radius=2)
    done = track.width * min(1.0, st.minute / span)
    draw_rect(s, INK, (track.x, track.y, done, track.height), border_radius=2)
    disc(s, INK, (track.x + done, track.centery), 8)
    disc(s, SURFACE, (track.x + done, track.centery), 3)
    for m in range(0, int(span) + 1, 60):
        mx = track.x + track.width * m / span
        text(s, clock(r.scenario, m), (mx, track.bottom + 7), 11, MUTED, anchor="midtop", mono=True)


# ---------------------------------------------------------------------------------------------
# tooltips
# ---------------------------------------------------------------------------------------------
# A tooltip is a list of lines:
#   ("title", text)  ("sub", text)  ("text", text[, colour])  ("kv", key, value[, colour])
#   ("bar", fraction, colour)  ("rule",)  ("head", text)
# The same lists fill the pinned Details card on the kitchen page.
KEY_W = 96  # width of the key column of "kv" lines


def layout_lines(lines, inner):
    """Wrap a line list to `inner` width: [(kind, payload, height)]."""
    rendered = []
    for ln in lines:
        kind = ln[0]
        if kind == "title":
            rendered.append((kind, ln, 24))
        elif kind in ("sub", "text"):
            for w_ in wrap(ln[1], 13, inner):
                rendered.append((kind, (kind, w_) + tuple(ln[2:]), 19))
        elif kind == "kv":
            for i, w_ in enumerate(wrap(ln[2], 13, inner - KEY_W)):
                rendered.append(("kv", ("kv", ln[1] if i == 0 else "", w_) + tuple(ln[3:]), 19))
        elif kind == "bar":
            rendered.append((kind, ln, 14))
        elif kind == "rule":
            rendered.append((kind, ln, 13))
        elif kind == "head":
            rendered.append((kind, ln, 24))
    return rendered


def render_lines(s, rendered, x, y, inner, bottom=None):
    """Draw wrapped lines from (x, y); stops before `bottom` if given. Returns the y after the last line."""
    for kind, ln, h in rendered:
        if bottom is not None and y + h > bottom:
            text(s, "…", (x, y), 13, MUTED)
            break
        if kind == "title":
            text(s, ln[1], (x, y), 16, INK, True)
        elif kind == "sub":
            text(s, ln[1], (x, y), 13, MUTED)
        elif kind == "text":
            text(s, ln[1], (x, y), 13, ln[2] if len(ln) > 2 else INK)
        elif kind == "head":
            text(s, ln[1], (x, y + 6), 13, INK, True)
        elif kind == "kv":
            text(s, ln[1], (x, y), 13, MUTED)
            text(s, ln[2], (x + KEY_W, y), 13, ln[3] if len(ln) > 3 else INK)
        elif kind == "bar":
            bar = pygame.Rect(x, y + 4, inner, 6)
            draw_rect(s, HIGHLIGHT, bar, border_radius=3)
            draw_rect(s, ln[2], (bar.x, bar.y, bar.width * max(0.0, min(1.0, ln[1])), 6), border_radius=3)
        elif kind == "rule":
            hline(s, x, x + inner, y + 6)
        y += h
    return y


def draw_tooltip(s, lines, mouse, width=380):
    pad, inner = 14, width - 28
    rendered = layout_lines(lines, inner)
    height = sum(h for *_, h in rendered) + 2 * pad - 4
    box = pygame.Rect(mouse[0] + 18, mouse[1] + 14, width, height)
    if box.right > W - 8:
        box.right = mouse[0] - 14
    if box.bottom > H - 8:
        box.bottom = H - 8
    shadow(s, (box.x - 2, box.y + 2, box.width + 8, box.height + 8))
    draw_rect(s, SURFACE, box, border_radius=6)
    draw_rect(s, HAIRLINE, box, 1, border_radius=6)
    render_lines(s, rendered, box.x + pad, box.y + pad, inner)


def card_height(lines, width: int, note: str = "") -> int:
    """Height a Details card needs to show every line."""
    return sum(h for *_, h in layout_lines(lines, width - 32)) + 32 + (22 if note else 0)


def draw_detail_card(s, lines, rect: pygame.Rect, note: str = ""):
    """A fixed panel showing a line list (the pinned item), with an optional note at its foot."""
    pad = 16
    inner = rect.width - 2 * pad
    draw_rect(s, SURFACE, rect, border_radius=6)
    draw_rect(s, HAIRLINE, rect, 1, border_radius=6)
    bottom = rect.bottom - pad - (22 if note else 0)
    render_lines(s, layout_lines(lines, inner), rect.x + pad, rect.y + pad, inner, bottom)
    if note:
        text(s, note, (rect.x + pad, rect.bottom - pad - 16), 12, MUTED)


def tabs(st: ViewState, s, x, y, items, active, action) -> int:
    """Underline tabs: items are (value, label). Registers clicks; returns the x after the last tab."""
    for value, label in items:
        on = value == active
        r = text(s, label, (x, y), 14, INK if on else MUTED, on)
        if on:
            draw_line(s, ACCENT, (r.x, r.bottom + 4), (r.right, r.bottom + 4), 2)
        st.clicks.append((r.inflate(16, 14), action, value))
        x = r.right + 26
    return x


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
    keys = [("Space", "play / pause"), ("← →", "10 minutes back / on"), ("↑ ↓", "speed"),
            ("Home", "start of the day"), ("C", "scenarios"), ("K V O", "kitchen, delivery, overview"), ("L U", "planning, uncertainty"),
            ("Tab  P", "next / previous plan step"), ("1–9", "load a scenario"), ("R", "close a road (live)"),
            ("F", "fail a stove (live)"), ("D", "next order"), ("Click", "pin a kitchen item"),
            ("S", "screenshot"), ("F11", "fullscreen"), ("H", "close"), ("Q  Esc", "quit")]
    rows = (len(keys) + 1) // 2
    box = pygame.Rect(0, 0, 640, 52 + rows * 30 + PAD)
    box.center = (W // 2, H // 2)
    y0 = panel(s, box, "Keys")
    for i, (k, what) in enumerate(keys):
        cx = box.x + PAD + (i // rows) * 310
        cy = y0 + (i % rows) * 30
        text(s, k, (cx, cy), 13, INK, mono=True, weight="semibold")
        text(s, what, (cx + 84, cy), 13, SUBTLE)


def busy_note(st: ViewState, s):
    if st.busy and current(st) is None:
        text(s, st.busy + " …", (W // 2, H // 2), 15, MUTED, anchor="center")

