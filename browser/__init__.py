"""
browser package — Playwright-based browser automation layer.

Public surface:
    BrowserDriver   — unified driver (navigation + element + utils)
    NavigationMixin — URL / history navigation helpers
    ElementMixin    — element extraction and interaction helpers
    WebUtilsMixin   — screenshot / artifact capture helpers
    extract_page_state — build a structured PageState from the current page
"""

from browser.driver import BrowserDriver
from browser.navigation import NavigationMixin
from browser.element import ElementMixin
from browser.web_utils import WebUtilsMixin
from browser.extractors import extract_page_state

__all__ = [
    "BrowserDriver",
    "NavigationMixin",
    "ElementMixin",
    "WebUtilsMixin",
    "extract_page_state",
]
