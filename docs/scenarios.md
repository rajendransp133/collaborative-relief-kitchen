# Scenarios

Every scenario is a YAML file in `configs/scenarios/`. It describes one relief day: the kitchen,
staff, recipes, road network, vehicles, orders and a list of **events** (disruptions) that happen
during the day.

All three modules read the same file:

| Module | What it does with a scenario |
|---|---|
| **M1** search and CSP ([module1.md](module1.md)) | Solves the initial plan, then **re-solves after each event** (events accumulate). Each solve gives the accepted orders, the schedule, routes and agent motion, plus a diagnosis for every rejected order. |
| **M2** planning ([module2.md](module2.md)) | Builds the partial-order plan from the scenario's `stages`. |
| **M3** uncertainty ([module3.md](module3.md)) | Turns each event into an observation, updates the belief and recomputes the plan risk. |

All numbers below come from real runs of the current code.

## 1. The shared world (`base.yaml`)

Six scenarios `extends: base.yaml` and change only what they need. `infeasible.yaml` is a complete
file of its own.

**Day.** 08:00–16:00 in 5-minute slots. Batches hold at most 50 meals. Cooked food must be served
within **150 minutes**.

**Kitchen floor** (16 × 9 grid):

```text
################      S  storage shelf      P  prep counter
#S.S.S.....K.K.#      C  stove              K  packing table
#..............#      D  dispatch door      #  wall / pillar
#.P.P.....###..#      .  walkable floor
#..............D
#.C.C.C........#      Stations are not walkable: each is used from its access
#......#.......#      cell, the floor cell next to it.
#..............#
################
```

| Station | Details |
|---|---|
| S1 | rice 40 kg, lentils 15 kg |
| S2 | millet 12, wheat 20, vegetables 30 kg |
| S3 | vegetables 20, cashew 3, rice 10, lentils 6 kg |
| C1, C2 | stoves, up to 60 meals per batch |
| C3 | small stove, up to 30 meals |
| P1, P2 | prep counters |
| K1, K2 | packing tables |
| D1 | dispatch door |

**Staff.**

| Agent | Kind | Skills |
|---|---|---|
| Anu | human | cook, prep |
| Ravi | human | cook, prep, pack |
| Meena | human | prep, pack, carry |
| R1 | robot | carry, pack |
| R2 | robot | carry |

**Stages** (per batch): fetch 10 min (carry, at storage) → prep 20 (prep counter) → cook 30
(stove) → pack 10 (packing table).

**Recipes.**

| Recipe | Tags | Allergens | Main ingredients per meal |
|---|---|---|---|
| Rice and dal | vegetarian | | rice 0.15, lentils 0.05, veg 0.05 kg |
| Vegetable pulao | vegetarian | nuts | rice 0.15, veg 0.08, cashew 0.01 |
| Millet khichdi | vegetarian, diabetic, soft | | millet 0.12, lentils 0.05, veg 0.05 |
| Roti and sabzi | vegetarian, diabetic | gluten | wheat 0.12, veg 0.10 |
| Idli sambar | vegetarian, soft, infant | | rice 0.10, lentils 0.05 |

**Roads.**

- Places: the kitchen (depot), junctions J1–J5, District Hospital (40 people), School Shelter A
  (100), Temple Shelter B (60) and Stadium Shelter C (80).
- 13 roads, R1–R13, each weighted in minutes.
- Base routes: hospital `depot > J1 > J4 > hospital` (47 min), Shelter A `depot > J1 > J3 >
  shelter_a` (49 min), Shelter B `depot > J2 > J3 > J5 > shelter_b` (53 min), Stadium `depot > J2 >
  shelter_c` (34 min).

**Vehicles.**

| Vehicle | Capacity | Speed |
|---|---|---|
| V1 | 120 meals | ×1.0 |
| V2 | 250 meals | ×0.8 |
| V3 | 40 meals | ×1.5 |

**Base orders** (200 meals):

