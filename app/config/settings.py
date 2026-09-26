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

    # ── Device profiles ───────────────────────────────────────────
    # Default profile(s) a flow runs under when neither `--profile` nor the
    # flow's `## Config` says otherwise; comma-separated (desktop, mobile).
    profile:       str  = field(default_factory=lambda: _str("PROFILE", "desktop").lower())
    # Playwright device descriptor behind the `mobile` profile.
    mobile_device: str  = field(default_factory=lambda: _str("MOBILE_DEVICE", "iPhone 13"))

    # ── Failure evidence ──────────────────────────────────────────
    # on-failure keeps a Playwright trace (traces/<flow>__<profile>.zip) for
    # flows that fail; off records nothing. Recording runs for every flow
    # either way — the decision to keep is only known at the end.
    trace:         str  = field(default_factory=lambda: _str("TRACE", "on-failure").lower())
    # Dismiss cookie banners / modals before each L1 attempt.
    dismiss_blockers: bool = field(default_factory=lambda: _bool("DISMISS_BLOCKERS", "false"))
    # Run a flow with a failed section once more (pytest); a section that
    # passes then is reported "passed on retry", one that fails again is a
    # consistent failure. A flow opts out with `rerun: false` in ## Config.
    rerun_failed: bool = field(default_factory=lambda: _bool("RERUN_FAILED", "false"))

    # ── Safety (autonomous skills) ────────────────────────────────
    # true lets explore_page / the planner press controls that look
    # destructive (delete, pay, send…) — for disposable test environments.
    allow_destructive: bool = field(default_factory=lambda: _bool("ALLOW_DESTRUCTIVE", "false"))

    # ── Oracle (automatic checks after navigation-class steps) ────
    # warn: record checks on the step, never fail it. strict: a failed
    # error-severity check fails the step. off: no automatic checks.
    oracle:        str  = field(default_factory=lambda: _str("ORACLE", "warn").lower())

    # ── Reporting ─────────────────────────────────────────────────
    # Extra sensitive key substrings (comma-separated) redacted from
    # report network headers/payloads, on top of the built-in list.
    report_redact: str  = field(default_factory=lambda: _str("REPORT_REDACT"))

    @property
    def remote(self) -> bool:
        return self.running_mode == "lambda"

    @property
    def trace_on_failure(self) -> bool:
        return self.trace == "on-failure"

    @property
    def report_dir(self) -> Path:
        """reports/<environment>/ — anchored to the project root, not the cwd."""
        return PROJECT_ROOT / "reports" / self.environment

    @property
    def images_dir(self) -> Path:
        return self.report_dir / "images"

    @property
    def traces_dir(self) -> Path:
        return self.report_dir / "traces"

    def run_label(self) -> str:
        """``staging · chromium · headless[ · lambda]`` for console and banner."""
        mode = "headless" if self.headless else "headed"
        label = f"{self.environment} · {self.browser} · {mode}"
        return f"{label} · lambda" if self.remote else label


# Singleton — import this everywhere instead of calling os.getenv() directly
settings = Settings()
