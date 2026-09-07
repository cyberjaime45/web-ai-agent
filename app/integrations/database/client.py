"""
database/db_client.py — Database connection lifecycle and query execution.

Supports:
  • MySQL / MariaDB via ``pymysql`` (lightweight, pure-Python, no C extension)
  • Context-manager usage (``with DatabaseClient.from_env() as db:``)
  • Parameterized queries throughout — no string interpolation of user data
  • Connection reuse with explicit open/close and auto-reconnect on stale connections
  • Thread-safe cursor handling (one cursor per query, always closed after use)

Install the driver (choose one):
    pip install pymysql                  # recommended for automation tooling
    pip install mysql-connector-python   # official Oracle driver (heavier)

SQLAlchemy note:
    This client intentionally avoids SQLAlchemy to keep the dependency
    footprint minimal.  If ORM support is ever needed, :class:`DatabaseClient`
    can be wrapped or replaced without touching agent code — just keep the
    same public interface.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, NamedTuple

from app.integrations.database.config import DatabaseConfig

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Raised for any database-level failure (connection, query, etc.)."""


class RawResult(NamedTuple):
    """Return value of :meth:`DatabaseClient.raw`.

    Attributes:
        rows:        List of tuples — one tuple per row, column order matches
                     ``columns``.  Empty list when the statement produces no
                     result set (DDL, DML without RETURNING, etc.).
        columns:     Column names in the order they appear in ``rows``.
                     Empty list when there is no result set.
        rowcount:    Rows affected (DML) or -1 when not applicable.
        lastrowid:   Auto-increment ID of the last inserted row, or ``None``.

    Example::

        result = db.raw("SELECT id, email FROM users WHERE id = %s", (1,))
        for row in result.rows:
            print(dict(zip(result.columns, row)))   # → {"id": 1, "email": "…"}
    """

    rows:      list[tuple]
    columns:   list[str]
    rowcount:  int
    lastrowid: int | None


