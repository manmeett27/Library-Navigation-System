"""Search logic for the Intelligent Library Search & Book Collection Agent.

Problem model
-------------
State   : a location in the library graph (BFS/DFS), or (location, set of
          collected books) for the multi-book A* planner.
Action  : walk along one walkway from the current location to a neighbour.
Cost    : walking distance in metres (+ crowd penalty when optimising time).
Goal    : the shelf that stocks the wanted book (BFS/DFS), or all chosen
          books collected (A*).
"""
import itertools
import heapq
import math
from collections import deque

import networkx as nx

MAX_EXACT_BOOKS = 8      # subsets are enumerated exactly up to this many books
LOG_LIMIT = 400          # max open/closed log lines kept for display


# ----------------------------------------------------------------- graph ----
def edge_key(a, b):
    return tuple(sorted((a, b)))


def build_full_graph(locations, walkways):
    """Complete library map, before any closure/restriction is applied."""
    g = nx.Graph()
    for loc in locations:
        g.add_node(loc["name"], kind=loc["kind"], pos=(loc["x"], loc["y"]))
    for a, b, d in walkways:
        g.add_edge(a, b, distance=float(d))
    return g


def build_graph(full, closed_sections, restricted_shelves, crowded_edges, crowd_penalty):
    """Walkable graph: closed sections and restricted shelves are removed.

    distance : physical metres
    weight   : metres + crowd penalty (used by the 'time' metric)
    """
    blocked = set(closed_sections) | set(restricted_shelves)
    g = nx.Graph()
    for n in full.nodes:
        if n not in blocked:
            g.add_node(n, **full.nodes[n])
    for a, b, data in full.edges(data=True):
        if a in blocked or b in blocked:
            continue
        crowded = edge_key(a, b) in crowded_edges
        g.add_edge(a, b, distance=data["distance"],
                   weight=data["distance"] + (crowd_penalty if crowded else 0.0),
                   crowded=crowded)
    return g


def actions(graph, node):
    """All legal actions from a state: walk to each adjacent location."""
    if node not in graph:
        return []
    return [{"action": f"Walk {node} -> {nb}", "to": nb,
             "distance": graph[node][nb]["distance"], "cost": graph[node][nb]["weight"],
             "crowded": graph[node][nb]["crowded"]}
            for nb in sorted(graph.neighbors(node))]


def shortest(graph, a, b, attr):
    """Cheapest path between two locations (Dijkstra) -> (path, cost)."""
    if a not in graph or b not in graph:
        return None, math.inf
    try:
        path = nx.shortest_path(graph, a, b, weight=attr)
        return path, sum(graph[u][v][attr] for u, v in zip(path, path[1:]))
    except nx.NetworkXNoPath:
        return None, math.inf


def path_totals(graph, path):
    """(physical metres, crowd-aware cost) of a path."""
    if not path:
        return math.inf, math.inf
    pairs = list(zip(path, path[1:]))
    return (sum(graph[a][b]["distance"] for a, b in pairs),
            sum(graph[a][b]["weight"] for a, b in pairs))


def _rebuild(parent, goal):
    path, node = [], goal
    while node is not None:
        path.append(node)
        node = parent[node]
    return path[::-1]


# ----------------------------------------------------- BFS / DFS (blind) ----
def bfs(graph, start, goal_test):
    """Breadth-first search. Returns dict(path, open, closed, expanded)."""
    out = {"path": None, "open": [], "closed": [], "expanded": 0}
    if start not in graph:
        return out
    frontier, parent, closed = deque([start]), {start: None}, []
    out["open"].append(f"init        OPEN = [{start}]")
    goal = None
    while frontier:
        node = frontier.popleft()
        closed.append(node)
        step = len(closed)
        out["closed"].append(f"step {step:<3} expand {node}   CLOSED = [{', '.join(closed)}]")
        if goal_test(node):
            goal = node
            break
        for nb in sorted(graph.neighbors(node)):
            if nb not in parent:
                parent[nb] = node
                frontier.append(nb)
        out["open"].append(f"step {step:<3} OPEN = [{', '.join(frontier)}]")
    out["expanded"] = len(closed)
    if goal is not None:
        out["path"] = _rebuild(parent, goal)
    return out


def dfs(graph, start, goal_test):
    """Depth-first search (neighbours tried in alphabetical order)."""
    out = {"path": None, "open": [], "closed": [], "expanded": 0}
    if start not in graph:
        return out
    stack, parent, closed = [(start, None)], {}, []
    out["open"].append(f"init        OPEN(stack top first) = [{start}]")
    goal = None
    while stack:
        node, par = stack.pop()
        if node in parent:
            continue
        parent[node] = par
        closed.append(node)
        step = len(closed)
        out["closed"].append(f"step {step:<3} expand {node}   CLOSED = [{', '.join(closed)}]")
        if goal_test(node):
            goal = node
            break
        for nb in sorted(graph.neighbors(node), reverse=True):
            if nb not in parent:
                stack.append((nb, node))
        top_first = [n for n, _ in reversed(stack)]
        out["open"].append(f"step {step:<3} OPEN(stack top first) = [{', '.join(top_first)}]")
    out["expanded"] = len(closed)
    if goal is not None:
        out["path"] = _rebuild(parent, goal)
    return out


