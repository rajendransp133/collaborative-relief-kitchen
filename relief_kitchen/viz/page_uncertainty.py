"""Uncertainty page (Module 3): Bayesian belief that stoves, roads and supplies are disrupted, how
each disruption updates it, the plan's risk and the contingencies it triggers.

Step i of the PLAN bar is the belief after the first i disruptions (live ones included)."""

from __future__ import annotations

import pygame

from ..uncertainty.belief import P_OBS_GIVEN_FAIL, P_OBS_GIVEN_OK
from ..uncertainty.contingency import THRESHOLD
from ..uncertainty.risk import STEP_RISK
from ..uncertainty.timeline import STAGE_NAMES, belief_timeline
from .state import ViewState
from .theme import (ACCENT, BAND, DIVIDER, ERROR, FAINT, GRID, HAIRLINE, INK, MUTED, OK, STATION_STYLE, SUBTLE,
                    SURFACE, caps, dashed, disc, draw_line, draw_rect, fit, hex_rgb, ring, text, wrap)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, GAP, LEFT_W, M, PAD, RIGHT_W, RIGHT_X, meter, panel

LEFT = pygame.Rect(M, CONTENT_TOP, LEFT_W, CONTENT_BOTTOM - CONTENT_TOP)
RIGHT = pygame.Rect(RIGHT_X, CONTENT_TOP, RIGHT_W, CONTENT_BOTTOM - CONTENT_TOP)
BELIEF_ROW = 44
PRIOR = 0.05

VARS = {  # belief variable -> (name, what it means, colour)
    "stove_ok": ("Stove", "a cooking station is disrupted", STATION_STYLE["stove"][1]),
    "road_ok": ("Road", "a delivery road is disrupted", hex_rgb("#4A6FA5")),
    "supply_ok": ("Supply", "ingredient stock is short", STATION_STYLE["storage"][1]),
}

_CACHE: dict = {}


def timeline(st: ViewState):
    """BeliefStep per PLAN step, computed once per set of steps."""
    key = tuple(id(x.scenario) for x in st.steps)
    if key not in _CACHE:
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[key] = (belief_timeline([x.scenario for x in st.steps]), list(st.steps))  # keep refs alive
    return _CACHE[key][0]


def var_name(var: str) -> str:
    return VARS.get(var, (var, "", MUTED))[0]


def var_colour(var: str):
    return VARS.get(var, (var, "", MUTED))[2]


# ---------------------------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------------------------
def draw_uncertainty_page(st: ViewState, s, r):
    steps = timeline(st)
    i = min(st.step, len(steps) - 1)
    now, prev = steps[i], steps[i - 1] if i else None
    belief = pygame.Rect(LEFT.x, LEFT.y, LEFT.width, 52 + BELIEF_ROW * len(now.probs) + 10)
    draw_beliefs(st, s, now, belief)
    bayes_h = 52 + 40 * max(1, len(now.updates)) + 10
    chart = pygame.Rect(LEFT.x, belief.bottom + GAP, LEFT.width, LEFT.bottom - belief.bottom - 2 * GAP - bayes_h)
    draw_chart(st, s, steps, i, chart)
    draw_bayes(st, s, now, i, pygame.Rect(LEFT.x, chart.bottom + GAP, LEFT.width, bayes_h))
    y = draw_risk(st, s, now, prev, RIGHT)
    draw_contingencies(s, now, pygame.Rect(RIGHT.x, y + GAP, RIGHT.width, RIGHT.bottom - y - GAP))


def draw_beliefs(st: ViewState, s, now, box):
    y = panel(s, box, "Belief", f"P(disrupted) · threshold {THRESHOLD:.2f}")
    x, right = box.x + PAD, box.right - PAD
    bar_x, bar_w = x + 110, right - x - 110 - 210
    for var, p in now.probs.items():
        name = var_name(var)
        row = pygame.Rect(x, y, right - x, BELIEF_ROW)
        st.hover.append((row, "belief", var))
        draw_line(s, DIVIDER, (x, y), (right, y))
        alarm = p >= THRESHOLD
        text(s, name, (x, row.centery), 15, INK, anchor="midleft", weight="semibold")
        bar = pygame.Rect(bar_x, row.centery - 4, bar_w, 8)
        meter(s, bar, p, ERROR if alarm else ACCENT)
        tx = bar.x + bar.width * THRESHOLD
        draw_line(s, ERROR, (tx, bar.y - 5), (tx, bar.bottom + 5), 1)
        v = text(s, f"{p:.3f}", (bar.right + 20, row.centery), 16, ERROR if alarm else INK, anchor="midleft",
                 mono=True, weight="semibold")
        if alarm:
            text(s, "above threshold", (right, row.centery), 13, ERROR, anchor="midright")
        y += BELIEF_ROW


