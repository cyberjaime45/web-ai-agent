"""
Browser Driver — Core driver lifecycle and setup.

Responsibilities:
  • Wrap a Playwright Page instance
  • Configure shared state (artifacts directory, counters)
  • Compose Navigation, Element, and WebUtils capabilities via mixins

All navigation, element, and artifact methods are implemented in their
respective modules and mixed in here so that callers continue to access
everything through a single ``BrowserDriver`` instance.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import Page

from tools.browser.navigation import NavigationMixin
from tools.browser.element import ElementMixin
from tools.browser.web_utils import WebUtilsMixin

logger = logging.getLogger(__name__)


class BrowserDriver(NavigationMixin, ElementMixin, WebUtilsMixin):
    """Unified browser interaction layer.

    Composed from:
    - :class:`~tools.browser.navigation.NavigationMixin` — URL navigation and history
    - :class:`~tools.browser.element.ElementMixin`        — element extraction and actions
    - :class:`~tools.browser.web_utils.WebUtilsMixin`     — screenshots and artifact capture
    """

    def __init__(self, page: Page, artifacts_dir: str = "artifacts") -> None:
        self.page = page
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter = 0
