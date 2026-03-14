"""
Element — Mixin containing all element inspection, extraction, and
interaction methods used by the BrowserDriver.

Provides helpers for AI agents to understand and interact with page
content: text extraction, form analysis, element discovery, and actions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class ElementMixin:
    """All element-related extraction and interaction methods for BrowserDriver."""

    page: "Page"  # set by BrowserDriver.__init__

    # ── Text extraction ─────────────────────────────────────────

    def extract_visible_text(self, max_length: int = 2000) -> str:
        """Return a truncated snapshot of all visible body text."""
        return self.page.inner_text("body")[:max_length]

    def extract_labels(self) -> list[str]:
        """Return visible text from every <label> element."""
        return [
            lb.inner_text().strip()
            for lb in self.page.locator("label").all()
            if lb.is_visible()
        ]

    def find_headings(self) -> list[dict]:
        """Return all visible heading elements (h1–h6) with level and text.

        Useful for understanding page structure and section titles.
        """
        results = []
        for level in range(1, 7):
            for el in self.page.locator(f"h{level}").all():
                if el.is_visible():
                    text = el.inner_text().strip()
                    if text:
                        results.append({"level": level, "text": text})
        return results

    def get_element_text(self, selector: str) -> str:
        """Return inner text of the first element matching *selector*, or ''."""
        el = self.page.locator(selector).first
        try:
            return el.inner_text().strip() if el.is_visible() else ""
        except Exception:
            return ""

    # ── Element discovery ───────────────────────────────────────

    def find_buttons(self) -> list[str]:
        """Return deduplicated visible text of all button-like elements."""
        results: list[str] = []
        for selector in (
            "button",
            "input[type='submit']",
            "a[role='button']",
            "[role='button']",
        ):
            for el in self.page.locator(selector).all():
                if el.is_visible():
                    text = el.inner_text().strip() or el.get_attribute("value") or ""
                    if text:
                        results.append(text)
        return list(dict.fromkeys(results))

    def find_links(self) -> list[str]:
        """Return visible link texts (capped at 50)."""
        results = []
        for link in self.page.locator("a").all():
            if link.is_visible():
                text = link.inner_text().strip()
                if text:
                    results.append(text)
        return results[:50]

    def find_link_hrefs(self) -> list[dict]:
        """Return dicts with ``text`` and ``href`` for all visible links.

        Useful when the AI agent needs to reason about where a link leads.
        """
        results = []
        for link in self.page.locator("a[href]").all():
            if link.is_visible():
                text = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if text or href:
                    results.append({"text": text, "href": href})
        return results[:50]

    def find_inputs(self) -> list[dict]:
        """Return metadata about every visible form input / textarea / select."""
        results = []
        for el in self.page.locator(
            "input:not([type='hidden']), textarea, select"
        ).all():
            if not el.is_visible():
                continue
            el_id = el.get_attribute("id") or ""
            label_text = ""
            if el_id:
                lbl = self.page.locator(f"label[for='{el_id}']")
                if lbl.count() > 0:
                    label_text = lbl.first.inner_text().strip()
            if not label_text:
                label_text = (
                    el.get_attribute("aria-label")
                    or el.get_attribute("placeholder")
                    or el.get_attribute("name")
                    or ""
                )
            results.append(
                {
                    "label":       label_text,
                    "input_type":  el.get_attribute("type") or "text",
                    "name":        el.get_attribute("name") or "",
                    "placeholder": el.get_attribute("placeholder") or "",
                    "value":       el.input_value() if el.is_editable() else "",
                    "is_enabled":  el.is_enabled(),
                }
            )
        return results

    def find_select_options(self, name_or_label: str) -> list[str]:
        """Return the option texts for a <select> matched by name or label.

        Useful when the AI agent needs to enumerate valid dropdown values.
        """
        sel = self.page.locator(
            f"select[name='{name_or_label}'], select[aria-label='{name_or_label}']"
        ).first
        try:
            return [
                o.inner_text().strip()
                for o in sel.locator("option").all()
                if o.inner_text().strip()
            ]
        except Exception:
            return []

    def find_errors(self) -> list[str]:
        """Return deduplicated visible error / alert messages."""
        selectors = [
            "[class*='error']",
            "[class*='alert']",
            "[role='alert']",
            "[class*='invalid']",
            "[class*='danger']",
        ]
        errors: list[str] = []
        for sel in selectors:
            for el in self.page.locator(sel).all():
                if el.is_visible():
                    text = el.inner_text().strip()
                    if text:
                        errors.append(text)
        return list(dict.fromkeys(errors))

    def find_images(self) -> list[dict]:
        """Return ``src`` and ``alt`` for all visible images.

        Useful for verifying that expected images are present on the page.
        """
        results = []
        for img in self.page.locator("img").all():
            if img.is_visible():
                results.append(
                    {
                        "alt": img.get_attribute("alt") or "",
                        "src": img.get_attribute("src") or "",
                    }
                )
        return results

    # ── State inspection ────────────────────────────────────────

    def is_element_visible(self, selector: str) -> bool:
        """Return True if at least one element matching *selector* is visible."""
        try:
            return self.page.locator(selector).first.is_visible()
        except Exception:
            return False

    def is_element_enabled(self, selector: str) -> bool:
        """Return True if the first element matching *selector* is enabled."""
        try:
            return self.page.locator(selector).first.is_enabled()
        except Exception:
            return False

    def get_element_attribute(self, selector: str, attribute: str) -> str:
        """Return an attribute value from the first matching element, or ''."""
        try:
            return self.page.locator(selector).first.get_attribute(attribute) or ""
        except Exception:
            return ""

    def get_page_meta(self) -> dict:
        """Return a dict of useful ``<meta>`` values for AI page understanding.

        Keys: ``description``, ``og_title``, ``og_description``, ``canonical``.
        """
        def _meta(attr: str, val: str) -> str:
            try:
                return (
                    self.page.locator(f"meta[{attr}='{val}']")
                    .first.get_attribute("content")
                    or ""
                )
            except Exception:
                return ""

        try:
            canonical = (
                self.page.locator("link[rel='canonical']")
                .first.get_attribute("href")
                or ""
            )
        except Exception:
            canonical = ""

        return {
            "description":    _meta("name",     "description"),
            "og_title":       _meta("property", "og:title"),
            "og_description": _meta("property", "og:description"),
            "canonical":      canonical,
        }

    def wait_for_element(self, selector: str, timeout: int = 10_000) -> None:
        """Wait until *selector* is visible in the DOM."""
        self.page.locator(selector).first.wait_for(state="visible", timeout=timeout)

    # ── Element interactions ────────────────────────────────────

    def click_button(self, text: str, timeout: int = 10_000) -> None:
        """Click a button/link by its visible text (role-based, most robust)."""
        logger.info("Clicking button: '%s'", text)
        locator = self.page.get_by_role("button", name=text)
        if locator.count() == 0:
            locator = self.page.get_by_role("link", name=text)
        if locator.count() == 0:
            locator = self.page.locator(f"text='{text}'")
        locator.first.click(timeout=timeout)

    def fill_input(self, label: str, value: str, timeout: int = 10_000) -> None:
        """Fill a form field located by its label, placeholder, or name."""
        logger.info("Filling input '%s'", label)
        locator = self.page.get_by_label(label)
        if locator.count() == 0:
            locator = self.page.get_by_placeholder(label)
        if locator.count() == 0:
            locator = self.page.locator(f"input[name='{label}' i]")
        locator.first.fill(value, timeout=timeout)

    def click_link(self, text: str, timeout: int = 10_000) -> None:
        """Click an anchor link by its visible text."""
        logger.info("Clicking link: '%s'", text)
        self.page.get_by_role("link", name=text).first.click(timeout=timeout)

    def select_option(
        self, name_or_label: str, value: str, timeout: int = 10_000
    ) -> None:
        """Select an option from a <select> element by name or label.

        *value* may be the visible text or the option value attribute.
        """
        logger.info("Selecting '%s' in '%s'", value, name_or_label)
        locator = self.page.locator(
            f"select[name='{name_or_label}'], select[aria-label='{name_or_label}']"
        ).first
        locator.select_option(label=value, timeout=timeout)

    def clear_input(self, label: str, timeout: int = 10_000) -> None:
        """Clear the content of an input field."""
        locator = self.page.get_by_label(label)
        if locator.count() == 0:
            locator = self.page.get_by_placeholder(label)
        locator.first.clear(timeout=timeout)
