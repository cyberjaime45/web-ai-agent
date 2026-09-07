"""Build name — the label a run is known by.

Read from ``BUILD_NAME``; blank or unset falls back to ``DEFAULT_BUILD_NAME``.
Everything that names the run (report title, LambdaTest build, summary tab)
goes through ``get_build_name`` so the fallback lives in exactly one place.
"""

from __future__ import annotations

import os

DEFAULT_BUILD_NAME = "Web Test Report"


def get_build_name() -> str:
    return os.getenv("BUILD_NAME", "").strip() or DEFAULT_BUILD_NAME
