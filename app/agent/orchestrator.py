"""
Orchestrator — run one flow end to end outside pytest (the CLI, other agents).

    flow file / Markdown → parser → BrowserSession page (profile) → FlowRunner → FlowResult

The same pieces the pytest plugin uses: ``BrowserSession`` for the browser
and context, a ``PageRecorder`` so console errors and requests feed the
oracle, ``wait_stable`` and failure evidence, and ``FlowRunner`` for the
steps. There is no HTML report or Playwright trace here — those belong to
the pytest run. For in-process callers this is the public entry point:
``Orchestrator(profile="mobile").run_file(path)``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.browser import profiles
from app.browser.session import BrowserSession
from app.execution.engine import FlowRunner
from app.flow.parser import FlowDefinition, parse_flow_file, parse_flow_markdown
from app.observability.recorder import PageRecorder
from app.schemas.actions import FlowResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """Drives a single flow from definition to FlowResult."""

    def __init__(
        self,
        artifacts_dir: str | Path | None = None,
        flows_dir: str | Path = "tests",
        profile: str = profiles.DESKTOP,
    ) -> None:
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.flows_dir = Path(flows_dir)
        self.profile = profiles.validate([profile])[0]

    def run_file(self, path: Path) -> FlowResult:
        """Parse a .md file and execute it; ``run_flow`` references resolve from its folder."""
        self.flows_dir = path.parent
        return self.run(parse_flow_file(path))

    def run_markdown(self, markdown: str, name: str = "inline") -> FlowResult:
        """Parse inline Markdown and execute it."""
        return self.run(parse_flow_markdown(markdown, name=name))

    def run(self, flow: FlowDefinition) -> FlowResult:
        """Execute a parsed FlowDefinition and return the result."""
        logger.info("[orchestrator] Starting flow: %s (%d actions)", flow.name, len(flow.actions))
        session = BrowserSession()
        try:
            with session.page(flow.name, self.profile) as page:
                page.set_default_timeout(flow.timeout)
                recorder = PageRecorder()
                recorder.attach(page)
                runner = FlowRunner(artifacts_dir=self.artifacts_dir, flows_dir=self.flows_dir,
                                    profile=self.profile)
                result = runner.run(flow, page, recorder=recorder)
        finally:
            session.close()
        logger.info("[orchestrator] Flow '%s' — %s (%d/%d steps passed)", flow.name,
                    "PASSED" if result.success else "FAILED", result.passed, len(result.steps))
        return result
