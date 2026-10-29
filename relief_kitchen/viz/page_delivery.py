"""Delivery page: road network, routes, vehicles in transit, and hover details."""

from __future__ import annotations

import math

import pygame

from ..support.env.road_network import road_between
from ..support.env.scenario import clock
from ..support.model_helpers import UNLOAD_MINUTES
from .state import ViewState
from .theme import (ACCENT, ERROR, FAINT, HAIRLINE, INK, MUTED, OK, PAPER, ROAD, SURFACE, dashed, disc, draw_line,
                    draw_rect, fit, hline, ring, section, text)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, M, W, meter


def network_projection(net, area: pygame.Rect):
    xs = [p.x for p in net.places.values()]
    ys = [p.y for p in net.places.values()]
    sx = area.width / max(1e-9, max(xs) - min(xs))
    sy = area.height / max(1e-9, max(ys) - min(ys))

    def to_px(pid):
        p = net.places[pid]
        return (area.x + (p.x - min(xs)) * sx, area.y + (p.y - min(ys)) * sy)

    return to_px


def vehicle_pos(minute, r, d, to_px):
    """Pixel position of a vehicle on its route (None when it is at the depot)."""
    if not d.route or minute < d.depart or minute > d.back:
        return None
    nodes, net = d.route.nodes, r.scenario.roads
    legs = [road_between(net, a, b).minutes for a, b in zip(nodes, nodes[1:])]
    if minute <= d.arrive:
        frac = (minute - d.depart) / max(1e-9, d.arrive - d.depart)
    elif minute <= d.arrive + UNLOAD_MINUTES:
        frac = 1.0
    else:
        frac = 1 - (minute - d.arrive - UNLOAD_MINUTES) / max(1e-9, d.back - d.arrive - UNLOAD_MINUTES)
    dist = frac * (sum(legs) or 1)
    for (a, b), leg in zip(zip(nodes, nodes[1:]), legs):
        if dist <= leg:
            pa, pb = to_px(a), to_px(b)
            f = dist / leg
            return (pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f)
        dist -= leg
    return to_px(nodes[-1])


def vehicle_leg(minute, d) -> str:
    if minute < d.depart:
        return "loading at the kitchen"
    if minute <= d.arrive:
        return "driving out"
    if minute <= d.arrive + UNLOAD_MINUTES:
        return "unloading"
    if minute <= d.back:
        return "returning to the kitchen"
    return "back at the kitchen"


def draw_network_map(st: ViewState, s, r, area: pygame.Rect, detailed: bool = True):
    net = r.scenario.roads
    to_px = network_projection(net, area)
    used_by: dict[str, list[str]] = {}
    if r.allocation:
        for d in r.allocation.deliveries:
            for rid in (d.route.roads if d.route else []):
                used_by.setdefault(rid, []).append(d.order)

    for road in net.roads.values():
        a, b = to_px(road.a), to_px(road.b)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        n = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        nx, ny = -(b[1] - a[1]) / n, (b[0] - a[0]) / n
        if road.open:
            draw_line(s, ROAD, a, b, 3 if detailed else 2)
            text(s, f"{road.minutes:g}′", (mx + nx * 12, my + ny * 12), 10 if detailed else 9, FAINT, anchor="center")
        else:
            dashed(s, ERROR, a, b, 2)
            text(s, f"{road.id} closed", (mx - nx * 14, my - ny * 14), 10, ERROR, True, anchor="center")
        orders = used_by.get(road.id, [])
        for i, oid in enumerate(orders):
            off = (i - (len(orders) - 1) / 2) * (5 if detailed else 4)
            draw_line(s, st.order_color.get(oid, ACCENT), (a[0] + nx * off, a[1] + ny * off),
                             (b[0] + nx * off, b[1] + ny * off), 3)
        # hover: a small box at the middle of the road
        st.hover.append((pygame.Rect(mx - 14, my - 10, 28, 20), "road", road.id))

    for p in net.places.values():
        x, y = to_px(p.id)
        if p.kind == "junction":
            disc(s, HAIRLINE, (x, y), 4)
            if detailed:
                text(s, p.id, (x + 8, y - 14), 10, FAINT)
            continue
        size = 1.25 if detailed else 1.0
        if p.kind == "depot":
            draw_rect(s, INK, (x - 8 * size, y - 8 * size, 16 * size, 16 * size), border_radius=2)
        elif p.kind == "hospital":
            disc(s, INK, (x, y), 10 * size)
            draw_rect(s, SURFACE, (x - 1.5, y - 6, 3, 12))
            draw_rect(s, SURFACE, (x - 6, y - 1.5, 12, 3))
        else:
            ring(s, INK, (x, y), 9 * size, PAPER)
        reachable = p.kind == "depot" or r.routes.get(p.id) is not None
        st.hover.append((pygame.Rect(x - 14, y - 14, 28, 28), "place", p.id))
        if p.kind == "depot":
            text(s, p.label, (x, y + 14), 12 if detailed else 11, INK, True, anchor="midtop")
            continue
        text(s, p.label, (x + 16, y - 16), 13 if detailed else 12, INK if reachable else ERROR, True)
        sub = f"{p.people} people" if reachable else "unreachable"
        text(s, sub, (x + 16, y + 1), 11, MUTED if reachable else ERROR)

    if r.allocation:
        for d in r.allocation.deliveries:
            pos = vehicle_pos(st.minute, r, d, to_px)
            if pos is None:
                continue
            box = pygame.Rect(0, 0, 30 if detailed else 26, 18 if detailed else 16)
            box.center = pos
            draw_rect(s, st.order_color.get(d.order, ACCENT), box, border_radius=3)
            text(s, d.vehicle, box.center, 10, SURFACE, True, anchor="center")
            st.hover.append((box.inflate(6, 6), "vehicle", d.order))
    return to_px