| Order | Destination | Meals | Diet | Deadline | Priority |
|---|---|---|---|---|---|
| O1 | District Hospital | 40 | diabetic, soft | 11:30 | 3 (most urgent) |
| O2 | School Shelter A | 100 | none | 12:30 | 2 |
| O3 | Temple Shelter B | 60 | nut-free | 13:00 | 1 |

## 2. Summary

| Key | Scenario | Events | Modules shown | Outcome |
|---|---|---|---|---|
| 1 | `base` | none | M1, M2 | All 3 orders served on time |
| 2 | `demand_surge` | +80 people, urgent hospital order, stadium order | M1 (priority, diagnosis) | Hospital orders first; O2 (180 meals) and O5 rejected |
| 3 | `dietary` | none (5 diet-specific orders) | M1 (dietary constraints) | All 5 served with diet-safe menus |
| 4 | `infeasible` | none (broken from the start) | M1 (diagnosis) | O1 served; 4 orders rejected, one per cause |
| 5 | `rice_shortage` | rice on S1, then S3, cut to 6 kg | M1 (substitution), M3 (stock check) | All served; menus switch to millet and roti |
| 6 | `road_closure` | R7, then R8, close | M1 (A\* reroute), M3 (road belief) | All served; two routes change |
| 7 | `stove_failure` | C2, then C1, fail | M1 (re-allocation), M3 (stove belief) | C2 out: all served. C1 out too: O2 rejected |

The key is the number to press in the visualiser to load that scenario. They are in alphabetical
order. The M2 plan is the same for every scenario (see [module2.md](module2.md) §7).

## 3. `base.yaml`: base relief day

**Story.** The first order of the day: 200 meals for three destinations (README event 1). Nothing
goes wrong.

**M1.** Every order is accepted. The CSP solves in 26 search nodes with 0 backtracks, and motion
planning gives 0 collisions.

| Order | Menu | Vehicle | Leaves | Arrives | Deadline |
|---|---|---|---|---|---|
| O1 | Millet khichdi (the only diabetic + soft recipe) | V3 | 09:55 | 10:26 | 11:30 |
| O2 | Rice and dal | V1 | 10:35 | 11:24 | 12:30 |
| O3 | Rice and dal (nut-free, so no pulao) | V2 | 11:15 | 12:21 | 13:00 |

- O2 and O3 are split into two batches each: 2 × 50 and 2 × 30.
- Cooking uses C1, C2 and C3.
- The hospital (priority 3) leaves first.

**M2.** fetch → prep → cook → pack, makespan 70 min. **M3.** The prior: every belief is 0.05,
analytical risk 0.115.

**Show in class:** the Kitchen page (`K`) at about 09:10. Hover a stove to see what it cooks.
Then show the Planning page (`L`).

```bash
python -m relief_kitchen.viz --scenario configs/scenarios/base.yaml
```

## 4. `demand_surge.yaml`: demand surge

**Story.** README events 2 and 7. Demand grows and an urgent medical order arrives. The more urgent
work must go first, and whatever no longer fits is rejected *with a reason*.

| Step | Event | M1 result |
|---|---|---|
| 0 | none | Same as base: all 3 served |
| 1 | Shelter A reports 80 more people (O2: 100 → 180 meals) | O1 and O3 served. O3 moves to V1 and arrives 11:28. **O2 rejected (contention)**: stoves, counters and packing tables are booked by higher-priority orders; every vehicle big enough is busy; and the food would wait more than 150 min between cooking and serving. |
| 2 | Urgent order O4: 60 soft meals for the hospital by 11:15 (priority 3) | **O4 accepted first**: millet khichdi on V1, arrives 11:02. O1 now arrives 11:06 and O3 12:51. O2 is still rejected, now for **time**: its 12:30 deadline is too tight once higher-priority orders are scheduled. |
| 3 | Stadium Shelter C asks for 120 meals by 11:30 | O5 rejected for **time**, for the same reason. O4, O1 and O3 are still served. |

"Contention" means the order could be served on its own, but not together with the
higher-priority orders already accepted. The diagnosis finds the cause by relaxing one constraint
category at a time ([module1.md](module1.md) §4).

**M3.** The belief stays at the prior: demand is not one of M3's variables.

