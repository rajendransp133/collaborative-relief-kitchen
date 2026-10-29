# Module 1: Search and Constraint Satisfaction

Module 1 decides who does what, on which station, by which path, and with which vehicle. It also
decides whether each order can be met, and if not, why. All algorithms are written from scratch. Every technique below is either a CS 188 topic or basic
graph theory.

The code is in three parts:

| Part | Folder | What |
|---|---|---|
| 1. Visualiser | `relief_kitchen/viz/` | Pygame pages, drawing helpers, input |
| 2. Algorithms (present these) | `relief_kitchen/algorithms/` | `grid_search`, `mapf`, `routing`, `csp`, `kitchen_csp`, `diagnosis`, `planner` |
| 3. Support | `relief_kitchen/support/` | Environment (`env/`), records, CSP-building and model helpers, motion, food flow, report, CLI |

![Kitchen page: agents carry batches between stations; hovering a stove shows what it is cooking](img/kitchen.png)

## 1. Graphs

| Graph | Nodes / edges | File |
|---|---|---|
| Kitchen grid | Floor cells, 4-connected. Shelves `S`, prep counters `P`, stoves `C`, steamer `T`, packing tables `K` and the door `D` are not walkable; each is used from its *access cell*. | `support/env/kitchen_grid.py` |
| Road network | Kitchen, junctions, shelters and the hospital; weighted by travel minutes; roads can close | `support/env/road_network.py` |
| Task-dependency DAG | Per order: batches of ≤ 50 meals, each running `fetch → prep → cook → pack`. Every pack feeds one `dispatch` node. | `support/task_graph.py` |

## 2. Search

| Problem | Algorithm | CS 188 topic | File |
|---|---|---|---|
| Path for one agent | A\* with the Manhattan heuristic | A\* search | `algorithms/grid_search.py` |
| Nearest ingredient shelf or working stove | BFS distances, then sort | BFS | `support/locate.py` |
| Delivery route; reroute after a closure | Uniform-cost search (Dijkstra) and A\* with a straight-line heuristic | UCS, A\*, admissible heuristics | `algorithms/routing.py` |
| Collision-free movement of all agents | Prioritised planning: agents planned one by one with A\* over (cell, time) states, avoiding cells and moves already reserved | A\* (state = cell + time) | `algorithms/mapf.py`, `support/motion.py` |
| Critical path of an order | Topological sort, then longest path in the DAG | Graph basics | `support/task_graph.py` |

Prioritised planning is fast but not complete: an unlucky agent order can block a solvable case
(`tests/test_mapf.py` shows one). In the kitchen scenarios it always succeeds, with 0 collisions.

## 3. Task and resource allocation as a CSP (`algorithms/kitchen_csp.py`)

Time is split into 5-minute slots. Variables for each order `O`:

| Variable | Domain |
|---|---|
| `O.variant` | Recipe (meal variant) |
| `O.b<k>.<stage>` | `(agent, station, start slot)` for each batch task |
| `O.dispatch` | `(vehicle, departure slot)` |

Packing agent, station and start into one value keeps every resource rule binary. For example:
"if two tasks use the same stove, their time intervals do not overlap".

| Category | Constraints |
|---|---|
| dietary | Chosen recipe satisfies the diet (`diabetic`, `soft`, `infant`, `nut_free`, `gluten_free`) |
| ingredients | Total ingredient use ≤ stock (global); the fetch shelf stocks the recipe's main ingredient |
| equipment | Station works; station capacity ≥ batch size; station type suits the recipe; one batch per station at a time (workspace occupancy) |
| staff | Agent has the skill; task inside the agent's shift; one task per agent at a time |
| time | Arrival ≤ deadline |
| transport | An open route exists; vehicle big enough; one trip per vehicle at a time |
| safety | Cooked food served within 150 minutes (maximum holding time) |
| collision | Two stations reached from the same floor cell are never used at once |
| priority | A more urgent order leaves first when sharing a vehicle |
| structure | DAG precedence, order release time, end of day. These are facts and are never relaxed. |

**Hand-offs (transfers).** Food never jumps between stations. Every task begins with a
*carry-in*: its agent walks to the station where the batch currently is (the previous step of the
same batch, or the shelf for a fetch), picks it up and carries it over. The last step (packing)
ends with a *carry-out* to the dispatch door. So a task's duration is

    carry-in + work (+ carry-out for packing)

