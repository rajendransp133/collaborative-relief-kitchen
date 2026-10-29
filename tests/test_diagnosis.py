import pytest

from conftest import SCENARIOS
from relief_kitchen.support.env import load_scenario
from relief_kitchen.algorithms.planner import run_timeline, solve_scenario


@pytest.fixture(scope="module")
def result():
    return solve_scenario(load_scenario(SCENARIOS / "infeasible.yaml"))


@pytest.mark.parametrize("order,category", [
    ("O2", "transport"),    # every road to the stadium is closed
    ("O4", "ingredients"),  # millet is out of stock
    ("O5", "staff"),        # cooks are off shift
    ("O6", "time"),         # deadline before the earliest possible arrival
])
def test_infeasible_orders_name_the_cause(result, order, category):
    assert order in result.diagnoses
    assert category in result.diagnoses[order].categories


def test_feasible_order_still_served(result):
    assert [o.id for o in result.accepted] == ["O1"]


def test_isolated_causes_are_direct_checks(result):
    assert all(d.mode == "isolated" for d in result.diagnoses.values())


def test_contention_is_detected():
    # demand surge: the stadium order no longer fits next to the hospital and shelter orders
    *_, last = run_timeline(str(SCENARIOS / "demand_surge.yaml"))
    d = last.diagnoses["O5"]
    assert d.mode == "contention" and d.categories
