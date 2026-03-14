"""
tools.database package — Relational database access layer for the QA Web Agent.

Public surface:
    DatabaseClient  — connection lifecycle, query/execute methods
    DatabaseConfig  — env-var based configuration object
    DatabaseError   — raised on any connection or query failure

Quick start::

    from tools.database import DatabaseClient

    with DatabaseClient.from_env() as db:
        rows = db.query(
            "SELECT id, name FROM users WHERE active = %s", (1,)
        )
        for row in rows:
            print(row["id"], row["name"])

Required environment variables (add to .env):
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

Optional helpers:
    from tools.database.queries import list_tables, describe_table, ping
    from tools.database.models  import Row, QueryResult, TableInfo
"""

from tools.database.config import DatabaseConfig
from tools.database.client import DatabaseClient, DatabaseError, RawResult

__all__ = [
    "DatabaseClient",
    "DatabaseConfig",
    "DatabaseError",
    "RawResult",
]
