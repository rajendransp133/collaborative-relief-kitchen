"""Planning page (Module 2): the partial-order plan POP builds from the kitchen stages, its schedule,
and a step-by-step trace of how the planner got there."""

from __future__ import annotations

import pygame

from ..planning.kitchen_plan import plan_for, problem
from ..planning.scheduler import STEP_DURATION
from .state import ViewState
from .theme import (ACCENT, BAND, DIVIDER, ERROR, FAINT, GRID, HAIRLINE, INK, MUTED, STATION_STYLE, SUBTLE, SURFACE,
                    caps, dashed, draw_line, draw_rect, fit, hline, mix, pt, text, text_width)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, GAP, LEFT_W, M, PAD, RIGHT_W, RIGHT_X, panel

GRAPH = pygame.Rect(M, CONTENT_TOP, LEFT_W, 250)
SCHEDULE = pygame.Rect(M, GRAPH.bottom + GAP, LEFT_W, CONTENT_BOTTOM - GRAPH.bottom - GAP)
RIGHT = pygame.Rect(RIGHT_X, CONTENT_TOP, RIGHT_W, CONTENT_BOTTOM - CONTENT_TOP)
TRACE_ROW = 46
NODE_W, NODE_H = 90, 52
ENDS = ("Start", "Finish")

_CACHE: dict = {}


def plan_data(sc):
    """(plan, start times, trace, operators) for a scenario, computed once."""
    key = id(sc)
    if key not in _CACHE:
        if len(_CACHE) > 32:
            _CACHE.clear()
        trace: list = []
        plan, times = plan_for(sc, trace=trace)
        _CACHE[key] = (plan, times, trace, problem(sc)[2], sc)  # keep sc so its id isn't reused
    return _CACHE[key][:4]


def op_of(step_id: str) -> str:
    return step_id.split("_")[0]


def duration(step_id: str) -> int:
    return STEP_DURATION.get(op_of(step_id), 10)


def step_colors(sc, step_id: str):
    """(fill, strong) colour of a step, from its stage's station type."""
    if step_id in ENDS:
        return SURFACE, INK
    stype = next((s.station_type for s in sc.stages if s.name == op_of(step_id)), "")
    return STATION_STYLE.get(stype, (SURFACE, MUTED))


# ---------------------------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------------------------
def draw_planning_page(st: ViewState, s, r):
    sc = r.scenario
    plan, times, trace, ops = plan_data(sc)
    focus = draw_trace(st, s, sc, plan, trace, ops, RIGHT)  # first, so the graph can highlight the hovered row
    draw_graph(st, s, sc, plan, times, GRAPH, focus)
    draw_schedule(st, s, sc, plan, times, SCHEDULE)


def depths(plan) -> dict[str, int]:
    """Column of each step: longest ordering chain from Start."""
    d = {sid: 0 for sid in plan.steps}
    for step in plan.sorted_steps():
        for a, b in plan.orderings:
            if a == step.id:
                d[b] = max(d[b], d[a] + 1)
    return d


