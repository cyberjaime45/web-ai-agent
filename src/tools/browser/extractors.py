"""
Page State Extractor — Builds a structured PageState from the current
browser page, ready to send to the AI planner.
"""

from __future__ import annotations

from schemas.models import InputField, PageState
from tools.browser.driver import BrowserDriver


def extract_page_state(driver: BrowserDriver) -> PageState:
    """Extract structured page state from the current browser page."""
    inputs_raw = driver.find_inputs()
    inputs = [InputField(**inp) for inp in inputs_raw]

    return PageState(
        url=driver.get_current_url(),
        title=driver.get_page_title(),
        labels=driver.extract_labels(),
        buttons=driver.find_buttons(),
        links=driver.find_links(),
        inputs=inputs,
        errors=driver.find_errors(),
        visible_text_snippet=driver.extract_visible_text(max_length=1500),
    )
