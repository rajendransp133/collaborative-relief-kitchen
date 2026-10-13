from relief_kitchen.env.kitchen_grid import KitchenGrid
from relief_kitchen.search_csp.mapf import (conflict_based_search, find_conflicts, prioritized_planning,
                                             verify_collision_free)

# a corridor with one side pocket: two agents must swap ends, one has to step aside
CORRIDOR = KitchenGrid([
    "#######",
    "###.###",
    "#.....#",
    "#######",
])


def test_cbs_swap_in_corridor():
    starts = {"a": (2, 1), "b": (2, 5)}
    goals = {"a": (2, 5), "b": (2, 1)}
    res = conflict_based_search(CORRIDOR, starts, goals)
    assert res.ok and res.solver == "cbs"
    assert verify_collision_free(res.paths)
    for a in starts:
        assert res.paths[a][0] == starts[a] and res.paths[a][-1] == goals[a]


def test_naive_paths_would_collide():
    straight = {"a": [(2, c) for c in range(1, 6)], "b": [(2, c) for c in range(5, 0, -1)]}
    assert find_conflicts(straight)


def test_cbs_is_no_worse_than_prioritized():
    grid = KitchenGrid([
        "########",
        "#......#",
        "#.##.#.#",
        "#......#",
        "########",
    ])
    starts = {"a": (1, 1), "b": (3, 6), "c": (1, 6), "d": (3, 1)}
    goals = {"a": (3, 6), "b": (1, 1), "c": (3, 1), "d": (1, 6)}
    cbs = conflict_based_search(grid, starts, goals)
    pp = prioritized_planning(grid, starts, goals)
    assert cbs.ok and verify_collision_free(cbs.paths)
    if pp.ok:
        assert verify_collision_free(pp.paths)
        assert cbs.cost <= pp.cost