def arrow(s, color, a, b, width=2):
    """Line from a to b with a filled head at b (logical coordinates)."""
    draw_line(s, color, a, b, width)
    (ax, ay), (bx, by) = a, b
    n = max(1e-9, ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
    ux, uy = (bx - ax) / n, (by - ay) / n
    head = [(bx, by), (bx - 9 * ux - 5 * uy, by - 9 * uy + 5 * ux), (bx - 9 * ux + 5 * uy, by - 9 * uy - 5 * ux)]
    phys = [pt(p) for p in head]
    pygame.draw.polygon(s, color, phys)
    pygame.draw.aalines(s, color, True, phys)


def draw_graph(st: ViewState, s, sc, plan, times, box, focus):
    note = f"{len(plan.steps)} steps · {len(plan.links)} causal links · {len(plan.orderings)} orderings"
    y0 = panel(s, box, "Partial-order plan", note)
    rect = pygame.Rect(box.x + PAD, y0, box.width - 2 * PAD, box.bottom - y0 - PAD)
    col = depths(plan)
    ncols = max(col.values()) + 1
    columns: dict[int, list[str]] = {}
    for step in plan.sorted_steps():
        columns.setdefault(col[step.id], []).append(step.id)
    area = pygame.Rect(rect.x, rect.y + 16, rect.width, rect.height - 16)
    gap_x = (area.width - NODE_W) / max(1, ncols - 1)
    box: dict[str, pygame.Rect] = {}
    for c, ids in columns.items():
        for i, sid in enumerate(ids):
            cy = area.centery + (i - (len(ids) - 1) / 2) * (NODE_H + 30)
            box[sid] = pygame.Rect(round(area.x + c * gap_x), round(cy - NODE_H / 2), NODE_W, NODE_H)

    # extra orderings (not causal links, not the trivial Start / Finish bounds)
    linked = {(lk.producer, lk.consumer) for lk in plan.links}
    for a, b in sorted(plan.orderings):
        if (a, b) not in linked and a != "Start" and b != "Finish":
            dashed(s, FAINT, box[a].midbottom, box[b].midbottom, 1)
    # causal links, labelled with the condition they carry
    for lk in plan.links:
        a, b = box[lk.producer], box[lk.consumer]
        hot = focus == (lk.producer, lk.consumer)
        colour = ACCENT if hot else MUTED
        arrow(s, colour, (a.right + 2, a.centery), (b.left - 3, b.centery), 3 if hot else 2)
        mid = ((a.right + b.left) / 2, (a.centery + b.centery) / 2 - 6)
        room = max(30, b.left - a.right - 6)
        lines = [lk.condition]
        if text_width(lk.condition, 10, hot) > room and "_" in lk.condition:  # ingredients_available: two lines
            head, tail = lk.condition.split("_", 1)
            lines = [head + "_", tail]
        for k, ln in enumerate(reversed(lines)):
            text(s, fit(ln, 10, room, hot), (mid[0], mid[1] - 13 * k), 10, ACCENT if hot else MUTED, hot,
                 anchor="midbottom")

    for sid, b in box.items():
        fill, strong = step_colors(sc, sid)
        hot = focus is not None and sid in focus
        draw_rect(s, fill, b, border_radius=8 if sid not in ENDS else 26)
        draw_rect(s, ACCENT if hot else strong, b, 3 if hot else 2, border_radius=8 if sid not in ENDS else 26)
        if sid in ENDS:
            text(s, sid, b.center, 13, INK, True, anchor="center")
        else:
            text(s, sid, (b.centerx, b.y + 9), 13, INK, True, anchor="midtop")
            t = times.get(sid, 0)
            text(s, f"{t}–{t + duration(sid)}", (b.centerx, b.bottom - 9), 11, SUBTLE, anchor="midbottom", mono=True)
        st.hover.append((b, "pstep", sid))


def draw_schedule(st: ViewState, s, sc, plan, times, box):
    steps = [sid for sid in (x.id for x in plan.sorted_steps()) if sid not in ENDS]
    span = max([times[x] + duration(x) for x in steps] or [10])
    y0 = panel(s, box, "Schedule", f"makespan {span} min")
    rect = pygame.Rect(box.x + PAD, y0, box.width - 2 * PAD, box.bottom - y0 - PAD)
    if not steps:
        return
    rows = []  # resources in stage order
    for stage in sc.stages:
        if any(op_of(x) == stage.name for x in steps):
            rows.append(stage.name)
    rows += sorted({op_of(x) for x in steps} - set(rows))
    left, right = rect.x + 60, rect.right
    top, bottom = rect.y + 20, min(rect.bottom - 8, rect.y + 20 + 66 * len(rows))
    rh = (bottom - top) / len(rows)
    axis = max(10, -(-span // 10) * 10)
    tx = lambda m: left + (right - left) * m / axis  # noqa: E731

    draw_rect(s, SURFACE, (left, top, right - left, bottom - top))
    for i, name in enumerate(rows):
        y = top + i * rh
        if i % 2:
            draw_rect(s, BAND, (left, y, right - left, rh))
        text(s, name, (rect.x, y + rh / 2), 13, INK, anchor="midleft")
    step_m = 5 if axis <= 60 else 10
    for m in range(0, axis + 1, step_m):
        x = tx(m)
        draw_line(s, HAIRLINE if m % 10 == 0 else GRID, (x, top), (x, bottom))
        if m % 10 == 0:
            text(s, f"{m}", (x, top - 16), 11, MUTED, anchor="midtop", mono=True)
    text(s, "min", (left - 10, top - 16), 11, MUTED, anchor="topright")
    hline(s, left, right, top)
    hline(s, left, right, bottom)
    for sid in steps:
        y = top + rows.index(op_of(sid)) * rh
        bar = pygame.Rect(tx(times[sid]) + 1, y + 6, max(2, tx(times[sid] + duration(sid)) - tx(times[sid]) - 2), rh - 12)
        _fill, strong = step_colors(sc, sid)
        draw_rect(s, strong, bar, border_radius=3)
        if text_width(sid, 11) < bar.width - 8:
            text(s, sid, (bar.x + 6, bar.centery), 11, SURFACE, True, anchor="midleft")
        st.hover.append((bar, "pstep", sid))
    x = tx(span)
    draw_line(s, ERROR, (x, top - 4), (x, bottom + 4), 2)


def trace_sentence(rec) -> tuple[str, str]:
    consumer, cond, achiever, reused, _resolved = rec
    head = f"{consumer} needs {cond}"
    act = f"reuse {achiever}" if reused else f"add {achiever}"
    return head, f"{act}  ·  link {achiever} → {consumer}"


def draw_trace(st: ViewState, s, sc, plan, trace, ops, rect):
    """POP iterations, then the operators. Returns the hovered link (producer, consumer) or None."""
    heights = [TRACE_ROW + 18 * len(rec[4]) for rec in trace] or [TRACE_ROW]
    box = pygame.Rect(rect.x, rect.y, rect.width, 52 + sum(heights) + 6)
    y = panel(s, box, "How POP built it", f"{len(trace)} steps")
    x, right = box.x + PAD, box.right - PAD
    focus = None
    for i, (rec, h) in enumerate(zip(trace, heights)):
        head, act = trace_sentence(rec)
        row = pygame.Rect(x - 6, y, right - x + 12, h)
        if row.collidepoint(st.mouse):
            focus = (rec[2], rec[0])
            draw_rect(s, mix(ACCENT, SURFACE, 0.9), row, border_radius=4)
        draw_line(s, DIVIDER, (x, y), (right, y))
        text(s, f"{i + 1}", (x, y + 8), 13, MUTED, mono=True)
        text(s, head, (x + 26, y + 7), 13, INK, weight="semibold")
        text(s, act, (x + 26, y + 25), 13, SUBTLE)
        for k, (threat, how) in enumerate(rec[4]):
            text(s, f"threat {threat} → {how}", (x + 26, y + 43 + 18 * k), 12, ERROR)
        y += h
    if not trace:
        text(s, "The goal already holds in the initial state.", (x, y + 12), 13, MUTED)

    ob = pygame.Rect(rect.x, box.bottom + GAP, rect.width, min(rect.bottom - box.bottom - GAP, 52 + 26 + 30 * len(ops) + 6))
    y = panel(s, ob, "Operators")
    cols = (x, x + 84, x + 254)
    for c, head in zip(cols, ("Operator", "Needs", "Adds")):
        caps(s, head, (c, y), 11)
    y += 20
    for op in ops:
        if y + 30 > ob.bottom:
            break
        draw_line(s, DIVIDER, (x, y), (right, y))
        _fill, strong = step_colors(sc, f"{op.name}_0")
        draw_rect(s, strong, (cols[0], y + 11, 8, 8), border_radius=2)
        text(s, op.name, (cols[0] + 14, y + 7), 13, INK, weight="semibold")
        text(s, fit(", ".join(sorted(op.pre)) or "–", 13, cols[2] - cols[1] - 10), (cols[1], y + 7), 13, SUBTLE)
        text(s, fit(", ".join(sorted(op.add)) or "–", 13, right - cols[2]), (cols[2], y + 7), 13, SUBTLE)
        y += 30
    return focus


def step_tooltip(st, r, sid):
    plan, times, _trace, _ops = plan_data(r.scenario)
    step = plan.steps[sid]
    lines = [("title", sid), ("sub", f"operator {step.operator.name}")]
    if sid not in ENDS:
        lines.append(("kv", "Time", f"{times.get(sid, 0)}–{times.get(sid, 0) + duration(sid)} min"))
    lines += [("kv", "Needs", ", ".join(sorted(step.operator.pre)) or "–"),
              ("kv", "Adds", ", ".join(sorted(step.operator.add)) or "–")]
    if step.operator.delete:
        lines.append(("kv", "Deletes", ", ".join(sorted(step.operator.delete)), ERROR))
    ins = [f"{lk.producer} ({lk.condition})" for lk in plan.links if lk.consumer == sid]
    outs = [f"{lk.consumer} ({lk.condition})" for lk in plan.links if lk.producer == sid]
    lines += [("rule",), ("kv", "From", ", ".join(ins) or "–"), ("kv", "To", ", ".join(outs) or "–")]
    return lines
