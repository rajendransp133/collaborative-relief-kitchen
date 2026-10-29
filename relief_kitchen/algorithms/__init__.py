"""Part 2 - Module 1's algorithms: search and constraint satisfaction. This is the code to present.

Read in this order (each file is one lecture idea):

* `grid_search`: A*, BFS and space-time A* on the kitchen grid.
* `mapf`: prioritised planning for collision-free movement of several agents.
* `routing`: uniform-cost search / A* delivery routes on the road graph, rerouting after closures.
* `csp`: a generic CSP solver (node consistency, AC-3, MRV/degree, LCV, forward checking).
* `kitchen_csp`: the kitchen's task and resource allocation written as a CSP.
* `diagnosis`: why an order is infeasible (direct checks, then relaxing one category at a time).
* `planner`: everything end to end - accept orders greedily, diagnose rejects, replan after events.

Records, environment and other helpers live in `relief_kitchen.support`; the visualiser is
`relief_kitchen.viz`.
"""

from .planner import run_timeline, solve_scenario

__all__ = ["run_timeline", "solve_scenario"]
