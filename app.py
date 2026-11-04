"""Intelligent Library Search & Book Collection Agent - Streamlit interface."""
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import streamlit as st
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import agent as ag
import database as db

st.set_page_config(page_title="Intelligent Library Agent", page_icon="📚", layout="wide")


# ------------------------------------------------------------- data layer ---
@st.cache_resource
def get_conn():
    conn = db.init_db()
    conn.close()
    return None


get_conn()                      # make sure library.db exists and is seeded
conn = db.connect()
LOCATIONS = db.load_locations(conn)
WALKWAYS = db.load_walkways(conn)
CATALOG = db.load_books(conn)
FULL = ag.build_full_graph(LOCATIONS, WALKWAYS)
SECTIONS = [l["name"] for l in LOCATIONS if l["kind"] == "section"]
SHELVES = sorted({b["shelf"] for b in CATALOG.values()})
START_OPTIONS = [l["name"] for l in LOCATIONS if l["kind"] != "shelf"]


# ----------------------------------------------------------------- drawing ---
def draw_library(graph, closed, restricted, crowded, route=None, collect_shelves=()):
    pos = {n: d["pos"] for n, d in FULL.nodes(data=True)}
    route_edges = {frozenset(e) for e in zip(route, route[1:])} if route else set()
    fig, ax = plt.subplots(figsize=(11, 4.8))
    colors = []
    for n in FULL.nodes:
        if n in closed:
            colors.append("#e05d5d")
        elif n in restricted:
            colors.append("#8e6bbf")
        elif route and n in route and n in collect_shelves:
            colors.append("#f4b942")
        elif route and n in route:
            colors.append("#22a06b")
        else:
            colors.append("#8ab6d6")
    nx.draw_networkx_nodes(FULL, pos, node_color=colors, node_size=2100, ax=ax, edgecolors="#333", linewidths=0.8)
    nx.draw_networkx_labels(FULL, pos, labels={n: n.replace(" ", "\n", 1) for n in FULL.nodes}, font_size=7.5, ax=ax)
    blocked_nodes = set(closed) | set(restricted)
    normal, blocked, hot = [], [], []
    for a, b in FULL.edges:
        if frozenset((a, b)) in route_edges:
            hot.append((a, b))
        elif a in blocked_nodes or b in blocked_nodes:
            blocked.append((a, b))
        else:
            normal.append((a, b))
    nx.draw_networkx_edges(FULL, pos, edgelist=normal, edge_color="#a5afba", width=1.6, ax=ax)
    nx.draw_networkx_edges(FULL, pos, edgelist=blocked, edge_color="#d9b3b3", width=1.2, style="dashed", ax=ax)
    nx.draw_networkx_edges(FULL, pos, edgelist=hot, edge_color="#16875c", width=4.5, ax=ax)
    labels = {}
    for a, b, d in FULL.edges(data=True):
        crowd = ag.edge_key(a, b) in crowded
        labels[(a, b)] = f"{d['distance']:.0f} m" + (" CROWDED" if crowd else "")
    nx.draw_networkx_edge_labels(FULL, pos, edge_labels=labels, font_size=7, ax=ax,
                                 bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    ax.legend(handles=[
        Patch(color="#22a06b", label="On route"), Patch(color="#f4b942", label="Book collected here"),
        Patch(color="#e05d5d", label="Closed section"), Patch(color="#8e6bbf", label="Restricted shelf"),
        Patch(color="#8ab6d6", label="Not used"), Line2D([0], [0], color="#16875c", lw=4, label="Walking route"),
    ], loc="upper center", ncol=6, fontsize=7.5, frameon=False, bbox_to_anchor=(0.5, 1.08))
    ax.margins(0.12)
    ax.set_axis_off()
    fig.tight_layout()
    return fig


# ----------------------------------------------------------------- sidebar ---
st.title("📚 Intelligent Library Search & Book Collection Agent")
st.write("Find books with BFS / DFS, or let A* plan an efficient route that collects several books "
         "while respecting closures, restrictions, crowds, priorities and your time limit.")

with st.sidebar:
    st.header("Library conditions")
    closed_sections = st.multiselect("Closed sections", SECTIONS)
    restricted_shelves = st.multiselect("Restricted shelves", SHELVES,
                                        help="Books on a restricted shelf cannot be collected.")
    crowd_labels = {f"{a} ↔ {b}": ag.edge_key(a, b) for a, b, _ in WALKWAYS}
    crowded_picked = st.multiselect("Crowded aisles", list(crowd_labels))
    crowd_penalty = st.slider("Crowd penalty (extra metres-equivalent)", 0, 40, 10, 1)
    st.divider()
    st.header("Optimisation settings")
    metric_label = st.radio("A* minimises", ["Estimated collection time", "Walking distance"],
                            help="Time includes the crowd penalty; distance ignores crowds.")
    metric = "time" if metric_label.startswith("Estimated") else "distance"
    speed = st.slider("Walking speed (m/min)", 30, 100, 60, 5)
    pickup = st.slider("Pickup time per book (min)", 0.0, 3.0, 0.5, 0.25)
    time_limit = st.slider("Time limit (min)", 1.0, 30.0, 6.0, 0.5)
    priority_weight = st.slider("Priority influence", 0.0, 3.0, 1.0, 0.25,
                                help="Higher = high-priority books are collected earlier in the route.")

crowded_edges = {crowd_labels[l] for l in crowded_picked}
graph = ag.build_graph(FULL, set(closed_sections), set(restricted_shelves), crowded_edges, crowd_penalty)

# ------------------------------------------------------------------ inputs ---
c1, c2 = st.columns(2)
with c1:
    st.subheader("1. Choose books")
    kw = st.text_input("Search catalogue by title", placeholder="e.g. algorithms")
    pool = [r["title"] for r in db.search_books(conn, kw)] if kw else list(CATALOG)
    defaults = [t for t in ("Introduction to Algorithms", "Artificial Intelligence: A Modern Approach") if t in pool]
    selected = st.multiselect("Books to collect", pool, default=defaults)
    for t in selected:
        i = CATALOG[t]
        st.write(f"**{t}** — shelf `{i['shelf']}` · priority {i['priority']}/5 · "
                 + ("✅ available" if i["available"] else "❌ unavailable"))
with c2:
    st.subheader("2. Choose search method")
    algorithm = st.selectbox("Algorithm", ["A* multi-book optimiser", "BFS (find one book)", "DFS (find one book)"])
    start = st.selectbox("Starting location", START_OPTIONS)
    target = st.selectbox("Book to find (BFS / DFS)", list(CATALOG))
    st.caption("BFS/DFS locate one book by exploring the library graph. A* plans the whole collection trip.")

if st.button("🚀 Calculate route", type="primary", width="stretch"):
    if algorithm.startswith("A*"):
        result = ag.plan_collection(graph, CATALOG, start, selected, speed, time_limit, pickup,
                                    priority_weight, metric)
        books_used = result["order"]
    else:
        result = ag.find_book(graph, CATALOG, start, target, algorithm[:3], speed, pickup)
        books_used = result["order"]
    if result["route"] and books_used:
        db.save_route(conn, result["algorithm"], books_used, result["route"], result["distance"], result["minutes"])
    st.session_state["run"] = dict(result=result, graph=graph, closed=set(closed_sections),
                                   restricted=set(restricted_shelves), crowded=set(crowded_edges),
                                   limit=time_limit, algo=algorithm, metric=metric)

# ----------------------------------------------------------------- results ---
run = st.session_state.get("run")
if run:
    r = run["result"]
    st.divider()
    st.subheader("3. Results")
    (st.success if r["route"] and r["order"] else st.warning)(r["message"])
    if r["route"] and r["order"]:
        m = st.columns(4)
        label = "Total path cost (min-cost metric)" if run["algo"].startswith("A*") else "Total path cost (metres)"
        unit = " m-eq" if (run["algo"].startswith("A*") and run["metric"] == "time") else " m"
        m[0].metric(label, f"{r['cost']:.1f}{unit}")
        m[1].metric("Walking distance", f"{r['distance']:.1f} m")
        m[2].metric("Estimated time", f"{r['minutes']:.1f} min")
        m[3].metric("Books collected", len(r["order"]))
        if run["algo"].startswith("A*") and r["minutes"] > run["limit"] + 1e-9:
            st.warning("This route exceeds the time limit.")
        st.markdown("**Collection route:** " + " → ".join(r["route"]))
        st.markdown("**Collection order:** " + " → ".join(f"{i}. {t}" for i, t in enumerate(r["order"], 1)))
        st.table([{"Stop": k, "Book": leg["book"], "From": leg["from"], "To (shelf)": leg["to"],
                   "Leg distance (m)": f"{leg['distance']:.1f}", "Leg cost": f"{leg['cost']:.1f}",
                   "Cumulative min": f"{leg['minutes']:.1f}"} for k, leg in enumerate(r["legs"], 1)])
        shelves = {CATALOG[t]["shelf"] for t in r["order"]}
        fig = draw_library(run["graph"], run["closed"], run["restricted"], run["crowded"], r["route"], shelves)
        st.pyplot(fig, width="stretch")
        plt.close(fig)
    else:
        fig = draw_library(run["graph"], run["closed"], run["restricted"], run["crowded"])
        st.pyplot(fig, width="stretch")
        plt.close(fig)
    if r["skipped"]:
        st.markdown("**Books not collected**")
        st.table([{"Book": t, "Reason": why} for t, why in r["skipped"]])

    left, right = st.columns(2)
    with left:
        st.markdown(f"#### Open list / frontier ({len(r['open'])} entries)")
        st.text_area("open", "\n".join(r["open"]) or "(empty)", height=260, label_visibility="collapsed")
    with right:
        st.markdown(f"#### Closed list / explored ({r['expanded']} expansions)")
        st.text_area("closed", "\n".join(r["closed"]) or "(empty)", height=260, label_visibility="collapsed")
    st.caption("A* entries read: location, bitmask of collected books, g (cost so far), h (heuristic), "
               "f = g + h. BFS/DFS entries show the frontier and explored set after each expansion.")

# --------------------------------------------------------------- extra info ---
with st.expander("State space & actions from the starting location"):
    st.write("**States:** a location (BFS/DFS) or *(location, books collected)* (A*). "
             "**Actions:** walk along a walkway to an adjacent location.")
    acts = ag.actions(graph, start)
    st.table([{"Action": a["action"], "Distance (m)": a["distance"], "Cost": a["cost"],
               "Crowded": "yes" if a["crowded"] else "no"} for a in acts]
             if acts else [{"Action": "No actions: start is closed"}])
with st.expander("Compare BFS vs DFS vs A* for one book"):
    cmp_book = st.selectbox("Book", [t for t, i in CATALOG.items() if i["available"]], key="cmp")
    st.table(ag.compare_algorithms(graph, CATALOG, start, cmp_book, speed, pickup, metric))
with st.expander("Book catalogue (database) and availability"):
    st.dataframe([{"Book": t, "Shelf": i["shelf"], "Priority": i["priority"], "Available": i["available"]}
                  for t, i in CATALOG.items()], width="stretch", hide_index=True)
    ec1, ec2, ec3 = st.columns([3, 1, 1])
    edit_book = ec1.selectbox("Book to update", list(CATALOG), key="edit_book")
    edit_val = ec2.checkbox("Available", value=CATALOG[edit_book]["available"], key=f"av_{edit_book}")
    if ec3.button("Save to database"):
        db.set_availability(conn, edit_book, edit_val)
        st.rerun()
with st.expander("Recent routes saved in the database"):
    hist = db.recent_routes(conn)
    st.table(hist) if hist else st.write("No routes saved yet.")
with st.expander("How the optimiser works"):
    st.markdown("""
1. The library is a weighted graph: sections and shelves are nodes, walkways are edges (metres).
2. Closed sections and restricted shelves are removed; crowded aisles get an extra cost.
3. An A* **state** is *(current location, set of collected books)*; an **action** walks to the shelf of an uncollected book along the cheapest path.
4. Cost `g` = walking cost + priority term (high-priority books collected late are penalised). Heuristic `h` = exact cost to the farthest uncollected shelf, which never over-estimates, so A* stays optimal.
5. Partial routes whose walking + pickup time exceed the limit are pruned. If not every book fits, the planner picks the subset with the **highest total priority** that fits, then the cheapest route for it.
6. Unavailable books, restricted shelves and unreachable shelves are reported, never silently ignored.
""")
conn.close()
