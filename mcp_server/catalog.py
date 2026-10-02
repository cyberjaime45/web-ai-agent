"""Flow catalog and environment allow-list — what a client may run, and where.

Flows are read with the Web Agent's own parser; nothing here executes one.
For each flow the catalog works out every site it opens (its ``goto`` steps
and those of the components it calls with ``run_flow``) and from that the
environments it may run against.
"""

from __future__ import annotations

import fnmatch
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.flow.parser import (
    FlowDefinition,
    FlowParseError,
    parse_flow_file,
    resolve_flow_path,
)
from app.schemas.actions import ActionType
from mcp_server.config import AdapterConfig, ConfigError
from mcp_server.models import EnvironmentInfo, FlowInfo, UnavailableFlow

FILE_TARGET = "file://"          # how a local file page shows up among a flow's hosts
_GENERIC_SECTIONS = frozenset({"steps"})   # the generic heading: the test is named after the flow
_SKIP_DIRS = frozenset({"_framework", "components", "baselines", "generated", "fixtures"})
_PLACEHOLDER_RE = re.compile(r"^<([A-Z_][A-Z0-9_]*)>$")
_MAX_DEPTH = 5                   # the engine's own nesting limit for run_flow


@dataclass(frozen=True)
class Environment:
    name: str
    description: str = ""
    hosts: tuple[str, ...] = ()
    production: bool = False
    allow_file_urls: bool = False

    def owns(self, target: str) -> bool:
        if target == FILE_TARGET:
            return self.allow_file_urls
        return any(fnmatch.fnmatchcase(target, pattern) for pattern in self.hosts)


def load_environments(path: Path) -> dict[str, Environment]:
    """The allow-list, keyed by lower-case name."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"environments file not readable: {path} ({exc})") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"environments file is not valid TOML: {path} ({exc})") from exc
    environments: dict[str, Environment] = {}
    for name, spec in (data.get("environments") or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"environment {name!r} must be a table in {path}")
        hosts = spec.get("hosts") or []
        if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
            raise ConfigError(f"environment {name!r}: hosts must be a list of strings")
        environments[name.lower()] = Environment(
            name=name.lower(),
            description=str(spec.get("description", "")),
            hosts=tuple(h.strip().lower() for h in hosts if h.strip()),
            production=bool(spec.get("production", False)),
            allow_file_urls=bool(spec.get("allow_file_urls", False)),
        )
    if not environments:
        raise ConfigError(f"no environments defined in {path}")
    return environments


@dataclass(frozen=True)
class FlowEntry:
    info: FlowInfo
    path: Path          # absolute


class Catalog:
    """The flows under the configured folder. Read from disk on every call, so
    a flow added or edited is visible without restarting the server."""

    def __init__(self, config: AdapterConfig, environments: dict[str, Environment]) -> None:
        self._config = config
        self._environments = environments

    # ── environments ────────────────────────────────────────────────────────

    def environment(self, name: str) -> Environment | None:
        return self._environments.get((name or "").strip().lower())

    def enabled(self, env: Environment) -> bool:
        return self._config.allow_production or not env.production

    def environment_infos(self) -> list[EnvironmentInfo]:
        return [
            EnvironmentInfo(name=e.name, description=e.description, hosts=list(e.hosts),
                            production=e.production, enabled=self.enabled(e))
            for e in self._environments.values()
        ]

    # ── flows ───────────────────────────────────────────────────────────────

    def list(self) -> tuple[list[FlowEntry], list[UnavailableFlow]]:
        entries: list[FlowEntry] = []
        unavailable: list[UnavailableFlow] = []
        root = self._config.flows_dir
        for path in sorted(root.rglob("*.md")):
            if _SKIP_DIRS & set(path.relative_to(root).parts[:-1]):
                continue
            flow_id = path.relative_to(root).as_posix()
            try:
                entries.append(self._entry(flow_id, path))
            except (FlowParseError, OSError, UnicodeDecodeError) as exc:
                unavailable.append(UnavailableFlow(id=flow_id, reason=f"cannot be read as a flow: {exc}"))
        return entries, unavailable

    def get(self, flow_id: str) -> FlowEntry | None:
        """The flow with this id, or None — also for anything that is not a
        catalog flow (a path outside the folder, a component, a non-.md file)."""
        flow_id = (flow_id or "").strip()
        if not flow_id or not flow_id.endswith(".md"):
            return None
        root = self._config.flows_dir
        path = (root / flow_id).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        if _SKIP_DIRS & set(path.relative_to(root).parts[:-1]):
            return None
        try:
            return self._entry(path.relative_to(root).as_posix(), path)
        except (FlowParseError, OSError, UnicodeDecodeError):
            return None

    def _entry(self, flow_id: str, path: Path) -> FlowEntry:
        flow = parse_flow_file(path)
        if not flow.actions:
            raise FlowParseError("no steps found (a flow needs a ## section with list items)")
        targets, problems = _targets(flow, path.parent)
        if problems or not targets:
            environments: list[str] = []      # where it runs cannot be established
        else:
            environments = [e.name for e in self._environments.values()
                            if all(e.owns(t) for t in targets)]
        tests = list(dict.fromkeys(
            a.section for a in flow.actions if a.section and a.section.lower() not in _GENERIC_SECTIONS))
        return FlowEntry(
            info=FlowInfo(
                id=flow_id,
                title=flow.title or flow.name,
                tests=tests or [flow.title or flow.name],
                markers=sorted({*flow.markers, *(m for ms in flow.section_markers.values() for m in ms)}),
                expected=list(flow.expected),
                hosts=sorted(targets),
                environments=environments,
                profiles=list(flow.profiles),
                steps=len(flow.actions),
            ),
            path=path,
        )


def _targets(flow: FlowDefinition, flows_dir: Path, depth: int = 0,
             seen: frozenset[str] = frozenset()) -> tuple[set[str], list[str]]:
    """``(sites, problems)``: every host the flow opens — components included,
    resolved from the top flow's folder as the engine does — and why any could
    not be worked out."""
    targets: set[str] = set()
    problems: list[str] = []
    for action in flow.actions:
        if action.type == ActionType.GOTO and action.args:
            target, problem = _site(action.args[0])
            if target:
                targets.add(target)
            if problem:
                problems.append(problem)
        elif action.type == ActionType.RUN_FLOW and action.args:
            ref = action.args[0]
            if ref in seen or depth >= _MAX_DEPTH:
                problems.append(f"run_flow {ref!r}: circular or too deeply nested")
                continue
            try:
                sub = parse_flow_file(resolve_flow_path(ref, flows_dir))
            except (FlowParseError, OSError) as exc:
                problems.append(f"run_flow {ref!r}: {exc}")
                continue
            sub_targets, sub_problems = _targets(sub, flows_dir, depth + 1, seen | {ref})
            targets |= sub_targets
            problems += sub_problems
    return targets, problems


def _site(url: str) -> tuple[str | None, str | None]:
    """The host of a ``goto`` argument (``<ENV_VAR>`` placeholders resolved), or the problem."""
    url = url.strip()
    if m := _PLACEHOLDER_RE.match(url):
        value = os.environ.get(m.group(1))
        if not value:
            return None, f"goto {url}: environment variable {m.group(1)} is not set"
        url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return FILE_TARGET, None
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return parsed.hostname.lower().rstrip("."), None
    return None, f"goto {url!r}: not an http(s) or file URL"
