from relief_kitchen.search_csp.csp import CSP, FnConstraint, solve

AUSTRALIA = {"WA": ["NT", "SA"], "NT": ["SA", "Q"], "SA": ["Q", "NSW", "V"], "Q": ["NSW"], "NSW": ["V"]}


def colouring(colours):
    csp = CSP()
    for r in ["WA", "NT", "SA", "Q", "NSW", "V", "T"]:
        csp.add_variable(r, colours)
    for a, ns in AUSTRALIA.items():
        for b in ns:
            csp.add(FnConstraint((a, b), lambda x, y: x != y, "equipment", f"{a} != {b}"))
    return csp


def test_map_colouring_solved():
    csp = colouring(["red", "green", "blue"])
    res = solve(csp)
    assert res.ok
    assert csp.violated(res.solution) == []


def test_map_colouring_two_colours_infeasible():
    res = solve(colouring(["red", "green"]))
    assert res.status == "infeasible"


def test_unary_wipeout_is_reported():
    csp = CSP()
    csp.add_variable("x", [1, 2, 3])
    c = csp.add(FnConstraint(("x",), lambda v: v > 5, "time", "x > 5"))
    res = solve(csp)
    assert res.status == "infeasible" and res.wipeout is c


def test_ac3_prunes_before_search():
    # x < y < z over {1, 2, 3}: AC-3 alone leaves exactly one value per variable
    csp = CSP()
    for v in "xyz":
        csp.add_variable(v, [1, 2, 3])
    csp.add(FnConstraint(("x", "y"), lambda a, b: a < b, "time", "x < y"))
    csp.add(FnConstraint(("y", "z"), lambda a, b: a < b, "time", "y < z"))
    res = solve(csp)
    assert res.solution == {"x": 1, "y": 2, "z": 3}
    assert res.stats.backtracks == 0 and res.stats.pruned == 6
