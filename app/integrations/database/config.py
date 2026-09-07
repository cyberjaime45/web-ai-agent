"""
database/config.py — Database connection configuration.

All values are read from environment variables so credentials are never
hard-coded.  Load your .env file before importing this module (the project
app.config.settings loads ``.env`` on import).

Required env vars (set in .env):
    DB_HOST       — hostname or IP of the database server  (default: localhost)
    DB_PORT       — TCP port                               (default: 3306)
    DB_USER       — database username
    DB_PASSWORD   — database password
    DB_NAME       — database / schema name
    DB_CHARSET    — connection charset                     (default: utf8mb4)
    DB_CONNECT_TIMEOUT — seconds before a connection attempt times out (default: 10)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConfig:
    """Immutable connection configuration object.

    Construct via :func:`from_env` to pull values from environment variables,
    or instantiate directly when writing tests.
    """

    host: str
    user: str
    password: str
    database: str
    port: int = 3306
    charset: str = "utf8mb4"
    connect_timeout: int = 10

    # ── Factory ─────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Build a :class:`DatabaseConfig` from environment variables.

        Raises :class:`EnvironmentError` if any required variable is missing.
        """
        missing = [v for v in ("DB_USER", "DB_PASSWORD", "DB_NAME") if not os.getenv(v)]
        if missing:
            raise EnvironmentError(
                f"Missing required database environment variables: {', '.join(missing)}. "
                "Add them to your .env file."
            )

        return cls(
            host            = os.getenv("DB_HOST", "localhost"),
            port            = int(os.getenv("DB_PORT", "3306")),
            user            = os.environ["DB_USER"],
            password        = os.environ["DB_PASSWORD"],
            database        = os.environ["DB_NAME"],
            charset         = os.getenv("DB_CHARSET", "utf8mb4"),
            connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        )

    # ── Helpers ─────────────────────────────────────────────────

    def as_pymysql_kwargs(self) -> dict:
        """Return a kwargs dict suitable for ``pymysql.connect(**kwargs)``."""
        return {
            "host":            self.host,
            "port":            self.port,
            "user":            self.user,
            "password":        self.password,
            "database":        self.database,
            "charset":         self.charset,
            "connect_timeout": self.connect_timeout,
            "cursorclass":     None,   # overridden in DatabaseClient
        }

    def __repr__(self) -> str:
        # Never expose the password in logs / reprs.
        return (
            f"DatabaseConfig(host={self.host!r}, port={self.port}, "
            f"user={self.user!r}, database={self.database!r})"
        )
