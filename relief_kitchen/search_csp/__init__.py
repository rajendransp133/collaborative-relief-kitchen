"""Module 1 - search and constraint satisfaction.

* `astar`, `mapf`, `motion`: A*, BFS, space-time A* and prioritised planning for collision-free
  movement on the kitchen grid.
* `locate`: breadth-first search for the nearest ingredient shelf or working station.
* `routing`: Dijkstra / A* delivery routes on the road graph, rerouting after closures.
* `task_graph`: per-order task-dependency DAG.
* `csp`: generic CSP solver (node consistency, AC-3, MRV/degree, LCV, forward checking).
* `allocation`: the kitchen's task and resource allocation CSP.
* `diagnosis`: why an order is infeasible - per-category checks, then relaxing one constraint
  category at a time (ingredients, equipment, staff, time, transport).
* `pipeline`: everything end to end.
"""

from .pipeline import M1Result, run_timeline, solve_scenario

__all__ = ["M1Result", "run_timeline", "solve_scenario"]
