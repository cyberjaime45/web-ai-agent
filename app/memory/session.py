"""
Short-term memory — current session state.

Tracks everything the agent has done and observed within the current
test session: actions executed, page snapshots, step outcomes.

Designed to feed into the orchestrator's context window so the agent
can make decisions based on what has already happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShortTermMemory:
    """In-process session state — cleared at the start of each flow run."""

    actions_taken:  list[str]        = field(default_factory=list)
    page_snapshots: list[str]        = field(default_factory=list)   # URLs visited
    observations:   list[str]        = field(default_factory=list)   # free-text notes
    scratch:        dict[str, Any]   = field(default_factory=dict)   # arbitrary k/v

    def record_action(self, description: str) -> None:
        self.actions_taken.append(description)

    def record_page(self, url: str) -> None:
        if not self.page_snapshots or self.page_snapshots[-1] != url:
            self.page_snapshots.append(url)

    def observe(self, note: str) -> None:
        self.observations.append(note)

    def clear(self) -> None:
        self.actions_taken.clear()
        self.page_snapshots.clear()
        self.observations.clear()
        self.scratch.clear()

    def summary(self) -> str:
        """Return a compact text summary suitable for an LLM context window."""
        lines = []
        if self.page_snapshots:
            lines.append(f"Pages visited: {' → '.join(self.page_snapshots)}")
        if self.actions_taken:
            lines.append(f"Actions taken ({len(self.actions_taken)}): "
                         + ", ".join(self.actions_taken[-5:]))
        if self.observations:
            lines.append("Observations: " + "; ".join(self.observations[-3:]))
        return "\n".join(lines) if lines else "No activity recorded."