The carry-in budget per stage is a worst-case walk taken from BFS distances on the floor grid
(20 s per step, plus 1 minute handling). For example, prep budgets
walk(agent home → any shelf) + walk(shelf → any prep counter). The agent and the station are
reserved for the whole task, so the existing "one task per agent" and "one batch per station"
constraints also cover carrying. The tests check that each budget covers the real walk between the
two scheduled stations.

**Solver** (`algorithms/csp.py`, generic; the tests also solve map colouring) works in three steps:

1. **Node consistency.** Unary constraints prune domains.
2. **AC-3** on binary constraints. Precedence has a cheap `revise`, so earliest-start and
   latest-start bounds flow through the DAG.
3. **Backtracking** with **MRV** and a **degree** tie-break, plus **forward checking**.
   - Generic problems use **LCV** for value ordering.
   - The kitchen uses a simpler heuristic instead: earliest start, then nearest station, then
     least-busy agent. LCV would be slow on hundreds of values per task.
   - Variables are taken in phases: menus, then tasks, then vehicles.

**Order acceptance** (`algorithms/planner.py`):
- Orders are added most urgent first.
- After each addition the CSP is re-solved, starting from the previous solution.
- If the CSP fails (or exceeds 3000 search nodes), the order is rejected and diagnosed, and the
  other orders are still served.

## 4. Infeasibility diagnosis (`algorithms/diagnosis.py`)

**Step 1: direct checks, one per category, without search.**

| Category | Check |
|---|---|
| dietary | Does any recipe satisfy the diet? |
| ingredients | Does a diet-safe recipe fit the stock left after already-accepted orders? |
| equipment | Does every stage have a working station of the right type and size? |
| staff | Is someone with each skill on shift after the order arrives? |
| transport | Is there an open road, and a vehicle big enough? |
| time | Is release + critical path + fastest drive ≤ deadline? |

**Step 2: relax one category at a time.** This runs only if every check passes but the CSP still
fails, which usually means the order competes with accepted orders. The module drops one
category's constraints for this order and re-solves. Every category whose removal lets the order
through is reported as a cause.

Output of `configs/scenarios/infeasible.yaml`:

```text
O2 (Stadium Shelter C, 80 meals): transport    - no open road from the kitchen to Stadium Shelter C (closed: R12, R13)
O3 (School Shelter A, 30 meals): equipment     - Idli sambar needs a steamer (T1 failed)
O6 (School Shelter A, 100 meals): time         - deadline 09:00, but the earliest possible arrival is 10:19 (106 min of kitchen work + 33 min drive)
O4 (Temple Shelter B, 50 meals): ingredients   - no diet-safe menu can be cooked: Millet khichdi (no shelf holds millet)
O5 (School Shelter A, 60 meals): staff         - everyone who can 'cook' is off shift after the order arrives at 13:30
```

![Overview page: infeasible orders with their cause categories](img/infeasible.png)

## 5. Scenarios (`configs/scenarios/`)

| File | What happens |
|---|---|
| `base.yaml` | 200 meals: hospital (diabetic and soft), Shelter A, Shelter B (nut-free) |
| `demand_surge.yaml` | +80 people at Shelter A, an urgent hospital order, then a stadium order that no longer fits |
| `stove_failure.yaml` | Stove C2 fails: work moves to the other stoves and every order is still served. C1 fails too: batches shrink to fit the small stove and steamer, and the order that no longer fits is rejected for equipment + time |
| `rice_shortage.yaml` | Rice drops to 12 kg. The CSP picks other diet-safe recipes |
| `road_closure.yaml` | R7, then R8, close. A\* reroutes and arrival times update |
| `dietary.yaml` | Allergen-free, diabetic and infant meals |
| `infeasible.yaml` | One rejected order per cause category |

![Delivery page: R7 closed, the hospital route moves to R14; hovering the hospital shows its orders](img/delivery.png)

## 6. The kitchen, step by step (`support/kitchen_flow.py`, `support/motion.py`)

These are pure functions over the schedule. They drive the visualiser and the report:

* **Stock over time.** At each fetch, the batch's ingredients (recipe × meals) are taken from the
  shelf the CSP chose, then from the nearest other shelves. `stock_at(minute)` gives the live
  kilograms on every shelf.
