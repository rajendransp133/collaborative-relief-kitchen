# Module 1: Search and Constraint Satisfaction

Module 1 decides who does what, on which station, by which path, and with which vehicle. It also
decides whether an order can be met at all, and if not, why. Everything in it is implemented from
scratch in `relief_kitchen/search_csp/`. The only dependencies are PyYAML for scenarios and
Pygame for the visualiser.

![Demand surge: four orders scheduled, one rejected for staff + time](img/demand_surge.png)

## 1. Graphs

| Graph | Where | Nodes / edges | Used by |
|---|---|---|---|
| Kitchen occupancy grid | `env/kitchen_grid.py` | Floor cells, 4-connected. Shelves (`S`), prep counters (`P`), stoves (`C`), steamer (`T`), packaging (`K`) and the dispatch door (`D`) are not walkable; each is worked from an *access cell*. Cells can be blocked at run time (spills). | A\*, BFS, MAPF |
| Road network | `env/road_network.py` | Depot, junctions, shelters and the hospital; weighted, undirected roads that can close | Dijkstra / A\* routing |
| Task-dependency DAG | `search_csp/task_graph.py` | Per order: batches of ≤ `batch_size` meals, each running `fetch → prep → cook → pack`, and every pack feeding one `dispatch` node | Precedence constraints, critical path, time diagnosis |

## 2. Search

| Problem | Algorithm | File |
|---|---|---|
| Single-agent path on the floor | A\* with the Manhattan heuristic | `astar.py` |
| Distances to every cell | Breadth-first search | `astar.py` |
| Collision-free movement of all agents | Space-time A\* (wait action, vertex and edge reservations) as the low level for **prioritised planning** and **Conflict-Based Search** (CBS, optimal sum of costs) | `mapf.py` |
| Turning the schedule into motion | At each slot boundary every agent's goal becomes the access cell of its current station (or its home cell). CBS moves everyone together, and the number of conflicts is checked afterwards. | `motion.py` |
| Nearest ingredient or equipment | BFS ranking of working shelves or stations. The pick list takes ingredients from the nearest shelves until the quantity is covered. | `locate.py` |
| Delivery routes | Dijkstra (uniform-cost search) and A\* with an admissible straight-line heuristic. Closed roads are skipped, and routes are recomputed after each closure. | `routing.py` |

## 3. The allocation CSP

Time is split into 10-minute slots over an 08:00–16:00 day.

**Variables**

| Variable | Domain |
|---|---|
| `O.variant` | Recipes (meal variants) |
| `O.b<k>.<stage>` (one per batch task) | `(agent, station, start slot)` triples |
| `O.dispatch` | `(vehicle, departure slot)` |

**Constraints.** Each constraint carries a category, which is what makes the diagnosis possible.

| Category | Constraint | Arity |
|---|---|---|
| dietary | Chosen variant satisfies the order's diet (`diabetic`, `soft`, `infant`, `nut_free`, `gluten_free`, …) | unary |
| ingredients | Total use of every ingredient by all chosen variants ≤ stock (global, checked on partial assignments) | n-ary |
| ingredients | The first-stage shelf actually stocks the variant's main ingredient (ingredient location) | binary |
| equipment | Station is working; station capacity ≥ batch size; station type suits the recipe (idli needs the steamer) | unary/binary |
| equipment | One batch per station at a time (workspace occupancy) | binary |
| staff | Agent has the stage's skill; task falls inside the agent's shift; one task per agent at a time | unary/binary |
| time | Arrival = departure + travel ≤ deadline | unary |
| transport | An open route exists; vehicle capacity ≥ meals; vehicle available; one trip per vehicle at a time | unary/binary |
| safety | Cooked food served within `max_hold` minutes; an allergen-free batch never follows an allergenic one on the same station without a cleaning gap | binary/ternary |
| collision | Stations that share an access cell are never worked at the same time | binary |
| priority | A higher-priority order leaves first on a shared vehicle | binary |
| (structure) | Task-DAG precedence, order release time, batch symmetry breaking, planning horizon. These are never relaxed. | binary/unary |

**Solver** (`csp.py`). The solver is generic and also solves map colouring (see the tests). It
works in four stages:

1. Node consistency, then AC-3 on binary constraints. Precedence uses a bounds-based `revise`,
   so deadlines propagate back through the whole DAG.
2. Backtracking search with **MRV and a degree tie-break**. **LCV** is used by default; the kitchen
   model supplies its own value order instead (earliest start, nearest station, least-loaded agent).
3. **Forward checking**, plus bounds propagation of precedence at every node (a light form of MAC).
4. An optional global `node_check`. The kitchen uses **energetic reasoning**: for each pool of
   skilled agents or same-type stations, and each time window, the work that must fall inside the
   window has to fit the pool's capacity. This is what proves "the cooks cannot finish in time"
   without enumerating schedules.

The kitchen model picks menus first, then vehicles and departures (latest first, so the kitchen
has room), then tasks. A bounded improvement pass then re-schedules as a list schedule and moves
departures as early as possible.

