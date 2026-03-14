"""
Agent Tests — Run flows through the full AI agent loop.
Uses the rule-based planner by default (no API key needed).
Set OPENAI_API_KEY to use the LLM-backed planner.
"""

import pytest

from agent.flow_parser import FlowDefinition
from agent.runner import run_flow
from tools.browser.driver import BrowserDriver


@pytest.mark.agent
class TestLoginAgent:
    """Test the Login flow through the agent runner."""

    def test_login_flow_succeeds(self, browser_driver: BrowserDriver, login_flow: FlowDefinition):
        """Agent should successfully complete the login flow."""
        result = run_flow(login_flow, browser_driver)

        # Print action log for debugging
        for ar in result.action_log:
            status = "PASS" if ar.success else "FAIL"
            print(f"  [{status}] {ar.action.action.value} {ar.action.target or ''} — {ar.message}")

        assert result.steps_executed > 0, "Agent should have executed at least one step"
        assert result.success, f"Login flow failed: {result.error}"


@pytest.mark.agent
class TestFormValidationAgent:
    """Test the FormValidation flow through the agent runner."""

    def test_invalid_login_detected(
        self, browser_driver: BrowserDriver, form_validation_flow: FlowDefinition
    ):
        """Agent should detect that invalid credentials fail."""
        result = run_flow(form_validation_flow, browser_driver)

        for ar in result.action_log:
            status = "PASS" if ar.success else "FAIL"
            print(f"  [{status}] {ar.action.action.value} {ar.action.target or ''} — {ar.message}")

        assert result.steps_executed > 0, "Agent should have executed steps"
        # For the form validation flow, the URL should NOT contain success
        final_url = browser_driver.get_current_url()
        assert "logged-in-successfully" not in final_url, (
            "Invalid credentials should not lead to success page"
        )


@pytest.mark.agent
class TestNavigationAgent:
    """Test the Navigation flow through the agent runner."""

    def test_navigation_flow(
        self, browser_driver: BrowserDriver, navigation_flow: FlowDefinition
    ):
        """Agent should navigate from home to an inner page."""
        result = run_flow(navigation_flow, browser_driver)

        for ar in result.action_log:
            status = "PASS" if ar.success else "FAIL"
            print(f"  [{status}] {ar.action.action.value} {ar.action.target or ''} — {ar.message}")

        assert result.steps_executed > 0, "Agent should have executed steps"