* **Batch journeys.** Each batch follows: collected at a shelf → waits → carried to a prep counter
  → washed and cut → carried to a stove → cooked → carried to packing → packed → carried to the
  door → on a vehicle → delivered. Each leg has a time, a place and an agent.
* **Motion with hand-offs.** Each agent visits the pickup cell, then its own station, then (for
  packing) the door. Prioritised planning moves all agents at each waypoint time. If an agent order
  fails, it retries with a few other orders ("random restarts"). Across all scenarios this gives 0
  collisions, and every agent is at its station when its work starts.

## 7. Visualiser: three pages

| Page | Shows |
|---|---|
| **Kitchen** | Floor plan tinted by zone. Agents walk on collision-free paths carrying food batches (coloured squares: I ingredients, P prepped, C cooked, K packed; a purple dot means allergen-free). Live stock per shelf, what every station is doing, and where every batch is. |
| **Delivery** | Road network with closures, A\* routes and vehicles moving. Deliveries table, vehicle usage and closed roads. |
| **Overview** | Small maps, the CSP schedule (light ends = carrying), and the orders with their diagnosis. |

**Hover tooltips.** Hover any station, agent, batch, place, road, vehicle or schedule bar for its
details. For example, a stove shows what it is cooking, for which order and agent, the time
window, carry-in and cook minutes, progress, and the next tasks. A shelf shows its stock now and
at the start, and its upcoming picks. A batch shows its whole journey.

**Station colours** follow the HACCP colour coding used in commercial kitchens:

| Colour | Used for |
|---|---|
| Brown | Stores |
| Green | Vegetable prep |
| Warm red / amber | Heat zones (stove, steamer) |
| Yellow | Cooked, ready-to-eat food (packing) |
| Purple | Allergen-free |

Sources: [StateFoodSafety](https://www.statefoodsafety.com/cutting-board-color-chart-guide),
[FoodDocs](https://www.fooddocs.com/post/chopping-board-colours),
[Tomkin](https://tomkin.com.au/blogs/news/haccp-colour-coded-kitchen).

![Overview page during the demand surge: the stadium order is rejected for time](img/demand_surge.png)

## 8. Code style

The code is functional, with OOP used only for data:

* **Records.** Entities and results (`Agent`, `Order`, `KitchenGrid`, `RoadNetwork`, `Scenario`,
  `CSP`, `Constraint`, `Allocation`, `Diagnosis`, ...) are `@dataclass` records. They have fields
  only: no methods and no inheritance.
* **Functions.** All behaviour is in module-level functions, for example `neighbors(grid, cell)`,
  `astar_route(net, a, b)`, `solve(csp)`, `decode(model, result)` and `apply_event(scenario, event)`.
  `apply_event` returns a *new* scenario and never changes its input.
* **Constraints are closures.** A `Constraint` record holds a `check(assignment)` function.
  Factories such as `precedence(...)`, `disjoint(...)` and `stock_limit(...)` build it, so there is
  no constraint class hierarchy.
* **Contained mutation.** For speed, the backtracking search edits a private copy of the domains
  and restores it from a trail. The CSP passed to `solve` is never modified. The Pygame window keeps
  one `ViewState` record that is changed only by `handle_event` and `tick`.

## 9. Running

```bash
pip install -r requirements.txt
python -m relief_kitchen.run --scenario configs/scenarios/infeasible.yaml   # text report
python -m relief_kitchen.viz --scenario configs/scenarios/road_closure.yaml  # Pygame visualiser
pytest -q
```

Visualiser keys:

| Key | Action |
|---|---|
| `K` / `V` / `O` (or click the tabs) | Kitchen / Delivery / Overview page |
| `SPACE` | Play / pause |
| `←` / `→`, or click the time bar | Move time |
| `↑` / `↓` | Change speed |
| `TAB` / `P` | Next / previous plan step |
| `1`–`9` | Load a scenario |
| `R` | Close a road and re-solve |
| `F` | Fail a stove and re-solve |
| `D` or click | Select an order |
| `S` | Screenshot |
| `H` | Help |

Headless screenshot of a page, with a tooltip:

```bash
python -m relief_kitchen.viz --scenario configs/scenarios/base.yaml --page kitchen --at 09:10 \
    --hover 289,434 --screenshot out.png
```