**Order acceptance** (`pipeline.py`). Orders are added in (priority, deadline) order. Each one
re-solves the joint CSP, warm-started from the previous solution. If an order makes the CSP
infeasible, it is rejected and diagnosed, and the remaining orders are still served.

## 4. Infeasibility diagnosis (`diagnosis.py`)

1. **Isolated or contention.** The order is first solved alone. If it fails alone, the cause is
   intrinsic. If it only fails next to the accepted orders, it is contention for shared
   resources.
2. **QuickXplain** (Junker, 2004) runs over the order's relaxable constraint *kinds*. The
   background is the structural constraints plus the accepted orders. It returns a **minimal
   conflicting set**; each kind maps to a category and to a sentence built from the scenario.
3. If a consistency check runs out of search budget, the module falls back to **correction
   sets**: the kinds whose relaxation alone makes the order schedulable. The report then marks
   the diagnosis "within search budget".
4. **Bottleneck analysis** (contention only) reports the saturated resource from the accepted
   schedule, for example *"staff who can 'cook' (Anu, Ravi) are 78% booked between 08:30 and
   10:57; O5 needs 90 more minutes of 65 free"*.
5. **Alternatives.** The largest meal count that still fits, and the earliest deadline at which
   all meals fit.

Output of `configs/scenarios/infeasible.yaml`:

```text
O2 (Stadium Shelter C, 80 meals): transport   - no open road from Kitchen to Stadium Shelter C (closed: R12, R13)
O3 (School Shelter A, 30 meals): equipment    - steamer: T1 failed
O6 (School Shelter A, 100 meals): time        - deadline 09:00, but the earliest arrival is 09:43 (70 min of kitchen work + 33 min drive)
                                               > alternative: deliver all 100 meals by 10:00
O4 (Temple Shelter B, 50 meals): ingredients + dietary - diet [diabetic, gluten_free] limits the menu to Millet khichdi; no storage shelf holds millet
O5 (School Shelter A, 60 meals): staff        - only Anu, Ravi can 'cook'; everyone who can 'cook' is off shift (Anu until 13:00, Ravi until 13:00)
```

![Infeasible orders with their cause categories](img/infeasible.png)

## 5. Scenarios

| File | README event | What happens |
|---|---|---|
| `base.yaml` | 1 | 200 meals: hospital (diabetic and soft), Shelter A, Shelter B (nut-free) |
| `demand_surge.yaml` | 2, 7 | +80 people at Shelter A, an urgent hospital order, then a stadium order that no longer fits (staff + time) |
| `stove_failure.yaml` | 3 | C2, then C1, fail. Batches shrink to the small stove and the steamer, and every order is still served |
| `rice_shortage.yaml` | 4 | Rice drops to 12 kg. The CSP substitutes millet khichdi or roti and still respects every diet |
| `road_closure.yaml` | 5 | R7, then R8, close. A\* reroutes, and ETAs and vehicle choices update |
| `dietary.yaml` | 6 | Allergen-free, diabetic and infant meals, with allergen separation on shared stations |
| `infeasible.yaml` | 8 | One rejected order per cause category |

Scenarios are YAML. `extends: base.yaml` deep-merges a file over another, and `events:` is a list
of disruptions (`close_road`, `fail_station`, `set_stock`, `demand_surge`, `add_order`,
`agent_off`, `block_cell`). Each event is applied cumulatively and the plan is re-solved.

![Road closure: the hospital route moves off R7](img/road_closure.png)

## 6. Running it

```bash
pip install -r requirements.txt

# text report: routes, CSP schedule, pick lists, MAPF stats, diagnoses (one block per timeline step)
python -m relief_kitchen.run --scenario configs/scenarios/infeasible.yaml

# visualiser
python -m relief_kitchen.viz --scenario configs/scenarios/road_closure.yaml
#   SPACE play/pause, LEFT/RIGHT time, UP/DOWN speed, TAB next timeline step, 1-9 load scenario,
#   R close a road (live re-solve), F fail a stove, C switch CBS/prioritised, D/click select order,
#   S screenshot, H help

# headless screenshot
python -m relief_kitchen.viz --scenario configs/scenarios/demand_surge.yaml --screenshot out.png --at 09:50

pytest -q
```

## 7. Interfaces for the other modules

* **M2 (planning)** can call `build_model(scenario, orders)` and use the task DAGs and
  `Allocation` (tasks with agent, station, start and end; deliveries with vehicle, route and
  times) as the initial resource schedule.
* **M3 (uncertainty)** can change stock, durations or travel times in the `Scenario` and re-solve.
  Diagnoses already separate the causes it would want to weigh.
* **M4 (MARL)** can mask actions with the CSP's unary constraints (skills, working stations,
  shifts) and use `solve_mapf` for collision-free motion.
* **M5 (GenAI)** reads `Diagnosis` (categories, sentences, alternatives) to explain to recipients
  why an order was delayed or modified.
