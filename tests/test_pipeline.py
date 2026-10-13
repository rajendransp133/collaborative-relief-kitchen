from conftest import SCENARIOS
from relief_kitchen.search_csp.pipeline import run_timeline


def test_road_closure_reroutes_hospital():
    first, after_r7, _ = run_timeline(str(SCENARIOS / "road_closure.yaml"))
    assert "R7" in first.routes["hospital"].roads
    assert "R7" not in after_r7.routes["hospital"].roads
    assert len(after_r7.accepted) == 3


def test_stove_failure_moves_work_to_working_stoves():
    *_, last = run_timeline(str(SCENARIOS / "stove_failure.yaml"))
    assert len(last.accepted) == 3
    assert {t.station for t in last.allocation.tasks} & {"C1", "C2"} == set()


def test_rice_shortage_substitutes_safe_menu():
    *_, last = run_timeline(str(SCENARIOS / "rice_shortage.yaml"))
    rice = sum(last.scenario.recipes[v].per_meal.get("rice", 0) * o.meals
               for o in last.accepted for v in [last.allocation.variants[o.id]])
    assert rice <= last.scenario.stock()["rice"] + 1e-6
    for o in last.accepted:
        assert last.scenario.recipes[last.allocation.variants[o.id]].satisfies(o.diet)


def test_kitchen_motion_is_collision_free():
    for name in ("base.yaml", "dietary.yaml"):
        for r in run_timeline(str(SCENARIOS / name)):
            assert r.motion.collisions == 0 and r.motion.failures == 0
