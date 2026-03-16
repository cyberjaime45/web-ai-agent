"""
tools.browser package — Playwright-based browser automation layer.

Public surface:
    BrowserDriver   — unified driver (navigation + element + utils)
    NavigationMixin — URL / history navigation helpers
    ElementMixin    — element extraction and interaction helpers
    WebUtilsMixin   — screenshot / artifact capture helpers
"""

from tools.browser.driver import BrowserDriver
from tools.browser.navigation import NavigationMixin
from tools.browser.element import ElementMixin
from tools.browser.web_utils import WebUtilsMixin

__all__ = [
    "BrowserDriver",
    "NavigationMixin",
    "ElementMixin",
    "WebUtilsMixin",
]
