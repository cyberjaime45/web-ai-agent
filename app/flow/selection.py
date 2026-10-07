"""Marker selection — which flows a run picks, the same way everywhere.

A flow's file-wide ``markers:`` line (before its first ``##``) is the flow's
selection markers: the whole file is the unit that runs, because its sections
share one page in order (a later section relies on an earlier one's login).
A ``markers:`` line under a ``##`` heading only labels that test in the report.

The filter is pytest's ``-m`` grammar — names joined by ``and`` / ``or`` /
``not`` and parentheses — evaluated by pytest's own parser, so ``pytest -m``
and the MCP ``list_flows(markers=...)`` agree on every expression. Names must
be registered in ``pytest.ini``; an unknown one is an error, never a silent
empty selection.

``non_destructive`` is a label for choosing flows. Whether a flow so labelled
really presses nothing destructive is the lint rule ``destructive-step``.
"""

from __future__ import annotations

import configparser
import re
from collections.abc import Iterable
from pathlib import Path

from _pytest.mark.expression import Expression, ParseError

_NAME_RE = re.compile(r"[A-Za-z_][\w.-]*")
_KEYWORDS = frozenset({"and", "or", "not"})
NON_DESTRUCTIVE = "non_destructive"


class SelectionError(ValueError):
    """A marker expression that does not parse or names an unregistered marker."""


def registered_markers(ini_lines: Iterable[str]) -> list[str]:
    """Marker names from pytest's ``markers`` ini lines (``name: description``)."""
    names = (line.split(":", 1)[0].split("(", 1)[0].strip() for line in ini_lines)
    return sorted({n for n in names if n})


def markers_from_ini(path: Path) -> list[str]:
    """The registered marker names in *path* (``pytest.ini``), for callers outside pytest."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return registered_markers(parser.get("pytest", "markers", fallback="").splitlines())


def compile_selection(expression: str, known: Iterable[str]) -> Expression:
    """Parse *expression*; raise SelectionError when it is malformed or names
    a marker that is not in *known*."""
    try:
        compiled = Expression.compile(expression)
    except ParseError as exc:
        raise SelectionError(f"Invalid marker expression {expression!r}: {exc.message}") from None
    known = set(known)
    unknown = sorted({n for n in _NAME_RE.findall(expression) if n not in _KEYWORDS} - known)
    if unknown:
        raise SelectionError(
            f"Unknown marker{'s' if len(unknown) > 1 else ''} {', '.join(map(repr, unknown))} "
            f"in {expression!r}; registered: {', '.join(sorted(known))}")
    return compiled


def matches(compiled: Expression, markers: Iterable[str]) -> bool:
    """True when a flow with *markers* is selected by *compiled*."""
    names = set(markers)
    return compiled.evaluate(lambda name, /, **kwargs: not kwargs and name in names)
