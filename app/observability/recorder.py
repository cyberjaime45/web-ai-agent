"""Per-test page recorder — console and network capture for the HTML report.

One instance lives for the duration of a single flow run. Attach it to a
Playwright page right after creation; it accumulates console errors/warnings
and app-relevant network traffic as plain dicts, ready for the report payload.

Capture policy (matches the Astra report the UI is shared with):
  console — only ``error`` / ``warning`` messages and uncaught page errors.
  network — xhr/fetch/document/websocket responses are always kept; other
            resource types (images, stylesheets, …) only when they fail.
            Failed responses keep a body excerpt — usually the most useful
            debugging context.
"""

from __future__ import annotations

from typing import Any

MAX_CONSOLE_ENTRIES = 100
MAX_NETWORK_ENTRIES = 400
MAX_RESPONSE_BODY = 2_000  # excerpt kept for failed responses
INTERESTING_RESOURCE_TYPES = {"xhr", "fetch", "document", "websocket"}


class PageRecorder:
    def __init__(self) -> None:
        self.console: list[dict[str, Any]] = []
        self.network: list[dict[str, Any]] = []

    def attach(self, page: Any) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)

    # ── Console ──────────────────────────────────────────────────────────

    def _on_console(self, msg: Any) -> None:
        if msg.type not in ("error", "warning") or len(self.console) >= MAX_CONSOLE_ENTRIES:
            return
        location = None
        if msg.location and msg.location.get("url"):
            location = f"{msg.location['url']}:{msg.location.get('lineNumber', 0)}"
        self.console.append({
            "level": msg.type,
            "text": msg.text[:2000],
            "location": location,
        })

    def _on_page_error(self, error: Exception) -> None:
        if len(self.console) < MAX_CONSOLE_ENTRIES:
            self.console.append({
                "level": "pageerror",
                "text": str(error)[:2000],
                "location": None,
            })

    # ── Network ──────────────────────────────────────────────────────────

    def _on_response(self, response: Any) -> None:
        if len(self.network) >= MAX_NETWORK_ENTRIES:
            return
        resource_type = response.request.resource_type
        failed = response.status >= 400
        if resource_type not in INTERESTING_RESOURCE_TYPES and not failed:
            return
        body = None
        if failed:
            # Best-effort: the body may be gone after a navigation.
            try:
                body = response.text().strip()[:MAX_RESPONSE_BODY] or None
            except Exception:
                body = None
        self.network.append({
            "method": response.request.method,
            "url": response.url[:500],
            "status": response.status,
            "ok": not failed,
            "failure": None,
            "resource_type": resource_type,
            "body": body,
        })

    def _on_request_failed(self, request: Any) -> None:
        if len(self.network) >= MAX_NETWORK_ENTRIES:
            return
        self.network.append({
            "method": request.method,
            "url": request.url[:500],
            "status": None,
            "ok": False,
            "failure": request.failure or "request failed",
            "resource_type": request.resource_type,
            "body": None,
        })
