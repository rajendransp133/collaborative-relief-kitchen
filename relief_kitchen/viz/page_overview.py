"""Overview page: small kitchen and network maps, the CSP schedule (Gantt) and the orders panel."""

from __future__ import annotations

import math

import pygame

from ..support.env.scenario import clock
from .page_delivery import draw_network_map
from .page_kitchen import draw_kitchen_map
from .state import ViewState, end_minute, sorted_orders
from .theme import (ACCENT, BAND, DIVIDER, ERROR, GRID, HAIRLINE, INK, MUTED, PAPER, SUBTLE, SURFACE,
                    caps, disc, draw_line, draw_rect, fit, hline, mix, text, text_width, wrap)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, GAP, LEFT_W, M, PAD, RIGHT_W, RIGHT_X, panel

MAP_H = 300
HALF = (LEFT_W - GAP) // 2
KITCHEN = pygame.Rect(M, CONTENT_TOP, HALF, MAP_H)
NETWORK = pygame.Rect(M + HALF + GAP, CONTENT_TOP, LEFT_W - HALF - GAP, MAP_H)
SCHEDULE = pygame.Rect(M, CONTENT_TOP + MAP_H + GAP, LEFT_W, CONTENT_BOTTOM - CONTENT_TOP - MAP_H - GAP)
ORDERS = pygame.Rect(RIGHT_X, CONTENT_TOP, RIGHT_W, CONTENT_BOTTOM - CONTENT_TOP)
ORDER_ROW = 30


def draw_overview_page(st: ViewState, s, r):
    y = panel(s, KITCHEN, "Kitchen")
    draw_kitchen_map(st, s, r, pygame.Rect(KITCHEN.x + PAD, y, KITCHEN.width - 2 * PAD, KITCHEN.bottom - y - PAD))
    y = panel(s, NETWORK, "Delivery network")
    draw_network_map(st, s, r, pygame.Rect(NETWORK.x + PAD + 20, y + 14, NETWORK.width - 2 * PAD - 150,
                                           NETWORK.bottom - y - PAD - 40), detailed=False)
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