class DatabaseClient:
    """MySQL / MariaDB client with a clean, minimal public API.

    Typical usage — context manager (recommended)::

        from database.db_client import DatabaseClient

        with DatabaseClient.from_env() as db:
            rows = db.query(
                "SELECT id, name FROM users WHERE status = %s",
                ("active",),
            )
            for row in rows:
                print(row["id"], row["name"])

    Manual lifecycle::

        db = DatabaseClient.from_env()
        db.connect()
        try:
            count = db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]
        finally:
            db.close()
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self._config     = config
        self._connection = None   # pymysql.Connection or None

    # ── Factory constructors ─────────────────────────────────────

    @classmethod
    def from_env(cls) -> "DatabaseClient":
        """Create a client whose config is read from environment variables.

        See :class:`~database.config.DatabaseConfig` for the expected env var
        names (``DB_HOST``, ``DB_USER``, ``DB_PASSWORD``, ``DB_NAME``, …).
        """
        return cls(DatabaseConfig.from_env())

    @classmethod
    def from_config(cls, config: DatabaseConfig) -> "DatabaseClient":
        """Create a client from an explicit :class:`~database.config.DatabaseConfig`."""
        return cls(config)

    # ── Connection lifecycle ─────────────────────────────────────

    def connect(self) -> None:
        """Open the database connection.

        Safe to call even if already connected — re-uses the existing
        connection rather than opening a duplicate.

        Raises:
            DatabaseError: if the connection attempt fails.
        """
        if self._connection is not None and self._is_alive():
            return

        try:
            import pymysql                          # deferred import — not required at module level
            import pymysql.cursors

            kwargs = self._config.as_pymysql_kwargs()
            kwargs["cursorclass"] = pymysql.cursors.DictCursor   # rows as dicts
            self._connection = pymysql.connect(**kwargs)
            logger.info(
                "Connected to %s@%s:%s/%s",
                self._config.user,
                self._config.host,
                self._config.port,
                self._config.database,
            )
        except Exception as exc:
            self._connection = None
            raise DatabaseError(f"Could not connect to database: {exc}") from exc

    def close(self) -> None:
        """Close the connection gracefully.  Safe to call multiple times."""
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("Database connection closed.")
            except Exception as exc:
                logger.warning("Error closing database connection: %s", exc)
            finally:
                self._connection = None

    def _is_alive(self) -> bool:
        """Return True if the current connection is still usable."""
        try:
            self._connection.ping(reconnect=False)
            return True
        except Exception:
            return False

    def _ensure_connected(self) -> None:
        """Reconnect if the connection is absent or stale."""
        if self._connection is None or not self._is_alive():
            logger.debug("Connection is absent or stale — reconnecting.")
            self._connection = None
            self.connect()

    # ── Context manager support ──────────────────────────────────

    def __enter__(self) -> "DatabaseClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return False   # do not suppress exceptions

    # ── Query execution ──────────────────────────────────────────

    def query(self, sql: str, params: tuple | None = None) -> list[dict]:
        """Execute a SELECT statement and return all rows as a list of dicts.

        Args:
            sql:    A parameterized SQL string using ``%s`` placeholders.
            params: A tuple of values to bind.  Never interpolate values
                    directly into the SQL string.

        Returns:
            A list of ``dict`` objects, one per row.  Empty list if no rows.

        Raises:
            DatabaseError: on any query failure.

        Example::

            rows = db.query(
                "SELECT id, email FROM users WHERE role = %s AND active = %s",
                ("admin", 1),
            )
        """
        self._ensure_connected()
        with self._cursor() as cursor:
            try:
                cursor.execute(sql, params)
                return cursor.fetchall() or []
            except Exception as exc:
                raise DatabaseError(f"Query failed: {exc}\nSQL: {sql}") from exc

    def query_one(self, sql: str, params: tuple | None = None) -> dict | None:
        """Execute a SELECT and return only the first row, or None.

        Useful when you expect at most one result (e.g. lookup by primary key).

        Example::

            user = db.query_one(
                "SELECT * FROM users WHERE id = %s", (user_id,)
            )
            if user:
                print(user["email"])
        """
        self._ensure_connected()
        with self._cursor() as cursor:
            try:
                cursor.execute(sql, params)
                return cursor.fetchone()
            except Exception as exc:
                raise DatabaseError(f"Query failed: {exc}\nSQL: {sql}") from exc

    def execute(self, sql: str, params: tuple | None = None) -> int:
        """Execute an INSERT / UPDATE / DELETE statement.

        Commits automatically after a successful execution.

        Args:
            sql:    A parameterized SQL string.
            params: A tuple of bound values.

        Returns:
            The number of rows affected.

        Raises:
            DatabaseError: on any execution failure (rolls back automatically).

        Example::

            affected = db.execute(
                "UPDATE sessions SET active = %s WHERE user_id = %s",
                (0, user_id),
            )
        """
        self._ensure_connected()
        with self._cursor() as cursor:
            try:
                cursor.execute(sql, params)
                self._connection.commit()
                return cursor.rowcount
            except Exception as exc:
                self._connection.rollback()
                raise DatabaseError(f"Execute failed: {exc}\nSQL: {sql}") from exc

    def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        """Execute a parameterized statement for multiple rows in one batch.

        More efficient than calling :meth:`execute` in a loop for bulk inserts.

        Returns:
            Total rows affected.

        Example::

            db.execute_many(
                "INSERT INTO events (name, ts) VALUES (%s, %s)",
                [("login", t1), ("logout", t2)],
            )
        """
        if not params_list:
            return 0
        self._ensure_connected()
        with self._cursor() as cursor:
            try:
                cursor.executemany(sql, params_list)
                self._connection.commit()
                return cursor.rowcount
            except Exception as exc:
                self._connection.rollback()
                raise DatabaseError(f"execute_many failed: {exc}\nSQL: {sql}") from exc

    # ── Raw execution ────────────────────────────────────────────

    def raw(
        self,
        sql: str,
        params: tuple | None = None,
        *,
        commit: bool = False,
    ) -> RawResult:
        """Execute *any* SQL statement and return a :class:`RawResult`.

        Unlike :meth:`query` and :meth:`execute`, this method:

        * Makes **no assumptions** about the statement type — use it for
          ``SELECT``, ``INSERT``, ``UPDATE``, ``DELETE``, ``CREATE``,
          ``DROP``, ``ALTER``, ``TRUNCATE``, ``CALL``, ``SET``, ``SHOW``, etc.
        * Returns **raw tuples** plus column metadata — you control how to
          interpret the result.
        * Does **not** auto-commit — pass ``commit=True`` to commit, or
          manage the transaction yourself with :meth:`transaction`.

        Args:
            sql:     Any valid SQL statement.  Use ``%s`` placeholders for
                     values that come from external input.
            params:  Tuple of bound values, or ``None`` for no parameters.
            commit:  If ``True``, commit after successful execution.  Useful
                     for one-off DDL/DML calls outside a transaction block.

        Returns:
            A :class:`RawResult` namedtuple with ``rows``, ``columns``,
            ``rowcount``, and ``lastrowid``.

        Raises:
            DatabaseError: on any execution failure.

        Examples::

            # Plain SELECT — raw tuples
            res = db.raw("SELECT id, email FROM users WHERE active = %s", (1,))
            headers = res.columns               # ["id", "email"]
            for row in res.rows:
                print(dict(zip(headers, row)))  # {"id": 1, "email": "…"}

            # DDL — no result set, just confirm it ran
            db.raw("CREATE TABLE IF NOT EXISTS tmp_ids (id INT)", commit=True)

            # Stored procedure
            res = db.raw("CALL generate_report(%s)", ("2024-01",))

            # SHOW statement
            res = db.raw("SHOW TABLES")
            tables = [row[0] for row in res.rows]

            # SET session variable (no commit needed)
            db.raw("SET SESSION wait_timeout = %s", (300,))
        """
        self._ensure_connected()
        import pymysql.cursors

        # Use a plain (tuple-returning) cursor so the caller gets unprocessed data.
        cursor = self._connection.cursor(pymysql.cursors.Cursor)
        try:
            cursor.execute(sql, params)

            # Fetch rows only when the statement produced a result set.
            rows: list[tuple] = []
            columns: list[str] = []
            if cursor.description is not None:
                rows    = list(cursor.fetchall() or [])
                columns = [col[0] for col in cursor.description]

            if commit:
                self._connection.commit()

            return RawResult(
                rows      = rows,
                columns   = columns,
                rowcount  = cursor.rowcount,
                lastrowid = cursor.lastrowid,
            )
        except Exception as exc:
            if commit:
                self._connection.rollback()
            raise DatabaseError(f"raw() failed: {exc}\nSQL: {sql}") from exc
        finally:
            cursor.close()

    # ── Transaction context manager ──────────────────────────────

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Context manager that wraps multiple statements in a transaction.

        Commits on success, rolls back on any exception.

        Example::

            with db.transaction():
                db.execute("INSERT INTO orders ...", (...,))
                db.execute("UPDATE inventory SET qty = qty - %s ...", (...,))
        """
        self._ensure_connected()
        try:
            self._connection.begin()
            yield
            self._connection.commit()
        except Exception as exc:
            self._connection.rollback()
            raise DatabaseError(f"Transaction rolled back: {exc}") from exc

    # ── Internal helpers ─────────────────────────────────────────

    @contextmanager
    def _cursor(self):
        """Yield an open cursor and guarantee it is closed afterwards."""
        cursor = self._connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    # ── Debug / introspection ────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """True if an active connection is held."""
        return self._connection is not None and self._is_alive()

    def __repr__(self) -> str:
        status = "connected" if self.is_connected else "disconnected"
        return f"DatabaseClient({self._config!r}, status={status!r})"
