"""
Flow Parser — Parses .md flow files into FlowDefinition objects.

Uses markdown-it-py to correctly extract list items from each ##
section (handles nested lists, inline formatting, and ordered numbers).

Supported syntax
────────────────
Old (space-separated):
  click "Button Text"
  fill "Username" with "admin"
  fill "Username" "admin"

New (colon-pipe):
  click: "Button Text"
  fill: "Username" | "admin"

Both syntaxes are fully supported and can be mixed within a flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from markdown_it import MarkdownIt

from app.schemas.actions import (
    ACTION_ALIASES,
    ACTION_ARG_SPEC,
    ActionType,
    FlowAction,
    _NEGATED_ALIASES,
    _OLD_VALUE_MAP,
)

_md = MarkdownIt()


class FlowParseError(ValueError):
    """Raised when a flow step cannot be parsed."""

    def __init__(self, message: str, step_num: int = 0, raw: str = ""):
        self.step_num = step_num
        self.raw = raw
        super().__init__(message)


@dataclass
class FlowDefinition:
    """Structured representation of a test flow."""

    name:             str
    url:              str = ""
    description:      str = ""
    timeout:          int = 30000
    credentials:      dict[str, str]   = field(default_factory=dict)
    steps:            list[str]        = field(default_factory=list)    # raw text (AI compat)
    actions:          list[FlowAction] = field(default_factory=list)    # parsed (runner)
    expected_outcome: list[str]        = field(default_factory=list)
    error_scenarios:  list[str]        = field(default_factory=list)
    notes:            list[str]        = field(default_factory=list)
    raw_markdown:     str = ""


# ── Section extraction ────────────────────────────────────────────────────────


def _section_items(text: str, header: str) -> list[str]:
    """
    Extract all list-item texts from a ## section using markdown-it-py.
    Handles both ordered (1. 2. 3.) and unordered (- *) lists.
    """
    # Isolate the section between its ## heading and the next ## heading
    pattern = re.compile(
        r"(?:^|\n)##\s+" + re.escape(header) + r"\s*\n(.*?)(?=\n##\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return []

    section_text = m.group(1)
    tokens = _md.parse(section_text)

    items: list[str] = []
    in_item = False
    for token in tokens:
        if token.type == "list_item_open":
            in_item = True
        elif token.type == "list_item_close":
            in_item = False
        elif token.type == "inline" and in_item and token.content.strip():
            items.append(token.content.strip())

    return items


def _section_lines(text: str, header: str) -> list[str]:
    """
    Return every non-blank line inside a ## section.
    Used for key:value sections (Config, Credentials, Target Application).
    """
    pattern = re.compile(
        r"(?:^|\n)##\s+" + re.escape(header) + r"\s*\n(.*?)(?=\n##\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return []
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]


# ── 4-stage action parsing pipeline ──────────────────────────────────────────
#
#   raw text → _tokenize → _normalize → _validate → _build → FlowAction
#

_COLON_RE = re.compile(r"^(\w+)\s*:\s*(.*)", re.DOTALL)
_QUOTED_RE = re.compile(r'"([^"]*)"')


def _tokenize(raw: str) -> tuple[str, str, str]:
    """
    Stage 1: Split raw step text into (keyword, raw_args, syntax_format).

    Detects colon syntax (new) vs space-separated (old).
    """
    raw = raw.strip()

    # Try new colon syntax first: `click: "Login"`
    m = _COLON_RE.match(raw)
    if m:
        return m.group(1).lower(), m.group(2).strip(), "new"

    # Old space-separated syntax: `click "Login"`
    parts = raw.split(None, 1)
    keyword = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return keyword, rest, "old"


def _normalize(
    keyword: str, raw_args: str, syntax: str
) -> tuple[ActionType, list[str], bool]:
    """
    Stage 2: Resolve keyword to ActionType and parse arguments.

    Returns (action_type, args_list, negated).
    """
    negated = keyword in _NEGATED_ALIASES

    # Resolve action type: try enum value, then aliases, then old value map
    action_type: ActionType | None = None
    try:
        action_type = ActionType(keyword)
    except ValueError:
        action_type = ACTION_ALIASES.get(keyword) or _OLD_VALUE_MAP.get(keyword)

    if action_type is None:
        raise FlowParseError(f"Unknown action keyword: '{keyword}'")

    # Parse arguments based on syntax format
    if syntax == "new":
        # New syntax: split on pipe, strip quotes from each part
        if raw_args:
            parts = [p.strip() for p in raw_args.split("|")]
            args = []
            for part in parts:
                # Strip surrounding quotes if present
                qm = _QUOTED_RE.search(part)
                if qm:
                    args.append(qm.group(1))
                elif part:
                    args.append(part)
        else:
            args = []
    else:
        # Old syntax: strip "with" separator, extract quoted args
        rest_clean = re.sub(r"\bwith\b", "", raw_args, count=1).strip()
        args = _QUOTED_RE.findall(rest_clean)
        # For bare unquoted single args: wait 2000, scroll down
        if not args and rest_clean:
            args = [rest_clean.strip()]

    return action_type, args, negated


def _validate(
    action_type: ActionType, args: list[str], step_num: int, raw: str
) -> None:
    """
    Stage 3: Validate argument count against ACTION_ARG_SPEC.
    """
    spec = ACTION_ARG_SPEC.get(action_type)
    if spec is None:
        return  # No spec defined — skip validation

    min_args, max_args = spec
    n = len(args)
    if n < min_args or n > max_args:
        if min_args == max_args:
            expected = f"exactly {min_args}"
        else:
            expected = f"{min_args}-{max_args}"
        raise FlowParseError(
            f"Step {step_num}: '{action_type.value}' expects {expected} "
            f"arg(s), got {n}. Raw: {raw!r}",
            step_num=step_num,
            raw=raw,
        )


def _build(
    action_type: ActionType,
    args: list[str],
    negated: bool,
    raw: str,
    step_num: int,
) -> FlowAction:
    """Stage 4: Construct the FlowAction."""
    return FlowAction(
        type=action_type,
        args=args,
        raw=raw,
        step_num=step_num,
        negated=negated,
    )


def _parse_action(raw: str, step_num: int) -> FlowAction | None:
    """
    Parse a single step line into a FlowAction using the 4-stage pipeline.

    Returns None for blank lines. Falls back to WAIT(0) for unknown keywords
    so the AI planner can still consume flow.steps[].
    """
    raw = raw.strip()
    if not raw:
        return None

    try:
        keyword, raw_args, syntax = _tokenize(raw)
        action_type, args, negated = _normalize(keyword, raw_args, syntax)
        _validate(action_type, args, step_num, raw)
        return _build(action_type, args, negated, raw, step_num)
    except FlowParseError:
        # Unknown keyword — keep as a raw WAIT(0) placeholder so the AI planner
        # can still consume flow.steps[] while the deterministic runner skips it.
        return FlowAction(
            type=ActionType.WAIT, args=["0"], raw=raw, step_num=step_num
        )


# ── Public API ────────────────────────────────────────────────────────────────


def parse_flow_markdown(text: str, name: str = "inline") -> FlowDefinition:
    """Parse raw Markdown text into a FlowDefinition.

    *name* is used as the fallback flow name when no ``# H1`` heading is
    present (e.g. ``filepath.stem`` for file-based flows, ``"inline"`` for
    content passed via ``--flow``).
    """
    flow = FlowDefinition(name=name, raw_markdown=text)

    # H1 heading → flow name
    h1 = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    if h1:
        flow.name = h1.group(1).strip()

    # ── Config (new format) ──────────────────────────────────────
    for line in _section_lines(text, "Config"):
        m = re.match(r"[-*]?\s*(\w+)\s*:\s*(.+)", line)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "url":
                flow.url = val
            elif key == "timeout":
                flow.timeout = int(re.sub(r"[^\d]", "", val) or "30000")
            elif key == "description":
                flow.description = val

    # ── Target Application (legacy format) ──────────────────────
    for line in _section_lines(text, "Target Application"):
        m_url  = re.match(r"[-*]\s+\*\*URL\*\*:\s*(.+)", line)
        m_desc = re.match(r"[-*]\s+\*\*Description\*\*:\s*(.+)", line)
        if m_url:
            flow.url = m_url.group(1).strip()
        if m_desc:
            flow.description = m_desc.group(1).strip()

    # ── Credentials ──────────────────────────────────────────────
    for line in _section_lines(text, "Credentials"):
        # Bold format:  - **Username**: student
        m_bold = re.match(r"[-*]\s+\*\*(\w+)\*\*:\s*(.+)", line)
        # Plain format: - username: student
        m_plain = re.match(r"[-*]?\s*(\w+)\s*:\s*(.+)", line)
        if m_bold:
            flow.credentials[m_bold.group(1).lower()] = m_bold.group(2).strip()
        elif m_plain:
            flow.credentials[m_plain.group(1).lower()] = m_plain.group(2).strip()

    # ── Steps ────────────────────────────────────────────────────
    for raw in _section_items(text, "Steps"):
        flow.steps.append(raw)
        action = _parse_action(raw, step_num=len(flow.steps))
        if action:
            flow.actions.append(action)

    # ── Expected Outcome / Error Scenarios / Notes ────────────────
    flow.expected_outcome = _section_items(text, "Expected Outcome")
    flow.error_scenarios  = _section_items(text, "Error Scenarios")
    flow.notes            = _section_items(text, "Notes")

    return flow


def parse_flow_file(filepath: Path) -> FlowDefinition:
    """Parse a single .md flow file into a FlowDefinition."""
    return parse_flow_markdown(
        text=filepath.read_text(encoding="utf-8"),
        name=filepath.stem,
    )


def load_all_flows(flows_dir: Path | str = "src/flows") -> dict[str, FlowDefinition]:
    """Load all .md flow files from the given directory."""
    flows_path = Path(flows_dir)
    if not flows_path.exists():
        raise FileNotFoundError(f"Flows directory not found: {flows_path}")

    flows: dict[str, FlowDefinition] = {}
    for md_file in sorted(flows_path.glob("*.md")):
        flow = parse_flow_file(md_file)
        flows[flow.name] = flow

    return flows


if __name__ == "__main__":
    from rich import print as rprint

    all_flows = load_all_flows()
    for name, f in all_flows.items():
        rprint(f"\n[bold cyan]{f.name}[/bold cyan]  ({len(f.actions)} actions)")
        for act in f.actions:
            rprint(f"  {act.step_num:>2}. {act.type.value:<20} {act.args}")
