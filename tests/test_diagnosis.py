import pytest

from conftest import SCENARIOS
from relief_kitchen.env import load_scenario
from relief_kitchen.search_csp.pipeline import solve_scenario


@pytest.fixture(scope="module")
def result():
    return solve_scenario(load_scenario(SCENARIOS / "infeasible.yaml"))


@pytest.mark.parametrize("order,category", [
    ("O2", "transport"),    # every road to the stadium is closed
    ("O3", "equipment"),    # the steamer has failed
    ("O4", "ingredients"),  # millet is out of stock
    ("O5", "staff"),        # cooks are off shift
    ("O6", "time"),         # deadline before the earliest possible arrival
])
def test_infeasible_orders_name_the_cause(result, order, category):
    assert order in result.diagnoses
    assert category in result.diagnoses[order].categories


def test_feasible_order_still_served(result):
    assert [o.id for o in result.accepted] == ["O1"]


def test_time_diagnosis_offers_alternative(result):
    assert any("10:00" in a for a in result.diagnoses["O6"].alternatives)
