"""Plain-text report of a Module 1 result."""

from __future__ import annotations

from .env.road_network import closed_roads
from .env.scenario import clock, total_stock
from .search_csp.diagnosis import summary
from .search_csp.pipeline import M1Result


def _table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths))  # noqa: E731
    return "\n".join([line(header), line(["-" * w for w in widths]), *[line(r) for r in rows]])


def format_result(r: M1Result) -> str:
    sc = r.scenario
    out = [f"=== {sc.name}: {r.label} ===", ""]
    closed = closed_roads(sc.roads)
    failed = [s.id for s in sc.kitchen.stations.values() if s.failed]
    out.append(f"Closed roads: {', '.join(closed) or 'none'}   Failed stations: {', '.join(failed) or 'none'}")
    out.append("Stock (kg): " + ", ".join(f"{k} {v:g}" for k, v in sorted(total_stock(sc).items())))
    out.append("")

    out.append("Delivery routes (A* on the road graph)")
    rows = []
    for pid, route in r.routes.items():
        place = sc.roads.places[pid]
        if place.kind == "junction":
            continue
        rows.append([place.label, " > ".join(route.nodes) if route else "UNREACHABLE",
                     f"{route.minutes:.0f} min" if route else "-"])
    out.append(_table(rows, ["destination", "route", "time"]))
    out.append("")

    if r.allocation:
        al = r.allocation
        out.append("Accepted orders (CSP solution)")
        rows = []
        for d in al.deliveries:
            o = next(o for o in sc.orders if o.id == d.order)
            rows.append([o.id, sc.roads.places[o.destination].label, o.meals, ",".join(sorted(o.diet)) or "-",
                         sc.recipes[d.recipe].name, d.vehicle, clock(sc, d.depart), clock(sc, d.arrive),
                         clock(sc, o.deadline), "yes" if d.arrive <= o.deadline else "LATE"])
        out.append(_table(rows, ["order", "destination", "meals", "diet", "menu", "vehicle", "leaves", "arrives",
                                 "deadline", "on time"]))
        out.append("")
        out.append("Kitchen schedule")
        rows = [[t.id, t.agent, t.station, clock(sc, t.start), clock(sc, t.end), t.meals] for t in al.tasks]
        out.append(_table(rows, ["task", "agent", "station", "start", "end", "meals"]))
        out.append("")
        out.append("Ingredient pick list (nearest shelves first, BFS from the dispatch door)")
        for oid, plan in r.ingredient_plan.items():
            picks = "; ".join(f"{ing}: " + ", ".join(f"{kg:g} kg @ {sh}" for sh, kg, _ in p) for ing, p in plan.items())
            out.append(f"  {oid}: {picks}")
        out.append("Nearest working equipment: " + ", ".join(f"{k} {v}" for k, v in r.nearest.items()))
        out.append("")
        st = al.result.stats
        out.append(f"CSP (last solve): {st.nodes} nodes, {st.backtracks} backtracks, {st.pruned} values pruned, "
                   f"{st.seconds * 1000:.0f} ms")
    if r.motion:
        m = r.motion
        out.append(f"Kitchen motion (prioritised planning): {len(m.segments)} multi-agent moves, {m.steps} agent "
                   f"time-steps, collisions: {m.collisions}, failures: {m.failures}")
    out.append("")
    if r.diagnoses:
        out.append("INFEASIBLE ORDERS")
        for d in r.diagnoses.values():
            out.append(f"  {summary(d)}  [{d.mode}]")
            for c in d.causes:
                out.append(f"    - {c.category}: {c.detail}")
    else:
        out.append("All orders are feasible.")
    out.append("")
    out.append("Solver log: " + " | ".join(r.log))
    return "\n".join(out)
