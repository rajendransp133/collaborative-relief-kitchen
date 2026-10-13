from relief_kitchen.search_csp.csp import CSP, FnConstraint, solve
from relief_kitchen.search_csp.diagnosis import quickxplain

AUSTRALIA = {"WA": ["NT", "SA"], "NT": ["SA", "Q"], "SA": ["Q", "NSW", "V"], "Q": ["NSW"], "NSW": ["V"]}


def colouring(colours):
    csp = CSP()
    for r in ["WA", "NT", "SA", "Q", "NSW", "V", "T"]:
        csp.add_variable(r, colours)
    for a, ns in AUSTRALIA.items():
        for b in ns:
            csp.add(FnConstraint((a, b), lambda x, y: x != y, "equipment", f"{a}-{b}", f"{a} != {b}"))
    return csp


def test_map_colouring_solved():
    csp = colouring(["red", "green", "blue"])
    res = solve(csp)
    assert res.ok
    assert csp.is_solution(res.solution) == []


def test_map_colouring_two_colours_infeasible():
    res = solve(colouring(["red", "green"]))
    assert res.status == "infeasible"


def test_unary_wipeout_is_reported():
    csp = CSP()
    csp.add_variable("x", [1, 2, 3])
    c = csp.add(FnConstraint(("x",), lambda v: v > 5, "time", "deadline", "x > 5"))
    res = solve(csp)
    assert res.status == "infeasible" and res.wipeout is c


def test_quickxplain_finds_minimal_conflict():
    # x in 0..9; constraints: a: x>=5, b: x<=3, c: x even, d: x<=8. Minimal conflict = {a, b}
    preds = {"a": lambda x: x >= 5, "b": lambda x: x <= 3, "c": lambda x: x % 2 == 0, "d": lambda x: x <= 8}

    def consistent(groups):
        return any(all(preds[g](x) for g in groups) for x in range(10))

    assert sorted(quickxplain(["c", "a", "d", "b"], consistent)) == ["a", "b"]
    assert quickxplain(["c", "d"], consistent) is None