def draw_chart(st: ViewState, s, steps, cur, box):
    y0 = panel(s, box, "Belief over the plan steps")
    rect = pygame.Rect(box.x + PAD, y0, box.width - 2 * PAD, box.bottom - y0 - PAD)
    left, right = rect.x + 36, rect.right - 12
    top, bottom = rect.y + 6, rect.bottom - 34
    n = len(steps)
    tx = lambda k: left + (right - left) * (k / max(1, n - 1) if n > 1 else 0.5)  # noqa: E731
    ty = lambda p: bottom - (bottom - top) * p  # noqa: E731
    draw_rect(s, SURFACE, (left, top, right - left, bottom - top))
    x = tx(cur)
    draw_rect(s, BAND, (x - 18, top, 36, bottom - top))
    draw_line(s, ACCENT, (x, top), (x, bottom), 1)
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        draw_line(s, HAIRLINE if v in (0.0, 1.0) else GRID, (left, ty(v)), (right, ty(v)))
        text(s, f"{v:.2f}".rstrip("0").rstrip(".") if v not in (0.0, 1.0) else f"{v:.0f}", (left - 8, ty(v)), 11,
             MUTED, anchor="midright", mono=True)
    dashed(s, ERROR, (left, ty(THRESHOLD)), (right, ty(THRESHOLD)), 1)
    text(s, f"{THRESHOLD:.2f}", (left + 6, ty(THRESHOLD) - 3), 11, ERROR, anchor="bottomleft", mono=True)
    names = list(steps[0].probs)
    for k in range(n - 1):
        # segments shared by several lines (e.g. two resources still at the prior) alternate their colours
        groups: dict[tuple, list[str]] = {}
        for var in names:
            groups.setdefault((round(steps[k].probs[var], 4), round(steps[k + 1].probs[var], 4)), []).append(var)
        for (p0, p1), vs in groups.items():
            a, b = (tx(k), ty(p0)), (tx(k + 1), ty(p1))
            if len(vs) == 1:
                draw_line(s, var_colour(vs[0]), a, b, 2)
                continue
            length = max(1e-9, ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)
            d, j = 0.0, 0
            while d < length:
                e = min(d + 10, length)
                draw_line(s, var_colour(vs[j % len(vs)]), (a[0] + (b[0] - a[0]) * d / length, a[1] + (b[1] - a[1]) * d / length),
                          (a[0] + (b[0] - a[0]) * e / length, a[1] + (b[1] - a[1]) * e / length), 2)
                d, j = e, j + 1
    for var in names:
        for k, step in enumerate(steps):
            (disc if k == cur else ring)(s, var_colour(var), (tx(k), ty(step.probs[var])), 5 if k == cur else 4)
    for k in range(n):
        label = "prior" if k == 0 else (st.steps[k].label if k < len(st.steps) else str(k))
        width = (right - left) / max(1, n - 1) - 8 if n > 1 else 200
        anchor = "topleft" if k == 0 and n > 1 else ("topright" if k == n - 1 and n > 1 else "midtop")
        dx = -6 if anchor == "topleft" else (6 if anchor == "topright" else 0)
        text(s, f"{k}", (tx(k), bottom + 6), 11, INK if k == cur else MUTED, anchor="midtop", mono=True,
             weight="semibold" if k == cur else None)
        text(s, fit(label, 12, max(40, width)), (tx(k) + dx, bottom + 20), 12, INK if k == cur else MUTED,
             anchor=anchor)
    # legend, in the card's title row
    lx = box.right - PAD
    for var in reversed(list(steps[0].probs)):
        r = text(s, var_name(var), (lx, box.y + 19), 13, SUBTLE, anchor="topright")
        draw_line(s, var_colour(var), (r.x - 22, r.centery), (r.x - 6, r.centery), 2)
        lx = r.x - 34


def draw_bayes(st: ViewState, s, now, i, box):
    label = st.steps[i].label if 0 < i < len(st.steps) else ""
    y = panel(s, box, "Bayes update", f"step {i} · {label}" if label else "prior")
    x = box.x + PAD
    if i == 0:
        text(s, f"Every resource starts at P = {PRIOR:.2f}.", (x, y + 4), 14, SUBTLE)
        return
    if not now.updates:
        text(s, "No disruption observed at this step; the belief is unchanged.", (x, y + 4), 14, SUBTLE)
        return
    f, o = P_OBS_GIVEN_FAIL, P_OBS_GIVEN_OK
    for var, prior, post in now.updates:
        if y + 40 > box.bottom:
            break
        draw_line(s, DIVIDER, (x, y), (box.right - PAD, y))
        draw_rect(s, var_colour(var), (x, y + 15, 8, 8), border_radius=2)
        text(s, var_name(var), (x + 16, y + 10), 15, INK, weight="semibold")
        eq = text(s, f"{f:.2f} × {prior:.3f} / ({f:.2f} × {prior:.3f} + {o:.2f} × {1 - prior:.3f}) = ",
                  (x + 110, y + 11), 14, SUBTLE, mono=True)
        rr = text(s, f"{post:.3f}", (eq.right, y + 10), 15, ERROR if post >= THRESHOLD else ACCENT, mono=True,
                  weight="semibold")
        text(s, f"was {prior:.3f}", (box.right - PAD, y + 12), 13, MUTED, anchor="topright")
        y += 40


