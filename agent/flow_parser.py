"""
Flow Parser — Reads .md flow files from the flows/ directory
and converts them into structured FlowDefinition objects that
the AI planner and executor can consume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FlowDefinition:
    """Structured representation of a test flow parsed from markdown."""

    name: str
    url: str
    description: str = ""
    credentials: dict[str, str] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)
    expected_outcome: list[str] = field(default_factory=list)
    error_scenarios: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_markdown: str = ""


def parse_flow_file(filepath: Path) -> FlowDefinition:
    """Parse a single .md flow file into a FlowDefinition."""
    text = filepath.read_text(encoding="utf-8")
    flow = FlowDefinition(
        name=filepath.stem,
        url="",
        raw_markdown=text,
    )

    current_section: Optional[str] = None
    section_lines: dict[str, list[str]] = {}

    for line in text.splitlines():
        stripped = line.strip()

        # Detect section headers (## Level)
        header_match = re.match(r"^##\s+(.+)$", stripped)
        if header_match:
            current_section = header_match.group(1).strip().lower()
            section_lines.setdefault(current_section, [])
            continue

        if current_section:
            section_lines.setdefault(current_section, []).append(stripped)

    # --- Parse Target Application ---
    for line in section_lines.get("target application", []):
        url_match = re.match(r"[-*]\s+\*\*URL\*\*:\s*(.+)", line)
        if url_match:
            flow.url = url_match.group(1).strip()
        desc_match = re.match(r"[-*]\s+\*\*Description\*\*:\s*(.+)", line)
        if desc_match:
            flow.description = desc_match.group(1).strip()

    # --- Parse Credentials ---
    for line in section_lines.get("credentials", []):
        cred_match = re.match(r"[-*]\s+\*\*(\w+)\*\*:\s*(.+)", line)
        if cred_match:
            flow.credentials[cred_match.group(1).strip().lower()] = cred_match.group(2).strip()

    # --- Parse Steps ---
    for line in section_lines.get("steps", []):
        step_match = re.match(r"^\d+\.\s+(.+)$", line)
        if step_match:
            flow.steps.append(step_match.group(1).strip())

    # --- Parse Expected Outcome ---
    for line in section_lines.get("expected outcome", []):
        item_match = re.match(r"^[-*]\s+(.+)$", line)
        if item_match:
            flow.expected_outcome.append(item_match.group(1).strip())

    # --- Parse Error Scenarios ---
    for line in section_lines.get("error scenarios", []):
        item_match = re.match(r"^[-*]\s+(.+)$", line)
        if item_match:
            flow.error_scenarios.append(item_match.group(1).strip())

    # --- Parse Notes ---
    for line in section_lines.get("notes", []):
        item_match = re.match(r"^[-*]\s+(.+)$", line)
        if item_match:
            flow.notes.append(item_match.group(1).strip())

    return flow


def load_all_flows(flows_dir: Path | str = "flows") -> dict[str, FlowDefinition]:
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
    # Quick test
    from rich import print as rprint

    all_flows = load_all_flows()
    for name, flow in all_flows.items():
        rprint(f"\n[bold cyan]Flow: {name}[/bold cyan]")
        rprint(f"  URL: {flow.url}")
        rprint(f"  Credentials: {flow.credentials}")
        rprint(f"  Steps: {len(flow.steps)}")
        for i, step in enumerate(flow.steps, 1):
            rprint(f"    {i}. {step}")
