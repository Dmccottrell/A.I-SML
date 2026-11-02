"""
code_db.py - vryxcode_dbview: a SQLite database in a VryxCode project, shown as tables in the Files panel. Read-only.

WHAT THIS FILE DOES
    `view(folder, rel, table, query)` opens the file read-only (SQLite's own mode=ro: nothing can be written, not even a journal) and returns every
    table with its columns and row count, and the first rows of one table (the first table unless one is chosen), filtered to rows where any
    column contains `query`.
"""
# os.path works with file paths; pathlib turns a path into a file:// address; sqlite3 is Python's built-in
# connector for SQLite (a database stored in one ordinary file).
import os
import pathlib
import sqlite3

# File endings that count as SQLite databases.
DB_FILES = (".db", ".sqlite", ".sqlite3", ".db3")
# Limits so a huge database cannot flood the page: at most 200 rows shown, and long values cut at 300 characters.
MAX_ROWS, MAX_CELL = 200, 300


class DbError(Exception):
    """A problem with the database request, with a plain-words message that is safe to show to the person."""
    pass


def is_db(path):
    """True if the file name ends with a known database ending (case does not matter)."""
    return str(path).lower().endswith(DB_FILES)


def _cell(v):
    """Make one table value safe to send as JSON: numbers/None stay, raw bytes become "[N bytes]", text is cut short."""
    if v is None or isinstance(v, (int, float)):
        return v
    if isinstance(v, bytes):
        return f"[{len(v)} bytes]"
    v = str(v)
    return v if len(v) <= MAX_CELL else v[:MAX_CELL] + "…"


def _q(name):
    """Quote a table or column name for SQL: wrap in double quotes and double any quote inside. Needed because names
    cannot be passed as ? placeholders, and an odd name must not break (or inject into) the query."""
    return '"' + name.replace('"', '""') + '"'


def view(folder, rel, table="", query=""):
    """Read a database file in the project. folder = project folder, rel = path of the file inside it, table = which
    table to show (default: the first), query = text to search for in any column.

    Returns {"tables": [{name, columns, rows}], "table", "columns", "rows", "limit"}. Raises DbError with a plain
    message if it is not a usable database file."""
    # realpath follows links, so the next check sees where the file REALLY is.
    root = os.path.realpath(folder)
    full = os.path.realpath(os.path.join(root, str(rel or "")))
    # Only real database files inside the project may be opened (stops "../" and links pointing elsewhere).
    if not full.startswith(root + os.sep) or not os.path.isfile(full) or not is_db(full):
        raise DbError("That is not a database file in this project.")
    # mode=ro opens the file read-only at the SQLite level; uri=True lets us pass that option; timeout=2 waits at most 2 s
    # if the file is locked.
    try:
        con = sqlite3.connect(pathlib.Path(full).as_uri() + "?mode=ro", uri=True, timeout=2)     # as_uri: file:///C:/... on Windows too
    except sqlite3.Error as e:
        raise DbError(f"It could not be opened: {e}")
    try:
        # A second safety lock: refuse any statement that would change data.
        con.execute("PRAGMA query_only = 1")
        # The names of all tables and views, leaving out SQLite's own internal tables (names starting "sqlite_").
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        # For each table: its column names and how many rows it has.
        tables = []
        for n in names:
            # PRAGMA table_info lists the columns; the name is in the second field (index 1).
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({_q(n)})")]
            # Counting can fail for a broken view; then the count is unknown (None).
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {_q(n)}").fetchone()[0]
            except sqlite3.Error:
                count = None
            tables.append({"name": n, "columns": cols, "rows": count})
        # Show the chosen table, or the first one if none was chosen or the name is unknown. "" when there are no tables.
        pick = table if table in names else (names[0] if names else "")
        rows, columns = [], []
        if pick:
            # Reuse the column list worked out above.
            columns = next(t["columns"] for t in tables if t["name"] == pick)
            sql, args = f"SELECT * FROM {_q(pick)}", []
            query = str(query or "").strip()
            # With a search text: keep rows where ANY column, turned into text, contains it. LIKE with % on both sides
            # means "contains". The text goes in as a ? placeholder (args), never glued into the SQL, so it is safe.
            if query and columns:
                sql += " WHERE " + " OR ".join(f"CAST({_q(c)} AS TEXT) LIKE ?" for c in columns)
                args = ["%" + query + "%"] * len(columns)
            # Run the query with a row limit and make each value JSON-safe.
            rows = [[_cell(v) for v in r] for r in con.execute(sql + f" LIMIT {MAX_ROWS}", args)]
        return {"tables": tables, "table": pick, "columns": columns, "rows": rows, "limit": MAX_ROWS}
    # A file with the right ending that is not really SQLite (or is damaged) fails here.
    except sqlite3.DatabaseError as e:
        raise DbError(f"That file is not a database SQLite can read ({e}).")
    finally:
        # Always close the connection, whether it worked or not.
        con.close()
