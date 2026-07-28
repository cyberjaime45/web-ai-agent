"""Per-flow page recorder — console and network capture for the HTML report.

One instance lives for the duration of a single flow run. Attach it to a
Playwright page right after creation; listeners stay attached for the whole
flow (never removed — removing them mid-run loses events). Every entry gets
a wall-clock ``ts`` (epoch ms) and a ``seq`` number so the reporter can route
it to the section/step that was active when it started.

Capture policy:
  console — every level, normalized to error/warning/info/debug (+pageerror),
            capped per class so noisy pages can't evict errors.
  network — every response is kept as a metadata row (the report offers
            JS/CSS/Image filters); xhr/fetch/document rows also carry
            redacted headers and post data. Bodies are kept only for failed
            responses and small JSON xhr/fetch responses.

Sensitive values (Authorization, cookies, tokens…) are redacted before
anything is stored; REPORT_REDACT adds project-specific key substrings.
"""

from __future__ import annotations

import itertools
import json
import re
import time
from typing import Any

from app.config.settings import settings

MAX_ERROR_CONSOLE = 200      # error / warning / pageerror entries
MAX_INFO_CONSOLE = 200       # info / debug entries
MAX_NETWORK_ENTRIES = 1500
MAX_RESPONSE_BODY = 2_000    # excerpt kept for bodies
MAX_POST_DATA = 1_000
MAX_JSON_BODY_SIZE = 50_000  # don't read successful bodies larger than this
RICH_TYPES = {"xhr", "fetch", "document"}   # rows that carry headers/payloads

REDACTED = "«redacted»"
_BUILTIN_SENSITIVE = (
    "authorization", "cookie", "x-api-key", "api-key", "apikey",
    "token", "auth", "secret", "password", "passwd", "session",
)

_LEVELS = {"error": "error", "warning": "warning", "info": "info",
           "log": "info", "debug": "debug", "trace": "debug"}


def _extra_keys() -> tuple[str, ...]:
    return tuple(k.strip().lower()
                 for k in settings.report_redact.split(",") if k.strip())


def _sensitive(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _BUILTIN_SENSITIVE + _extra_keys())


def redact_headers(headers: dict) -> dict:
    return {k: (REDACTED if _sensitive(k) else str(v)[:500])
            for k, v in headers.items()}


def redact_url(url: str) -> str:
    base, sep, qs = url.partition("?")
    if not sep:
        return url
    parts = []
    for pair in qs.split("&"):
        name, eq, _val = pair.partition("=")
        parts.append(f"{name}={REDACTED}" if eq and _sensitive(name) else pair)
    return f"{base}?{'&'.join(parts)}"


def redact_text(text: str) -> str:
    """Redact sensitive keys in a JSON or form-encoded payload excerpt."""
    try:
        data = json.loads(text)
    except Exception:
        keys = "|".join(re.escape(k) for k in _BUILTIN_SENSITIVE + _extra_keys())
        return re.sub(rf"(?i)([^&=\s]*(?:{keys})[^&=\s]*)=([^&\s]*)",
                      rf"\1={REDACTED}", text)

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: (REDACTED if _sensitive(k) else walk(x))
                    for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return json.dumps(walk(data), ensure_ascii=False)


def _now_ms() -> int:
    return round(time.time() * 1000)


