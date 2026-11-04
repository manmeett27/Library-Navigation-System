"""Automated checks for the library agent (run: python test_agent.py)."""
import itertools, math, os, tempfile
import database as db
import agent as ag

path = os.path.join(tempfile.mkdtemp(), "t.db")
conn = db.init_db(path)
full = ag.build_full_graph(db.load_locations(conn), db.load_walkways(conn))
cat = db.load_books(conn)

def G(closed=(), restricted=(), crowded=(), pen=8):
    return ag.build_graph(full, set(closed), set(restricted), {ag.edge_key(*e) for e in crowded}, pen)

def brute(graph, start, titles, attr="distance"):
    best = math.inf
    for perm in itertools.permutations(titles):
        node, tot = start, 0
        for t in perm:
            tot += ag.shortest(graph, node, cat[t]["shelf"], attr)[1]; node = cat[t]["shelf"]
        best = min(best, tot)
    return best

ok = 0
def check(name, cond):
    global ok
    assert cond, "FAILED: " + name
    ok += 1; print("PASS", name)

g = G()
# 1 BFS / DFS find every available book
for t, i in cat.items():
    if i["available"]:
        for m in ("BFS", "DFS"):
            r = ag.find_book(g, cat, "Entrance", t, m, 75)
            check(f"{m} finds {t[:20]}", r["route"] and r["route"][-1] == i["shelf"])
# 2 unavailable book is reported, not routed
r = ag.find_book(g, cat, "Entrance", "Discrete Mathematics", "BFS", 75)
check("unavailable book -> no route + reason", r["route"] is None and r["skipped"])
# 3 A* optimal vs brute force for several selections
for sel in (["Introduction to Algorithms", "Artificial Intelligence: A Modern Approach"],
            ["Database System Concepts", "Computer Networks", "The Design of Everyday Things"],
            [t for t, i in cat.items() if i["available"]]):
    r = ag.plan_collection(g, cat, "Entrance", sel, 75, 999, 0, 0.0, "distance")
    check(f"A* optimal ({len(sel)} books): {r['distance']:.0f} m", abs(r["distance"] - brute(g, "Entrance", sel)) < 1e-9)
    check("  collects every book", set(r["order"]) == set(sel))
# 4 crowd penalty changes the time-metric route cost and is optimal vs brute force
crowd = [("Main Hall", "Algorithms Shelf"), ("Quiet Study", "AI Shelf")]
gc = G(crowded=crowd, pen=20)
sel = ["Introduction to Algorithms", "Artificial Intelligence: A Modern Approach", "Database System Concepts"]
r = ag.plan_collection(gc, cat, "Entrance", sel, 75, 999, 0, 0.0, "time")
check("time metric optimal with crowding", abs(r["cost"] - brute(gc, "Entrance", sel, "weight")) < 1e-9)
r2 = ag.plan_collection(gc, cat, "Entrance", sel, 75, 999, 0, 0.0, "distance")
check("distance metric ignores crowding", abs(r2["distance"] - brute(gc, "Entrance", sel, "distance")) < 1e-9)
# 5 restricted shelf: book skipped, others still routed
r = ag.plan_collection(G(restricted=["AI Shelf"]), cat, "Entrance", sel, 75, 999, 0, 0.0, "time")
check("restricted shelf skipped", any(t.startswith("Artificial") for t, _ in r["skipped"]) and len(r["order"]) == 2)
# 6 closed section blocks / reroutes
r = ag.plan_collection(G(closed=["Main Hall"]), cat, "Entrance", ["Computer Networks"], 75, 999, 0, 0.0, "distance")
check("closed Main Hall -> reroute via Literature (35 m)", r["route"] == ["Entrance", "Literature Shelf", "Networks Shelf"] and r["distance"] == 35)
r = ag.plan_collection(G(closed=["Main Hall"]), cat, "Entrance", ["Introduction to Algorithms"], 75, 999, 0, 0.0, "distance")
check("Main Hall closed -> Algorithms still reachable the long way", r["order"] and r["distance"] == 25 + 10 + 11 + 8 + 9 + 7)
r = ag.plan_collection(G(closed=["Main Hall", "Quiet Study"]), cat, "Entrance", ["Introduction to Algorithms"], 75, 999, 0, 0.0, "distance")
check("Main Hall + Quiet Study closed isolate the shelf -> reported", not r["order"] and r["skipped"])
# 7 time limit: drops lowest-priority books, keeps highest-priority total
allb = [t for t, i in cat.items() if i["available"]]
r = ag.plan_collection(g, cat, "Entrance", allb, 75, 1.0, 0, 0.0, "distance")   # 75 m budget
check("tight time limit -> subset within limit", r["order"] and r["minutes"] <= 1.0 + 1e-9)
best_pri = r["priority_total"]
# brute-force best priority within 75 m
bp = 0
for k in range(1, len(allb)+1):
    for sub in itertools.combinations(allb, k):
        if brute(g, "Entrance", sub) <= 75 + 1e-9: bp = max(bp, sum(cat[t]["priority"] for t in sub))
check(f"subset priority is the best possible ({best_pri} == {bp})", best_pri == bp)
r = ag.plan_collection(g, cat, "Entrance", allb, 75, 0.05, 0, 0.0, "distance")
check("impossible limit -> clear message", r["route"] is None and "No book" in r["message"])
# 8 priority weight can change order but never loses a book
r0 = ag.plan_collection(g, cat, "Entrance", allb, 75, 999, 0, 0.0, "distance")
r3 = ag.plan_collection(g, cat, "Entrance", allb, 75, 999, 0, 3.0, "distance")
check("priority weight keeps all books", set(r3["order"]) == set(allb))
check("priority weight=0 is distance-optimal", r0["distance"] <= r3["distance"] + 1e-9)
# 9 actions and logs
check("actions from Entrance", len(ag.actions(g, "Entrance")) == 2)
r = ag.plan_collection(g, cat, "Entrance", allb, 75, 999, 0, 1.0, "time")
check("open/closed lists populated", r["open"] and r["closed"])
# 10 database
db.set_availability(conn, "Computer Networks", False)
check("db availability update", db.load_books(conn)["Computer Networks"]["available"] is False)
db.save_route(conn, "A*", ["x"], ["a", "b"], 10.0, 1.0)
check("db route history", len(db.recent_routes(conn)) == 1)
check("db keyword search", len(db.search_books(conn, "algor")) >= 1)
print(f"\nALL {ok} CHECKS PASSED")
