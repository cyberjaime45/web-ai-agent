"""Failure evidence — what the report needs to explain a failed step.

One call per failed step, from the engine (``FlowRunner.attach_evidence``),
after the L1 → L2 → L3 chain has given up. Everything here is best-effort:
a capture that fails (page navigating, crashed, element hidden) is skipped
and logged at DEBUG; nothing raises. The flow-level Playwright trace is not
captured here — it is stopped at flow end by conftest, which sets
``Evidence.trace`` on the failing step.

Files land under ``reports/<env>/images/`` as
``<flow>__<profile>__<n>__viewport.png`` / ``…__full.png`` / ``…__element.png``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.browser.profiles import describe
from app.schemas.actions import Evidence

logger = logging.getLogger(__name__)

VIEWPORT_TIMEOUT_MS = 5_000
FULL_PAGE_TIMEOUT_MS = 10_000   # long pages take a while to stitch; give up rather than hang
ELEMENT_TIMEOUT_MS = 2_000
MAX_ENTRIES = 20                # console / network rows kept per step (full lists live in the shards)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SUFFIX = {"viewport": "viewport", "full_page": "full", "element": "element"}


def slugify(text: str) -> str:
    """``"FMS MVC Smoke Tests"`` → ``"fms_mvc_smoke_tests"`` (file-name safe)."""
    return _SLUG_RE.sub("_", (text or "").lower()).strip("_")[:80].rstrip("_") or "flow"


def _viewport(page: Any) -> dict | None:
    try:
        vp = page.viewport_size
        if vp:
            return dict(vp)
        w, h = page.evaluate("() => [window.innerWidth, window.innerHeight]")
        return {"width": int(w), "height": int(h)}
    except Exception:
        return None


def _shoot(kind: str, path: Path, fn) -> str | None:
    try:
        fn(str(path))
        return str(path)
    except Exception as exc:
        # %-style: Playwright errors carry multi-KB call logs.
        logger.debug("[evidence] %s screenshot skipped: %s", kind, exc)
        return None


def collect(
    page: Any,
    images_dir: Path,
    stem: str,
    *,
    evidence: Evidence | None = None,
    profile: str = "desktop",
    recorder: Any = None,
    since_seq: int = 0,
    locator: Any = None,
) -> Evidence:
    """Fill *evidence* (or a new one) with screenshots, page state and diagnostics.

    *stem* names the files (``<flow>__<profile>__<n>``); *locator* is the
    element the step targeted when L1 could still resolve one — its shot is
    the "failed element" screenshot. *recorder* + *since_seq* give the
    console/network entries that happened during the step.
    """
    ev = evidence if evidence is not None else Evidence()
    ev.profile = describe(profile, _viewport(page))

    try:
        ev.url = page.url
    except Exception:
        pass
    try:
        ev.title = page.title()
    except Exception:
        pass

    shots = ev.screenshots
    wanted = {
        "viewport": lambda p: page.screenshot(path=p, full_page=False, timeout=VIEWPORT_TIMEOUT_MS),
        "full_page": lambda p: page.screenshot(path=p, full_page=True, timeout=FULL_PAGE_TIMEOUT_MS),
    }
    if locator is not None:
        wanted["element"] = lambda p: locator.screenshot(path=p, timeout=ELEMENT_TIMEOUT_MS)
    for kind, shoot in wanted.items():
        if kind in shots:
            continue   # already captured (flow-end fallback after a failure-site capture)
        if path := _shoot(kind, images_dir / f"{stem}__{_SUFFIX[kind]}.png", shoot):
            shots[kind] = path

    if recorder is not None:
        try:
            ev.console = list(recorder.errors_since(since_seq, MAX_ENTRIES))
            ev.network = list(recorder.failures_since(since_seq, MAX_ENTRIES))
        except Exception as exc:
            logger.debug("[evidence] diagnostics skipped: %s", exc)
    return ev


# ── Playwright trace ────────────────────────────────────────────────────────

def stop_trace(page: Any, keep: bool, traces_dir: Path, stem: str) -> str | None:
    """Stop the context's trace; keep it as ``traces_dir/<stem>.zip`` when *keep*.

    Recording starts with the context (conftest); this runs at flow end,
    before the context closes. Returns the zip path or ``None``.
    """
    try:
        tracing = page.context.tracing
        if not keep:
            tracing.stop()
            return None
        traces_dir.mkdir(parents=True, exist_ok=True)
        path = traces_dir / f"{stem}.zip"
        tracing.stop(path=str(path))
        return str(path)
    except Exception as exc:
        logger.debug("[evidence] trace not kept: %s", exc)
        return None


# ── Screenshot annotation ───────────────────────────────────────────────────

_ERROR_ELEMENT_JS = """
    () => {
        const selectors = [
            '[role="alert"]', '.error', '.alert-danger', '.alert-error',
            '[aria-invalid="true"]', '.invalid-feedback', 'p.error',
            'span.error', '.flash.error', '.notification-error',
            '#error', '.error-message', '.validation-error', '.is-invalid'
        ];
        const found = [];
        for (const sel of selectors) {
            try {
                for (const el of document.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.top >= 0)
                        found.push({x: r.left, y: r.top, w: r.width, h: r.height});
                }
            } catch(e) {}
        }
        return found;
    }
"""


def annotate_error_elements(shot_path: str, page: Any) -> None:
    """Draw red rectangles on a viewport screenshot where the DOM shows error
    elements (alerts, invalid fields). Best-effort; never blocks reporting."""
    try:
        from PIL import Image, ImageDraw  # type: ignore[import]

        rects = page.evaluate(_ERROR_ELEMENT_JS)
        if not rects:
            return  # No identifiable error elements — keep screenshot clean

        img = Image.open(shot_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        vp_width = (page.viewport_size or {}).get("width", 1280)
        scale = img.width / vp_width if vp_width else 1.0
        for rect in rects[:4]:
            pad = 3
            x1 = max(0,         int(rect["x"] * scale) - pad)
            y1 = max(0,         int(rect["y"] * scale) - pad)
            x2 = min(img.width, int((rect["x"] + rect["w"]) * scale) + pad)
            y2 = min(img.height, int((rect["y"] + rect["h"]) * scale) + pad)
            if x2 > x1 and y2 > y1:
                for offset in range(3):
                    draw.rectangle(
                        [x1 - offset, y1 - offset, x2 + offset, y2 + offset],
                        outline=(220, 38, 38),
                    )
        img.save(shot_path)
    except Exception as exc:
        logger.debug("[evidence] annotation skipped: %s", exc)
