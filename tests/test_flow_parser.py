"""
Tests for the flow parser — verifies that .md flow files
are correctly parsed into FlowDefinition objects.
"""

import pytest
from pathlib import Path

from agent.flow_parser import load_all_flows, parse_flow_file


class TestFlowParser:
    """Test flow file parsing."""

    def test_load_all_flows(self, all_flows):
        """All flow files should load successfully."""
        assert len(all_flows) >= 3, f"Expected at least 3 flows, got {len(all_flows)}"
        assert "Login" in all_flows
        assert "Navigation" in all_flows
        assert "FormValidation" in all_flows

    def test_login_flow_parsed_correctly(self, login_flow):
        """Login flow should have correct structure."""
        assert login_flow.url == "https://practicetestautomation.com/practice-test-login/"
        assert login_flow.credentials.get("username") == "student"
        assert login_flow.credentials.get("password") == "Password123"
        assert len(login_flow.steps) >= 4, f"Expected at least 4 steps, got {len(login_flow.steps)}"
        assert len(login_flow.expected_outcome) >= 1

    def test_navigation_flow_has_url(self, navigation_flow):
        """Navigation flow should have a target URL."""
        assert navigation_flow.url.startswith("http")
        assert len(navigation_flow.steps) >= 3

    def test_form_validation_flow_has_bad_creds(self, form_validation_flow):
        """FormValidation flow should have intentionally wrong credentials."""
        assert form_validation_flow.credentials.get("username") == "wronguser"
        assert form_validation_flow.credentials.get("password") == "wrongpass"
