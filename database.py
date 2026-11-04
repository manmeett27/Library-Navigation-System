"""SQLite persistence layer for the Intelligent Library Agent.

Tables
------
locations      entrance / sections / shelves with map coordinates
walkways       weighted undirected edges (walking distance in metres)
books          catalogue: title, shelf, priority (1-5), availability
route_history  every route the agent has calculated
"""
import csv
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "library.db")
CSV_PATH = os.path.join(BASE_DIR, "sample_books.csv")

SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('entrance', 'section', 'shelf')),
    x    REAL NOT NULL,
    y    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS walkways (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    loc_a      TEXT NOT NULL REFERENCES locations(name),
    loc_b      TEXT NOT NULL REFERENCES locations(name),
    distance_m REAL NOT NULL CHECK (distance_m > 0),
    UNIQUE (loc_a, loc_b)
);
CREATE TABLE IF NOT EXISTS books (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL UNIQUE,
    shelf     TEXT NOT NULL REFERENCES locations(name),
    priority  INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1))
);
CREATE TABLE IF NOT EXISTS route_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    algorithm  TEXT NOT NULL,
    books      TEXT NOT NULL,
    route      TEXT NOT NULL,
    distance_m REAL,
    minutes    REAL
);
"""

SEED_LOCATIONS = [
    ("Entrance", "entrance", 0, 1),
    ("Main Hall", "section", 1, 1),
    ("Science Hall", "section", 2, 1),
    ("Quiet Study", "section", 3, 1),
    ("Algorithms Shelf", "shelf", 2, 2),
    ("AI Shelf", "shelf", 3, 2),
    ("Database Shelf", "shelf", 2, 0),
    ("Networks Shelf", "shelf", 3, 0),
    ("Literature Shelf", "shelf", 4, 0),
]
SEED_WALKWAYS = [
    ("Entrance", "Main Hall", 8),
    ("Main Hall", "Algorithms Shelf", 12),
    ("Main Hall", "Database Shelf", 10),
    ("Main Hall", "Science Hall", 14),
    ("Science Hall", "AI Shelf", 8),
    ("Science Hall", "Networks Shelf", 11),
    ("Database Shelf", "AI Shelf", 13),
    ("Algorithms Shelf", "Quiet Study", 7),
    ("Quiet Study", "AI Shelf", 9),
    ("Networks Shelf", "Literature Shelf", 10),
    ("Literature Shelf", "Entrance", 25),
    ("Database Shelf", "Networks Shelf", 15),
]
SEED_BOOKS = [
    ("Introduction to Algorithms", "Algorithms Shelf", 5, True),
    ("Database System Concepts", "Database Shelf", 4, True),
    ("Artificial Intelligence: A Modern Approach", "AI Shelf", 5, True),
    ("Computer Networks", "Networks Shelf", 3, True),
    ("The Design of Everyday Things", "Literature Shelf", 2, True),
    ("Discrete Mathematics", "Algorithms Shelf", 3, False),
]


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _read_books_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((r["title"].strip(), r["shelf"].strip(), int(r["priority"]),
                         r["available"].strip().lower() in ("true", "1", "yes")))
    return rows


def init_db(path=DB_PATH, csv_path=CSV_PATH, reset=False):
    """Create the schema and seed it (books come from the CSV when present)."""
    if reset and os.path.exists(path):
        os.remove(path)
    conn = connect(path)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
        conn.executemany("INSERT INTO locations VALUES (?,?,?,?)", SEED_LOCATIONS)
        conn.executemany("INSERT INTO walkways (loc_a, loc_b, distance_m) VALUES (?,?,?)", SEED_WALKWAYS)
    if conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
        books = _read_books_csv(csv_path) if os.path.exists(csv_path) else SEED_BOOKS
        conn.executemany("INSERT INTO books (title, shelf, priority, available) VALUES (?,?,?,?)",
                         [(t, s, p, int(a)) for t, s, p, a in books])
    conn.commit()
    return conn


def load_locations(conn):
    return [dict(r) for r in conn.execute("SELECT name, kind, x, y FROM locations ORDER BY rowid")]


def load_walkways(conn):
    return [(r["loc_a"], r["loc_b"], r["distance_m"])
            for r in conn.execute("SELECT loc_a, loc_b, distance_m FROM walkways ORDER BY id")]


def load_books(conn):
    return {r["title"]: {"shelf": r["shelf"], "priority": r["priority"], "available": bool(r["available"])}
            for r in conn.execute("SELECT title, shelf, priority, available FROM books ORDER BY id")}


def search_books(conn, keyword):
    like = f"%{keyword.strip()}%"
    return [dict(r) for r in conn.execute(
        "SELECT title, shelf, priority, available FROM books WHERE title LIKE ? ORDER BY title", (like,))]


def set_availability(conn, title, available):
    conn.execute("UPDATE books SET available = ? WHERE title = ?", (int(available), title))
    conn.commit()


def save_route(conn, algorithm, books, route, distance, minutes):
    conn.execute(
        "INSERT INTO route_history (created_at, algorithm, books, route, distance_m, minutes) VALUES (?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), algorithm, "; ".join(books),
         " -> ".join(route), float(distance), float(minutes)))
    conn.commit()


def recent_routes(conn, limit=5):
    return [dict(r) for r in conn.execute(
        "SELECT created_at, algorithm, books, route, distance_m, minutes "
        "FROM route_history ORDER BY id DESC LIMIT ?", (limit,))]
