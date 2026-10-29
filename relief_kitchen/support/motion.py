"""Turn the CSP schedule into collision-free movement on the kitchen floor, hand-offs included.

Every task gives its agent a list of waypoints (grid cells with a time):

    fetch              walk to the shelf
    prep / cook / pack walk to the previous station of the same batch (pick the batch up),
                       then carry it to the task's own station
    pack (last stage)  when packing is done, carry the meals to the dispatch door
    task ends, nothing next   walk home (homes keep idle agents out of the way)

At each waypoint time, prioritised planning (space-time A*, see `algorithms/mapf.py`) moves all agents at
once without collisions. A two-step waypoint (pickup, then station) gives two segments in a row.
If two agents want the same cell, the later one waits on the nearest free cell beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..algorithms.grid_search import bfs_distances
from ..algorithms.mapf import find_conflicts, plan_with_restarts
from .env.entities import Cell
from .env.kitchen_grid import WALK_SECONDS, KitchenGrid
from .env.scenario import Scenario
from .kitchen_flow import door_station, previous_task
from .records import Allocation, MAPFResult


@dataclass
class Segment:
    start: float  # minute the joint move starts
    result: MAPFResult


@dataclass
class KitchenMotion:
    homes: dict[str, Cell]
    segments: list[Segment] = field(default_factory=list)
    collisions: int = 0
    failures: int = 0
    steps: int = 0  # total agent time steps (moves + waits)
    arrivals: dict[tuple[str, str], float] = field(default_factory=dict)  # (task, pickup|work|door) -> minute


def agent_position(motion: KitchenMotion, agent: str, minute: float) -> tuple[float, float]:
    """Interpolated (row, col) of an agent at a simulation minute (for animation)."""
    pos = motion.homes[agent]
    for seg in motion.segments:
        if seg.start > minute:
            break
        path = seg.result.paths.get(agent)
        if not path:
            continue
        k = (minute - seg.start) * 60.0 / WALK_SECONDS
        if k >= len(path) - 1:
            pos = path[-1]
            continue
        i, f = int(k), k - int(k)
        a, b = path[i], path[i + 1]
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
    return pos


def agent_trail(motion: KitchenMotion, agent: str, minute: float, linger: float = 1.0) -> list[Cell]:
    """Path of the agent's current move (shown while walking and `linger` minutes after)."""
    cur: list[Cell] = []
    for seg in motion.segments:
        if seg.start > minute:
            break
        path = seg.result.paths.get(agent)
        if path and len(set(path)) > 1 and minute <= seg.start + len(path) * WALK_SECONDS / 60 + linger:
            cur = path
    return cur


def agent_waypoints(sc: Scenario, alloc: Allocation) -> dict[float, dict[str, list[tuple[Cell, tuple]]]]:
    """time -> agent -> [(cell, (task id, purpose))] to visit in order at that time."""
    grid = sc.kitchen
    door = door_station(sc)
    homes = {a.id: a.home for a in sc.agents.values()}
    out: dict[float, dict[str, list[tuple[Cell, tuple]]]] = {}

    def add(t, agent, cell, tag=("", "home")):
        out.setdefault(t, {}).setdefault(agent, []).append((cell, tag))

    starts = {(t.agent, t.start) for t in alloc.tasks}
    for t in sorted(alloc.tasks, key=lambda t: t.start):
        prev = previous_task(alloc, t)
        if prev is not None:
            add(t.start, t.agent, grid.stations[prev.station].access, (t.id, "pickup"))  # pick the batch up
        add(t.start, t.agent, grid.stations[t.station].access, (t.id, "work"))  # bring it here and work
        if t.carry_out and door:
            add(t.end - t.carry_out, t.agent, grid.stations[door].access, (t.id, "door"))
        if (t.agent, t.end) not in starts:
            add(t.end, t.agent, homes[t.agent])
    return out


def _free_cell_near(grid: KitchenGrid, cell: Cell, taken: set[Cell]) -> Cell:
    dist = bfs_distances(grid, cell)
    return min((c for c in dist if c not in taken), key=lambda c: (dist[c], c), default=cell)


def plan_kitchen_motion(sc: Scenario, alloc: Allocation) -> KitchenMotion:
    grid = sc.kitchen
    homes = {a.id: a.home for a in sc.agents.values()}
    segments: list[Segment] = []
    collisions = failures = steps = 0
    arrivals: dict[tuple[str, str], float] = {}
    pos = dict(homes)
    clock = 0.0  # when the previous joint move finished
    for t, wanted in sorted(agent_waypoints(sc, alloc).items()):
        for r in range(max(len(cells) for cells in wanted.values())):
            # agents without a new waypoint this round keep their cell and claim it first
            movers = {a: cells[r][0] for a, cells in wanted.items() if r < len(cells)}
            tags = {a: cells[r][1] for a, cells in wanted.items() if r < len(cells)}
            goals = {a: p for a, p in pos.items() if a not in movers}
            taken = set(goals.values())
            # an agent heading to its own work cell beats one only picking a batch up there
            # (the picker can reach over from the next cell)
            for a, cell in sorted(movers.items(), key=lambda kv: r < len(wanted[kv[0]]) - 1):
                goals[a] = cell if cell not in taken else _free_cell_near(grid, cell, taken)
                taken.add(goals[a])
            start = max(t, clock)
            if goals == pos:
                arrivals.update({tags[a]: start for a in movers})
                continue
            order = sorted(goals, key=lambda a: a in movers)  # stay-put agents first (see mapf)
            res = plan_with_restarts(grid, pos, goals, order=order)
            if not res.ok:
                failures += 1
                pos = goals  # skip this move rather than stop the simulation
                continue
            collisions += len(find_conflicts(res.paths))  # sanity check, expected 0
            steps += sum(len(p) - 1 for p in res.paths.values())
            segments.append(Segment(start, res))
            for a in movers:
                arrivals[tags[a]] = start + _arrival_step(res.paths[a]) * WALK_SECONDS / 60
            clock = start + (max(len(p) for p in res.paths.values()) - 1) * WALK_SECONDS / 60
            pos = {a: p[-1] for a, p in res.paths.items()}
    return KitchenMotion(homes, segments, collisions, failures, steps, arrivals)


def _arrival_step(path: list[Cell]) -> int:
    """First time step from which the agent stays at its final cell."""
    k = len(path) - 1
    while k > 0 and path[k - 1] == path[-1]:
        k -= 1
    return k
