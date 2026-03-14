"""
tools.browser package — Playwright-based browser automation layer.

Public surface:
    BrowserDriver   — unified driver (navigation + element + utils)
    NavigationMixin — URL / history navigation helpers
    ElementMixin    — element extraction and interaction helpers
    WebUtilsMixin   — screenshot / artifact capture helpers
    extract_page_state — build a structured PageState from the current page
"""

from tools.browser.driver import BrowserDriver
from tools.browser.navigation import NavigationMixin
from tools.browser.element import ElementMixin
from tools.browser.web_utils import WebUtilsMixin
from tools.browser.extractors import extract_page_state

__all__ = [
    "BrowserDriver",
    "NavigationMixin",
    "ElementMixin",
    "WebUtilsMixin",
    "extract_page_state",
]
