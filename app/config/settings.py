"""
Typed application settings loaded from environment variables.

Usage:
    from config.settings import settings

    if settings.running_mode == "lambda":
        ...

All env vars are documented here — this file is the single source of truth
for what configuration the application accepts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(key: str, default: str = "true") -> bool:
    return os.getenv(key, default).lower() not in ("false", "0", "no")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # ── Environment ───────────────────────────────────────────────
    environment:       str  = field(default_factory=lambda: os.getenv("ENVIRONMENT", "staging"))

    # ── Execution mode ────────────────────────────────────────────
    running_mode:      str  = field(default_factory=lambda: os.getenv("RUNNING_MODE", "local"))

    # ── Browser ───────────────────────────────────────────────────
    browser:           str  = field(default_factory=lambda: os.getenv("BROWSER", "chromium"))
    headless:          bool = field(default_factory=lambda: _bool("HEADLESS", "true"))
    slow_mo:           int  = field(default_factory=lambda: _int("SLOW_MO", 0))

    # ── LambdaTest ────────────────────────────────────────────────
    lt_username:       str  = field(default_factory=lambda: os.getenv("LT_USERNAME", ""))
    lt_access_key:     str  = field(default_factory=lambda: os.getenv("LT_ACCESS_KEY", ""))
    lt_grid_url:       str  = field(default_factory=lambda: os.getenv("LT_GRID_URL", ""))

    # ── AI ────────────────────────────────────────────────────────
    openai_api_key:    str  = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model:      str  = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    # ── Timeouts (ms) ─────────────────────────────────────────────
    navigation_timeout: int = field(default_factory=lambda: _int("NAVIGATION_TIMEOUT", 30000))
    action_timeout:     int = field(default_factory=lambda: _int("ACTION_TIMEOUT", 10000))

    # ── Reporting ─────────────────────────────────────────────────
    coverage:          int  = field(default_factory=lambda: _int("COVERAGE", 0))
    coverage_target:   int  = field(default_factory=lambda: _int("COVERAGE_TARGET", 80))
    theme_style:       str  = field(default_factory=lambda: os.getenv("THEME_STYLE", "system"))

    # ── Artifact capture ──────────────────────────────────────────
    capture_screenshots:     bool = field(default_factory=lambda: _bool("CAPTURE_SCREENSHOTS", "true"))
    capture_html_snapshots:  bool = field(default_factory=lambda: _bool("CAPTURE_HTML_SNAPSHOTS", "true"))


# Singleton — import this everywhere instead of calling os.getenv() directly
settings = Settings()
