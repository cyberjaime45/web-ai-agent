"""
database/models.py — Lightweight data containers for query results.

These are plain Python dataclasses — no ORM, no magic.  They give callers
typed, attribute-accessible objects instead of raw dicts or tuples, making
agent logic easier to read and test.

Add a new dataclass here whenever a query returns a well-known result shape
that is used in more than one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Generic row container ─────────────────────────────────────────────────────

@dataclass
class Row:
    """A single result row returned as a dict-backed object.

    Provides both attribute access (``row.column_name``) and dict-style access
    (``row["column_name"]``) so callers can choose the style that reads best.

    Example::

        rows = db.query("SELECT id, email FROM users WHERE active = %s", (1,))
        for row in rows:
            print(row.id, row.email)
    """

    _data: dict = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__!r} has no attribute {name!r}. "
                f"Available columns: {list(self._data)}"
            )

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def to_dict(self) -> dict:
        """Return a plain dict copy of this row."""
        return dict(self._data)

    def __repr__(self) -> str:
        pairs = ", ".join(f"{k}={v!r}" for k, v in self._data.items())
        return f"Row({pairs})"


# ── Query result wrapper ──────────────────────────────────────────────────────

@dataclass
class QueryResult:
    """Wrapper around a list of :class:`Row` objects.

    Provides convenience accessors so callers do not need to index lists
    manually for the common single-row or first-row cases.

    Example::

        result = db.query_result("SELECT * FROM products WHERE id = %s", (42,))
        product = result.first()   # Row or None
        all_rows = result.rows     # list[Row]
    """

    rows: list[Row] = field(default_factory=list)
    row_count: int = 0

    def first(self) -> Row | None:
        """Return the first row, or ``None`` if the result set is empty."""
        return self.rows[0] if self.rows else None

    def one(self) -> Row:
        """Return exactly one row.  Raises if zero or more than one row found."""
        if len(self.rows) != 1:
            raise ValueError(
                f"Expected exactly 1 row, got {len(self.rows)}."
            )
        return self.rows[0]

    def column(self, name: str) -> list[Any]:
        """Return a flat list of values for a single column across all rows."""
        return [r[name] for r in self.rows]

    def is_empty(self) -> bool:
        return len(self.rows) == 0

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def __bool__(self) -> bool:
        return bool(self.rows)


# ── Domain models ─────────────────────────────────────────────────────────────
# Add project-specific models below as needed.
# Each model maps to the columns returned by a specific query.

@dataclass
class TableInfo:
    """Metadata about a database table — returned by :data:`~queries.TABLE_INFO`."""

    table_name: str
    table_rows: int | None
    data_length: int | None
    create_time: Any | None

    @classmethod
    def from_row(cls, row: Row) -> "TableInfo":
        return cls(
            table_name  = row["TABLE_NAME"],
            table_rows  = row["TABLE_ROWS"],
            data_length = row["DATA_LENGTH"],
            create_time = row["CREATE_TIME"],
        )
