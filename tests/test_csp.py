from relief_kitchen.algorithms.csp import solve
from relief_kitchen.support.csp_build import constraint, violated
from relief_kitchen.support.records import CSP

AUSTRALIA = {"WA": ["NT", "SA"], "NT": ["SA", "Q"], "SA": ["Q", "NSW", "V"], "Q": ["NSW"], "NSW": ["V"]}


def make_csp(domains: dict, constraints: list) -> CSP:
    return CSP(domains, constraints, {})


def colouring(colours):
    regions = ["WA", "NT", "SA", "Q", "NSW", "V", "T"]
    return make_csp({r: list(colours) for r in regions},
                    [constraint((a, b), lambda x, y: x != y, "equipment", f"{a} != {b}")
                     for a, ns in AUSTRALIA.items() for b in ns])


def test_map_colouring_solved():
    csp = colouring(["red", "green", "blue"])
    res = solve(csp)
    assert res.ok
    assert violated(csp, res.solution) == []


def test_map_colouring_two_colours_infeasible():
    res = solve(colouring(["red", "green"]))
    assert res.status == "infeasible"


def test_unary_wipeout_is_reported():
    c = constraint(("x",), lambda v: v > 5, "time", "x > 5")
    res = solve(make_csp({"x": [1, 2, 3]}, [c]))
    assert res.status == "infeasible" and res.wipeout is c


def test_ac3_prunes_before_search():
    # x < y < z over {1, 2, 3}: AC-3 alone leaves exactly one value per variable
    csp = make_csp({v: [1, 2, 3] for v in "xyz"},
                   [constraint(("x", "y"), lambda a, b: a < b, "time", "x < y"),
                    constraint(("y", "z"), lambda a, b: a < b, "time", "y < z")])
    res = solve(csp)
    assert res.solution == {"x": 1, "y": 2, "z": 3}
    assert res.stats.backtracks == 0 and res.stats.pruned == 6


def test_solver_does_not_mutate_the_csp():
    csp = colouring(["red", "green", "blue"])
    before = {v: list(d) for v, d in csp.domains.items()}
    solve(csp)
    assert csp.domains == before
