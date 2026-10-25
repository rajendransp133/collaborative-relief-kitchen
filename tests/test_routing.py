from relief_kitchen.env.road_network import Place, Road, make_network
from relief_kitchen.search_csp.routing import astar_route, dijkstra, reroute


def net():
    places = [Place("K", "depot", 0, 0), Place("A", "junction", 10, 0), Place("B", "junction", 10, 10),
              Place("H", "hospital", 20, 0)]
    roads = [Road("r1", "K", "A", 10), Road("r2", "A", "H", 10), Road("r3", "K", "B", 15), Road("r4", "B", "H", 15)]
    return make_network(places, roads)


def test_astar_matches_dijkstra():
    n = net()
    a, d = astar_route(n, "K", "H"), dijkstra(n, "K", "H")
    assert a.minutes == d.minutes == 20
    assert a.nodes == ["K", "A", "H"]
    assert a.expanded <= d.expanded


def test_reroute_after_closure():
    n = net()
    old = astar_route(n, "K", "H")
    n.roads["r2"].open = False
    new = reroute(n, old, "r2")
    assert new.nodes == ["K", "B", "H"] and new.minutes == 30


def test_unreachable_when_all_roads_closed():
    n = net()
    n.roads["r2"].open = False
    n.roads["r4"].open = False
    assert astar_route(n, "K", "H") is None
    assert astar_route(n, "K", "H", include_closed=True).minutes == 20