class PageRecorder:
    def __init__(self) -> None:
        self.console: list[dict[str, Any]] = []
        self.network: list[dict[str, Any]] = []
        self.dropped = {"console": 0, "network": 0}
        self._seq = itertools.count(1)
        self._n_err = 0    # error/warning/pageerror count
        self._n_info = 0   # info/debug count
        self._starts: dict[int, float] = {}   # id(request) → epoch seconds

    def attach(self, page: Any) -> None:
        page.on("request", self._on_request)
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        page.on("websocket", self._on_websocket)

    # ── Console ──────────────────────────────────────────────────────────

    def _push_console(self, level: str, text: str, location: str | None) -> None:
        errish = level in ("error", "warning", "pageerror")
        if (self._n_err if errish else self._n_info) >= \
                (MAX_ERROR_CONSOLE if errish else MAX_INFO_CONSOLE):
            self.dropped["console"] += 1
            return
        if errish:
            self._n_err += 1
        else:
            self._n_info += 1
        self.console.append({
            "level": level, "text": text[:2000], "location": location,
            "ts": _now_ms(), "seq": next(self._seq),
        })

    def _on_console(self, msg: Any) -> None:
        level = _LEVELS.get(msg.type)
        if level is None:   # startGroup, table, …
            return
        location = None
        if msg.location and msg.location.get("url"):
            location = (f"{msg.location['url']}:{msg.location.get('lineNumber', 0)}"
                        f":{msg.location.get('columnNumber', 0)}")
        self._push_console(level, msg.text, location)

    def _on_page_error(self, error: Exception) -> None:
        self._push_console("pageerror", str(error), None)

    # ── Network ──────────────────────────────────────────────────────────

    def _on_request(self, request: Any) -> None:
        self._starts[id(request)] = time.time()

    def _finish(self, request: Any) -> tuple[int, float | None]:
        """Return (start ts in epoch ms, duration in ms) for a completing request."""
        start = self._starts.pop(id(request), None)
        if start is None:
            return _now_ms(), None
        return round(start * 1000), round((time.time() - start) * 1000, 1)

    def _push_network(self, entry: dict) -> None:
        if len(self.network) >= MAX_NETWORK_ENTRIES:
            self.dropped["network"] += 1
            return
        entry["seq"] = next(self._seq)
        self.network.append(entry)

    def _on_response(self, response: Any) -> None:
        request = response.request
        ts, duration = self._finish(request)   # always pop, even when capped
        if len(self.network) >= MAX_NETWORK_ENTRIES:
            self.dropped["network"] += 1
            return
        rt = request.resource_type
        failed = response.status >= 400
        headers = response.headers or {}
        size = None
        if str(headers.get("content-length", "")).isdigit():
            size = int(headers["content-length"])
        entry: dict[str, Any] = {
            "method": request.method, "url": redact_url(response.url)[:500],
            "status": response.status, "ok": not failed, "failure": None,
            "resource_type": rt, "ts": ts, "duration_ms": duration, "size": size,
        }
        if rt in RICH_TYPES:
            try:
                entry["request_headers"] = redact_headers(request.headers or {})
            except Exception:
                pass
            entry["response_headers"] = redact_headers(headers)
            post = None
            try:
                post = request.post_data
            except Exception:
                pass
            if post:
                entry["post_data"] = redact_text(
                    post[:MAX_POST_DATA * 2])[:MAX_POST_DATA]
        body = None
        want_ok_body = (not failed and rt in ("xhr", "fetch")
                        and "json" in str(headers.get("content-type", ""))
                        and (size or 0) <= MAX_JSON_BODY_SIZE)
        if failed or want_ok_body:
            # Best-effort: the body may be gone after a navigation.
            try:
                text = response.text().strip()[:MAX_RESPONSE_BODY]
                body = redact_text(text)[:MAX_RESPONSE_BODY] if text else None
            except Exception:
                body = None
        entry["body"] = body
        self._push_network(entry)

    def _on_request_failed(self, request: Any) -> None:
        ts, duration = self._finish(request)
        self._push_network({
            "method": request.method, "url": redact_url(request.url)[:500],
            "status": None, "ok": False,
            "failure": request.failure or "request failed",
            "resource_type": request.resource_type,
            "ts": ts, "duration_ms": duration, "size": None, "body": None,
        })

    def _on_websocket(self, ws: Any) -> None:
        self._push_network({
            "method": "WS", "url": redact_url(ws.url)[:500], "status": None,
            "ok": True, "failure": None, "resource_type": "websocket",
            "ts": _now_ms(), "duration_ms": None, "size": None, "body": None,
        })
