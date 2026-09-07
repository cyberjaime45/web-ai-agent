"""Typed application settings, loaded once from the environment.

``.env`` is loaded here so every entry point (pytest via conftest, the CLI via
main.py) sees the same configuration. Import ``settings`` instead of calling
``os.getenv`` — every value the runtime reads is a field below, so this file is
the single source of truth for what configuration the application accepts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _bool(key: str, default: str = "true") -> bool:
    return _str(key, default).lower() not in ("false", "0", "no")


def _int(key: str, default: int) -> int:
    try:
        return int(_str(key, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # ── Environment ───────────────────────────────────────────────
    environment:   str  = field(default_factory=lambda: _str("ENVIRONMENT", "staging"))

    # ── Execution mode ────────────────────────────────────────────
    running_mode:  str  = field(default_factory=lambda: _str("RUNNING_MODE", "local").lower())

    # ── Browser (local mode) ──────────────────────────────────────
    browser:       str  = field(default_factory=lambda: _str("BROWSER", "chromium").lower())
    headless:      bool = field(default_factory=lambda: _bool("HEADLESS", "true"))
    slow_mo:       int  = field(default_factory=lambda: _int("SLOW_MO", 0))
    viewport:      str  = field(default_factory=lambda: _str("VIEWPORT", "1920x1080"))

    # ── LambdaTest (lambda mode) ──────────────────────────────────
    lt_username:   str  = field(default_factory=lambda: _str("LT_USERNAME"))
    lt_access_key: str  = field(default_factory=lambda: _str("LT_ACCESS_KEY"))

    # ── AI (Layer 3, optional) ────────────────────────────────────
    ai_provider:   str  = field(default_factory=lambda: _str("AI_PROVIDER"))
    llm_key:       str  = field(default_factory=lambda: _str("LLM_KEY"))
    llm_model:     str  = field(default_factory=lambda: _str("LLM_MODEL"))

    # ── Reporting ─────────────────────────────────────────────────
    # Extra sensitive key substrings (comma-separated) redacted from
    # report network headers/payloads, on top of the built-in list.
    report_redact: str  = field(default_factory=lambda: _str("REPORT_REDACT"))

    @property
    def remote(self) -> bool:
        return self.running_mode == "lambda"

    @property
    def report_dir(self) -> Path:
        """reports/<environment>/ — anchored to the project root, not the cwd."""
        return PROJECT_ROOT / "reports" / self.environment

    @property
    def images_dir(self) -> Path:
        return self.report_dir / "images"

    def run_label(self) -> str:
        """``staging · chromium · headless[ · lambda]`` for console and banner."""
        mode = "headless" if self.headless else "headed"
        label = f"{self.environment} · {self.browser} · {mode}"
        return f"{label} · lambda" if self.remote else label


# Singleton — import this everywhere instead of calling os.getenv() directly
settings = Settings()