def draw_risk(st: ViewState, s, now, prev, rect) -> int:
    box = pygame.Rect(rect.x, rect.y, rect.width, 52 + 2 * 40 + 14 + 20 + 28 * len(STAGE_NAMES) + 6)
    y = panel(s, box, "Plan risk", "P(some stage fails)")
    x, right = box.x + PAD, box.right - PAD
    for name, v, was in (("Monte Carlo", now.mc, prev.mc if prev else None),
                         ("Analytical", now.analytical, prev.analytical if prev else None)):
        text(s, name, (x, y + 10), 14, INK, weight="semibold")
        meter(s, pygame.Rect(x + 110, y + 15, 124, 8), v, ERROR if v >= THRESHOLD else ACCENT)
        text(s, f"{v:.3f}", (x + 248, y + 9), 15, INK, mono=True, weight="semibold")
        if was is not None and abs(was - v) > 1e-9:
            text(s, f"was {was:.3f}", (right, y + 11), 12, MUTED, anchor="topright", mono=True)
        y += 40
    y += 14
    cols = (x, x + 80, x + 200, right)
    for c, head, anchor in zip(cols, ("Stage", "Depends on", "Weight", "Weight × P"),
                               ("topleft", "topleft", "topleft", "topright")):
        caps(s, head, (c, y), 11, anchor=anchor)
    y += 20
    for stage in STAGE_NAMES:
        draw_line(s, DIVIDER, (x, y), (right, y))
        var, weight = STEP_RISK.get(stage, (None, 0.0))
        text(s, stage, (cols[0], y + 6), 13, INK)
        if var:
            text(s, var_name(var), (cols[1], y + 6), 13, var_colour(var), weight="semibold")
            text(s, f"{weight:.1f}", (cols[2], y + 6), 13, SUBTLE, mono=True)
            text(s, f"{weight * now.probs.get(var, 0.0):.3f}", (cols[3], y + 6), 13, INK, anchor="topright", mono=True)
        else:
            text(s, "–", (cols[1], y + 6), 13, FAINT)
        y += 28
    return box.bottom


def draw_contingencies(s, now, box):
    y = panel(s, box, "Contingencies", f"once P ≥ {THRESHOLD:.2f}")
    x, right = box.x + PAD, box.right - PAD
    if not now.contingencies:
        disc(s, OK, (x + 4, y + 13), 4)
        text(s, "None needed.", (x + 16, y + 4), 14, SUBTLE)
        return
    for line in now.contingencies:
        if y > box.bottom - PAD - 18:
            break
        if line.startswith("["):  # "[stove_ok  risk=0.49]"
            var = line[1:].split()[0]
            draw_rect(s, var_colour(var), (x, y + 6, 8, 8), border_radius=2)
            text(s, f"{var_name(var)} at risk · {line.split('risk=')[-1].rstrip(']')}", (x + 16, y), 14, ERROR,
                 weight="semibold")
            y += 28
        else:
            for k, ln in enumerate(wrap(line.strip().lstrip("->").strip(), 13, right - x - 20)):
                text(s, ("→ " if k == 0 else "   ") + ln, (x + 4, y), 13, INK)
                y += 20
            y += 6


def belief_tooltip(st, r, var):
    steps = timeline(st)
    i = min(st.step, len(steps) - 1)
    name, meaning, _c = VARS.get(var, (var, "", MUTED))
    lines = [("title", f"{name}  ·  P = {steps[i].probs[var]:.3f}"), ("sub", f"{var}: probability that {meaning}"),
             ("kv", "Prior", f"{PRIOR:.2f}"),
             ("kv", "Likelihood", f"P(signal | disrupted) = {P_OBS_GIVEN_FAIL:.2f}, P(signal | ok) = {P_OBS_GIVEN_OK:.2f}"),
             ("kv", "Threshold", f"{THRESHOLD:.2f} (contingencies)"), ("rule",), ("head", "Over the timeline")]
    for k, step in enumerate(steps):
        label = "prior" if k == 0 else st.steps[k].label
        p = step.probs[var]
        lines.append(("kv", f"{k}", f"{p:.3f}   {label}", ERROR if p >= THRESHOLD else (INK if k == i else MUTED)))
    return lines
