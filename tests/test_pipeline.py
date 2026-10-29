from conftest import SCENARIOS
from relief_kitchen.support.env.entities import recipe_satisfies
from relief_kitchen.support.env.scenario import total_stock
from relief_kitchen.algorithms.planner import run_timeline


def test_road_closure_reroutes_hospital():
    first, after_r7, _ = run_timeline(str(SCENARIOS / "road_closure.yaml"))
    assert "R7" in first.routes["hospital"].roads
    assert "R7" not in after_r7.routes["hospital"].roads
    assert len(after_r7.accepted) == 3


def test_stove_failure_moves_work_to_working_stoves():
    _, after_c2, after_c1 = run_timeline(str(SCENARIOS / "stove_failure.yaml"))
    assert len(after_c2.accepted) == 3  # one stove down: work moves to the others
    assert all(t.station != "C2" for t in after_c2.allocation.tasks)
    assert {t.station for t in after_c1.allocation.tasks} & {"C1", "C2"} == set()
    for d in after_c1.diagnoses.values():  # two stoves down: anything dropped is blamed on equipment
        assert "equipment" in d.categories


def test_rice_shortage_substitutes_safe_menu():
    *_, last = run_timeline(str(SCENARIOS / "rice_shortage.yaml"))
    rice = sum(last.scenario.recipes[v].per_meal.get("rice", 0) * o.meals
               for o in last.accepted for v in [last.allocation.variants[o.id]])
    assert rice <= total_stock(last.scenario)["rice"] + 1e-6
    for o in last.accepted:
        assert recipe_satisfies(last.scenario.recipes[last.allocation.variants[o.id]], o.diet)


def test_kitchen_motion_is_collision_free():
    for name in ("base.yaml", "dietary.yaml"):
        for r in run_timeline(str(SCENARIOS / name)):
            assert r.motion.collisions == 0 and r.motion.failures == 0


def test_events_do_not_modify_the_original_scenario():
    from relief_kitchen.support.env import apply_event, load_scenario

    sc = load_scenario(SCENARIOS / "road_closure.yaml")
    new, _ = apply_event(sc, sc.events[0])
    assert sc.roads.roads["R7"].open and not new.roads.roads["R7"].open
