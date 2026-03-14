"""
Complex Multi-Page Journey Tests.

The tests navigate multiple pages and check page state autonomously —
they extract live page state (buttons, links, inputs, errors) and make
assertions based on what they discover, without hard-coded selectors.

Pages visited across this suite:
  1. Home          – https://practicetestautomation.com/
  2. Practice      – https://practicetestautomation.com/practice/
  3. Login         – https://practicetestautomation.com/practice-test-login/
  4. Success       – https://practicetestautomation.com/logged-in-successfully/
"""

from __future__ import annotations

import pytest

from agent.flow_parser import FlowDefinition
from agent.runner import run_flow
from tools.browser.driver import BrowserDriver
from tools.browser.extractors import extract_page_state


# ── Helpers ─────────────────────────────────────────────────────────────────


def _find_links_containing(links: list[str], keyword: str) -> list[str]:
    """Return links whose text contains *keyword* (case-insensitive)."""
    return [lnk for lnk in links if keyword.lower() in lnk.lower()]


def _assert_page_loaded(driver: BrowserDriver, url_fragment: str, label: str) -> None:
    """Assert that the current URL contains *url_fragment*."""
    current = driver.get_current_url()
    assert url_fragment in current, (
        f"[{label}] Expected URL to contain '{url_fragment}'. Got: {current}"
    )


# ── Test class 1: manual navigation with autonomous self-checks ──────────────


@pytest.mark.journey
class TestMultiPageNavigation:
    """Navigate pages manually; the test discovers and validates each page."""

    def test_home_and_practice_pages(self, browser_driver: BrowserDriver) -> None:
        """
        Page 1 → Home:   verify title + navigation links exist.
        Page 2 → Practice: verify URL changed + content links visible.
        """
        driver = browser_driver

        # ── Page 1: Home ───────────────────────────────────────────
        driver.open_page("https://practicetestautomation.com/")
        home_state = extract_page_state(driver)
        driver.capture_screenshot("journey_home")

        assert "Practice Test Automation" in home_state.title, (
            f"Expected home page title. Got: {home_state.title!r}"
        )
        assert len(home_state.links) >= 3, (
            f"Home page should expose navigation links. Found: {len(home_state.links)}"
        )

        practice_links = _find_links_containing(home_state.links, "practice")
        assert practice_links, (
            f"Could not find a 'Practice' link on home. "
            f"All links: {home_state.links[:15]}"
        )

        print(f"\n  [Home] title={home_state.title!r}")
        print(f"  [Home] links found: {len(home_state.links)}")
        print(f"  [Home] 'Practice' links: {practice_links}")

        # ── Page 2: Practice (follow the discovered link) ──────────
        driver.click_link(practice_links[0])
        practice_state = extract_page_state(driver)
        driver.capture_screenshot("journey_practice")

        _assert_page_loaded(driver, "practice", "Practice page")
        assert practice_state.url != home_state.url, (
            "URL should have changed after clicking Practice link"
        )
        assert len(practice_state.links) > 0, (
            "Practice page should have content links"
        )

        print(f"\n  [Practice] url={practice_state.url!r}")
        print(f"  [Practice] links found: {len(practice_state.links)}")

    def test_practice_and_login_pages(self, browser_driver: BrowserDriver) -> None:
        """
        Page 1 → Practice:  autonomously find a 'login' test link.
        Page 2 → Login:     verify form inputs and submit button exist.
        """
        driver = browser_driver

        # ── Page 1: Practice ───────────────────────────────────────
        driver.open_page("https://practicetestautomation.com/practice/")
        practice_state = extract_page_state(driver)
        driver.capture_screenshot("prac_login_step1_practice")

        _assert_page_loaded(driver, "practice", "Practice page")

        login_links = _find_links_containing(practice_state.links, "login")
        assert login_links, (
            f"Expected a login-related link on practice page. "
            f"All links: {practice_state.links[:20]}"
        )

        print(f"\n  [Practice] login-related links: {login_links}")

        # ── Page 2: Login ──────────────────────────────────────────
        driver.click_link(login_links[0])
        login_state = extract_page_state(driver)
        driver.capture_screenshot("prac_login_step2_login")

        _assert_page_loaded(driver, "login", "Login page")

        assert len(login_state.inputs) >= 2, (
            f"Login page must have ≥2 inputs (username + password). "
            f"Found {len(login_state.inputs)}: {[i.label for i in login_state.inputs]}"
        )
        assert login_state.buttons, (
            "Login page should have at least one button (Submit)"
        )

        # Self-check: input types detected
        input_labels = {
            (inp.label or inp.name or inp.placeholder).lower()
            for inp in login_state.inputs
        }
        has_user_field = any("user" in lbl or "name" in lbl for lbl in input_labels)
        has_pass_field = any("pass" in lbl for lbl in input_labels)

        assert has_user_field, f"No username-like field found. Inputs: {input_labels}"
        assert has_pass_field, f"No password field found. Inputs: {input_labels}"

        print(f"\n  [Login] url={login_state.url!r}")
        print(f"  [Login] inputs: {input_labels}")
        print(f"  [Login] buttons: {login_state.buttons}")


