"""Overview page: small kitchen and network maps, the CSP schedule (Gantt) and the orders panel."""

from __future__ import annotations

import math

import pygame

from ..env.scenario import clock
from .page_delivery import draw_network_map
from .page_kitchen import draw_kitchen_map
from .state import ViewState, end_minute, sorted_orders
from .theme import (ACCENT, BAND, ERROR, FAINT, GRID, HAIRLINE, HIGHLIGHT, INK, MUTED, SURFACE, disc, fit, hline,
                    mix, section, text, text_width, wrap)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, M, W

KITCHEN = pygame.Rect(M, CONTENT_TOP, 640, 330)
NETWORK = pygame.Rect(696, CONTENT_TOP, W - M - 696, 330)
SCHEDULE = pygame.Rect(M, CONTENT_TOP + 350, 904, CONTENT_BOTTOM - CONTENT_TOP - 350)
ORDERS = pygame.Rect(960, CONTENT_TOP + 350, W - M - 960, CONTENT_BOTTOM - CONTENT_TOP - 350)


def draw_overview_page(st: ViewState, s, r):
    section(s, KITCHEN.x, KITCHEN.y, "Kitchen", "see the Kitchen page for details")
    draw_kitchen_map(st, s, r, pygame.Rect(KITCHEN.x, KITCHEN.y + 24, KITCHEN.width, KITCHEN.height - 30),
                     detailed=False)
    section(s, NETWORK.x, NETWORK.y, "Delivery network", "see the Delivery page for details")
    draw_network_map(st, s, r, pygame.Rect(NETWORK.x + 20, NETWORK.y + 40, NETWORK.width - 170, NETWORK.height - 70),
                     detailed=False)
    pygame.draw.line(s, HAIRLINE, (672, KITCHEN.y), (672, KITCHEN.bottom))
    hline(s, M, W - M, KITCHEN.bottom + 8)
    pygame.draw.line(s, HAIRLINE, (936, SCHEDULE.y), (936, SCHEDULE.bottom))
    draw_schedule(st, s, r, SCHEDULE)
    draw_orders(st, s, r, ORDERS)


def task_tooltip(st, r, task_id):
    sc = r.scenario
    t = next(t for t in r.allocation.tasks if t.id == task_id)
    return [("title", t.id), ("sub", f"{sc.recipes[t.recipe].name} · {t.meals} meals"),
            ("kv", "Agent", t.agent), ("kv", "Station", t.station),
            ("kv", "Time", f"{clock(sc, t.start)} – {clock(sc, t.end)}"),
            ("kv", "Steps", f"carry-in {t.carry_in} min, {t.stage} {t.work} min"
                            + (f", to door {t.carry_out} min" if t.carry_out else ""))]


def draw_schedule(st: ViewState, s, r, rect):
    section(s, rect.x, rect.y, "Schedule", "CSP solution  ·  light ends = carrying the batch in / to the door")
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
    rh = (bottom - top) / len(rows)
    tx = lambda m: left + (right - left) * m / span  # noqa: E731

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
        # lighter lead-in / tail: carrying the batch in from the previous station, out to the door
        lead = pygame.Rect(bar.x, bar.y, max(0, tx(t.start + t.carry_in) - tx(t.start)), bar.height)
        pygame.draw.rect(s, mix(col, SURFACE, 0.55), lead, border_top_left_radius=3, border_bottom_left_radius=3)
        if t.carry_out:
            tail = pygame.Rect(tx(t.end - t.carry_out), bar.y, tx(t.end) - tx(t.end - t.carry_out) - 1, bar.height)
            pygame.draw.rect(s, mix(col, SURFACE, 0.55), tail, border_top_right_radius=3, border_bottom_right_radius=3)
        st.hover.append((bar, "task", t.id))
        if st.selected == t.order:
            pygame.draw.rect(s, INK, bar.inflate(2, 2), 1, border_radius=4)
        solid = pygame.Rect(lead.right, bar.y, bar.right - lead.right, bar.height)
        for label in (f"{t.order} {t.stage}", t.stage[0].upper()):
            if text_width(label, 10) < solid.width - 6:
                text(s, label, (solid.x + 3, bar.centery), 10, SURFACE, anchor="midleft")
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
        st.clicks.append((row, "order", o.id))
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
