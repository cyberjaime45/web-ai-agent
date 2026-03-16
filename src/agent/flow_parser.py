"""
Flow Parser — Parses .md flow files into FlowDefinition objects.

Uses markdown-it-py to correctly extract list items from each ##
section (handles nested lists, inline formatting, and ordered numbers).

Supported step syntax
─────────────────────
open            "https://url"
click           "Button Text"
click_link      "Link Text"
click_button    "Button Text"
fill            "Field Label" with "value"
fill            "Field Label" "value"
select          "Dropdown Label" "Option Text"
check           "Checkbox Label"
uncheck         "Checkbox Label"
assert_text     "expected text on page"
assert_title    "expected page title"
assert_url      "url-fragment"
wait            2000
wait_for_load
wait_for_element ".css-selector"
screenshot      "name"
scroll          down | up | <pixels>
hover           "Element Text"

Aliases: go_to / navigate / goto → open
         type / enter             → fill
         verify_text / assert     → assert_text
         verify_url               → assert_url
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from markdown_it import MarkdownIt

from runner.actions import ACTION_ALIASES, ActionType, FlowAction

_md = MarkdownIt()


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


# ── Action parsing ────────────────────────────────────────────────────────────


def _parse_action(raw: str, step_num: int) -> FlowAction | None:
    """
    Parse a single step line (already stripped of its list number/bullet)
    into a FlowAction.

    Examples
    ────────
    open "https://example.com"          → OPEN, ["https://example.com"]
    fill "Username" with "student"      → FILL, ["Username", "student"]
    fill "Username" "student"           → FILL, ["Username", "student"]
    click "Submit"                      → CLICK, ["Submit"]
    wait 2000                           → WAIT, ["2000"]
    wait_for_load                       → WAIT_FOR_LOAD, []
    scroll down                         → SCROLL, ["down"]
    """
    raw = raw.strip()
    if not raw:
        return None

    parts   = raw.split(None, 1)
    keyword = parts[0].lower()
    rest    = parts[1].strip() if len(parts) > 1 else ""

    # Resolve action type
    action_type: ActionType | None = None
    try:
        action_type = ActionType(keyword)
    except ValueError:
        action_type = ACTION_ALIASES.get(keyword)

    if action_type is None:
        # Unknown keyword — keep as a raw WAIT(0) placeholder so the AI planner
        # can still consume flow.steps[] while the deterministic runner skips it.
        return FlowAction(type=ActionType.WAIT, args=["0"], raw=raw, step_num=step_num)

    # Strip the literal word "with" used as a readability separator:
    #   fill "Username" with "student" → fill "Username" "student"
    rest_clean = re.sub(r"\bwith\b", "", rest, count=1).strip()

    # Extract all quoted args first
    args: list[str] = re.findall(r'"([^"]*)"', rest_clean)

    # For actions that accept bare (unquoted) single args: wait 2000, scroll down
    if not args and rest_clean:
        args = [rest_clean.strip()]

    return FlowAction(type=action_type, args=args, raw=raw, step_num=step_num)


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