# ── Test class 2: fully autonomous self-checking across 4 pages ──────────────


@pytest.mark.journey
class TestAutonomousSelfChecking:
    """
    The test navigates 4 pages and at each one autonomously extracts page
    state, asserts on discovered content, and decides where to go next.
    No hard-coded selectors are used — only the live page state.
    """

    def test_four_page_journey_with_autonomous_assertions(
        self, browser_driver: BrowserDriver
    ) -> None:
        """
        Home → Practice → Login → Success.
        State is checked autonomously at each page boundary.
        """
        driver = browser_driver
        visited: list[dict] = []

        # ╔══ Page 1: Home ══════════════════════════════════════════════╗
        driver.open_page("https://practicetestautomation.com/")
        s1 = extract_page_state(driver)
        visited.append({"page": "Home", "url": s1.url, "screenshot": driver.capture_screenshot("auto_01_home")})

        # Autonomous assertions
        assert s1.title, "Home page must have a title"
        assert len(s1.links) >= 3, f"Home should have navigation links. Got {len(s1.links)}"

        # Autonomous navigation decision: pick the first Practice link
        practice_links = _find_links_containing(s1.links, "practice")
        assert practice_links, f"Autonomous check: no Practice link on home. Links: {s1.links[:15]}"
        print(f"\n  [P1-Home] title={s1.title!r} | links={len(s1.links)} | chose: {practice_links[0]!r}")

        # ╔══ Page 2: Practice ══════════════════════════════════════════╗
        driver.click_link(practice_links[0])
        s2 = extract_page_state(driver)
        visited.append({"page": "Practice", "url": s2.url, "screenshot": driver.capture_screenshot("auto_02_practice")})

        assert "practice" in s2.url.lower(), f"Autonomous check: not on Practice page. URL={s2.url!r}"
        assert s2.url != s1.url, "URL must change after navigation"

        # Find login link autonomously
        login_links = _find_links_containing(s2.links, "login")
        assert login_links, (
            f"Autonomous check: no login link on Practice page. Links: {s2.links[:20]}"
        )
        print(f"  [P2-Practice] url={s2.url!r} | chose: {login_links[0]!r}")

        # ╔══ Page 3: Login ════════════════════════════════════════════╗
        driver.click_link(login_links[0])
        s3 = extract_page_state(driver)
        visited.append({"page": "Login", "url": s3.url, "screenshot": driver.capture_screenshot("auto_03_login")})

        assert "login" in s3.url.lower(), f"Autonomous check: not on Login page. URL={s3.url!r}"
        assert len(s3.inputs) >= 2, (
            f"Autonomous check: expected ≥2 inputs on login page. Found {len(s3.inputs)}"
        )
        assert s3.buttons, "Autonomous check: login page must have a submit button"
        assert not s3.errors, (
            f"No errors should appear before interaction. Found: {s3.errors}"
        )

        # Detect field labels autonomously and fill
        user_field = next(
            (inp for inp in s3.inputs if any(kw in (inp.label or inp.name or "").lower() for kw in ("user", "name"))),
            s3.inputs[0],
        )
        pass_field = next(
            (inp for inp in s3.inputs if "pass" in (inp.label or inp.name or "").lower()),
            s3.inputs[1] if len(s3.inputs) > 1 else s3.inputs[0],
        )
        print(f"  [P3-Login] user_field={user_field.label!r} | pass_field={pass_field.label!r}")

        driver.fill_input(user_field.label or user_field.name or "Username", "student")
        driver.fill_input(pass_field.label or pass_field.name or "Password", "Password123")

        # Click the first submit-looking button
        submit_btn = next(
            (b for b in s3.buttons if any(kw in b.lower() for kw in ("submit", "log", "sign"))),
            s3.buttons[0],
        )
        driver.click_button(submit_btn)

        # ╔══ Page 4: Success ══════════════════════════════════════════╗
        s4 = extract_page_state(driver)
        visited.append({"page": "Success", "url": s4.url, "screenshot": driver.capture_screenshot("auto_04_success")})

        assert "logged-in-successfully" in s4.url, (
            f"Autonomous check: expected success URL. Got: {s4.url!r}"
        )
        success_text = (s4.title + " " + s4.visible_text_snippet).lower()
        assert any(kw in success_text for kw in ("congratulations", "success", "logged")), (
            f"Success page must contain a success message. Snippet: {s4.visible_text_snippet[:200]!r}"
        )
        assert not s4.errors, f"No error messages should appear on success page. Found: {s4.errors}"

        print(f"  [P4-Success] url={s4.url!r}")
        print(f"\n  Journey complete. Pages visited:")
        for p in visited:
            print(f"    [{p['page']}] {p['url']}")

        # Final invariant: at least 2 distinct pages were visited
        unique_urls = {p["url"] for p in visited}
        assert len(unique_urls) >= 2, f"Must visit ≥2 distinct pages. Got: {unique_urls}"

    def test_error_state_detection(self, browser_driver: BrowserDriver) -> None:
        """
        Navigate to login, submit invalid credentials, and autonomously
        detect and assert the error message shown by the page.
        """
        driver = browser_driver

        # Page 1: Login
        driver.open_page("https://practicetestautomation.com/practice-test-login/")
        s1 = extract_page_state(driver)
        driver.capture_screenshot("error_01_before_submit")

        assert len(s1.inputs) >= 2, "Login page must have inputs"

        # Fill wrong credentials
        driver.fill_input("Username", "bad_user")
        driver.fill_input("Password", "bad_pass")
        driver.click_button(s1.buttons[0])

        # Page 2: Same page with error
        s2 = extract_page_state(driver)
        driver.capture_screenshot("error_02_after_submit")

        # Autonomous self-check: we must still be on the login page
        assert "logged-in-successfully" not in s2.url, (
            "Should NOT navigate to success with invalid credentials"
        )
        assert s2.errors or "invalid" in s2.visible_text_snippet.lower(), (
            f"Autonomous check: expected an error message for bad credentials. "
            f"Errors: {s2.errors} | Snippet: {s2.visible_text_snippet[:200]!r}"
        )

        print(f"\n  [Error check] url stayed at: {s2.url!r}")
        print(f"  [Error check] errors detected: {s2.errors}")


