"""Web Agent MCP configuration — every ``WEB_AGENT_MCP_*`` variable, read once.

Only the Web Agent MCP reads these; the Web Agent's own configuration stays in
``app/config/settings.py``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigError(ValueError):
    """The Web Agent MCP cannot start with this configuration."""


def _path(key: str, default: str) -> Path:
    """A path from the environment; relative paths are taken from the project root."""
    return (PROJECT_ROOT / Path(os.getenv(key, "").strip() or default).expanduser()).resolve()


def _positive(key: str, default: float) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be greater than zero, got {raw!r}")
    return value


def _flag(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    return default if not raw else raw not in ("false", "0", "no", "off")


@dataclass(frozen=True)
class AdapterConfig:
    project_root: Path
    flows_dir: Path             # WEB_AGENT_MCP_FLOWS_DIR — the flows a client may run
    executions_dir: Path        # WEB_AGENT_MCP_EXECUTIONS_DIR — one folder per execution
    environments_file: Path     # WEB_AGENT_MCP_ENVIRONMENTS_FILE — the environment allow-list
    extra_environments_file: Path | None   # JANUS_ENVIRONMENTS_FILE — more environments, from the orchestrator
    timeout_seconds: float      # WEB_AGENT_MCP_TIMEOUT_SECONDS — an execution is stopped after this
    stop_grace_seconds: float   # WEB_AGENT_MCP_STOP_GRACE_SECONDS — interrupt → terminate → kill
    max_concurrent: int         # WEB_AGENT_MCP_MAX_CONCURRENT — others wait as QUEUED
    headless: bool              # WEB_AGENT_MCP_HEADLESS — executions never open a window by default
    allow_production: bool      # WEB_AGENT_MCP_ALLOW_PRODUCTION — off unless set
    python: str                 # the interpreter flows run under (this one)


def load_config() -> AdapterConfig:
    config = AdapterConfig(
        project_root=PROJECT_ROOT,
        flows_dir=_path("WEB_AGENT_MCP_FLOWS_DIR", "tests"),
        executions_dir=_path("WEB_AGENT_MCP_EXECUTIONS_DIR", "reports/_executions"),
        environments_file=_path("WEB_AGENT_MCP_ENVIRONMENTS_FILE", "mcp_server/environments.toml"),
        extra_environments_file=_path("JANUS_ENVIRONMENTS_FILE", "") if os.getenv("JANUS_ENVIRONMENTS_FILE", "").strip()
        else None,
        timeout_seconds=_positive("WEB_AGENT_MCP_TIMEOUT_SECONDS", 1800),
        stop_grace_seconds=_positive("WEB_AGENT_MCP_STOP_GRACE_SECONDS", 20),
        max_concurrent=int(_positive("WEB_AGENT_MCP_MAX_CONCURRENT", 1)),
        headless=_flag("WEB_AGENT_MCP_HEADLESS", True),
        allow_production=_flag("WEB_AGENT_MCP_ALLOW_PRODUCTION", False),
        python=sys.executable,
    )
    # pytest only loads the project's conftest.py for files inside the project.
    if not config.flows_dir.is_relative_to(config.project_root):
        raise ConfigError(f"WEB_AGENT_MCP_FLOWS_DIR must be inside {config.project_root}, got {config.flows_dir}")
    if not config.flows_dir.is_dir():
        raise ConfigError(f"flows directory not found: {config.flows_dir}")
    return config
