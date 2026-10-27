"""
code_db.py - vryxcode_dbview: a SQLite database in a VryxCode project, shown as tables in the Files panel. Read-only.

WHAT THIS FILE DOES
    `view(folder, rel, table, query)` opens the file read-only (SQLite's own mode=ro: nothing can be written, not even a journal) and returns every
    table with its columns and row count, and the first rows of one table (the first table unless one is chosen), filtered to rows where any
    column contains `query`.
"""
import os
import pathlib
import sqlite3

DB_FILES = (".db", ".sqlite", ".sqlite3", ".db3")
MAX_ROWS, MAX_CELL = 200, 300


class DbError(Exception):
    pass


def is_db(path):
    return str(path).lower().endswith(DB_FILES)


def _cell(v):
    if v is None or isinstance(v, (int, float)):
        return v
    if isinstance(v, bytes):
        return f"[{len(v)} bytes]"
    v = str(v)
    return v if len(v) <= MAX_CELL else v[:MAX_CELL] + "…"


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def view(folder, rel, table="", query=""):
    root = os.path.realpath(folder)
    full = os.path.realpath(os.path.join(root, str(rel or "")))
    if not full.startswith(root + os.sep) or not os.path.isfile(full) or not is_db(full):
        raise DbError("That is not a database file in this project.")
    try:
        con = sqlite3.connect(pathlib.Path(full).as_uri() + "?mode=ro", uri=True, timeout=2)     # as_uri: file:///C:/... on Windows too
    except sqlite3.Error as e:
        raise DbError(f"It could not be opened: {e}")
    try:
        con.execute("PRAGMA query_only = 1")
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = []
        for n in names:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({_q(n)})")]
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {_q(n)}").fetchone()[0]
            except sqlite3.Error:
                count = None
            tables.append({"name": n, "columns": cols, "rows": count})
        pick = table if table in names else (names[0] if names else "")
        rows, columns = [], []
        if pick:
            columns = next(t["columns"] for t in tables if t["name"] == pick)
            sql, args = f"SELECT * FROM {_q(pick)}", []
            query = str(query or "").strip()
            if query and columns:
                sql += " WHERE " + " OR ".join(f"CAST({_q(c)} AS TEXT) LIKE ?" for c in columns)
                args = ["%" + query + "%"] * len(columns)
            rows = [[_cell(v) for v in r] for r in con.execute(sql + f" LIMIT {MAX_ROWS}", args)]
        return {"tables": tables, "table": pick, "columns": columns, "rows": rows, "limit": MAX_ROWS}
    except sqlite3.DatabaseError as e:
        raise DbError(f"That file is not a database SQLite can read ({e}).")
    finally:
        con.close()
