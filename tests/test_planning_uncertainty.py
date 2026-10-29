from relief_kitchen.planning.kitchen_plan import plan_for
from relief_kitchen.planning.scheduler import STEP_DURATION
from relief_kitchen.support.env.scenario import apply_event, load_scenario
from relief_kitchen.uncertainty.timeline import belief_timeline, observed_disruptions


def duration(step_id):
    return STEP_DURATION.get(step_id.split("_")[0], 10)


def test_pop_plan_follows_the_stages_and_the_schedule_respects_links():
    sc = load_scenario("configs/scenarios/base.yaml")
    trace = []
    plan, times = plan_for(sc, trace=trace)
    order = [s.operator.name for s in plan.sorted_steps() if s.id not in ("Start", "Finish")]
    assert order == [s.name for s in sc.stages]
    assert len(trace) == len(plan.links)
    for lk in plan.links:
        if "Start" not in (lk.producer, lk.consumer) and "Finish" not in (lk.producer, lk.consumer):
            assert times[lk.producer] + duration(lk.producer) <= times[lk.consumer]


def scenario_steps(path):
    sc = load_scenario(path)
    out = [sc]
    for ev in sc.events:
        sc, _ = apply_event(sc, ev)
        out.append(sc)
    return out


def test_belief_rises_only_for_the_disrupted_resource():
    steps = belief_timeline(scenario_steps("configs/scenarios/stove_failure.yaml"))
    assert steps[0].probs["stove_ok"] == 0.05 and not steps[0].updates
    assert steps[1].probs["stove_ok"] > 0.4 > steps[0].probs["stove_ok"]
    assert steps[2].probs["stove_ok"] > steps[1].probs["stove_ok"]
    assert steps[-1].probs["road_ok"] == 0.05 and steps[-1].probs["supply_ok"] == 0.05
    assert steps[1].contingencies and steps[1].mc > steps[0].mc


def test_road_and_stock_events_map_to_their_variables():
    road = scenario_steps("configs/scenarios/road_closure.yaml")
    rice = scenario_steps("configs/scenarios/rice_shortage.yaml")
    assert observed_disruptions(road[0], road[1]) == ["road_ok"]
    assert observed_disruptions(rice[0], rice[1]) == ["supply_ok"]


def test_monte_carlo_is_reproducible():
    scs = scenario_steps("configs/scenarios/road_closure.yaml")
    assert [s.mc for s in belief_timeline(scs)] == [s.mc for s in belief_timeline(scs)]
