"""Flow lint — static checks over flow files, and the healed-steps report.

No browser, no LLM: flows go through the real parser and each rule looks at
the parsed steps. Every finding is advice; ``main.py lint --strict`` is what
turns findings into a non-zero exit.

    unknown-step        a line whose keyword is not an action runs as a no-op
    fixed-wait          ``wait: <ms>`` — prefer wait_stable / wait_for_*
    duplicate-step      the same check, wait or goto twice in a row (a repeated
                        click or check can be deliberate: a counter, the next box)
    no-assertion        a section that never checks anything (components exempt)
    literal-secret      a literal typed into a password / token field
    missing-component   a run_flow reference that does not resolve
    unused-component    a components/ flow nothing calls
    repeated-steps      3+ steps also found in another flow — a component candidate
    parse-error         the file does not parse

``healings(report files)`` lists steps that passed only through L2 / L3 in
report JSON files — the UI text changed and the flow target is due an update.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from app.flow.parser import FlowParseError, parse_flow_markdown, resolve_flow_path
from app.schemas.actions import SKILL_ACTIONS, ActionType, FlowAction

REPEAT_MIN = 3          # consecutive steps shared with another flow before it is reported
_SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__"}
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_PLACEHOLDER_RE = re.compile(r"^<[A-Z_][A-Z0-9_]*>$")
_SECRET_FIELD_RE = re.compile(r"pass(word|code|phrase)?\b|secret|token|api[\s_-]?key|\bpin\b", re.IGNORECASE)

# Steps that verify something: a section with none of these only proves nothing errored.
VERIFYING: frozenset[ActionType] = frozenset({
    ActionType.ASSERT_TEXT, ActionType.ASSERT_NOT_TEXT, ActionType.ASSERT_VISIBLE,
    ActionType.ASSERT_HIDDEN, ActionType.ASSERT_URL, ActionType.ASSERT_ENABLED,
    ActionType.ASSERT_DISABLED, ActionType.ASSERT_CHECKED, ActionType.WAIT_FOR_TEXT,
    ActionType.WAIT_FOR_URL, ActionType.WAIT_FOR_ELEMENT, ActionType.FIND_ROW,
    ActionType.READ_ROW, ActionType.AI_ASSERT,
}) | SKILL_ACTIONS

# Steps that cannot change the page: running one twice in a row is always redundant.
_IDEMPOTENT: frozenset[ActionType] = (VERIFYING - SKILL_ACTIONS) | {
    ActionType.GOTO, ActionType.WAIT_LOAD, ActionType.WAIT_STABLE, ActionType.ASSERT_URL,
}


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


@dataclass
class _Flow:
    path: Path
    actions: list[FlowAction]
    lines: list[int]            # 1-based source line of each action

    @property
    def is_component(self) -> bool:
        return "components" in self.path.parts


def flow_files(paths: list[Path]) -> list[Path]:
    """Every ``.md`` file under *paths* (files are taken as given), sorted."""
    found: set[Path] = set()
    for p in paths:
        if p.is_file() and p.suffix == ".md":
            found.add(p)
        elif p.is_dir():
            found.update(f for f in p.rglob("*.md") if not _SKIP_DIRS & set(f.parts))
    return sorted(found)


def _source_lines(text: str, actions: list[FlowAction]) -> list[int]:
    """Line number of each action: the next list item whose text is its raw step."""
    items = [(n, _LIST_MARKER_RE.sub("", line).strip())
             for n, line in enumerate(text.splitlines(), start=1) if _LIST_MARKER_RE.match(line)]
    out, cursor = [], 0
    for action in actions:
        hit = next((i for i in range(cursor, len(items)) if items[i][1] == action.raw), None)
        if hit is None:
            out.append(items[cursor][0] if cursor < len(items) else 1)
        else:
            out.append(items[hit][0])
            cursor = hit + 1
    return out


def _sections(flow: _Flow) -> list[list[int]]:
    """Indexes of *flow*'s actions grouped by ``## section``, in order."""
    groups: dict[str, list[int]] = {}
    for i, action in enumerate(flow.actions):
        groups.setdefault(action.section, []).append(i)
    return list(groups.values())


