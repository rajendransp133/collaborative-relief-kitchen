"""Kitchen page: the floor card, a "Kitchen now" / pinned-details card and the Batches card.

Layout follows the Relief Kitchen web-console design: white cards on a grey ground, the floor in
a grey inset with zone labels, ids and times in mono, colour only on orders, zones and problems.
"""

from __future__ import annotations

import pygame

from ..support.env.kitchen_grid import stations_of
from ..support.env.scenario import clock
from ..support.kitchen_flow import (STAGE_VERB, agent_activity, batch_journey, batch_status, leg_at,
                                       previous_task, station_activity, stock_at, tasks_by_batch)
from ..support.motion import agent_position, agent_trail
from .state import ViewState
from .theme import (ACCENT, BORDER, DIVIDER, ERROR, FAINT, GRID, HAIRLINE, HATCH_EDGE,
                    INK, MAP_BG, MUTED, PAPER, PATH_DOT, STATION_BUSY, STATION_NAME, STATION_STYLE, SUBTLE,
                    SURFACE, WALL, ZONE_NAME, ZONE_TINT, caps, card, disc, draw_line, draw_rect, fit, hatch, hex_rgb,
                    mix, text, text_width, wrap)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, M, W, button, meter

TOKEN_LETTER = {"storage": "I", "prep": "P", "stove": "C", "packaging": "K", "dispatch": "K"}
ZONE_LABEL = {"storage": "Storage", "prep": "Prep", "stove": "Cooking",
              "packaging": "Packing", "dispatch": "Out"}
STAGE_NAME = {"fetch": "Fetch", "prep": "Prep", "cook": "Cook", "pack": "Pack"}
WORK_TYPES = ("prep", "stove", "packaging")  # stations that do a stage (and can fail live)
AGENT_IDLE = hex_rgb("#1E2128")
ZONE_TEXT = hex_rgb("#4A505E")
TAG_EDGE = hex_rgb("#F0C3B0")

# layout (logical px): floor card on the left, two cards stacked on the right
GAP = 20
LEFT = pygame.Rect(M, CONTENT_TOP, 952, CONTENT_BOTTOM - CONTENT_TOP)
RIGHT = pygame.Rect(LEFT.right + GAP, CONTENT_TOP, W - M - LEFT.right - GAP, CONTENT_BOTTOM - CONTENT_TOP)
PAD = 18  # card padding
ROW = 28  # rows in the Kitchen now / details card
STOCK_ROW = 20  # ingredient rows in the Stock view
BATCH_ROW = 36
GUTTER = 80  # left of the floor grid, for the Prep / Cooking labels


# ---------------------------------------------------------------------------------------------
# derived data, cached per plan step (journeys are recomputed only when the plan changes)
# ---------------------------------------------------------------------------------------------
_CACHE: dict = {}


def journeys(r):
    key = id(r)
    if key not in _CACHE:
        _CACHE.clear()
        arrivals = r.motion.arrivals if r.motion else {}
        _CACHE[key] = {k: batch_journey(r.scenario, r.allocation, k, arrivals)
                       for k in tasks_by_batch(r.allocation)} if r.allocation else {}
    return _CACHE[key]


def zone_tints(grid):
    """Floor cell -> station type of an adjacent station (tints the floor by kitchen zone)."""
    tint = {}
    for st_ in grid.stations.values():
        r0, c0 = st_.cell
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                cell = (r0 + dr, c0 + dc)
                if 0 <= cell[0] < grid.height and 0 <= cell[1] < grid.width and grid.rows[cell[0]][cell[1]] == ".":
                    tint.setdefault(cell, st_.type)
    return tint


def valid_pin(r, pin) -> bool:
    """Does the pinned item still exist at this plan step?"""
    kind, payload = pin
    if kind == "station":
        return payload in r.scenario.kitchen.stations
    if kind == "agent":
        return payload in r.scenario.agents
    return kind == "batch" and payload in journeys(r)


def baseline(st: ViewState):
    """From the initial plan: (order, batch, stage) -> station, and batch -> minute it reaches the door."""
    first = st.steps[0] if st.steps else None
    if not first or not first.allocation:
        return {}, {}
    where = {(t.order, t.batch, t.stage): t.station for t in first.allocation.tasks}
    door = {k: chain[-1].end for k, chain in tasks_by_batch(first.allocation).items()}
    return where, door


def road_leg(legs):
    return next((lg for lg in legs if lg.kind == "in_vehicle"), None)


def span(sc, a, b) -> str:
    return f"{clock(sc, a)}–{clock(sc, b)}"


def phase_text(task, minute) -> str:
    if minute < task.start + task.carry_in:
        return "Bringing in"
    if minute >= task.end - task.carry_out:
        return "To door"
    return STAGE_VERB.get(task.stage, task.stage)


