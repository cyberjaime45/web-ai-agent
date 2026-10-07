"""Flow authoring over the Web Agent MCP — what a client needs to write a flow
the Web Agent will run, and to keep it.

    describe   the actions, skills and flow format, read from the Web Agent's
               own registries (ActionType, ACTION_ARG_SPEC, SKILLS) and its
               reference documentation — never a copy kept here
    read       a flow's content and catalog entry
    validate   parse + lint flow text as the Web Agent's own ``lint`` does,
               without writing it
    save       validate, then write under the flows folder (never outside it,
               never over an existing flow unless asked)
    explore    the flow text an exploration runs: open the page, inspect it,
               test_page without submitting — its result carries the
               observation and the generated draft
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from app.flow import selection
from app.flow.lint import lint_markdown
from app.flow.parser import FlowParseError
from app.schemas.actions import ACTION_ARG_SPEC, SKILL_ACTIONS
from app.skills.base import SKILLS
from app.utils.banner import APP_VERSION
from mcp_server.catalog import _SKIP_DIRS, Catalog, FlowEntry
from mcp_server.config import AdapterConfig
from mcp_server.models import (
    ActionSpec,
    Capabilities,
    ErrorCode,
    ErrorInfo,
    LintFinding,
    SkillSpec,
    ValidationResult,
)

BLOCKING_RULES = frozenset({"parse-error", "no-steps", "unknown-step", "literal-secret", "missing-component"})
_FLOW_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*(/[a-z0-9][a-z0-9_\-]*)*\.md$")
_PLACEHOLDER_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*_(URL|EMAIL|USER|USERNAME|LOGIN|PASSWORD)$")
_INTERNAL_PREFIXES = ("WEB_AGENT_", "JANUS_", "LLM_", "LT_", "CLAUDE_", "OPENAI_", "ANTHROPIC_", "GITHUB_", "GH_")
_DOC_EXAMPLE_OPTION_RE = re.compile(r'"([a-z_]+)=([^"]*)"')
_DOC_KEYWORD_RE = re.compile(r"^#### `([a-z_]+)`\s*$", re.MULTILINE)
_DOC_GROUP_RE = re.compile(r"^## (.+?)(?: \(\d+\))?\s*$", re.MULTILINE)
_OPTION_ROW_RE = re.compile(r"^\| `([a-z_]+)` \| `?([^|`]*?)`? \| (.+?) \|\s*$", re.MULTILINE)
MAX_CONTENT = 200_000

FLOW_FORMAT = {
    "file": "Markdown, .md, under the flows folder; the id is the path under it (members_site/login.md)",
    "title": "# Title — the suite name",
    "sections": "every other ## section is a test: list items `keyword: \"arg\" | \"arg\"`; "
                "no-argument keywords omit the colon (wait_load)",
    "metadata_sections": ["Config", "Credentials", "Expected Outcome", "Error Scenarios", "Notes"],
    "config_keys": ["timeout", "profiles", "ignore_console", "ignore_network", "allow_destructive",
                    "allow_actions", "rerun", "site_domain"],
    "expected_outcome": "## Expected Outcome — one list item per expectation; shown with every test",
    "markers": "a plain line `markers: smoke, non_destructive` before the first ## selects the whole flow "
               "(pytest -m / list_flows(markers=)); under a ## heading it only labels that test. "
               "Names must be registered in pytest.ini",
    "placeholders": "{NAME} anywhere in an argument (\"{APP_URL}/path?q=1\") is filled from the run's inputs "
                    "or the environment; unset or empty fails the step; legacy <NAME> is still read; "
                    "secrets (PASSWORD, SECRET, KEY, TOKEN) are masked in reports and must be placeholders",
    "targets": "an element is named by its label, placeholder or visible text; a CSS selector (.x, #x, [x], tag[...]) "
               "or XPath (//...) is used as written",
    "components": "run_flow: \"components/name\" runs a sub-flow from the flow's folder",
    "assertions": "a section should end in an assert_* step; the lint rule no-assertion says so",
}


# ── describe ────────────────────────────────────────────────────────────────

def describe(config: AdapterConfig, tools: list[str]) -> Capabilities:
    descriptions, groups, options = _documentation(config.project_root / "docs" / "ACTIONS.md")
    actions = [ActionSpec(keyword=a.value, group=groups.get(a.value, ""), min_args=lo, max_args=hi,
                          description=descriptions.get(a.value, ""))
               for a, (lo, hi) in ACTION_ARG_SPEC.items() if a not in SKILL_ACTIONS]
    skills = [SkillSpec(keyword=a.value, description=descriptions.get(a.value) or _first_line(_doc(fn)),
                        options=options.get(a.value) or _docstring_options(_doc(fn)))
              for a, fn in SKILLS.items()]
    return Capabilities(
        web_agent_version=APP_VERSION, actions=actions, skills=sorted(skills, key=lambda s: s.keyword),
        flow_format=FLOW_FORMAT, configured_placeholders=configured_placeholders(),
        markers=selection.markers_from_ini(config.project_root / "pytest.ini"), tools=sorted(tools))


def configured_placeholders() -> list[str]:
    """Names (never values) of the environment variables a flow may reference
    as {NAME}: application URLs and credentials the Web Agent is configured with."""
    return sorted(k for k in os.environ if _PLACEHOLDER_NAME_RE.match(k) and os.environ[k].strip()
                  and not k.startswith(_INTERNAL_PREFIXES))


def _documentation(path: Path) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """Per keyword: its one-paragraph description, its group, and its option table,
    from the reference the Web Agent ships; empty when the file is not there."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}, {}, {}
    descriptions: dict[str, str] = {}
    groups: dict[str, str] = {}
    options: dict[str, dict[str, str]] = {}
    group = ""
    pieces = re.split(r"(?m)^(?=#{2,4} )", text)
    for piece in pieces:
        if m := _DOC_GROUP_RE.match(piece):
            group = m.group(1).strip()
            continue
        m = _DOC_KEYWORD_RE.match(piece)
        if not m:
            continue
        keyword = m.group(1)
        body = piece[m.end():].strip()
        paragraph = body.split("\n\n", 1)[0] if not body.startswith("```") else ""
        descriptions[keyword] = " ".join(paragraph.split())
        groups[keyword] = group
        if rows := _OPTION_ROW_RE.findall(body):
            options[keyword] = {name: f"{meaning.strip()} (default {default.strip() or '—'})"
                                for name, default, meaning in rows}
    return descriptions, groups, options


