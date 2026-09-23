"""Device profiles — the BrowserContext options a flow runs under.

A profile only changes context creation (viewport, device emulation); the
browser process, the flow and every step stay the same. The same Markdown
therefore runs unchanged on desktop and on a phone.

    desktop   the session's own context options (VIEWPORT, or the maximized
              window in headed Chromium)
    mobile    Playwright's device descriptor named by MOBILE_DEVICE
              (default "iPhone 13": 390x664, touch, mobile user agent)

Which profiles a flow runs under is decided in this order: ``pytest --profile``,
then the flow's ``## Config`` ``profiles:`` line, then the PROFILE setting.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.config.settings import settings

DESKTOP = "desktop"
MOBILE = "mobile"
BUILTIN: tuple[str, ...] = (DESKTOP, MOBILE)

# Descriptor keys Playwright's `devices` carry that new_context() rejects.
_NOT_CONTEXT_OPTIONS = ("default_browser_type",)


def parse_names(spec: str | None) -> list[str]:
    """``"desktop, mobile"`` → ``["desktop", "mobile"]`` (lower-cased, de-duplicated)."""
    names: list[str] = []
    for part in (spec or "").split(","):
        name = part.strip().lower()
        if name and name not in names:
            names.append(name)
    return names


def validate(names: list[str]) -> list[str]:
    """Return *names* unchanged, or raise ``ValueError`` naming the unknown ones."""
    unknown = [n for n in names if n not in BUILTIN]
    if unknown:
        raise ValueError(
            f"Unknown profile(s): {', '.join(unknown)}. Available: {', '.join(BUILTIN)}"
        )
    return names


def context_options(name: str, base: dict, devices: Mapping[str, dict]) -> dict:
    """Merge the profile's emulation options into the session's context options.

    *base* comes from ``create_browser()``; *devices* is ``playwright.devices``.
    The mobile profile always sets an explicit viewport, so headed Chromium's
    ``no_viewport`` (maximized window) is dropped for it.
    """
    validate([name])
    if name == DESKTOP:
        return dict(base)

    descriptor = devices.get(settings.mobile_device)
    if descriptor is None:
        raise ValueError(
            f"MOBILE_DEVICE {settings.mobile_device!r} is not a Playwright device name"
        )
    options = {k: v for k, v in descriptor.items() if k not in _NOT_CONTEXT_OPTIONS}
    if settings.browser == "firefox":
        options.pop("is_mobile", None)   # Firefox rejects is_mobile
    merged = dict(base)
    merged.pop("no_viewport", None)
    merged.update(options)
    return merged


def describe(name: str, viewport: dict | None) -> str:
    """``mobile · iPhone 13 · chromium · 390x664`` — the label shown in the report."""
    parts = [name]
    if name == MOBILE:
        parts.append(settings.mobile_device)
    parts.append(settings.browser)
    if viewport:
        parts.append(f"{viewport.get('width', '?')}x{viewport.get('height', '?')}")
    return " · ".join(parts)
