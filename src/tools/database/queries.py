"""
database/queries.py — Reusable, parameterized SQL queries.

All SQL lives here — never scattered across agent or test files.
Each public constant is a SQL string; each public function wraps a query
with a typed Python interface so callers don't deal with raw SQL at all.

Design rules:
  • Every query that accepts user-supplied values uses %s placeholders.
  • Functions return plain Python types (list, dict) or model objects.
  • No business logic here — only data retrieval / shaping.

Usage::

    from tools.database.client import DatabaseClient
    from database.queries import fetch_active_users, PING

    db = DatabaseClient.from_env()
    with db:
        db.query(PING)                        # raw SQL constant
        users = fetch_active_users(db)         # typed helper function
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.database.client import DatabaseClient
    from tools.database.models import Row, QueryResult


# ── Connection health ─────────────────────────────────────────────────────────

PING = "SELECT 1 AS alive"

SERVER_VERSION = "SELECT VERSION() AS version"


# ── Schema introspection ──────────────────────────────────────────────────────

LIST_TABLES = """
SELECT TABLE_NAME
FROM   INFORMATION_SCHEMA.TABLES
WHERE  TABLE_SCHEMA = DATABASE()
ORDER  BY TABLE_NAME
"""

DESCRIBE_TABLE = """
SELECT COLUMN_NAME,
       COLUMN_TYPE,
       IS_NULLABLE,
       COLUMN_KEY,
       COLUMN_DEFAULT,
       EXTRA
FROM   INFORMATION_SCHEMA.COLUMNS
WHERE  TABLE_SCHEMA = DATABASE()
  AND  TABLE_NAME   = %s
ORDER  BY ORDINAL_POSITION
"""

TABLE_INFO = """
SELECT TABLE_NAME,
       TABLE_ROWS,
       DATA_LENGTH,
       CREATE_TIME
FROM   INFORMATION_SCHEMA.TABLES
WHERE  TABLE_SCHEMA = DATABASE()
  AND  TABLE_NAME   = %s
"""

ROW_COUNT = "SELECT COUNT(*) AS total FROM `{table}`"


# ── Generic helpers ───────────────────────────────────────────────────────────

def ping(db: "DatabaseClient") -> bool:
    """Return True if the database is reachable."""
    try:
        rows = db.query(PING)
        return bool(rows and rows[0].get("alive") == 1)
    except Exception:
        return False


def server_version(db: "DatabaseClient") -> str:
    """Return the database server version string."""
    rows = db.query(SERVER_VERSION)
    return rows[0]["version"] if rows else "unknown"


def list_tables(db: "DatabaseClient") -> list[str]:
    """Return a list of table names in the current schema."""
    rows = db.query(LIST_TABLES)
    return [r["TABLE_NAME"] for r in rows]


def describe_table(db: "DatabaseClient", table_name: str) -> list[dict]:
    """Return column metadata for *table_name*.

    Each dict has keys: COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
    COLUMN_KEY, COLUMN_DEFAULT, EXTRA.
    """
    return db.query(DESCRIBE_TABLE, (table_name,))


def row_count(db: "DatabaseClient", table_name: str) -> int:
    """Return the number of rows in *table_name*.

    Uses a formatted table name (backtick-quoted).  ``table_name`` must come
    from a trusted source (schema introspection, not user input) since it is
    not parameterised via %s — MySQL does not support parameterised table names.
    """
    safe_name = table_name.replace("`", "")          # strip any stray backticks
    sql = ROW_COUNT.format(table=safe_name)
    rows = db.query(sql)
    return int(rows[0]["total"]) if rows else 0


def table_info(db: "DatabaseClient", table_name: str) -> dict | None:
    """Return table metadata dict, or None if the table does not exist."""
    rows = db.query(TABLE_INFO, (table_name,))
    return rows[0] if rows else None


# ── Convenience SELECT builder ────────────────────────────────────────────────

def select_where(
    db: "DatabaseClient",
    table: str,
    conditions: dict[str, Any],
    columns: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Execute a SELECT with WHERE clauses built from *conditions*.

    Args:
        db:         Active :class:`~database.db_client.DatabaseClient`.
        table:      Table name (must come from a trusted source).
        conditions: ``{column: value}`` pairs joined with AND.
        columns:    Column names to SELECT; defaults to ``*``.
        limit:      Optional LIMIT clause.

    Returns:
        List of row dicts.

    Example::

        rows = select_where(db, "orders", {"status": "pending", "user_id": 7})
    """
    safe_table = table.replace("`", "")
    col_clause  = ", ".join(f"`{c}`" for c in columns) if columns else "*"
    where_parts = " AND ".join(f"`{k}` = %s" for k in conditions)
    params      = tuple(conditions.values())

    sql = f"SELECT {col_clause} FROM `{safe_table}` WHERE {where_parts}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    return db.query(sql, params)