def _doc(fn) -> str:
    """A skill documents itself at the top of its module (its function has no docstring)."""
    module = sys.modules.get(getattr(fn, "__module__", "") or "")
    return fn.__doc__ or (module.__doc__ if module else "") or ""


def _docstring_options(doc: str | None) -> dict[str, str]:
    """A skill whose reference has no option table documents them in its
    docstring's example line: ``- test_page: "depth=1" | "submit=false"``."""
    return {name: f"for example {name}={value}" for name, value in _DOC_EXAMPLE_OPTION_RE.findall(doc or "")}


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().splitlines()[0].strip() if doc else ""


# ── read ────────────────────────────────────────────────────────────────────

def read(catalog: Catalog, config: AdapterConfig, flow_id: str) -> tuple[FlowEntry | None, str, ErrorInfo | None]:
    entry = catalog.get(flow_id)
    if entry is None:
        return None, "", ErrorInfo(code=ErrorCode.INVALID_REQUEST,
                                   message=f"Unknown flow {flow_id!r}. Use a flow id from list_flows.")
    return entry, entry.path.read_text(encoding="utf-8"), None


# ── validate and save ───────────────────────────────────────────────────────

def validate(catalog: Catalog, config: AdapterConfig, content: str, flow_id: str | None) -> ValidationResult:
    """Parse and lint *content* as if it were saved as *flow_id* (a folder of
    the flows tree, for component references); nothing is written."""
    flow_id = flow_id or "draft.md"
    if problem := _bad_id(flow_id):
        return ValidationResult(error=ErrorInfo(code=ErrorCode.INVALID_REQUEST, message=problem))
    if not content.strip() or len(content) > MAX_CONTENT:
        return ValidationResult(error=ErrorInfo(code=ErrorCode.INVALID_REQUEST,
                                                message="content must be non-empty flow Markdown"))
    path = (config.flows_dir / flow_id).resolve()
    findings = [LintFinding(line=f.line, rule=f.rule, message=f.message, blocking=f.rule in BLOCKING_RULES)
                for f in lint_markdown(content, path, config.project_root)]
    info = None
    try:
        info = catalog.describe_text(flow_id, content).info
    except FlowParseError:
        pass                                           # already a parse-error finding
    return ValidationResult(valid=not any(f.blocking for f in findings), findings=findings, info=info)


