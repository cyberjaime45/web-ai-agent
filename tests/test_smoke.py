"""
Smoke Tests — Deterministic browser automation tests.
These validate the browser layer WITHOUT any AI involvement.
"""

import pytest
from browser.driver import BrowserDriver


@pytest.mark.smoke
class TestBrowserSmoke:
    """Basic browser interaction tests against the practice site."""

    PRACTICE_LOGIN_URL = "https://practicetestautomation.com/practice-test-login/"

    def test_open_page_and_get_title(self, browser_driver: BrowserDriver):
        """Verify we can navigate and read the page title."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)
        title = browser_driver.get_page_title()
        assert title, "Page title should not be empty"

    def test_extract_labels(self, browser_driver: BrowserDriver):
        """Verify we can find labels on the login page."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)
        labels = browser_driver.extract_labels()
        # The page should have Username and Password labels
        labels_lower = [lb.lower() for lb in labels]
        assert any("username" in lb for lb in labels_lower), (
            f"Expected 'Username' label, found: {labels}"
        )
        assert any("password" in lb for lb in labels_lower), (
            f"Expected 'Password' label, found: {labels}"
        )

    def test_find_buttons(self, browser_driver: BrowserDriver):
        """Verify we can detect the Submit button."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)
        buttons = browser_driver.find_buttons()
        buttons_lower = [b.lower() for b in buttons]
        assert any("submit" in b for b in buttons_lower), (
            f"Expected 'Submit' button, found: {buttons}"
        )

    def test_find_inputs(self, browser_driver: BrowserDriver):
        """Verify we can detect input fields."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)
        inputs = browser_driver.find_inputs()
        assert len(inputs) >= 2, f"Expected at least 2 inputs, found {len(inputs)}"

    def test_fill_and_submit_login(self, browser_driver: BrowserDriver):
        """Full deterministic login test — no AI involved."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)

        # Fill credentials
        browser_driver.fill_input("Username", "student")
        browser_driver.fill_input("Password", "Password123")

        # Click submit
        browser_driver.click_button("Submit")

        # Wait for navigation
        browser_driver.page.wait_for_load_state("domcontentloaded")

        # Assert success
        url = browser_driver.get_current_url()
        assert "logged-in-successfully" in url, f"Expected success URL, got: {url}"

        page_text = browser_driver.extract_visible_text()
        assert "congratulations" in page_text.lower() or "logged in" in page_text.lower(), (
            "Expected success message on page"
        )

    def test_capture_screenshot(self, browser_driver: BrowserDriver):
        """Verify screenshot capture works."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)
        path = browser_driver.capture_screenshot("smoke_test")
        assert path.endswith(".png")

    def test_invalid_login_shows_error(self, browser_driver: BrowserDriver):
        """Verify that wrong credentials produce an error."""
        browser_driver.open_page(self.PRACTICE_LOGIN_URL)
        browser_driver.fill_input("Username", "wronguser")
        browser_driver.fill_input("Password", "wrongpass")
        browser_driver.click_button("Submit")

        # Wait a moment for error to appear
        browser_driver.page.wait_for_timeout(1000)

        # Should still be on the login page
        url = browser_driver.get_current_url()
        assert "logged-in-successfully" not in url, "Should NOT navigate on invalid creds"
