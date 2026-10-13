from dataclasses import replace

from relief_kitchen.env.kitchen_grid import parse_kitchen, walkable
from relief_kitchen.search_csp.astar import astar, bfs_distances, space_time_astar

GRID = parse_kitchen([
    "#######",
    "#.....#",
    "#.###.#",
    "#.....#",
    "#######",
])


def test_astar_shortest_path():
    path = astar(GRID, (1, 1), (3, 5))
    assert path[0] == (1, 1) and path[-1] == (3, 5)
    assert len(path) - 1 == 6  # Manhattan distance, the wall does not force a detour here
    for a, b in zip(path, path[1:]):
        assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
        assert walkable(GRID, b)


def test_astar_unreachable_and_blocked_cells():
    g = parse_kitchen(["#####", "#.#.#", "#####"])
    assert astar(g, (1, 1), (1, 3)) is None
    spill = replace(GRID, blocked={(1, 3)})  # same kitchen, one cell blocked
    path = astar(spill, (1, 1), (1, 5))
    assert (1, 3) not in path and len(path) - 1 == 8  # detour round the pillar


def test_bfs_distances_match_astar():
    dist = bfs_distances(GRID, (1, 1))
    for cell, d in dist.items():
        assert len(astar(GRID, (1, 1), cell)) - 1 == d


def test_space_time_astar_waits_for_reserved_cell():
    # (1,2) is occupied at t=1 and t=2, so the agent must wait or detour
    blocked = {((1, 2), 1), ((1, 2), 2)}
    path = space_time_astar(GRID, (1, 1), (1, 3), lambda c, t: (c, t) in blocked, lambda a, b, t: False)
    for t, c in enumerate(path):
        assert (c, t) not in blocked
    assert path[-1] == (1, 3)