def save(catalog: Catalog, config: AdapterConfig, flow_id: str, content: str, overwrite: bool) -> ValidationResult:
    """Validate, then write the flow under the flows folder. An existing flow is
    kept unless *overwrite* is asked for; a flow with blocking findings is never written."""
    result = validate(catalog, config, content, flow_id)
    if result.error is not None:
        return result
    path = (config.flows_dir / flow_id).resolve()
    if path.exists() and not overwrite:
        result.error = ErrorInfo(code=ErrorCode.INVALID_REQUEST,
                                 message=f"Flow {flow_id!r} already exists; pass overwrite=true to replace it.",
                                 details={"path": str(path)})
        return result
    if not result.valid:
        blocking = "; ".join(f"line {f.line}: {f.rule}: {f.message}" for f in result.findings if f.blocking)
        result.error = ErrorInfo(code=ErrorCode.INVALID_REQUEST, message=f"The flow is not valid: {blocking}")
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    os.replace(tmp, path)
    listed = catalog.get(flow_id)
    result.info = listed.info if listed else result.info
    result.saved, result.path = flow_id, str(path)
    return result


def _bad_id(flow_id: str) -> str | None:
    if not _FLOW_ID_RE.match(flow_id or ""):
        return (f"Invalid flow id {flow_id!r}: lower-case letters, digits, _ and -, folders separated by /, "
                "ending in .md (for example atlas/login.md).")
    parts = flow_id.split("/")
    if (_SKIP_DIRS - {"components"}) & set(parts[:-1]):
        return f"Invalid flow id {flow_id!r}: {', '.join(sorted(_SKIP_DIRS - {'components'}))} are reserved folders."
    return None


# ── explore ─────────────────────────────────────────────────────────────────

def explore_markdown(url: str, depth: int, max_actions: int) -> str:
    """Open the page, inspect it, let test_page decide what to try — without
    submitting any form — and generate a draft. Credentials are never typed.
    When the orchestrator runs without an LLM (JANUS_LLM=off), the skill's own
    planner is kept off too."""
    ai = ' | "max_ai_calls=0"' if os.environ.get("JANUS_LLM", "").strip().lower() == "off" else ""
    return (f"# Exploration — {url}\n\n## Explore\n- goto: \"{url}\"\n- wait_load\n- inspect_page\n"
            f"- test_page: \"depth={depth}\" | \"max_actions={max_actions}\" | \"submit=false\"{ai}\n")


def bad_exploration(url: str, depth: int, max_actions: int) -> str | None:
    if not re.match(r"^(https?|file)://\S+$", url or ""):
        return "url must be an http(s) or file URL"
    if not 0 <= depth <= 3:
        return "depth must be between 0 and 3"
    if not 1 <= max_actions <= 50:
        return "max_actions must be between 1 and 50"
    return None