def _step_rules(flow: _Flow, rel: str) -> list[Finding]:
    out: list[Finding] = []
    for i, action in enumerate(flow.actions):
        line, raw = flow.lines[i], action.raw
        if action.type == ActionType.WAIT and action.args == ["0"] and not raw.lower().startswith("wait"):
            keyword = raw.split(":", 1)[0].split()[0] if raw.split() else raw
            out.append(Finding(rel, line, "unknown-step",
                               f"'{keyword}' is not an action keyword, so this step does nothing"))
        elif action.type == ActionType.WAIT:
            ms = action.args[0] if action.args else "1000"
            if ms.isdigit() and int(ms) > 0:
                out.append(Finding(rel, line, "fixed-wait",
                                   f"fixed wait of {ms} ms; prefer wait_stable, wait_for_text or wait_for_element"))
        if action.type in (ActionType.FILL, ActionType.TYPE) and len(action.args) == 2:
            target, value = action.args
            if value and not _PLACEHOLDER_RE.match(value) and _SECRET_FIELD_RE.search(target):
                out.append(Finding(rel, line, "literal-secret",
                                   f"literal value typed into '{target}'; use a <PLACEHOLDER> set in .env"))
        prev = flow.actions[i - 1] if i else None
        if (prev is not None and prev.section == action.section and prev.raw == raw
                and action.type in _IDEMPOTENT):
            out.append(Finding(rel, line, "duplicate-step", "same as the previous step"))
    if not flow.is_component:
        for idx in _sections(flow):
            if not any(flow.actions[i].type in VERIFYING for i in idx):
                name = flow.actions[idx[0]].section or "Steps"
                out.append(Finding(rel, flow.lines[idx[0]], "no-assertion",
                                   f"section '{name}' never checks anything; add an assert_* step"))
    return out


def _run_flow_refs(flow: _Flow, rel: str) -> tuple[set[Path], list[Finding]]:
    used: set[Path] = set()
    missing: list[Finding] = []
    for i, action in enumerate(flow.actions):
        if action.type != ActionType.RUN_FLOW:
            continue
        try:
            used.add(resolve_flow_path(action.args[0], flow.path.parent).resolve())
        except FlowParseError:
            missing.append(Finding(rel, flow.lines[i], "missing-component",
                                   f"run_flow '{action.args[0]}' does not resolve from {flow.path.parent}"))
    return used, missing


def _repeated_steps(flows: list[_Flow], rel) -> list[Finding]:
    """Runs of REPEAT_MIN+ steps already seen, in the same order, in an earlier flow."""
    first: dict[tuple[str, ...], tuple[Path, int]] = {}
    windows: list[tuple[_Flow, list[int], list[tuple[str, ...]]]] = []
    for flow in flows:
        if flow.is_component:
            continue
        for idx in _sections(flow):
            keys = [tuple(flow.actions[j].raw for j in idx[k:k + REPEAT_MIN])
                    for k in range(len(idx) - REPEAT_MIN + 1)]
            for k, key in enumerate(keys):
                first.setdefault(key, (flow.path, flow.lines[idx[k]]))
            windows.append((flow, idx, keys))

    out: list[Finding] = []
    for flow, idx, keys in windows:
        k = 0
        while k < len(keys):
            origin = first[keys[k]]
            if origin[0] == flow.path:
                k += 1
                continue
            end = k
            while end + 1 < len(keys) and first[keys[end + 1]][0] == origin[0]:
                end += 1
            length = end - k + REPEAT_MIN
            out.append(Finding(rel(flow.path), flow.lines[idx[k]], "repeated-steps",
                               f"{length} steps also in {rel(origin[0])}:{origin[1]}; "
                               "consider a components/ sub-flow called with run_flow"))
            k = end + 1
    return out


def lint(paths: list[Path], root: Path | None = None) -> list[Finding]:
    """Findings for every flow file under *paths*, paths shown relative to *root*."""
    root = (root or Path.cwd()).resolve()

    def rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(root))
        except ValueError:
            return str(p)

    findings: list[Finding] = []
    flows: list[_Flow] = []
    for path in flow_files(paths):
        text = path.read_text(encoding="utf-8")
        try:
            parsed = parse_flow_markdown(text, name=path.stem)
        except FlowParseError as exc:
            line = next((n for n, ln in enumerate(text.splitlines(), 1) if exc.raw and exc.raw in ln), 1)
            findings.append(Finding(rel(path), line, "parse-error", str(exc)))
            continue
        if parsed.actions:
            flows.append(_Flow(path, parsed.actions, _source_lines(text, parsed.actions)))

    used: set[Path] = set()
    for flow in flows:
        findings += _step_rules(flow, rel(flow.path))
        refs, missing = _run_flow_refs(flow, rel(flow.path))
        used |= refs
        findings += missing
    for flow in flows:
        if flow.is_component and flow.path.resolve() not in used:
            findings.append(Finding(rel(flow.path), 1, "unused-component",
                                    "no scanned flow calls this component with run_flow"))
    findings += _repeated_steps(flows, rel)
    return sorted(findings, key=lambda f: (f.path, f.line, f.rule))


def healings(report_files: list[Path]) -> list[dict]:
    """Steps healed by L2 / L3 in report JSON files, most frequent first."""
    seen: Counter[tuple[str, str, str, str]] = Counter()
    for report in report_files:
        data = json.loads(report.read_text(encoding="utf-8"))
        for test in data.get("tests", []):
            for h in test.get("healings") or []:
                seen[(test.get("file") or "", test.get("name") or "",
                      h.get("description") or "", h.get("healed_by") or "")] += 1
    return [{"file": f, "test": t, "step": s, "healed_by": by, "reports": n}
            for (f, t, s, by), n in seen.most_common()]


def to_dict(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]
