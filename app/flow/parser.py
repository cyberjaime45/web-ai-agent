"""
Flow Parser — Parses .md flow files into FlowDefinition objects.

Uses markdown-it-py to correctly extract list items from each ##
section (handles nested lists, inline formatting, and ordered numbers).

Syntax
──────
  keyword: "arg1" | "arg2"

  click: "Button Text"
  fill: "Username" | "admin"
  wait_load
  scroll: "down"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache

from markdown_it import MarkdownIt

from app.schemas.actions import (
    ACTION_ARG_SPEC,
    ActionType,
    FlowAction,
)

_md = MarkdownIt()


class FlowParseError(ValueError):
    """Raised when a flow step cannot be parsed."""

    def __init__(self, message: str, step_num: int = 0, raw: str = ""):
        self.step_num = step_num
        self.raw = raw
        super().__init__(message)


class UnknownActionError(FlowParseError):
    """The step keyword is not an ActionType (a comment or prose line)."""


@dataclass
class FlowDefinition:
    """Structured representation of a test flow.

    One file is a suite: ``title`` is its ``# H1`` (None when the file has
    none — ``name`` then falls back to the file stem), and every non-metadata
    ``## section`` is a test of its own in the report. ``markers`` are the
    file-wide ``markers:`` tags; ``section_markers`` the ones declared under
    a specific ``##`` heading.
    """

    name:    str
    timeout: int = 30000
    actions: list[FlowAction] = field(default_factory=list)
    title:   str | None = None
    markers: list[str] = field(default_factory=list)
    section_markers: dict[str, list[str]] = field(default_factory=dict)


# ── Section extraction ────────────────────────────────────────────────────────

# Sections reserved for metadata — NOT treated as action sections.
_METADATA_SECTIONS = frozenset({
    "config", "credentials", "expected outcome", "error scenarios", "notes",
})

_H2_RE = re.compile(r"(?:^|\n)##\s+(.+?)\s*(?=\n)", re.MULTILINE)
# `markers: smoke, regression` — a tag line, not a step (never a list item).
_MARKERS_RE = re.compile(r"^\s*markers?\s*:\s*(?P<names>[\w\s,-]+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _items_from_section(section_text: str) -> list[str]:
    """Extract list-item texts from already-isolated section content."""
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


def _sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a flow into ``(preamble, [(heading, body), ...])`` by ``##`` heading.

    The preamble is everything before the first ``##`` (title, prose,
    file-wide ``markers:``). Bodies run up to the next heading or EOF.
    """
    headers = [(m.start(), m.group(1).strip()) for m in _H2_RE.finditer(text)]
    if not headers:
        return text, []
    sections: list[tuple[str, str]] = []
    for idx, (start, heading) in enumerate(headers):
        content_start = text.index("\n", start) + 1
        content_end = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        sections.append((heading, text[content_start:content_end]))
    return text[:headers[0][0]], sections


def _all_action_sections(text: str) -> list[tuple[str, str]]:
    """Return ``(section_name, item_text)`` pairs from all non-metadata sections.

    Any ``## <heading>`` that is not in ``_METADATA_SECTIONS`` is treated as
    an action section.  This allows flow authors to use descriptive section
    names like ``## Login``, ``## FMS MCV Page``, or ``## Steps``.
    """
    return [
        (heading, item)
        for heading, body in _sections(text)[1]
        if heading.lower() not in _METADATA_SECTIONS
        for item in _items_from_section(body)
    ]


def _marker_names(block: str) -> list[str]:
    """Every tag from the ``markers:`` lines in a block, in order, de-duplicated."""
    names: list[str] = []
    for m in _MARKERS_RE.finditer(block):
        for name in m.group("names").split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return names


def _section_lines(text: str, header: str) -> list[str]:
    """
    Return every non-blank line inside a ## section.
    Used for key:value sections (Config, Credentials, Target Application).
    """
    m = _section_pattern(header).search(text)
    if not m:
        return []
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]


@lru_cache(maxsize=None)
def _section_pattern(header: str) -> re.Pattern[str]:
    """Body of ``## <header>`` up to the next ``##`` heading (compiled once)."""
    return re.compile(
        r"(?:^|\n)##\s+" + re.escape(header) + r"\s*\n(.*?)(?=\n##\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )


# ── 4-stage action parsing pipeline ──────────────────────────────────────────
#
#   raw text → _tokenize → _normalize → _validate → _build → FlowAction
#

_COLON_RE = re.compile(r"^(\w+)\s*:\s*(.*)", re.DOTALL)
_QUOTED_RE = re.compile(r'"([^"]*)"')


def _tokenize(raw: str) -> tuple[str, str]:
    """
    Stage 1: Split raw step text into (keyword, raw_args).

    Syntax: `keyword: "arg1" | "arg2"` or bare `keyword` for no-arg actions.
    """
    raw = raw.strip()

    # Colon syntax: `click: "Login"` or `fill: "Username" | "admin"`
    m = _COLON_RE.match(raw)
    if m:
        return m.group(1).lower(), m.group(2).strip()

    # Bare keyword with no colon (e.g. `wait_load`, `reload`, `back`)
    parts = raw.split(None, 1)
    keyword = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return keyword, rest


def _normalize(
    keyword: str, raw_args: str
) -> tuple[ActionType, list[str]]:
    """
    Stage 2: Resolve keyword to ActionType and parse pipe-separated arguments.

    Returns (action_type, args_list).
    """
    # Resolve action type from enum value
    try:
        action_type = ActionType(keyword)
    except ValueError:
        raise UnknownActionError(f"Unknown action keyword: '{keyword}'")

    # Parse arguments: split on pipe, strip quotes from each part
    if raw_args:
        parts = [p.strip() for p in raw_args.split("|")]
        args = []
        for part in parts:
            qm = _QUOTED_RE.search(part)
            if qm:
                args.append(qm.group(1))
            elif part:
                args.append(part)
    else:
        args = []

    return action_type, args


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
    raw: str,
    step_num: int,
) -> FlowAction:
    """Stage 4: Construct the FlowAction."""
    return FlowAction(
        type=action_type,
        args=args,
        raw=raw,
        step_num=step_num,
    )