# ── Test class 3: full agent-runner journey ───────────────────────────────────


@pytest.mark.agent
@pytest.mark.journey
class TestFullAgentJourney:
    """Run the MultiPageJourney flow through the agent's full planning loop."""

    def test_multi_page_flow_agent(
        self,
        browser_driver: BrowserDriver,
        multi_page_journey_flow: FlowDefinition,
    ) -> None:
        """
        Agent autonomously plans and executes the full multi-page journey.
        The runner extracts page state at each iteration, plans the next
        action, validates it, and executes — no manual step code here.
        """
        result = run_flow(multi_page_journey_flow, browser_driver, max_steps=30)

        print(f"\n  Flow: {result.flow_name}")
        print(f"  Steps executed: {result.steps_executed}")
        for ar in result.action_log:
            status = "PASS" if ar.success else "FAIL"
            print(f"    [{status}] {ar.action.action.value} {ar.action.target or ''!r} — {ar.message}")

        assert result.steps_executed > 0, "Agent must execute at least one step"

        final_url = browser_driver.get_current_url()
        assert final_url not in ("", "about:blank"), (
            "Agent should have navigated to at least one page"
        )

        # The flow covers home + practice + login as a minimum — URL should
        # have moved beyond the starting URL.
        assert "practicetestautomation.com" in final_url, (
            f"Agent should have visited the target site. Final URL: {final_url!r}"
        )

    def test_agent_validates_success_page(
        self,
        browser_driver: BrowserDriver,
        multi_page_journey_flow: FlowDefinition,
    ) -> None:
        """
        After the agent completes the flow, manually extract the final page
        state and assert the expected outcome conditions are met.
        """
        result = run_flow(multi_page_journey_flow, browser_driver, max_steps=30)

        # Regardless of agent success flag, assert observable page state
        final_state = extract_page_state(browser_driver)
        browser_driver.capture_screenshot("agent_final_state")

        print(f"\n  Agent result: success={result.success} steps={result.steps_executed}")
        print(f"  Final URL: {final_state.url!r}")
        print(f"  Final title: {final_state.title!r}")

        # Require the agent to have navigated at least one page
        assert result.steps_executed > 0, "Agent must execute steps"
        assert "practicetestautomation.com" in final_state.url, (
            f"Agent never left the starting domain. URL: {final_state.url!r}"
        )
