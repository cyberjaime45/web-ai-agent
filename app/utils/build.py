"""Build name — the label a run is known by.

Read from ``BUILD_NAME``; blank or unset falls back to ``DEFAULT_BUILD_NAME``.
Everything that names the run (report title, LambdaTest build, summary tab)
goes through ``get_build_name`` so the fallback lives in exactly one place.
"""

from __future__ import annotations

import os
import re

DEFAULT_BUILD_NAME = "Web Test Report"


def get_build_name() -> str:
    return os.getenv("BUILD_NAME", "").strip() or DEFAULT_BUILD_NAME


def build_slug(name: str | None = None) -> str:
    """Filename-safe form of the build name: lowercase, runs of anything
    that is not a letter or digit collapse to one underscore.
    ``"Release 4.2 Smoke"`` → ``release_4_2_smoke``; ``"Web Test Report"`` →
    ``web_test_report``. Never empty."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or get_build_name()).lower()).strip("_")
    return slug or "build"
