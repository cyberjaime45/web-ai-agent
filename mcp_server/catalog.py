"""Flow catalog and environment allow-list — what a client may run, and where.

Flows are read with the Web Agent's own parser; nothing here executes one.
For each flow the catalog works out every site it opens (its ``goto`` steps
and those of the components it calls with ``run_flow``) and from that the
environments it may run against. A ``goto`` written as ``<NAME>`` takes its
URL from the run's inputs (``run_flow(inputs=...)``) or else from this
process's environment; the flow lists such names as ``inputs``.

The environment allow-list is the server's own file plus, when the
orchestrator supplies one (``JANUS_ENVIRONMENTS_FILE``), the environments it
knows: both files are re-read on every call, so a change applies without a
restart.
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


def load_environments(path: Path, extra: Path | None = None) -> dict[str, Environment]:
    """The allow-list, keyed by lower-case name: *path*, plus the environments of
    *extra* when given. The same name in both merges their hosts; an environment
    is production when either file says so."""
    environments = _load_environments(path)
    if extra is not None and extra.is_file():          # the orchestrator may not have written it yet
        for name, more in _load_environments(extra).items():
            own = environments.get(name)
            environments[name] = more if own is None else Environment(
                name=name, description=own.description or more.description,
                hosts=tuple(dict.fromkeys([*own.hosts, *more.hosts])),
                production=own.production or more.production,
                allow_file_urls=own.allow_file_urls or more.allow_file_urls)
    return environments


def _load_environments(path: Path) -> dict[str, Environment]:
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

    def __init__(self, config: AdapterConfig, environments: dict[str, Environment] | None = None) -> None:
        self._config = config
        self._environments = environments      # given once (tests); None: read from the files on every call

    # ── environments ────────────────────────────────────────────────────────

    @property
    def environments(self) -> dict[str, Environment]:
        if self._environments is not None:
            return self._environments
        try:
            self._last_good = load_environments(self._config.environments_file, self._config.extra_environments_file)
        except ConfigError:
            if not hasattr(self, "_last_good"):     # unreadable from the start: let the server say so
                raise
        return self._last_good

    def environment(self, name: str) -> Environment | None:
        return self.environments.get((name or "").strip().lower())

    def enabled(self, env: Environment) -> bool:
        return self._config.allow_production or not env.production

    def environment_infos(self) -> list[EnvironmentInfo]:
        return [
            EnvironmentInfo(name=e.name, description=e.description, hosts=list(e.hosts),
                            production=e.production, enabled=self.enabled(e))
            for e in self.environments.values()
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

    def get(self, flow_id: str, inputs: dict[str, str] | None = None) -> FlowEntry | None:
        """The flow with this id, or None — also for anything that is not a
        catalog flow (a path outside the folder, a component, a non-.md file).
        *inputs* fill the flow's ``<NAME>`` sites for this call."""
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
            return self._entry(path.relative_to(root).as_posix(), path, inputs)
        except (FlowParseError, OSError, UnicodeDecodeError):
            return None

    def _entry(self, flow_id: str, path: Path, inputs: dict[str, str] | None = None) -> FlowEntry:
        flow = parse_flow_file(path)
        if not flow.actions:
            raise FlowParseError("no steps found (a flow needs a ## section with list items)")
        targets, names, problems = _targets(flow, path.parent, inputs or {})
        if problems or not targets:
            environments: list[str] = []      # where it runs cannot be established
        else:
            environments = [e.name for e in self.environments.values()
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
                inputs=sorted(names),
                profiles=list(flow.profiles),
                steps=len(flow.actions),
            ),
            path=path,
        )


def _targets(flow: FlowDefinition, flows_dir: Path, inputs: dict[str, str], depth: int = 0,
             seen: frozenset[str] = frozenset()) -> tuple[set[str], set[str], list[str]]:
    """``(sites, placeholders, problems)``: every host the flow opens — components
    included, resolved from the top flow's folder as the engine does — the
    ``<NAME>`` placeholders those sites come from, and why any could not be
    worked out."""
    targets: set[str] = set()
    names: set[str] = set()
    problems: list[str] = []
    for action in flow.actions:
        if action.type == ActionType.GOTO and action.args:
            target, name, problem = _site(action.args[0], inputs)
            if name:
                names.add(name)
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
            sub_targets, sub_names, sub_problems = _targets(sub, flows_dir, inputs, depth + 1, seen | {ref})
            targets |= sub_targets
            names |= sub_names
            problems += sub_problems
    return targets, names, problems


def _site(url: str, inputs: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    """``(host, placeholder, problem)`` of a ``goto`` argument: a ``<NAME>``
    placeholder is filled from *inputs*, else from the environment."""
    url = url.strip()
    name = None
    if m := _PLACEHOLDER_RE.match(url):
        name = m.group(1)
        value = inputs.get(name) or os.environ.get(name)
        if not value:
            return None, name, f"goto {url}: {name} is neither a run input nor an environment variable"
        url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return FILE_TARGET, name, None
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return parsed.hostname.lower().rstrip("."), name, None
    return None, name, f"goto {url!r}: not an http(s) or file URL"