def find_book(graph, catalog, start, title, method, speed, pickup_minutes=0.0):
    """Locate one book with BFS or DFS and describe the walk to its shelf."""
    base = {"algorithm": method, "route": None, "order": [], "distance": math.inf, "cost": math.inf,
            "minutes": math.inf, "open": [], "closed": [], "expanded": 0, "legs": [], "skipped": []}
    info = catalog[title]
    if not info["available"]:
        base["skipped"].append((title, "unavailable"))
        base["message"] = f"'{title}' is currently unavailable (not on the shelf)."
        return base
    shelf = info["shelf"]
    search = bfs if method == "BFS" else dfs
    res = search(graph, start, lambda n: n == shelf)
    base.update(open=res["open"][:LOG_LIMIT], closed=res["closed"][:LOG_LIMIT], expanded=res["expanded"])
    if res["path"] is None:
        reason = ("is closed or restricted" if shelf not in graph else "cannot be reached from the start")
        base["skipped"].append((title, f"shelf {reason}"))
        base["message"] = f"{method} could not find '{title}': its shelf ({shelf}) {reason}."
        return base
    dist, cost = path_totals(graph, res["path"])
    minutes = dist / max(speed, 1) + pickup_minutes
    base.update(route=res["path"], order=[title], distance=dist, cost=dist, minutes=minutes,
                crowd_cost=cost,
                legs=[{"from": start, "to": shelf, "book": title, "path": res["path"],
                       "distance": dist, "cost": dist, "minutes": minutes}],
                message=(f"{method} found '{title}' on {shelf} after expanding {res['expanded']} "
                         f"locations. {method} counts edges, not metres, so the path is not guaranteed "
                         f"to be the shortest."))
    return base


# --------------------------------------------------- multi-book A* planner --
def _astar_subset(start, items, pair_path, pair_cost, speed, time_limit, pickup, w):
    """A* over states (location, collected-mask) for one fixed set of books.

    g(n) = walking cost so far + w * sum(priority/5 * cost-at-collection)
           (high-priority books collected late are penalised; never negative)
    h(n) = largest exact walking cost to any still-uncollected shelf
           (admissible: the agent must at least reach the farthest one)
    A partial route is pruned when walking + pickup time exceeds the limit.
    """
    n = len(items)
    full = (1 << n) - 1
    shelves = [it["shelf"] for it in items]

    def h(node, mask):
        rem = [pair_cost[(node, shelves[i])] for i in range(n) if not (mask >> i) & 1]
        return max(rem) if rem else 0.0

    serial = itertools.count()
    heap = [(h(start, 0), 0.0, next(serial), start, 0, 0.0, ())]
    pareto = {(start, 0): [(0.0, 0.0)]}
    open_log = [f"+ {start:<17} got={0:0{n}b} g=0.0 h={h(start, 0):.1f} f={h(start, 0):.1f}"]
    closed_log, expansions = [], 0
    while heap:
        f, g, _, node, mask, walk, order = heapq.heappop(heap)
        expansions += 1
        closed_log.append(f"#{expansions:<3} {node:<17} got={mask:0{n}b} g={g:.1f} f={f:.1f}")
        if mask == full:
            return {"order": list(order), "g": g, "walk": walk, "open": open_log,
                    "closed": closed_log, "expanded": expansions}
        for i in range(n):
            if (mask >> i) & 1:
                continue
            leg = pair_cost[(node, shelves[i])]
            if math.isinf(leg):
                continue
            nwalk = walk + leg
            if nwalk / max(speed, 1) + pickup * (len(order) + 1) > time_limit + 1e-9:
                continue
            ng = g + leg + w * (items[i]["priority"] / 5.0) * nwalk
            nmask = mask | (1 << i)
            key = (shelves[i], nmask)
            front = pareto.setdefault(key, [])
            if any(g0 <= ng + 1e-12 and w0 <= nwalk + 1e-12 for g0, w0 in front):
                continue
            front[:] = [(g0, w0) for g0, w0 in front if not (ng <= g0 and nwalk <= w0)] + [(ng, nwalk)]
            nf = ng + h(shelves[i], nmask)
            open_log.append(f"+ {shelves[i]:<17} got={nmask:0{n}b} g={ng:.1f} h={nf - ng:.1f} f={nf:.1f}")
            heapq.heappush(heap, (nf, ng, next(serial), shelves[i], nmask, nwalk, order + (i,)))
    return None