def draw_delivery_page(st: ViewState, s, r):
    section(s, M, CONTENT_TOP, "Delivery network", "weighted road graph  ·  A* routes  ·  hover places, roads, vehicles")
    draw_network_map(st, s, r, pygame.Rect(M + 40, CONTENT_TOP + 60, 700, CONTENT_BOTTOM - CONTENT_TOP - 120))
    draw_line(s, HAIRLINE, (928, CONTENT_TOP), (928, CONTENT_BOTTOM))
    right = pygame.Rect(948, CONTENT_TOP, W - M - 948, CONTENT_BOTTOM - CONTENT_TOP)
    y = draw_delivery_table(st, s, r, right)
    y = draw_vehicle_panel(st, s, r, pygame.Rect(right.x, y + 18, right.width, 200))
    draw_roads_panel(st, s, r, pygame.Rect(right.x, y + 18, right.width, right.bottom - y - 18))


def draw_delivery_table(st, s, r, rect) -> int:
    sc = r.scenario
    section(s, rect.x, rect.y, "Deliveries", "times are wall-clock")
    y = rect.y + 26
    cols = (("ORDER", 12), ("VEH", 64), ("LEAVES", 110), ("ARRIVES", 170), ("DUE", 236), ("TO", 290))
    for label, dx in cols:
        text(s, label, (rect.x + dx, y), 10, FAINT, True)
    y += 16
    hline(s, rect.x, rect.right, y)
    for d in (r.allocation.deliveries if r.allocation else []):
        o = next(o for o in sc.orders if o.id == d.order)
        late = d.arrive > o.deadline
        disc(s, st.order_color.get(d.order, ACCENT), (rect.x + 4, y + 10), 4)
        text(s, d.order, (rect.x + 12, y + 3), 12, INK, True)
        text(s, d.vehicle, (rect.x + 64, y + 3), 12, INK)
        text(s, clock(sc, d.depart), (rect.x + 110, y + 3), 12, INK)
        text(s, clock(sc, d.arrive), (rect.x + 170, y + 3), 12, ERROR if late else INK)
        text(s, clock(sc, o.deadline), (rect.x + 236, y + 3), 12, MUTED)
        text(s, fit(sc.roads.places[d.destination].label, 12, rect.width - 290), (rect.x + 290, y + 3), 12, INK)
        st.hover.append((pygame.Rect(rect.x, y, rect.width, 20), "place", d.destination))
        y += 21
    for oid, diag in r.diagnoses.items():
        disc(s, st.order_color.get(oid, ACCENT), (rect.x + 4, y + 10), 4)
        text(s, oid, (rect.x + 12, y + 3), 12, INK, True)
        text(s, fit(f"not delivered — {', '.join(diag.categories)}", 12, rect.width - 64), (rect.x + 64, y + 3), 12,
             ERROR)
        y += 21
    return y