# ---------------------------------------------------------------------------------------------
# the small floor plan on the overview page
# ---------------------------------------------------------------------------------------------
def draw_kitchen_map(st: ViewState, s, r, rect: pygame.Rect, detailed: bool = False):
    sc, grid = r.scenario, r.scenario.kitchen
    cell = min(rect.width // grid.width, rect.height // grid.height)
    ox = rect.x + (rect.width - cell * grid.width) // 2
    oy = rect.y
    to_px = lambda rc: (ox + rc[1] * cell + cell / 2, oy + rc[0] * cell + cell / 2)  # noqa: E731
    al, now = r.allocation, st.minute
    tints = zone_tints(grid)
    for rr in range(grid.height):
        for cc in range(grid.width):
            cr = pygame.Rect(ox + cc * cell, oy + rr * cell, cell, cell)
            if grid.rows[rr][cc] == "#":
                draw_rect(s, MAP_BG, cr)
                continue
            zone = tints.get((rr, cc))
            draw_rect(s, ZONE_TINT[zone] if zone else SURFACE, cr)
            draw_rect(s, GRID, cr, 1)
    for stn in grid.stations.values():
        cr = pygame.Rect(ox + stn.cell[1] * cell + 2, oy + stn.cell[0] * cell + 2, cell - 4, cell - 4)
        if stn.failed:
            hatch(s, cr, 4)
            draw_rect(s, HATCH_EDGE, cr, 1, border_radius=4)
        else:
            fill, edge = STATION_STYLE[stn.type]
            draw_rect(s, fill, cr, border_radius=4)
            draw_rect(s, edge, cr, 1, border_radius=4)
        text(s, stn.id, cr.center, 10, MUTED if stn.failed else INK, anchor="center", mono=True, weight="semibold")
        st.hover.append((cr, "station", stn.id))
    if r.motion:
        for ag in sorted(sc.agents.values(), key=lambda a: a.id):
            px, py = to_px(agent_position(r.motion, ag.id, now))
            task, _, _ = agent_activity(al, ag.id, now) if al else (None, "idle", None)
            col = st.order_color.get(task.order, AGENT_IDLE) if task else AGENT_IDLE
            rad = cell * 0.32
            box = pygame.Rect(0, 0, rad * 2, rad * 2)
            box.center = (px, py)
            if ag.kind == "robot":
                draw_rect(s, col, box, border_radius=4)
            else:
                disc(s, col, (px, py), rad)
            text(s, ag.id[:2], (px, py), 9, SURFACE, anchor="center", weight="semibold")
            st.hover.append((box.inflate(6, 6), "agent", ag.id))
    return ox, oy, cell


# ---------------------------------------------------------------------------------------------
# the floor card
# ---------------------------------------------------------------------------------------------
def floor_box(grid):
    """Rows and columns worth drawing: every non-wall cell and every station (the door sits in the wall)."""
    cells = [(rr, cc) for rr in range(grid.height) for cc in range(grid.width) if grid.rows[rr][cc] != "#"]
    cells += [x.cell for x in grid.stations.values()]
    return (min(c[0] for c in cells), max(c[0] for c in cells), min(c[1] for c in cells), max(c[1] for c in cells))


def draw_floor_card(st: ViewState, s, r) -> pygame.Rect:
    sc, grid = r.scenario, r.scenario.kitchen
    r0, r1, c0, c1 = floor_box(grid)
    inset_w = LEFT.width - 2 * PAD
    pitch = (inset_w - 14 - GUTTER) // (c1 - c0 + 1)
    inset_h = 10 + 20 + pitch * (r1 - r0 + 1) + 12
    legend = legend_items()
    legend_rows = legend_layout(legend, LEFT.width - 2 * PAD)
    height = PAD + 24 + 14 + inset_h + 16 + 24 * len(legend_rows) + PAD - 6
    box = pygame.Rect(LEFT.x, LEFT.y, LEFT.width, height)
    card(s, box)
    t = text(s, "Kitchen floor", (box.x + PAD, box.y + PAD), 17, INK, weight="semibold")

    inset = pygame.Rect(box.x + PAD, t.bottom + 14, inset_w, inset_h)
    draw_rect(s, MAP_BG, inset, border_radius=10)
    gx, gy = inset.x + GUTTER, inset.y + 30
    cell_rect = lambda rr, cc: pygame.Rect(gx + (cc - c0) * pitch, gy + (rr - r0) * pitch, pitch - 2, pitch - 2)  # noqa: E731
    centre = lambda rc: cell_rect(*rc).center  # noqa: E731
    draw_zone_labels(s, grid, (r0, c0), pitch, gx, gy, inset)
    draw_floor(st, s, r, (r0, r1, c0, c1), cell_rect, centre, pitch)
    draw_legend(s, legend_rows, box.x + PAD, inset.bottom + 16)
    return box


def draw_zone_labels(s, grid, origin, pitch, gx, gy, inset):
    """Zones along the top row get a label over their columns, the others one beside their row."""
    r0, c0 = origin
    tints = zone_tints(grid)
    done = set()
    for stn in sorted(grid.stations.values(), key=lambda x: x.cell):
        label = ZONE_LABEL[stn.type]
        if label in done:
            continue
        done.add(label)
        same = [x for x in grid.stations.values() if ZONE_LABEL[x.type] == label]
        cols = [x.cell[1] for x in same] + [c for (rr, c), z in tints.items() if ZONE_LABEL[z] == label]
        if stn.type == "dispatch":
            caps(s, label, (gx + (max(cols) - c0 + 1) * pitch - 2, inset.y + 10), 11, ZONE_TEXT, anchor="topright")
        elif min(x.cell[0] for x in same) <= r0:
            caps(s, label, (gx + (min(cols) - c0) * pitch, inset.y + 10), 11, ZONE_TEXT)
        else:
            row = sum(x.cell[0] for x in same) / len(same)
            caps(s, label, (inset.x + 14, gy + (row - r0) * pitch + pitch / 2 - 1), 11, ZONE_TEXT, anchor="midleft")


def draw_floor(st, s, r, box, cell_rect, centre, pitch):
    sc, grid = r.scenario, r.scenario.kitchen
    r0, r1, c0, c1 = box
    al, now, pin = r.allocation, st.minute, st.pinned
    tints = zone_tints(grid)
    station_cells = {x.cell for x in grid.stations.values()}

    # floor: zone tints, interior walls; outer walls are left as the inset
    for rr in range(r0, r1 + 1):
        for cc in range(c0, c1 + 1):
            cr = cell_rect(rr, cc)
            if grid.rows[rr][cc] == "#" and (rr, cc) not in station_cells:
                outer = rr in (0, grid.height - 1) or cc in (0, grid.width - 1)
                if not outer:
                    draw_rect(s, WALL, cr)
                continue
            zone = tints.get((rr, cc))
            draw_rect(s, ZONE_TINT[zone] if zone else SURFACE, cr)
            if (rr, cc) in grid.blocked:
                draw_line(s, ERROR, cr.topleft, cr.bottomright, 2)

    # planned paths (the current move of every agent)
    if r.motion:
        for ag in sc.agents.values():
            for c in agent_trail(r.motion, ag.id, now, linger=1.0)[1:-1]:
                if r0 <= c[0] <= r1 and c0 <= c[1] <= c1:
                    disc(s, PATH_DOT, centre(c), 3)

    # stations
    stock_now = stock_at(sc, r.withdrawals, now)
    for stn in grid.stations.values():
        tile = cell_rect(*stn.cell).inflate(-8, -8)
        fill, edge = STATION_STYLE[stn.type]
        task, _ = station_activity(al, stn.id, now) if al and not stn.failed else (None, [])
        if pin == ("station", stn.id):
            draw_rect(s, INK, tile.inflate(6, 6), border_radius=10)
        if stn.failed:
            hatch(s, tile, 7)
            draw_rect(s, HATCH_EDGE, tile, 2, border_radius=7)
        else:
            draw_rect(s, STATION_BUSY[stn.type] if task else fill, tile, border_radius=7)
            draw_rect(s, edge, tile, 2, border_radius=7)
        id_r = text(s, stn.id, tile.center, 14, INK if not stn.failed else HATCH_EDGE, anchor="center", mono=True,
                    weight="semibold")
        if stn.failed:
            draw_line(s, HATCH_EDGE, (id_r.x - 1, id_r.centery + 1), (id_r.right + 1, id_r.centery + 1), 1.5)
        bar = pygame.Rect(tile.x + 6, tile.bottom - 8, tile.width - 12, 3)
        if stn.type == "storage":
            start = sum(stn.stock.values()) or 1
            meter(s, bar, sum(stock_now.get(stn.id, {}).values()) / start, edge, back=mix(fill, INK, 0.14))
        elif task:
            colour = st.order_color.get(task.order, ACCENT)
            disc(s, colour, (tile.right - 7, tile.y + 7), 3.5)
            meter(s, bar, (now - task.start) / max(1, task.end - task.start), colour, back=mix(fill, INK, 0.14))
        st.hover.append((tile, "station", stn.id))

    # agents
    agent_px = {}
    if r.motion:
        for ag in sorted(sc.agents.values(), key=lambda a: a.id):
            row, col = agent_position(r.motion, ag.id, now)  # fractional while walking
            origin = cell_rect(r0, c0)
            px, py = origin.centerx + (col - c0) * pitch, origin.centery + (row - r0) * pitch
            agent_px[ag.id] = (px, py)
            task, _, _ = agent_activity(al, ag.id, now) if al else (None, "idle", None)
            colour = st.order_color.get(task.order, AGENT_IDLE) if task else AGENT_IDLE
            rad = pitch * 0.34
            body = pygame.Rect(0, 0, rad * 2, rad * 2)
            body.center = (px, py)
            robot = ag.kind == "robot"
            if pin == ("agent", ag.id):
                if robot:
                    draw_rect(s, INK, body.inflate(10, 10), border_radius=11)
                    draw_rect(s, SURFACE, body.inflate(6, 6), border_radius=10)
                else:
                    disc(s, INK, (px, py), rad + 5)
                    disc(s, SURFACE, (px, py), rad + 3)
            if robot:
                draw_rect(s, colour, body, border_radius=8)
            else:
                disc(s, colour, (px, py), rad)
            text(s, ag.id[:2], (px, py), 12, SURFACE, anchor="center", weight="semibold")
            st.hover.append((body.inflate(6, 6), "agent", ag.id))

    # food batches: on a station, carried by an agent, or waiting at the door
    if al:
        stacks: dict[str, int] = {}
        size = 16
        for key, legs in journeys(r).items():
            leg = leg_at(legs, now)
            if leg is None or leg.kind in ("in_vehicle", "delivered"):
                continue
            if leg.kind in ("carried", "to_door") and leg.who in agent_px:
                x, y = agent_px[leg.who]
                x, y = x + pitch * 0.30, y - pitch * 0.30
                letter = TOKEN_LETTER[grid.stations[leg.origin].type] if leg.origin else "I"
            else:
                stn = grid.stations[leg.where]
                n = stacks.get(stn.id, 0)
                stacks[stn.id] = n + 1
                tile = cell_rect(*stn.cell).inflate(-8, -8)
                x, y = tile.x + 5 + n * (size - 4), tile.y + 5
                letter = TOKEN_LETTER[stn.type] if leg.kind != "collecting" else "I"
                if leg.kind == "working":  # not finished yet: still shows what came in
                    prev_type = {"prep": "storage", "stove": "prep", "packaging": "stove"}
                    letter = TOKEN_LETTER.get(prev_type.get(stn.type, stn.type), "I")
            tok = pygame.Rect(0, 0, size, size)
            tok.center = (x, y)
            if pin == ("batch", key):
                draw_rect(s, INK, tok.inflate(8, 8), border_radius=6)
            draw_rect(s, st.order_color.get(key[0], ACCENT), tok, border_radius=4)
            draw_rect(s, SURFACE, tok, 1, border_radius=4)
            text(s, letter, tok.center, 10, SURFACE, anchor="center", mono=True, weight="semibold")
            st.hover.append((tok.inflate(4, 4), "batch", key))


def legend_items():
    items = [(("station", t), STATION_NAME[t]) for t in ("storage", "prep", "stove", "packaging",
                                                          "dispatch")]
    return items + [(("person",), "Person"), (("robot",), "Robot"), (("token",), "Food batch"),
                    (("path",), "Planned path"), (("failed",), "Out of service")]


def legend_layout(items, width):
    rows, row, x = [], [], 0
    for item in items:
        w = 20 + text_width(item[1], 12) + 18
        if row and x + w > width:
            rows.append(row)
            row, x = [], 0
        row.append(item)
        x += w
    return rows + [row] if row else rows


def draw_legend(s, rows, x0, y):
    for row in rows:
        x = x0
        for (kind, *arg), label in row:
            sw = pygame.Rect(x, y + 3, 12, 12)
            if kind == "station":
                fill, edge = STATION_STYLE[arg[0]]
                draw_rect(s, fill, sw, border_radius=3)
                draw_rect(s, edge, sw, 2, border_radius=3)
            elif kind == "person":
                disc(s, AGENT_IDLE, sw.center, 6)
            elif kind == "robot":
                draw_rect(s, AGENT_IDLE, sw, border_radius=3)
            elif kind == "token":
                draw_rect(s, MUTED, sw, border_radius=3)
                text(s, "I", sw.center, 9, SURFACE, anchor="center", mono=True, weight="semibold")
            elif kind == "path":
                disc(s, PATH_DOT, sw.center, 3)
            elif kind == "failed":
                hatch(s, sw, 3, step=4)
                draw_rect(s, HATCH_EDGE, sw, 2, border_radius=3)
            x = text(s, label, (x + 18, y), 12, SUBTLE).right + 18
        y += 24


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
def draw_kitchen_page(st: ViewState, s, r):
    floor = draw_floor_card(st, s, r)
    if st.pinned and not valid_pin(r, st.pinned):
        st.pinned = None
    bottom = CONTENT_BOTTOM
    min_batches = 52 + 26 + 2 * BATCH_ROW + PAD  # the Batches card always shows its header and two rows
    if st.pinned:
        info = pinned_info(st, r, *st.pinned)
        top = draw_pinned_card(st, s, r, info, RIGHT.y, bottom - GAP - min_batches)
    else:
        top = draw_now_card(st, s, r, RIGHT.y)
    shelves = stations_of(r.scenario.kitchen, "storage")
    body = (BATCH_ROW * max(1, len(journeys(r))) if st.kitchen_tab == "batches"
            else sum(STOCK_ROW * len(x.stock) + 6 for x in shelves) + 4)
    wanted = 52 + 26 + body + PAD - 4
    lower = pygame.Rect(RIGHT.x, top + 16, RIGHT.width, max(min_batches, min(wanted, CONTENT_BOTTOM - top - 16)))
    if st.kitchen_tab == "stock":
        draw_stock_card(st, s, r, lower)
    else:
        draw_batch_card(st, s, r, lower)


# ---------------------------------------------------------------------------------------------
# Kitchen now card
# ---------------------------------------------------------------------------------------------
def station_status(st, r, stn):
    """(status text, dot colour, text colour, progress or None) for a working station right now."""
    sc, al = r.scenario, r.allocation
    if stn.failed:
        return "out of service", HATCH_EDGE, ERROR, None
    task, queue = station_activity(al, stn.id, st.minute) if al else (None, [])
    if task:
        left = max(0, task.end - st.minute)
        return (f"{phase_text(task, st.minute)} {task.order} b{task.batch} · {task.agent} · {left:.0f} min",
                st.order_color.get(task.order, ACCENT), SUBTLE,
                (st.minute - task.start) / max(1, task.end - task.start))
    if queue:
        return f"next {queue[0].order} b{queue[0].batch} at {clock(sc, queue[0].start)}", BORDER, MUTED, None
    return "idle", BORDER, MUTED, None


def draw_now_card(st, s, r, y) -> int:
    sc = r.scenario
    stations = [x for x in sorted(sc.kitchen.stations.values(), key=lambda x: x.id) if x.type in WORK_TYPES]
    statuses = [station_status(st, r, x) for x in stations]
    legs = [leg_at(lg, st.minute) for lg in journeys(r).values()]
    busy = sum(1 for x, stt in zip(stations, statuses) if stt[3] is not None)
    working = sum(1 for x in stations if not x.failed)
    on_road = sum(1 for lg in legs if lg and lg.kind == "in_vehicle")
    delivered = sum(1 for lg in legs if lg and lg.kind == "delivered")
    summary = (f"{busy} of {working} stations busy · {on_road} batches on the road · {delivered} delivered"
               if r.allocation else "No plan: every order was rejected.")
    inner = RIGHT.width - 2 * PAD
    summary_lines = wrap(summary, 13, inner)
    head = 46 + 19 * len(summary_lines) + 10
    box = pygame.Rect(RIGHT.x, y, RIGHT.width, head + ROW * len(stations) + PAD - 8)
    card(s, box)
    x = box.x + PAD
    text(s, "Kitchen now", (x, box.y + 16), 17, INK, weight="semibold")
    ty = box.y + 46
    for ln in summary_lines:
        text(s, ln, (x, ty), 13, MUTED)
        ty += 19
    ry = box.y + head
    draw_line(s, DIVIDER, (x, ry), (box.right - PAD, ry))
    for stn, (msg, dot, colour, _) in zip(stations, statuses):
        row = pygame.Rect(x - 6, ry, inner + 12, ROW)
        if st.pinned == ("station", stn.id):
            draw_rect(s, PAPER, row, border_radius=4)
        disc(s, dot, (x + 4, row.centery), 4)
        text(s, stn.id, (x + 16, row.centery), 13, INK, anchor="midleft", mono=True, weight="semibold")
        text(s, fit(msg, 13, inner - 54), (x + 52, row.centery), 13, colour, anchor="midleft")
        draw_line(s, DIVIDER, (x, row.bottom), (box.right - PAD, row.bottom))
        st.hover.append((row, "station", stn.id))
        ry += ROW
    return box.bottom


# ---------------------------------------------------------------------------------------------
# pinned details card
# ---------------------------------------------------------------------------------------------
def pinned_info(st, r, kind, payload) -> dict:
    """What the pinned card shows: kicker, title, text, progress, list rows and the fail action."""
    sc, al = r.scenario, r.allocation
    where0, _ = baseline(st)
    info = {"kicker": "", "title": "", "text": "", "progress": None, "colour": INK, "rows_title": "", "rows": [],
            "empty": "", "fail": None, "failed": False, "mono": kind == "station"}  # order ids stay sans
    if kind == "station":
        stn = sc.kitchen.stations[payload]
        info.update(kicker=f"{ZONE_LABEL[stn.type] if stn.type != 'dispatch' else 'Dispatch'} · "
                           f"{STATION_NAME[stn.type]}", title=stn.id)
        if stn.type == "storage":
            now = stock_at(sc, r.withdrawals, st.minute)[stn.id]
            left, start = sum(now.values()), sum(stn.stock.values())
            upcoming = [w for w in r.withdrawals if w.shelf == stn.id and w.minute > st.minute]
            info["text"] = f"{left:.1f} kg left of {start:g} kg" + (
                f" · next pick {upcoming[0].kg:g} kg {upcoming[0].ingredient} at {clock(sc, upcoming[0].minute)}"
                if upcoming else " · no more picks planned")
            info["rows_title"] = "Stock now / start of day"
            for ing, kg in stn.stock.items():
                have = now.get(ing, 0.0)
                info["rows"].append((STATION_STYLE["storage"][1] if have else ERROR, ing, f"{have:.1f} / {kg:g} kg",
                                     "" if have else "empty"))
        elif stn.type == "dispatch":
            info["rows_title"] = "Departures"
            for key, legs in journeys(r).items():
                lg = road_leg(legs)
                if lg:
                    info["rows"].append((st.order_color.get(key[0], ACCENT),
                                         f"{key[0]} b{key[1]} → {sc.roads.places[order.destination].label}",
                                         span(sc, lg.start, lg.end), ""))
            info["text"] = f"{len(info['rows'])} batches leave through this door today"
            info["empty"] = "No departures planned."
        else:
            msg, dot, _, frac = station_status(st, r, stn)
            info.update(text=msg[0].upper() + msg[1:], progress=frac, colour=dot, fail=stn.id, failed=stn.failed,
                        rows_title="Schedule", empty="Nothing is scheduled here.")
            if stn.failed:
                info["text"] = "Out of service. The plan routes its work to the other stations."
            for t in sorted((t for t in al.tasks if t.station == stn.id), key=lambda t: t.start) if al else []:
                before = where0.get((t.order, t.batch, t.stage))
                info["rows"].append((st.order_color.get(t.order, ACCENT),
                                     f"{t.order} b{t.batch} · {STAGE_NAME.get(t.stage, t.stage)} · {t.agent}",
                                     span(sc, t.start, t.end),
                                     f"moved from {before}" if before and before != stn.id else ""))
    elif kind == "agent":
        ag = sc.agents[payload]
        info.update(kicker=f"{ag.kind.capitalize()} · {', '.join(sorted(ag.skills))}", title=ag.id,
                    rows_title="Today", empty="No tasks today.")
        task, phase, nxt = agent_activity(al, ag.id, st.minute) if al else (None, "idle", None)
        if task is None:
            info["text"] = "Idle, waiting at its home spot" + (
                f" · next {nxt.order} b{nxt.batch} at {clock(sc, nxt.start)}" if nxt else "")
        else:
            prev = previous_task(al, task)
            if phase == "carry-in":
                what = (f"Carrying {task.order} b{task.batch} from {prev.station} to {task.station}" if prev
                        else f"Walking to shelf {task.station}")
            elif phase == "carry-out":
                what = f"Carrying packed {task.order} b{task.batch} to the dispatch door"
            else:
                what = f"{STAGE_VERB.get(task.stage, task.stage)} {task.order} b{task.batch} at {task.station}"
            info.update(text=f"{what} · {max(0, task.end - st.minute):.0f} min left",
                        progress=(st.minute - task.start) / max(1, task.end - task.start),
                        colour=st.order_color.get(task.order, ACCENT))
        for t in sorted((t for t in al.tasks if t.agent == ag.id), key=lambda t: t.start) if al else []:
            info["rows"].append((st.order_color.get(t.order, ACCENT),
                                 f"{t.order} b{t.batch} · {STAGE_NAME.get(t.stage, t.stage)} at {t.station}",
                                 span(sc, t.start, t.end), ""))
    else:
        key = payload
        order = next(o for o in sc.orders if o.id == key[0])
        chain = tasks_by_batch(al)[key]
        legs = journeys(r)[key]
        leg = leg_at(legs, st.minute)
        task = next((t for t in chain if leg and t.id == leg.task), None)
        _, door0 = baseline(st)
        late = chain[-1].end - door0[key] if key in door0 else 0
        status = batch_status(leg, task.stage if task else "")
        info.update(kicker=f"Batch · order {key[0]} · {chain[0].meals} meals", title=f"{key[0]} b{key[1]}",
                    text=status[0].upper() + status[1:] + (f" · {late} min late vs plan 0" if late > 0
                                                           else ""),
                    rows_title="Plan for this batch", colour=st.order_color.get(key[0], ACCENT))
        for t in chain:
            before = where0.get((t.order, t.batch, t.stage))
            info["rows"].append((info["colour"], f"{STAGE_NAME.get(t.stage, t.stage)} at {t.station} · {t.agent}",
                                 span(sc, t.start, t.end),
                                 f"moved from {before}" if before and before != t.station else ""))
        lg = road_leg(legs)
        if lg:
            info["rows"].append((info["colour"], f"Road → {sc.roads.places[order.destination].label}"
                                                 + (f" ({lg.who})" if lg.who else ""), span(sc, lg.start, lg.end), ""))
    return info


def draw_pinned_card(st, s, r, info, y, max_bottom) -> int:
    inner = RIGHT.width - 2 * PAD
    text_lines = wrap(info["text"], 14, inner)
    head = PAD + 16 + 36 + 8 + 20 * len(text_lines) + (16 if info["progress"] is not None else 0)
    fail_h = 52 if info["fail"] else 0
    list_head = 34 if info["rows_title"] else 0
    room = max(1, int((max_bottom - y - head - list_head - fail_h - PAD) // ROW))
    rows = info["rows"]
    shown = rows if len(rows) <= room else rows[:room - 1]
    n_rows = len(shown) + (1 if len(shown) < len(rows) else 0) + (1 if not rows and info["empty"] else 0)
    box = pygame.Rect(RIGHT.x, y, RIGHT.width, head + list_head + ROW * n_rows + fail_h + PAD)
    card(s, box)
    x = box.x + PAD
    caps(s, info["kicker"], (x, box.y + PAD), 12)
    text(s, info["title"], (x, box.y + PAD + 14), 26, INK, mono=info["mono"], weight="semibold")
    close = pygame.Rect(box.right - PAD - 36, box.y + 14, 36, 36)
    draw_rect(s, SURFACE, close, border_radius=8)
    draw_rect(s, HAIRLINE, close, 1, border_radius=8)
    for a, b in (((-5, -5), (5, 5)), ((5, -5), (-5, 5))):
        draw_line(s, INK, (close.centerx + a[0], close.centery + a[1]), (close.centerx + b[0], close.centery + b[1]),
                  1.6)
    st.clicks.append((close, "unpin", None))

    ty = box.y + PAD + 16 + 36 + 8
    for ln in text_lines:
        text(s, ln, (x, ty), 14, SUBTLE)
        ty += 20
    if info["progress"] is not None:
        meter(s, pygame.Rect(x, ty + 6, inner, 6), info["progress"], info["colour"], back=DIVIDER)
        ty += 16
    if info["rows_title"]:
        caps(s, info["rows_title"], (x, ty + 14), 12)
        ty += list_head
        draw_line(s, DIVIDER, (x, ty), (box.right - PAD, ty))
    for colour, label, when, note in shown:
        cy = ty + ROW / 2
        disc(s, colour, (x + 4, cy), 4)
        time_r = text(s, when, (box.right - PAD, cy), 13, SUBTLE, anchor="midright", mono=True)
        note_w = text_width(note, 11) + 12 if note else 0
        lab = text(s, fit(label, 13, time_r.x - x - 30 - note_w), (x + 16, cy), 13, INK, anchor="midleft")
        if note:
            tag = pygame.Rect(lab.right + 8, cy - 9, note_w, 18)
            draw_rect(s, TAG_EDGE, tag, 1, border_radius=4)
            text(s, note, tag.center, 11, ERROR, anchor="center")
        ty += ROW
        draw_line(s, DIVIDER, (x, ty), (box.right - PAD, ty))
    if len(shown) < len(rows):
        text(s, f"+ {len(rows) - len(shown)} more", (x + 16, ty + ROW / 2), 13, MUTED, anchor="midleft")
        ty += ROW
    elif not rows and info["empty"]:
        text(s, info["empty"], (x, ty + ROW / 2), 13, MUTED, anchor="midleft")
        ty += ROW
    if info["fail"]:
        b = pygame.Rect(x, box.bottom - PAD - 40, inner, 40)
        if info["failed"]:
            button(st, s, b, "Out of service", "fail", kind="disabled")
        elif st.busy:
            button(st, s, b, "Re-solving …", "fail", kind="disabled")
        else:
            button(st, s, b, f"Mark {info['fail']} as failed at {clock(r.scenario, st.minute)}", "fail", info["fail"],
                   kind="danger")
    return box.bottom


# ---------------------------------------------------------------------------------------------
# Batches card (and its Stock view)
# ---------------------------------------------------------------------------------------------
def card_tabs(st, s, r, box, caption) -> int:
    """'Batches n' and 'Stock' as the card's title tabs; returns the y under the header."""
    x, y = box.x + PAD, box.y + PAD
    n = len(journeys(r))
    for value, label, count in (("batches", "Batches", str(n)), ("stock", "Stock", "")):
        on = st.kitchen_tab == value
        t = text(s, label, (x, y), 17, INK if on else MUTED, weight="semibold" if on else None)
        right = t.right
        if count:
            right = text(s, count, (t.right + 8, y + 4), 13, MUTED, mono=True).right
        if on:
            draw_line(s, INK, (t.x, t.bottom + 3), (right, t.bottom + 3), 2)
        st.clicks.append((pygame.Rect(t.x - 6, t.y - 6, right - t.x + 12, t.height + 14), "ktab", value))
        x = right + 22
    if text_width(caption, 13) < box.right - PAD - x:
        text(s, caption, (box.right - PAD, y + 4), 13, MUTED, anchor="topright")
    return y + 36


def draw_batch_card(st, s, r, box):
    card(s, box)
    y = card_tabs(st, s, r, box, "")
    sc, al = r.scenario, r.allocation
    x, right = box.x + PAD, box.right - PAD
    pip_w, door_w = 76, 58
    pip_x = right - door_w - 20 - pip_w
    for label, lx, anchor in (("Batch", x, "topleft"), ("Now", x + 72, "topleft"), ("Prep→Road", pip_x, "topleft"),
                              ("At door", right, "topright")):
        caps(s, label, (lx, y), 11, anchor=anchor)
    y += 20
    draw_line(s, DIVIDER, (x, y), (right, y))
    if not al:
        text(s, "No batches scheduled.", (x, y + 12), 13, MUTED)
        return
    _, door0 = baseline(st)
    items = list(journeys(r).items())
    fits = max(1, int((box.bottom - PAD + 6 - y) // BATCH_ROW))
    more = len(items) - fits + 1 if len(items) > fits else 0
    chains = tasks_by_batch(al)
    for key, legs in (items[:fits - 1] if more else items):
        chain = chains[key]
        leg = leg_at(legs, st.minute)
        task = next((t for t in chain if t.id == (leg.task if leg else "")), None)
        colour = st.order_color.get(key[0], ACCENT)
        row = pygame.Rect(x - 6, y, right - x + 12, BATCH_ROW)
        if st.pinned == ("batch", key):
            draw_rect(s, PAPER, row, border_radius=4)
        cy = row.centery
        disc(s, colour, (x + 4, cy), 4.5)
        text(s, f"{key[0]} b{key[1]}", (x + 14, cy), 13, INK, anchor="midleft", weight="semibold")  # sans: O is not 0
        status = batch_status(leg, task.stage if task else "")
        text(s, fit(status, 13, pip_x - x - 82), (x + 72, cy), 13, SUBTLE if leg else MUTED, anchor="midleft")
        by_stage = {t.stage: t for t in chain}
        road = road_leg(legs)
        spans = [(by_stage[g].start, by_stage[g].end) if g in by_stage else None for g in ("prep", "cook", "pack")]
        spans.append((road.start, road.end) if road else None)
        pw = (pip_w - 9) / 4
        for i, sp in enumerate(spans):
            pip = pygame.Rect(round(pip_x + i * (pw + 3)), cy - 4, round(pw), 8)
            if sp and st.minute >= sp[1]:
                draw_rect(s, colour, pip, border_radius=2)
            elif sp and st.minute >= sp[0]:
                draw_rect(s, SURFACE, pip, border_radius=2)
                draw_rect(s, colour, pip, 2, border_radius=2)
            else:
                draw_rect(s, DIVIDER, pip, border_radius=2)
        late = chain[-1].end - door0[key] if key in door0 else 0
        if late > 0:
            text(s, clock(sc, chain[-1].end), (right, cy - 7), 13, INK, anchor="midright", mono=True)
            text(s, f"+{late} min", (right, cy + 8), 11, ERROR, anchor="midright")
        else:
            text(s, clock(sc, chain[-1].end), (right, cy), 13, INK, anchor="midright", mono=True)
        draw_line(s, DIVIDER, (x, row.bottom), (right, row.bottom))
        st.hover.append((row, "batch", key))
        y += BATCH_ROW
    if more:
        text(s, f"+ {more} more batches (Overview page, key O)", (x + 14, y + BATCH_ROW / 2), 13, MUTED,
             anchor="midleft")


def draw_stock_card(st, s, r, box):
    card(s, box)
    y = card_tabs(st, s, r, box, "kg on each shelf, now / start")
    sc = r.scenario
    x, right = box.x + PAD, box.right - PAD
    now = stock_at(sc, r.withdrawals, st.minute)
    bar_x, bar_w = x + 150, right - x - 150 - 96
    for label, lx, anchor in (("Shelf", x, "topleft"), ("Ingredient", x + 50, "topleft"), ("kg left", right, "topright")):
        caps(s, label, (lx, y), 11, anchor=anchor)
    y += 20
    draw_line(s, DIVIDER, (x, y), (right, y))
    y += 4
    pitch = STOCK_ROW
    for shelf in stations_of(sc.kitchen, "storage"):
        top = y
        for i, (ing, start) in enumerate(shelf.stock.items()):
            if y + pitch > box.bottom - PAD + 6:
                return
            cy = y + pitch / 2
            if i == 0:
                text(s, shelf.id, (x, cy), 13, INK, anchor="midleft", mono=True, weight="semibold")
            left = now[shelf.id].get(ing, 0.0)
            text(s, ing, (x + 50, cy), 13, INK if left else ERROR, anchor="midleft")
            meter(s, pygame.Rect(bar_x, cy - 3, bar_w, 6), left / start if start else 0,
                  STATION_STYLE["storage"][1] if left > 0 else ERROR, back=DIVIDER)
            text(s, f"{left:.1f} / {start:g}", (right, cy), 13, INK if left else ERROR, anchor="midright", mono=True)
            y += pitch
        st.hover.append((pygame.Rect(x - 6, top, right - x + 12, y - top), "station", shelf.id))
        draw_line(s, DIVIDER, (x, y + 2), (right, y + 2))
        y += 6


# ---------------------------------------------------------------------------------------------
# tooltips
# ---------------------------------------------------------------------------------------------
def station_tooltip(st, r, sid):
    sc, al = r.scenario, r.allocation
    stn = sc.kitchen.stations[sid]
    lines = [("title", f"{STATION_NAME[stn.type]} {sid}"),
             ("sub", f"{ZONE_NAME[stn.type]}  ·  "
                     + ("FAILED - the plan does not use it" if stn.failed else "working")
                     + (f"  ·  takes batches up to {stn.max_batch} meals" if stn.max_batch < 10_000 else ""))]
    if stn.type == "storage":
        now = stock_at(sc, r.withdrawals, st.minute)[sid]
        lines.append(("head", "Stock now / start of day"))
        for ing, start in stn.stock.items():
            lines.append(("kv", ing, f"{now.get(ing, 0):.1f} kg of {start:g} kg"))
        upcoming = [w for w in r.withdrawals if w.shelf == sid and w.minute > st.minute][:4]
        if upcoming:
            lines.append(("head", "Next picks"))
            for w in upcoming:
                lines.append(("kv", clock(sc, w.minute), f"−{w.kg:g} kg {w.ingredient}  ({w.task})"))
    if not al:
        return lines
    task, queue = station_activity(al, sid, st.minute)
    lines.append(("rule",))
    if task:
        order = next(o for o in sc.orders if o.id == task.order)
        recipe = sc.recipes[task.recipe].name
        n_batches = len([b for b in tasks_by_batch(al) if b[0] == task.order])
        lines += [
            ("text", f"{STAGE_VERB.get(task.stage, task.stage)} — {recipe}", INK),
            ("kv", "Order", f"{task.order}, batch {task.batch} of {n_batches}, {task.meals} meals"),
            ("kv", "For", f"{sc.roads.places[order.destination].label} (due {clock(sc, order.deadline)})"),
            ("kv", "Agent", f"{task.agent} ({sc.agents[task.agent].kind})"),
            ("kv", "Time", f"{clock(sc, task.start)} – {clock(sc, task.end)}"),
            ("kv", "Steps", f"carry-in {task.carry_in} min, {task.stage} {task.work} min"
                            + (f", to door {task.carry_out} min" if task.carry_out else "")),
            ("kv", "Now", f"{phase_text(task, st.minute).lower()}, {max(0, task.end - st.minute):.0f} min left"),
            ("bar", (st.minute - task.start) / max(1, task.end - task.start), st.order_color.get(task.order, ACCENT)),
        ]
    elif stn.type != "storage":
        lines.append(("text", "Idle right now", MUTED))
    if queue:
        lines.append(("head", "Coming up"))
        for t in queue[:4]:
            lines.append(("kv", clock(sc, t.start), f"{t.order} b{t.batch} {t.stage} — {t.agent}"))
    return lines


def agent_tooltip(st, r, aid):
    sc, al = r.scenario, r.allocation
    ag = sc.agents[aid]
    shift = f"{clock(sc, ag.shift_start)}–{clock(sc, min(ag.shift_end, sc.horizon))}"
    lines = [("title", aid), ("sub", f"{ag.kind}  ·  skills: {', '.join(sorted(ag.skills))}  ·  shift {shift}")]
    if not al:
        return lines
    task, phase, nxt = agent_activity(al, aid, st.minute)
    lines.append(("rule",))
    if task is None:
        lines.append(("text", "Idle (waiting at home position)", MUTED))
    else:
        prev = previous_task(al, task)
        if phase == "carry-in":
            what = (f"carrying {task.order} batch {task.batch} from {prev.station} to {task.station}" if prev
                    else f"walking to shelf {task.station}")
        elif phase == "carry-out":
            what = f"carrying packed {task.order} batch {task.batch} to the dispatch door"
        else:
            what = f"{STAGE_VERB.get(task.stage, task.stage).lower()} {task.order} batch {task.batch} at {task.station}"
        lines += [("text", what[0].upper() + what[1:]),
                  ("kv", "Task", f"{task.id}  {clock(sc, task.start)}–{clock(sc, task.end)}"),
                  ("bar", (st.minute - task.start) / max(1, task.end - task.start),
                   st.order_color.get(task.order, ACCENT))]
    if nxt:
        lines.append(("kv", "Next", f"{nxt.order} b{nxt.batch} {nxt.stage} at {nxt.station}, {clock(sc, nxt.start)}"))
    busy = sum(t.end - t.start for t in al.tasks if t.agent == aid)
    lines.append(("kv", "Today", f"{len([t for t in al.tasks if t.agent == aid])} tasks, {busy} min busy"))
    return lines


def batch_tooltip(st, r, key):
    sc, al = r.scenario, r.allocation
    order = next(o for o in sc.orders if o.id == key[0])
    chain = tasks_by_batch(al)[key]
    recipe = sc.recipes[chain[0].recipe]
    diet = ", ".join(sorted(order.diet)) or "no restriction"
    lines = [("title", f"{key[0]} batch {key[1]} — {recipe.name}"),
             ("sub", f"{chain[0].meals} meals for {sc.roads.places[order.destination].label}  ·  diet: {diet}")]
    legs = journeys(r)[key]
    leg = leg_at(legs, st.minute)
    task = next((t for t in chain if leg and t.id == leg.task), None)
    lines += [("text", "Now: " + batch_status(leg, task.stage if task else ""), INK), ("head", "Journey")]
    names = {"collecting": "collected", "carried": "carried", "working": "", "waiting": "waits",
             "to_door": "to door", "at_door": "at door", "in_vehicle": "on", "delivered": "delivered"}
    for lg in legs:
        if lg.kind == "delivered":
            label = f"delivered to {sc.roads.places[lg.where].label}"
            when = clock(sc, lg.start)
        else:
            t = next((x for x in chain if x.id == lg.task), None)
            verb = STAGE_VERB.get(t.stage, "") if (lg.kind == "working" and t) else names[lg.kind]
            where = f"{lg.origin} → {lg.where}" if lg.origin else lg.where
            label = f"{verb} {where}" + (f" ({lg.who})" if lg.who and lg.kind != "in_vehicle" else "")
            when = f"{clock(sc, lg.start)}–{clock(sc, lg.end)}"
        colour = INK if lg.start <= st.minute else FAINT
        lines.append(("kv", when, label.strip(), colour))
    return lines
