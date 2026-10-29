from relief_kitchen.support.env.kitchen_grid import parse_kitchen
from relief_kitchen.algorithms.mapf import find_conflicts, prioritized_planning, verify_collision_free

# a two-lane aisle: agents swapping ends must not meet head-on or swap cells
AISLE = parse_kitchen([
    "#######",
    "#.....#",
    "#.....#",
    "#######",
])


def test_swap_in_aisle_is_collision_free():
    starts = {"a": (2, 1), "b": (2, 5)}
    goals = {"a": (2, 5), "b": (2, 1)}
    res = prioritized_planning(AISLE, starts, goals)
    assert res.ok
    assert verify_collision_free(res.paths)
    for a in starts:
        assert res.paths[a][0] == starts[a] and res.paths[a][-1] == goals[a]


def test_naive_paths_would_collide():
    straight = {"a": [(2, c) for c in range(1, 6)], "b": [(2, c) for c in range(5, 0, -1)]}
    assert find_conflicts(straight)


def test_agent_staying_put_is_avoided():
    grid = parse_kitchen(["#####", "#...#", "#...#", "#####"])
    starts = {"still": (1, 2), "mover": (1, 1)}
    goals = {"still": (1, 2), "mover": (1, 3)}
    res = prioritized_planning(grid, starts, goals)
    assert res.ok and verify_collision_free(res.paths)
    assert (1, 2) not in res.paths["mover"]  # walks round the agent instead of through it


def test_prioritized_planning_is_not_complete():
    # one-lane corridor with a side pocket: solvable, but the first agent plans as if alone and
    # blocks the second - the known weakness of prioritised planning (reported, not hidden)
    corridor = parse_kitchen(["#######", "###.###", "#.....#", "#######"])
    res = prioritized_planning(corridor, {"a": (2, 1), "b": (2, 5)}, {"a": (2, 5), "b": (2, 1)})
    assert not res.ok