**Show in class:** the Overview page (`O`) at step 3. The orders list shows O2 and O5 rejected
for time.

## 5. `dietary.yaml`: dietary constraints

**Story.** README event 6. The orders are replaced by five diet-specific ones. The dietary
constraint only lets a recipe through if it satisfies every tag, so an unsafe menu can never be
chosen.

| Order | Destination | Meals | Diet | Menu chosen | Why | Arrives / due |
|---|---|---|---|---|---|---|
| O1 | Hospital | 40 | diabetic, soft | Millet khichdi | the only diabetic and soft recipe | 10:26 / 11:30 |
| O5 | Stadium C | 30 | infant | Idli sambar | the only infant recipe | 11:38 / 12:00 |
| O3 | Shelter A | 40 | diabetic | Millet khichdi | roti would also be allowed; the CSP picks khichdi | 11:43 / 12:30 |
| O2 | Shelter A | 60 | gluten-free, nut-free | Rice and dal | rules out roti (gluten) and pulao (nuts) | 12:24 / 12:30 |
| O4 | Shelter B | 50 | vegetarian | Rice and dal | | 13:36 / 14:00 |

All five are served. O2 arrives six minutes before its deadline.

**Show in class:** the Overview page: each order's menu and the diet it satisfies.

## 6. `infeasible.yaml`: one rejection per cause

**Story.** A bad afternoon, built so that each problem order fails for a different reason:

- Roads R12 and R13 (the only ways into the stadium) are closed.
- Millet is at 0 kg.
- The cooks Anu and Ravi leave at 13:00.
- One deadline is impossible.

All of this is in the initial state; there are no events. An **equipment** rejection is shown live
instead: `stove_failure.yaml` step 2, or **Mark as failed** on the Kitchen page.

| Order | Request | Result | Cause found by the diagnosis |
|---|---|---|---|
| O1 | 40 diabetic, hospital, by 11:00 | **served** (Roti and sabzi, arrives 10:26) | none |
| O2 | 80 meals, Stadium C | rejected | **transport**: no open road to Stadium Shelter C (closed: R12, R13) |
| O4 | 50 diabetic + gluten-free, Shelter B | rejected | **ingredients**: only millet khichdi fits, and no shelf holds millet (6.0 kg needed, 0 left) |
| O5 | 60 meals, released 13:30 | rejected | **staff**: everyone who can cook is off shift after 13:30 (Anu and Ravi until 13:00) |
| O6 | 100 meals, Shelter A, by 09:00 | rejected | **time**: earliest arrival is 10:19 (106 min of kitchen work + 33 min drive) |

All four rejections are "isolated": each order is impossible even on its own. The direct checks in
`algorithms/diagnosis.py` find each cause without any search.

**M3.** Stove and road stay at the prior, because the closed roads are given at the start and are
not observed as events ([module3.md](module3.md) §10). Supply is **1.0**: the stock check sees that
M1 rejects O4 for lack of millet. The analytical risk is 0.816 and the supply contingency appears.

**Show in class:** the Overview page, which shows each rejected order with its cause category.

## 7. `rice_shortage.yaml`: rice shortage

**Story.** README event 4. A stock check finds far less rice: 50 kg drops to 16 kg, then to 12 kg.

| Step | Event | M1 result |
|---|---|---|
| 0 | none | O1 millet khichdi; O2 and O3 rice and dal |
| 1 | S1 holds only 6 kg rice (total 16 kg) | All served. **O3 switches to millet khichdi** (still nut-free), so the remaining rice goes to O2. |
| 2 | S3 holds only 6 kg rice (total 12 kg) | All served. **O2 switches to roti and sabzi** (wheat, on V2, arrives 11:46 / due 12:30). O3 goes back to rice and dal (on V1, arrives 12:18). |

The stock constraint (total use ≤ stock) and the "the shelf holds the main ingredient" constraint
force these substitutions. The dietary constraint keeps them safe: O1 still gets the diabetic and
soft recipe.