def draw_schedule(st: ViewState, s, r, box):
    sc = r.scenario
    al = r.allocation
    y0 = panel(s, box, "Schedule", f"{len(al.tasks)} tasks · {len(al.deliveries)} trips" if al else "")
    rect = pygame.Rect(box.x + PAD, y0, box.width - 2 * PAD, box.bottom - y0 - PAD)
    if not al:
        text(s, "No order could be scheduled.", (rect.x, rect.y + 10), 14, MUTED)
        return
    agents, vehicles = sorted(sc.agents), sorted(sc.vehicles)
    rows = [("agent", a) for a in agents] + [("vehicle", v) for v in vehicles]
    left, right = rect.x + 76, rect.right
    top, bottom = rect.y + 20, rect.bottom - 22
    span = max(60.0, math.ceil(end_minute(st) / 60) * 60)
    rh = (bottom - top) / len(rows)
    tx = lambda m: left + (right - left) * m / span  # noqa: E731

    draw_rect(s, SURFACE, (left, top, right - left, bottom - top))
    for i, (kind, rid) in enumerate(rows):
        y = top + i * rh
        if i % 2:
            draw_rect(s, BAND, (left, y, right - left, rh))
        text(s, rid, (rect.x, y + rh / 2), 13, INK, anchor="midleft", mono=kind == "vehicle")
    now_x = tx(st.minute)
    for m in range(0, int(span) + 1, 30):
        x = tx(m)
        draw_line(s, HAIRLINE if m % 60 == 0 else GRID, (x, top), (x, bottom))
        if m % 60 == 0 and abs(x - now_x) > 52 and x < right - 20:  # keep clear of the "now" tag
            text(s, clock(sc, m), (x, top - 18), 11, MUTED, anchor="midtop", mono=True)
    hline(s, left, right, top)
    hline(s, left, right, bottom)
    sep = top + len(agents) * rh
    hline(s, rect.x, right, sep)

    for t in al.tasks:
        y = top + agents.index(t.agent) * rh
        bar = pygame.Rect(tx(t.start) + 1, y + 5, max(2, tx(t.end) - tx(t.start) - 2), rh - 10)
        col = st.order_color.get(t.order, ACCENT)
        draw_rect(s, col, bar, border_radius=3)
        # lighter lead-in / tail: carrying the batch in from the previous station, out to the door
        lead = pygame.Rect(bar.x, bar.y, max(0, tx(t.start + t.carry_in) - tx(t.start)), bar.height)
        draw_rect(s, mix(col, SURFACE, 0.55), lead, border_top_left_radius=3, border_bottom_left_radius=3)
        if t.carry_out:
            tail = pygame.Rect(tx(t.end - t.carry_out), bar.y, tx(t.end) - tx(t.end - t.carry_out) - 1, bar.height)
            draw_rect(s, mix(col, SURFACE, 0.55), tail, border_top_right_radius=3, border_bottom_right_radius=3)
        st.hover.append((bar, "task", t.id))
        if st.selected == t.order:
            draw_rect(s, INK, bar.inflate(2, 2), 1, border_radius=4)
        solid = pygame.Rect(lead.right, bar.y, bar.right - lead.right, bar.height)
        for label in (f"{t.order} {t.stage}", t.stage[0].upper()):
            if text_width(label, 10) < solid.width - 6:
                text(s, label, (solid.x + 3, bar.centery), 10, SURFACE, anchor="midleft")
                break

    for d in al.deliveries:
        y = top + (len(agents) + vehicles.index(d.vehicle)) * rh
        col = st.order_color.get(d.order, ACCENT)
        out = pygame.Rect(tx(d.depart), y + 5, max(2, tx(d.arrive) - tx(d.depart)), rh - 10)
        draw_rect(s, col, out, border_radius=3)
        draw_line(s, col, (out.right, y + rh / 2), (tx(d.back), y + rh / 2), 2)
        draw_line(s, col, (tx(d.back), y + rh / 2 - 4), (tx(d.back), y + rh / 2 + 4), 2)
        label = f"{d.order} → {sc.roads.places[d.destination].label}"
        for lab in (label, d.order):
            if text_width(lab, 10) < out.width - 6:
                text(s, lab, (out.x + 4, out.centery), 10, SURFACE, anchor="midleft")
                break

    # deadlines below the axis
    last = -99.0
    for o in sorted(sc.orders, key=lambda o: o.deadline):
        if o.deadline <= span:
            x = tx(o.deadline)
            col = st.order_color.get(o.id, ACCENT)
            draw_line(s, col, (x, bottom + 2), (x, bottom + 8), 2)
            if x - last > 22:  # deadlines a few minutes apart share one label
                text(s, o.id, (x, bottom + 10), 11, MUTED, anchor="midtop")
                last = x
    text(s, "due", (rect.x, bottom + 10), 11, MUTED)

    # now
    x = tx(st.minute)
    draw_line(s, ACCENT, (x, top), (x, bottom), 2)
    tag = text(s, clock(sc, st.minute), (x, top - 4), 11, SURFACE, anchor="midbottom", mono=True)
    draw_rect(s, ACCENT, tag.inflate(8, 2), border_radius=3)
    text(s, clock(sc, st.minute), (x, top - 4), 11, SURFACE, anchor="midbottom", mono=True)



