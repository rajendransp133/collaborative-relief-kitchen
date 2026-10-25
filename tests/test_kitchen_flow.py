"""Hand-offs, stock withdrawals and batch journeys derived from the schedule."""

import pytest

from conftest import SCENARIOS
from relief_kitchen.env.kitchen_grid import WALK_SECONDS
from relief_kitchen.env.scenario import total_stock
from relief_kitchen.search_csp.astar import bfs_distances
from relief_kitchen.search_csp.kitchen_flow import batch_journey, previous_task, stock_at, tasks_by_batch
from relief_kitchen.search_csp.pipeline import run_timeline


@pytest.fixture(scope="module")
def result():
    return run_timeline(str(SCENARIOS / "base.yaml"))[0]


def test_every_step_budgets_its_carry_in(result):
    """A task starts after the previous step of its batch ends, and its carry-in budget covers the
    real walk between the two scheduled stations."""
    sc, al = result.scenario, result.allocation
    for t in al.tasks:
        prev = previous_task(al, t)
        if prev is None:
            continue
        assert prev.end <= t.start
        a, b = sc.kitchen.stations[prev.station].access, sc.kitchen.stations[t.station].access
        walk = bfs_distances(sc.kitchen, a)[b] * WALK_SECONDS / 60
        assert t.carry_in >= walk


def test_stock_goes_down_and_never_below_zero(result):
    sc = result.scenario
    start, end = stock_at(sc, [], 0), stock_at(sc, result.withdrawals, 10_000)
    for shelf in start:
        for ing, kg in end[shelf].items():
            assert -1e-9 <= kg <= start[shelf][ing]
    taken = sum(w.kg for w in result.withdrawals)
    used = sum(q * o.meals for o in result.accepted
               for q in sc.recipes[result.allocation.variants[o.id]].per_meal.values())
    assert taken == pytest.approx(used, abs=1e-6)
    assert sum(total_stock(sc).values()) - taken == pytest.approx(sum(sum(d.values()) for d in end.values()))


def test_batch_journeys_are_continuous(result):
    sc, al = result.scenario, result.allocation
    for key in tasks_by_batch(al):
        legs = batch_journey(sc, al, key, result.motion.arrivals)
        for a, b in zip(legs, legs[1:]):
            assert a.end == pytest.approx(b.start)  # no gaps: the batch is always somewhere
        for leg in legs:
            if leg.kind == "carried":
                assert leg.origin and leg.who  # picked up from a station by an agent
        delivery = next(d for d in al.deliveries if d.order == key[0])
        door_legs = [leg for leg in legs if leg.kind == "to_door"]
        assert door_legs and door_legs[-1].end <= delivery.depart


def test_agents_reach_their_station_before_work_starts(result):
    from relief_kitchen.search_csp.motion import agent_position

    sc, al = result.scenario, result.allocation
    assert result.motion.failures == 0 and result.motion.collisions == 0
    for t in al.tasks:
        p = agent_position(result.motion, t.agent, t.start + t.carry_in)
        assert (round(p[0]), round(p[1])) == sc.kitchen.stations[t.station].access