def draw_vehicle_panel(st, s, r, rect) -> int:
    sc = r.scenario
    section(s, rect.x, rect.y, "Vehicles", "busy time over the day")
    y = rect.y + 26
    trips = r.allocation.deliveries if r.allocation else []
    day = max([d.back for d in trips] + [sc.horizon])
    for vid, v in sorted(sc.vehicles.items()):
        mine = [d for d in trips if d.vehicle == vid]
        busy = sum(d.back - d.depart for d in mine)
        now = next((d for d in mine if d.depart <= st.minute <= d.back), None)
        text(s, vid, (rect.x, y), 12, INK, True)
        text(s, f"{v.capacity} meals · speed ×{v.speed:g}", (rect.x + 30, y + 1), 11, MUTED)
        state = f"{vehicle_leg(st.minute, now)} ({now.order})" if now else "at the kitchen"
        text(s, fit(state, 11, 190), (rect.right, y + 1), 11, INK if now else FAINT, anchor="topright")
        y += 17
        meter(s, pygame.Rect(rect.x, y + 2, rect.width, 5), busy / day if day else 0, OK)
        text(s, f"{len(mine)} trip(s), {busy:.0f} min", (rect.x, y + 9), 10, FAINT)
        y += 26
    return y


def draw_roads_panel(st, s, r, rect):
    net = r.scenario.roads
    section(s, rect.x, rect.y, "Roads", "")
    closed = [rd for rd in net.roads.values() if not rd.open]
    y = rect.y + 24
    if not closed:
        text(s, "All roads open.", (rect.x, y), 12, MUTED)
        return
    for rd in closed:
        text(s, f"{rd.id} closed: {rd.a} – {rd.b} ({rd.minutes:g} min)", (rect.x, y), 12, ERROR)
        y += 18


# ---------------------------------------------------------------------------------------------
# tooltips
# ---------------------------------------------------------------------------------------------
def place_tooltip(st, r, pid):
    sc = r.scenario
    p = sc.roads.places[pid]
    lines = [("title", p.label or pid), ("sub", p.kind + (f"  ·  about {p.people} people" if p.people else ""))]
    if p.kind == "depot":
        return lines + [("text", "The kitchen: every route starts here.")]
    route = r.routes.get(pid)
    if route is None:
        return lines + [("text", "Unreachable: every road into this place is closed.", ERROR)]
    lines += [("kv", "Route", " – ".join(route.nodes)), ("kv", "Drive", f"{route.minutes:.0f} min (at speed ×1)")]
    orders = [o for o in sc.orders if o.destination == pid]
    if orders:
        lines.append(("head", "Orders"))
    deliveries = {d.order: d for d in (r.allocation.deliveries if r.allocation else [])}
    for o in orders:
        if o.id in deliveries:
            d = deliveries[o.id]
            lines.append(("kv", o.id, f"{o.meals} meals by {d.vehicle}, arrives {clock(sc, d.arrive)} "
                                      f"(due {clock(sc, o.deadline)})"))
        else:
            lines.append(("kv", o.id, f"{o.meals} meals — not delivered", ERROR))
    return lines


def road_tooltip(st, r, rid):
    road = r.scenario.roads.roads[rid]
    users = [d.order for d in (r.allocation.deliveries if r.allocation else []) if d.route and rid in d.route.roads]
    return [("title", f"Road {rid}"), ("sub", f"{road.a} – {road.b}"),
            ("kv", "Travel", f"{road.minutes:g} min"),
            ("kv", "Status", "open" if road.open else "closed", INK if road.open else ERROR),
            ("kv", "Used by", ", ".join(users) or "no delivery")]


def vehicle_tooltip(st, r, oid):
    sc = r.scenario
    d = next(d for d in r.allocation.deliveries if d.order == oid)
    v = sc.vehicles[d.vehicle]
    return [("title", f"Vehicle {d.vehicle}"), ("sub", f"capacity {v.capacity} meals · speed ×{v.speed:g}"),
            ("kv", "Load", f"{d.meals} meals of {sc.recipes[d.recipe].name} ({oid})"),
            ("kv", "To", sc.roads.places[d.destination].label),
            ("kv", "Now", vehicle_leg(st.minute, d)),
            ("kv", "Times", f"leaves {clock(sc, d.depart)}, arrives {clock(sc, d.arrive)}, back {clock(sc, d.back)}"),
            ("bar", (st.minute - d.depart) / max(1, d.back - d.depart), st.order_color.get(oid, ACCENT))]
