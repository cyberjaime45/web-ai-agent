"""
Agent Orchestrator — top-level runtime that drives a full flow execution.

The orchestrator is the entry point for running a flow end-to-end:
  1. Parse the flow definition (app.flow.parser)
  2. Boot a browser session (app.browser.session)
  3. Run the execution engine (app.execution.engine)
  4. Return a FlowResult for reporting

This module is a placeholder — extend it with planning, skill dispatch,
and multi-step reasoning as the agent capabilities grow.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.browser.session import create_browser
from app.execution.engine import FlowRunner
from app.flow.parser import FlowDefinition, parse_flow_file, parse_flow_markdown
from app.schemas.actions import FlowResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """Drives a single flow from definition to FlowResult."""

    def __init__(self, artifacts_dir: str | Path = "reports/local/images") -> None:
        self.artifacts_dir = Path(artifacts_dir)

    def run_file(self, path: Path) -> FlowResult:
        """Parse a .md file and execute it."""
        flow = parse_flow_file(path)
        return self.run(flow)

    def run_markdown(self, markdown: str, name: str = "inline") -> FlowResult:
        """Parse inline Markdown and execute it."""
        flow = parse_flow_markdown(markdown, name=name)
        return self.run(flow)

    def run(self, flow: FlowDefinition) -> FlowResult:
        """Execute a parsed FlowDefinition and return the result."""
        logger.info("[orchestrator] Starting flow: %s (%d actions)", flow.name, len(flow.actions))
        with sync_playwright() as pw:
            browser = create_browser(pw, test_name=flow.name)
            ctx = browser.new_context(viewport={"width": 1280, "height": 720})
            page = ctx.new_page()
            page.set_default_timeout(flow.timeout)

            runner = FlowRunner(artifacts_dir=self.artifacts_dir)
            result = runner.run(flow, page)

            ctx.close()
            browser.close()

        logger.info(
            "[orchestrator] Flow '%s' — %s (%d/%d steps passed)",
            flow.name,
            "PASSED" if result.success else "FAILED",
            result.passed,
            len(result.steps),
        )
        return result
