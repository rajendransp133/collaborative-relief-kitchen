"""Kitchen page: the floor plan with agents, food batches, live stock and hover details."""

from __future__ import annotations

import pygame

from ..env.kitchen_grid import stations_of
from ..env.scenario import clock
from ..search_csp.kitchen_flow import (STAGE_VERB, agent_activity, batch_journey, batch_status, leg_at,
                                       previous_task, station_activity, stock_at, tasks_by_batch)
from ..search_csp.motion import agent_position, agent_trail
from .state import ViewState
from .theme import (ACCENT, ALLERGEN_FREE, ERROR, FAILED_STYLE, FAINT, GRID, HAIRLINE, INK, MUTED, STATION_NAME,
                    STATION_STYLE, SURFACE, WALL, ZONE_NAME, card, disc, fit, hline, mix, section, text)
from .widgets import CONTENT_BOTTOM, CONTENT_TOP, M, W, meter

TOKEN_LETTER = {"storage": "I", "prep": "P", "stove": "C", "steamer": "C", "packaging": "K", "dispatch": "K"}
TOKEN_MEANING = "I ingredients · P prepped · C cooked · K packed"


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


def allergen_free(order) -> bool:
    return any(d.endswith("_free") for d in order.diet)


# ---------------------------------------------------------------------------------------------
# the floor plan (also used small on the overview page)
# ---------------------------------------------------------------------------------------------
def draw_kitchen_map(st: ViewState, s, r, rect: pygame.Rect, detailed: bool = True):
    sc, grid = r.scenario, r.scenario.kitchen
    cell = min(rect.width // grid.width, rect.height // grid.height)
    ox = rect.x + (rect.width - cell * grid.width) // 2
    oy = rect.y
    to_px = lambda rc: (ox + rc[1] * cell + cell / 2, oy + rc[0] * cell + cell / 2)  # noqa: E731
    al = r.allocation
    now = st.minute

    # floor (tinted by zone), walls, blocked cells
    tints = zone_tints(grid)
    for rr in range(grid.height):
        for cc in range(grid.width):
            cr = pygame.Rect(ox + cc * cell, oy + rr * cell, cell, cell)
            if grid.rows[rr][cc] == "#":
                pygame.draw.rect(s, WALL, cr)
                continue
            zone = tints.get((rr, cc))
            pygame.draw.rect(s, mix(SURFACE, STATION_STYLE[zone][0], 0.45) if zone else SURFACE, cr)
            pygame.draw.rect(s, GRID, cr, 1)
            if (rr, cc) in grid.blocked:
                pygame.draw.line(s, ERROR, cr.topleft, cr.bottomright, 2)
    pygame.draw.rect(s, HAIRLINE, (ox, oy, cell * grid.width, cell * grid.height), 1)

    # stations
    stock_now = stock_at(sc, r.withdrawals, now)
    for stn in grid.stations.values():
        cr = pygame.Rect(ox + stn.cell[1] * cell + 3, oy + stn.cell[0] * cell + 3, cell - 6, cell - 6)
        fill, edge = FAILED_STYLE if stn.failed else STATION_STYLE[stn.type]
        task, _ = station_activity(al, stn.id, now) if al else (None, [])
        pygame.draw.rect(s, fill, cr, border_radius=5)
        pygame.draw.rect(s, edge, cr, 2, border_radius=5)
        id_size = 12 if detailed else 10
        text(s, stn.id, (cr.centerx, cr.y + (7 if detailed else cr.height / 2 - 6)), id_size,
             MUTED if stn.failed else INK, True, anchor="midtop")
        if stn.failed:
            pad = 7
            pygame.draw.line(s, ERROR, (cr.x + pad, cr.y + pad), (cr.right - pad, cr.bottom - pad), 2)
            pygame.draw.line(s, ERROR, (cr.right - pad, cr.y + pad), (cr.x + pad, cr.bottom - pad), 2)
        elif stn.type == "storage":
            start = sum(stn.stock.values()) or 1
            left = sum(stock_now.get(stn.id, {}).values())
            meter(s, pygame.Rect(cr.x + 5, cr.bottom - 8, cr.width - 10, 3), left / start, edge)
        elif task and detailed:
            text(s, f"{task.order}·b{task.batch}", (cr.centerx, cr.y + 23), 9, INK, anchor="midtop")
        if task and not stn.failed:
            frac = (now - task.start) / max(1, task.end - task.start)
            meter(s, pygame.Rect(cr.x + 5, cr.bottom - 8, cr.width - 10, 3), frac,
                  st.order_color.get(task.order, ACCENT))
        st.hover.append((cr, "station", stn.id))

    # agents (trail, body, initials)
    agent_px = {}
    if r.motion:
        agents = sorted(sc.agents.values(), key=lambda a: a.id)
        for ag in agents:
            for c in agent_trail(r.motion, ag.id, now, linger=1.0)[1:-1]:
                disc(s, FAINT, to_px(c), 1.5)
        for ag in agents:
            px, py = to_px(agent_position(r.motion, ag.id, now))
            agent_px[ag.id] = (px, py)
            task, phase, _ = agent_activity(al, ag.id, now) if al else (None, "idle", None)
            col = st.order_color.get(task.order, INK) if task else INK
            rad = cell * 0.32
            box = pygame.Rect(0, 0, rad * 2, rad * 2)
            box.center = (px, py)
            if ag.kind == "robot":
                pygame.draw.rect(s, col, box, border_radius=5)
            else:
                disc(s, col, (px, py), rad)
            text(s, ag.id[:2], (px, py), 10 if detailed else 9, SURFACE, True, anchor="center")
            st.hover.append((box.inflate(6, 6), "agent", ag.id))

    # food batches: on a station, carried by an agent, or waiting at the door
    if al:
        stacks: dict[str, int] = {}
        size = 14 if detailed else 9
        for key, legs in journeys(r).items():
            leg = leg_at(legs, now)
            if leg is None or leg.kind in ("in_vehicle", "delivered"):
                continue
            order = next(o for o in sc.orders if o.id == key[0])
            if leg.kind in ("carried", "to_door") and leg.who in agent_px:
                x, y = agent_px[leg.who]
                x, y = x + cell * 0.28, y - cell * 0.30
                letter = TOKEN_LETTER[grid.stations[leg.origin].type] if leg.origin else "I"
            else:
                stn = grid.stations[leg.where]
                n = stacks.get(stn.id, 0)
                stacks[stn.id] = n + 1
                x = ox + stn.cell[1] * cell + cell - 8 - n * (size - 3)
                y = oy + stn.cell[0] * cell + 6
                letter = TOKEN_LETTER[stn.type] if leg.kind != "collecting" else "I"
                if leg.kind == "working":  # not finished yet: still shows what came in
                    prev_type = {"prep": "storage", "stove": "prep", "steamer": "prep", "packaging": "stove"}
                    letter = TOKEN_LETTER.get(prev_type.get(stn.type, stn.type), "I")
            tok = pygame.Rect(0, 0, size, size)
            tok.center = (x, y)
            colour = st.order_color.get(key[0], ACCENT)
            pygame.draw.rect(s, colour, tok, border_radius=3)
            pygame.draw.rect(s, SURFACE, tok, 1, border_radius=3)
            if detailed:
                text(s, letter, tok.center, 9, SURFACE, True, anchor="center")
                if allergen_free(order):
                    disc(s, ALLERGEN_FREE, (tok.right - 1, tok.y + 1), 3)
            st.hover.append((tok.inflate(4, 4), "batch", key))
    return ox, oy, cell


# ---------------------------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------------------------
def draw_kitchen_page(st: ViewState, s, r):
    sc = r.scenario
    pad = 12
    left_card = pygame.Rect(M, CONTENT_TOP + 8, 892, CONTENT_BOTTOM - CONTENT_TOP - 16)
    card(s, left_card)
    left = left_card.inflate(-pad * 2, -pad * 2)
    left.topleft = (left_card.x + pad, left_card.y + pad)
    section(s, left.x, left.y, "Kitchen Floor", "hover a station, agent or food batch for details")
    map_rect = pygame.Rect(left.x, left.y + 24, left.width, 450)
    ox, oy, cell = draw_kitchen_map(st, s, r, map_rect, detailed=True)
    y = oy + cell * sc.kitchen.height + 10
    draw_legend(s, left.x, y)
    draw_station_strip(st, s, r, pygame.Rect(left.x, y + 26, left.width, left.bottom - y - 26))
    right_card = pygame.Rect(920, CONTENT_TOP + 8, W - M - 920, CONTENT_BOTTOM - CONTENT_TOP - 16)
    card(s, right_card)
    right = right_card.inflate(-pad * 2, -pad * 2)
    right.topleft = (right_card.x + pad, right_card.y + pad)
    y = draw_stock_panel(st, s, r, right)
    draw_batch_panel(st, s, r, pygame.Rect(right.x, y + 14, right.width, right.bottom - y - 14))


def draw_legend(s, x, y):
    for stype in ("storage", "prep", "stove", "steamer", "packaging", "dispatch"):
        fill, edge = STATION_STYLE[stype]
        sw = pygame.Rect(x, y + 3, 11, 11)
        pygame.draw.rect(s, fill, sw, border_radius=2)
        pygame.draw.rect(s, edge, sw, 2, border_radius=2)
        x = text(s, STATION_NAME[stype], (x + 16, y), 11, MUTED).right + 14
    disc(s, INK, (x + 5, y + 8), 5)
    x = text(s, "human", (x + 14, y), 11, MUTED).right + 10
    pygame.draw.rect(s, INK, (x, y + 3, 10, 10), border_radius=2)
    x = text(s, "robot", (x + 14, y), 11, MUTED).right + 14
    pygame.draw.rect(s, MUTED, (x, y + 2, 12, 12), border_radius=3)
    text(s, f"food batch: {TOKEN_MEANING}", (x + 17, y), 11, MUTED)


def draw_station_strip(st, s, r, rect):
    """What every station is doing right now, in two columns."""
    sc, al = r.scenario, r.allocation
    text(s, "STATIONS NOW", (rect.x, rect.y), 10, FAINT, True)
    stations = [x for x in sorted(sc.kitchen.stations.values(), key=lambda x: x.id) if x.type != "dispatch"]
    col_w, row_h = rect.width // 2, 17
    rows_per_col = (len(stations) + 1) // 2
    for i, stn in enumerate(stations):
        x = rect.x + (i // rows_per_col) * col_w
        y = rect.y + 18 + (i % rows_per_col) * row_h
        edge = STATION_STYLE[stn.type][1]
        pygame.draw.rect(s, edge, (x, y + 4, 8, 8), border_radius=2)
        text(s, stn.id, (x + 14, y), 11, INK, True)
        if stn.failed:
            msg, colour = "failed - not used", ERROR
        elif stn.type == "storage":
            left = stock_at(sc, r.withdrawals, st.minute)[stn.id]
            msg = ", ".join(f"{k} {v:.1f}" for k, v in left.items() if v > 0) or "empty"
            colour = MUTED
        else:
            task, queue = station_activity(al, stn.id, st.minute) if al else (None, [])
            if task:
                msg = f"{phase_text(task, st.minute)} {task.order} batch {task.batch} · {task.agent} · " \
                      f"{max(0, task.end - st.minute):.0f} min left"
                colour = INK
            else:
                msg = f"idle · next {queue[0].order} b{queue[0].batch} at {clock(sc, queue[0].start)}" if queue \
                    else "idle"
                colour = MUTED
        text(s, fit(msg, 11, col_w - 46), (x + 36, y), 11, colour)


def phase_text(task, minute) -> str:
    if minute < task.start + task.carry_in:
        return "Bringing in"
    if minute >= task.end - task.carry_out:
        return "Carrying to door"
    return STAGE_VERB.get(task.stage, task.stage)


def draw_stock_panel(st, s, r, rect) -> int:
    """Live stock per shelf; returns the y where the panel ends."""
    sc = r.scenario
    section(s, rect.x, rect.y, "Stock", "kg on each shelf, now / start of day")
    now = stock_at(sc, r.withdrawals, st.minute)
    y = rect.y + 26
    bar_w = 150
    for shelf in stations_of(sc.kitchen, "storage"):
        upcoming = [w for w in r.withdrawals if w.shelf == shelf.id and w.minute > st.minute]
        text(s, f"{shelf.id}", (rect.x, y), 12, INK, True)
        note = (f"next: −{upcoming[0].kg:g} kg {upcoming[0].ingredient} at {clock(sc, upcoming[0].minute)}"
                if upcoming else "no more picks planned")
        text(s, fit(note, 11, rect.width - 40), (rect.x + 30, y + 1), 11, FAINT)
        y += 18
        for ing, start in shelf.stock.items():
            left = now[shelf.id].get(ing, 0.0)
            text(s, ing, (rect.x + 12, y), 11, MUTED)
            colour = STATION_STYLE["storage"][1] if left > 0 else ERROR
            meter(s, pygame.Rect(rect.x + 96, y + 5, bar_w, 6), left / start if start else 0, colour)
            text(s, f"{left:5.1f} / {start:g}", (rect.x + 96 + bar_w + 10, y), 11, INK if left else ERROR)
            y += 16
        y += 6
    return y


def draw_batch_panel(st, s, r, rect):
    section(s, rect.x, rect.y, "Batches", "where every batch of food is now")
    al = r.allocation
    if not al:
        text(s, "No batches scheduled.", (rect.x, rect.y + 26), 12, MUTED)
        return
    y = rect.y + 26
    for label, x in (("BATCH", rect.x + 12), ("STATUS", rect.x + 80), ("AT DOOR", rect.right)):
        text(s, label, (x, y), 10, FAINT, True, anchor="topright" if label == "AT DOOR" else "topleft")
    y += 16
    hline(s, rect.x, rect.right, y)
    for key, legs in journeys(r).items():
        if y > rect.bottom - 16:
            break
        chain = tasks_by_batch(al)[key]
        leg = leg_at(legs, st.minute)
        task = next((t for t in chain if t.id == (leg.task if leg else "")), None)
        row = pygame.Rect(rect.x, y, rect.width, 18)
        disc(s, st.order_color.get(key[0], ACCENT), (rect.x + 4, y + 9), 4)
        text(s, f"{key[0]} b{key[1]}", (rect.x + 12, y + 2), 11, INK, True)
        status = batch_status(leg, task.stage if task else "")
        text(s, fit(status, 11, rect.width - 140), (rect.x + 80, y + 2), 11, INK if leg else FAINT)
        text(s, clock(r.scenario, chain[-1].end), (rect.right, y + 2), 11, MUTED, anchor="topright")
        st.hover.append((row, "batch", key))
        y += 18


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
             ("sub", f"{chain[0].meals} meals for {sc.roads.places[order.destination].label}  ·  diet: {diet}"
                     + ("  ·  allergen-free" if allergen_free(order) else ""))]
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
