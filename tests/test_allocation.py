import pytest

from conftest import SCENARIOS
from relief_kitchen.env import load_scenario
from relief_kitchen.search_csp.allocation import build_model


@pytest.fixture(scope="module")
def solved():
    sc = load_scenario(SCENARIOS / "base.yaml")
    m = build_model(sc, sc.orders)
    res = m.solve()
    assert res.ok
    return sc, m, res, m.decode(res)


def test_solution_satisfies_every_constraint(solved):
    sc, m, res, _ = solved
    assert m.csp.violated(res.solution) == []


def test_diet_stock_and_deadlines(solved):
    sc, m, res, al = solved
    use = {}
    for o in sc.orders:
        r = sc.recipes[al.variants[o.id]]
        assert r.satisfies(o.diet)
        for ing, q in r.per_meal.items():
            use[ing] = use.get(ing, 0) + q * o.meals
    stock = sc.stock()
    assert all(kg <= stock[ing] + 1e-6 for ing, kg in use.items())
    for d in al.deliveries:
        o = next(o for o in sc.orders if o.id == d.order)
        assert d.arrive <= o.deadline
        assert sc.vehicles[d.vehicle].capacity >= o.meals


def test_no_double_booking_and_skills(solved):
    sc, m, res, al = solved
    for i, a in enumerate(al.tasks):
        assert sc.agents[a.agent].available(a.start, a.end)
        stage = next(s for s in sc.stages if s.name == a.stage)
        assert stage.skill in sc.agents[a.agent].skills
        for b in al.tasks[i + 1:]:
            overlap = a.start < b.end and b.start < a.end
            if overlap:
                assert a.agent != b.agent
                assert a.station != b.station


def test_task_dependencies_respected(solved):
    sc, m, res, al = solved
    by_id = {t.id: t for t in al.tasks}
    for o in sc.orders:
        for node in m.graphs[o.id].tasks():
            for p in node.preds:
                assert by_id[p].end <= by_id[node.id].start


def test_failed_station_never_used():
    sc = load_scenario(SCENARIOS / "base.yaml")
    sc.kitchen.stations["C2"].failed = True
    m = build_model(sc, sc.orders)
    res = m.solve()
    assert res.ok
    assert all(t.station != "C2" for t in m.decode(res).tasks)