**M3.** A stock count is a fact, not a noisy report, so it does not go through Bayes. M3 checks it
against M1 instead: both times M1 still cooks every order (only 9 kg of the 12 kg is needed), so
P(supply) stays at 0.05, the risk stays at 0.115 and no contingency appears. The Uncertainty page
shows each stock count and says why the belief did not move.

**Show in class:** the Overview page, where a swapped menu is highlighted ("Millet khichdi, was
Rice and dal"); the Kitchen page's Stock tab; and the Uncertainty page (`U`) at step 2.

## 8. `road_closure.yaml`: road closure

**Story.** README event 5. A landslide closes R7, the last stretch to the hospital. Then flooding
closes R8 into Shelter A. The scenario adds a longer road, R14 (J3 → hospital, 30 min).

| Step | Event | M1 result |
|---|---|---|
| 0 | none | Base routes |
| 1 | R7 closes | The hospital route changes to `depot > J1 > J3 > hospital` over R14 (57 min instead of 47). O1 arrives **10:33** instead of 10:26, still well before 11:30. |
| 2 | R8 closes | The Shelter A route changes to `depot > J1 > J4 > shelter_a`. O2 arrives **11:28** instead of 11:24. |

A\* on the road graph recomputes every route over the open roads, and the arrival estimates update.
The kitchen schedule doesn't change.

**M3.** P(road) goes 0.05 → 0.486 → 0.945, and the analytical risk goes 0.115 → 0.395 → 0.689. The
road weight is 0.7, lower than the stove's 0.9, so this rise is smaller than in the stove scenario.

**Show in class:** the Delivery page (`V`). The closed road is dashed, and the rerouted hospital
line is visible. Press `R` to close another road live.

## 9. `stove_failure.yaml`: stove failure

**Story.** README event 3. Stove C2 fails mid-morning, then C1 fails as well.

| Step | Event | M1 result |
|---|---|---|
| 0 | none | Cooking spread over C1, C2 and C3 |
| 1 | C2 fails | **All orders still served.** C1 now cooks O1 and both O2 batches. O3's two 30-meal batches go to the small stove C3. O2 leaves later and arrives 12:04 (deadline 12:30). |
| 2 | C1 fails too | Only C3 is left (30 meals max). O1 is split into **2 × 20** and O3 into 2 × 30, all on C3. O1 now arrives 11:06 and O3 12:48. **O2 is rejected for equipment (isolated)**: even on its own, its 100 meals cannot be cooked on the one small stove left. Relaxing the equipment constraints is what lets it through. |

**M3.** P(stove) goes 0.05 → 0.486 → 0.945, and the analytical risk goes 0.115 → 0.479 → 0.861,
the biggest rise of any scenario. The stove contingencies ("split batch across the remaining
working stoves") match what M1 tries.

**Show in class:** the Kitchen page for the moved batches, then the Uncertainty page while
pressing `Tab`, to show the worked Bayes formula at each step.

```bash
python -m relief_kitchen.viz --scenario configs/scenarios/stove_failure.yaml
python -m relief_kitchen.run --module m3 --scenario configs/scenarios/stove_failure.yaml
```

## 10. Writing a new scenario

```yaml
extends: base.yaml          # deep-merge over base; lists (orders, events, stages) are replaced
name: My scenario
description: One or two sentences.
events:
  - {kind: fail_station, station: C3, label: "Stove C3 fails"}
```

Event kinds (`support/env/scenario.py`, `apply_event`):

| Kind | Parameters | M3 observation |
|---|---|---|
| `close_road` / `open_road` | `road` | closing → `road_ok` |
| `fail_station` / `repair_station` | `station` | failing a stove → `stove_ok` |
| `set_stock` | `shelf`, `ingredient`, `kg` | none by Bayes; `supply_ok` = 1.0 only if M1 then rejects an order for ingredients |
| `demand_surge` | `order`, `extra` | none |
| `add_order` | `order: {id, destination, meals, diet, deadline, priority, release}` | none |
| `agent_off` | `agent` | none |
| `block_cell` | `cell` (a floor cell, as in `home:`) | none |

`label` is the text shown on the PLAN step bar. Put the file in `configs/scenarios/`. It then
appears under the number keys in the visualiser, which lists the files alphabetically.