def plan_collection(graph, catalog, start, selected, speed, time_limit, pickup_minutes,
                    priority_weight, metric="time"):
    """Plan a route that collects as much priority as fits in the time limit.

    metric = "distance": minimise physical metres (crowd penalty ignored)
    metric = "time"    : minimise crowd-aware walking cost (estimated time)
    """
    attr = "weight" if metric == "time" else "distance"
    res = {"algorithm": "A*", "route": None, "order": [], "distance": math.inf, "cost": math.inf,
           "minutes": math.inf, "open": [], "closed": [], "expanded": 0, "legs": [], "skipped": []}
    if start not in graph:
        res["message"] = "The starting location is closed or unknown."
        return res

    cands = []
    for title in selected:
        info = catalog[title]
        if not info["available"]:
            res["skipped"].append((title, "unavailable"))
        elif info["shelf"] not in graph:
            res["skipped"].append((title, f"{info['shelf']} is closed or restricted"))
        elif shortest(graph, start, info["shelf"], attr)[0] is None:
            res["skipped"].append((title, "cannot be reached from the start (closures)"))
        else:
            cands.append(title)
    if len(cands) > MAX_EXACT_BOOKS:
        cands.sort(key=lambda t: -catalog[t]["priority"])
        for t in cands[MAX_EXACT_BOOKS:]:
            res["skipped"].append((t, f"more than {MAX_EXACT_BOOKS} books selected"))
        cands = cands[:MAX_EXACT_BOOKS]
    if not cands:
        res.update(route=[start], distance=0.0, cost=0.0, minutes=0.0,
                   message="No collectable books: every selected book is unavailable or blocked, "
                           "or nothing was selected.")
        return res

    points = list(dict.fromkeys([start] + [catalog[t]["shelf"] for t in cands]))
    pair_path, pair_cost = {}, {}
    for a in points:
        for b in points:
            pair_path[(a, b)], pair_cost[(a, b)] = shortest(graph, a, b, attr)

    items = [{"title": t, "shelf": catalog[t]["shelf"], "priority": catalog[t]["priority"]} for t in cands]
    subsets = []
    for r in range(len(items), 0, -1):
        for combo in itertools.combinations(range(len(items)), r):
            subsets.append((sum(items[i]["priority"] for i in combo), r, combo))
    subsets.sort(key=lambda s: (-s[0], -s[1]))

    best = None
    for _, group in itertools.groupby(subsets, key=lambda s: (s[0], s[1])):
        feasible = []
        for _, _, combo in group:
            sub = [items[i] for i in combo]
            r = _astar_subset(start, sub, pair_path, pair_cost, speed, time_limit,
                              pickup_minutes, priority_weight)
            if r:
                r["items"] = sub
                feasible.append(r)
        if feasible:
            best = min(feasible, key=lambda r: r["g"])
            break

    chosen_titles = set()
    if best is None:
        res["skipped"] += [(t, "does not fit in the time limit") for t in cands]
        res["message"] = ("No book can be collected within the time limit. Increase the limit, "
                          "walking speed, or reduce pickup time.")
        return res

    seq = [best["items"][i] for i in best["order"]]
    route, legs, node, clock = [start], [], start, 0.0
    for k, it in enumerate(seq, 1):
        seg = pair_path[(node, it["shelf"])]
        route += seg[1:]
        d, c = path_totals(graph, seg)
        clock += (c if attr == "weight" else d) / max(speed, 1) + pickup_minutes
        legs.append({"from": node, "to": it["shelf"], "book": it["title"], "path": seg,
                     "distance": d, "cost": c if attr == "weight" else d, "minutes": clock})
        node = it["shelf"]
        chosen_titles.add(it["title"])
    dist, crowd_cost = path_totals(graph, route)
    cost = crowd_cost if attr == "weight" else dist
    minutes = cost / max(speed, 1) + pickup_minutes * len(seq)
    for t in cands:
        if t not in chosen_titles:
            res["skipped"].append((t, "dropped to respect the time limit (lowest total priority)"))
    msg = f"Optimal route found for {len(seq)} of {len(selected)} selected books."
    if res["skipped"]:
        msg += " Some books were skipped (see table below)."
    res.update(route=route, order=[it["title"] for it in seq], distance=dist, cost=cost,
               crowd_cost=crowd_cost, minutes=minutes, legs=legs, expanded=best["expanded"],
               open=best["open"][:LOG_LIMIT], closed=best["closed"][:LOG_LIMIT],
               priority_total=sum(it["priority"] for it in seq), score=best["g"], message=msg)
    return res


def compare_algorithms(graph, catalog, start, title, speed, pickup_minutes, metric="time"):
    """BFS vs DFS vs A* for a single book (used by the UI and the report)."""
    rows = []
    for m in ("BFS", "DFS"):
        r = find_book(graph, catalog, start, title, m, speed, pickup_minutes)
        rows.append({"Algorithm": m, "Found": r["route"] is not None,
                     "Path": " -> ".join(r["route"]) if r["route"] else "-",
                     "Distance (m)": round(r["distance"], 1) if r["route"] else None,
                     "Locations expanded": r["expanded"]})
    a = plan_collection(graph, catalog, start, [title], speed, 999, pickup_minutes, 0.0, metric)
    rows.append({"Algorithm": "A*", "Found": a["route"] is not None and bool(a["order"]),
                 "Path": " -> ".join(a["route"]) if a["order"] else "-",
                 "Distance (m)": round(a["distance"], 1) if a["order"] else None,
                 "Locations expanded": a["expanded"]})
    return rows
