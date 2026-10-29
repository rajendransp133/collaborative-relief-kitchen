"""Scenarios page: one row per scenario file; click a row to load it."""

from __future__ import annotations

import pygame

from .state import ViewState
from .theme import ACCENT, DIVIDER, INK, MUTED, OK, PAPER, SUBTLE, card, disc, draw_line, draw_rect, fit, text
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, M, PAD, W


def draw_scenarios_page(st: ViewState, s, r):
    box = pygame.Rect(M, CONTENT_TOP, W - 2 * M, CONTENT_BOTTOM - CONTENT_TOP)
    card(s, box)
    row_h = (box.height - 16) / max(1, len(st.catalog))
    for i, sc in enumerate(st.catalog):
        row = pygame.Rect(box.x + 1, round(box.y + 8 + i * row_h), box.width - 2, round(row_h))
        draw_row(st, s, sc, row, first=i == 0)


def draw_row(st: ViewState, s, sc, row, first):
    loaded = sc.path == st.path
    x, right = row.x + PAD + 8, row.right - PAD - 8
    if loaded or (row.collidepoint(st.mouse) and not st.busy):
        draw_rect(s, PAPER, row)
    if loaded:
        draw_rect(s, INK, (row.x, row.y + 10, 3, row.height - 20), border_radius=2)
    elif not st.busy:
        st.clicks.append((row, "load", sc.path))
    if not first:
        draw_line(s, DIVIDER, (x, row.y), (right, row.y))

    facts = text(s, f"{len(sc.orders)} orders · {sum(o.meals for o in sc.orders)} meals",
                 (right - 120, row.centery), 14, SUBTLE, anchor="midright")
    if loaded:
        t = text(s, "Solving" if st.busy else "Loaded", (right, row.centery), 14, INK, anchor="midright",
                 weight="semibold")
        disc(s, ACCENT if st.busy else OK, (t.x - 12, t.centery), 4)

    text(s, sc.name, (x, row.centery - 2), 20, INK, anchor="bottomleft", weight="semibold")
    events = " · ".join(ev.label or ev.kind for ev in sc.events)
    text(s, fit(events, 14, facts.x - x - 40) if events else "No disruptions", (x, row.centery + 4), 14,
         SUBTLE if events else MUTED)