def draw_orders(st: ViewState, s, r, box):
    sc = r.scenario
    deliveries = {d.order: d for d in r.allocation.deliveries} if r.allocation else {}
    y = panel(s, box, "Orders")
    x0, x1 = box.x + PAD, box.right - PAD
    for label, x, anchor in (("Order", x0, "topleft"), ("To", x0 + 64, "topleft"), ("Meals", x0 + 250, "topright"),
                             ("Arrives", x1, "topright")):
        caps(s, label, (x, y), 11, anchor=anchor)
    y += 20
    draw_line(s, DIVIDER, (x0, y), (x1, y))
    for o in sorted_orders(r):
        row = pygame.Rect(x0 - 6, y, x1 - x0 + 12, ORDER_ROW)
        if st.selected == o.id:
            draw_rect(s, PAPER, row, border_radius=4)
        disc(s, st.order_color.get(o.id, ACCENT), (x0 + 4, row.centery), 4)
        text(s, o.id, (x0 + 16, row.centery), 13, INK, anchor="midleft", weight="semibold")
        text(s, fit(sc.roads.places[o.destination].label, 13, 150), (x0 + 64, row.centery), 13, INK, anchor="midleft")
        text(s, str(o.meals), (x0 + 250, row.centery), 13, SUBTLE, anchor="midright", mono=True)
        if o.id in deliveries:
            d = deliveries[o.id]
            text(s, clock(sc, d.arrive), (x1, row.centery), 13, ERROR if d.arrive > o.deadline else INK,
                 anchor="midright", mono=True, weight="semibold")
        else:
            text(s, "rejected", (x1, row.centery), 13, ERROR, anchor="midright", weight="semibold")
        draw_line(s, DIVIDER, (x0, row.bottom), (x1, row.bottom))
        st.clicks.append((row, "order", o.id))
        y = row.bottom

    # details of the selected order (the first one until something is chosen)
    sel = next((o for o in sc.orders if o.id == st.selected), None) or next(iter(sorted_orders(r)), None)
    if sel is None:
        return
    y += 26
    width = x1 - x0
    text(s, f"{sel.id} · {sc.roads.places[sel.destination].label}", (x0, y), 17, INK, weight="semibold")
    y += 28
    diet = ", ".join(sorted(sel.diet)) or "no restriction"
    text(s, fit(f"{sel.meals} meals · {diet} · priority {sel.priority} · due {clock(sc, sel.deadline)}", 13, width),
         (x0, y), 13, MUTED)
    y += 30
    lines: list[tuple[str, str, tuple]] = []  # (label, body, colour)
    if sel.id in r.diagnoses:
        d = r.diagnoses[sel.id]
        head = "Cannot be met on its own." if d.mode == "isolated" else "Does not fit next to more urgent orders."
        text(s, head, (x0, y), 14, ERROR, weight="semibold")
        y += 28
        lines = [(c.category, c.detail, INK) for c in d.causes]
    elif sel.id in deliveries:
        dl = deliveries[sel.id]
        rec = sc.recipes[dl.recipe]
        lines.append(("Menu", f"{rec.name} (allergens: {', '.join(sorted(rec.allergens)) or 'none'})", INK))
        lines.append(("Vehicle", f"{dl.vehicle}: leaves {clock(sc, dl.depart)}, arrives {clock(sc, dl.arrive)}, "
                                 f"back {clock(sc, dl.back)}", INK))
        if dl.route:
            lines.append(("Route", f"{' – '.join(dl.route.nodes)} ({dl.route.minutes:.0f} min)", INK))
        plan = r.ingredient_plan.get(sel.id, {})
        picks = ", ".join(f"{ing} {sum(kg for _, kg, _ in p):g} kg ({'+'.join(sh for sh, _, _ in p)})"
                          for ing, p in plan.items())
        if picks:
            lines.append(("Picks", picks, INK))
    for label, body, colour in lines:
        draw_line(s, DIVIDER, (x0, y - 8), (x1, y - 8))
        caps(s, label, (x0, y + 2), 11)
        for ln in wrap(body, 13, width - 86):
            if y > box.bottom - PAD - 18:
                return
            text(s, ln, (x0 + 86, y), 13, colour)
            y += 19
        y += 14