def _parse_action(raw: str, step_num: int) -> FlowAction | None:
    """
    Parse a single step line into a FlowAction using the 4-stage pipeline.

    Returns None for blank lines. An unknown keyword (prose, a comment line)
    becomes a WAIT(0) placeholder so the step still shows in the report;
    a known keyword with the wrong argument count raises FlowParseError —
    silently turning a malformed step into a no-op would make it pass.
    """
    raw = raw.strip()
    if not raw:
        return None

    try:
        keyword, raw_args = _tokenize(raw)
        action_type, args = _normalize(keyword, raw_args)
    except UnknownActionError:
        return FlowAction(
            type=ActionType.WAIT, args=["0"], raw=raw, step_num=step_num
        )
    _validate(action_type, args, step_num, raw)
    return _build(action_type, args, raw, step_num)


# ── Flow path resolution ──────────────────────────────────────────────────────


def resolve_flow_path(reference: str, base_dir: Path) -> Path:
    """Resolve a flow reference to an absolute .md file path.

    Accepted forms:
      "sso_login"        → base_dir/sso_login.md
      "common/login"     → base_dir/common/login.md
      "common/login.md"  → base_dir/common/login.md
    """
    ref = reference.strip()
    # Try with .md extension added
    if not ref.endswith(".md"):
        candidate = base_dir / f"{ref}.md"
        if candidate.is_file():
            return candidate
    # Try as-is
    candidate = base_dir / ref
    if candidate.is_file():
        return candidate
    raise FlowParseError(
        f"Flow file not found: '{reference}' "
        f"(looked in {base_dir})"
    )


# ── Public API ────────────────────────────────────────────────────────────────


def parse_flow_markdown(text: str, name: str = "inline") -> FlowDefinition:
    """Parse raw Markdown text into a FlowDefinition.

    *name* is used as the fallback flow name when no ``# H1`` heading is
    present (e.g. ``filepath.stem`` for file-based flows, ``"inline"`` for
    content passed via ``--flow``).
    """
    flow = FlowDefinition(name=name)

    # H1 heading → suite title and flow name (name keeps the fallback otherwise)
    h1 = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
    if h1:
        flow.title = flow.name = h1.group(1).strip()

    # ── markers: file-wide before the first ##, per test under its heading ──
    preamble, sections = _sections(text)
    flow.markers = _marker_names(preamble)
    for heading, body in sections:
        if heading.lower() in _METADATA_SECTIONS:
            continue
        if names := _marker_names(body):
            flow.section_markers[heading] = names

    # ── Config: only `timeout` is consumed (page default timeout) ──
    for line in _section_lines(text, "Config"):
        m = re.match(r"[-*]?\s*(\w+)\s*:\s*(.+)", line)
        if m and m.group(1).lower() == "timeout":
            flow.timeout = int(re.sub(r"[^\d]", "", m.group(2)) or "30000")

    # ── Steps — every non-metadata ## section (Credentials, Notes… are skipped) ──
    for step_num, (section_name, raw) in enumerate(_all_action_sections(text), start=1):
        action = _parse_action(raw, step_num=step_num)
        if action:
            action.section = section_name
            flow.actions.append(action)

    return flow


def parse_flow_file(filepath: Path) -> FlowDefinition:
    """Parse a single .md flow file into a FlowDefinition."""
    return parse_flow_markdown(
        text=filepath.read_text(encoding="utf-8"),
        name=filepath.stem,
    )


def load_all_flows(flows_dir: Path | str = "tests") -> dict[str, FlowDefinition]:
    """Load every .md flow file under any ``flows/`` directory below *flows_dir*.

    Flows live at ``tests/<app>/flows/`` (components included), so the walk
    is recursive and keyed by flow name.
    """
    flows_path = Path(flows_dir)
    if not flows_path.exists():
        raise FileNotFoundError(f"Flows directory not found: {flows_path}")

    flows: dict[str, FlowDefinition] = {}
    for md_file in sorted(flows_path.rglob("*.md")):
        if "flows" not in md_file.relative_to(flows_path).parts:
            continue
        flow = parse_flow_file(md_file)
        flows[flow.name] = flow

    return flows


if __name__ == "__main__":
    all_flows = load_all_flows()
    for f in all_flows.values():
        print(f"\n{f.name}  ({len(f.actions)} actions)")
        for act in f.actions:
            print(f"  {act.step_num:>2}. {act.type.value:<20} {act.args}")
