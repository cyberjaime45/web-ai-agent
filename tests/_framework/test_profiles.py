"""Device profiles: name parsing, validation, context options, labels."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.browser import profiles

IPHONE = {
    "user_agent": "Mozilla/5.0 (iPhone; …)",
    "viewport": {"width": 390, "height": 664},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "default_browser_type": "webkit",
}
DEVICES = {"iPhone 13": IPHONE}


def test_parse_names_lowercases_strips_and_dedupes():
    assert profiles.parse_names(" Desktop, mobile ,desktop") == ["desktop", "mobile"]
    assert profiles.parse_names("") == [] and profiles.parse_names(None) == []


def test_validate_names_the_unknown_ones():
    assert profiles.validate(["desktop", "mobile"]) == ["desktop", "mobile"]
    with pytest.raises(ValueError, match="tablet"):
        profiles.validate(["desktop", "tablet"])


def test_desktop_keeps_the_session_options():
    base = {"viewport": {"width": 1920, "height": 1080}}
    assert profiles.context_options("desktop", base, DEVICES) == base
    assert profiles.context_options("desktop", base, DEVICES) is not base


def _settings(monkeypatch, browser="chromium", mobile_device="iPhone 13"):
    # Settings is a frozen dataclass: swap the module's reference, not a field.
    monkeypatch.setattr(profiles, "settings",
                        SimpleNamespace(browser=browser, mobile_device=mobile_device))


def test_mobile_applies_the_device_and_drops_no_viewport(monkeypatch):
    _settings(monkeypatch)
    opts = profiles.context_options("mobile", {"no_viewport": True}, DEVICES)
    assert "no_viewport" not in opts                 # headed Chromium's maximized window
    assert "default_browser_type" not in opts        # descriptor key new_context() rejects
    assert opts["viewport"] == {"width": 390, "height": 664}
    assert opts["is_mobile"] and opts["has_touch"]


def test_mobile_on_firefox_drops_is_mobile(monkeypatch):
    _settings(monkeypatch, browser="firefox")
    opts = profiles.context_options("mobile", {}, DEVICES)
    assert "is_mobile" not in opts and opts["has_touch"]


def test_unknown_device_name_is_an_error(monkeypatch):
    _settings(monkeypatch, mobile_device="Nokia 3310")
    with pytest.raises(ValueError, match="Nokia 3310"):
        profiles.context_options("mobile", {}, DEVICES)


def test_describe_labels(monkeypatch):
    _settings(monkeypatch)
    assert profiles.describe("desktop", {"width": 1920, "height": 1080}) == "desktop · chromium · 1920x1080"
    assert profiles.describe("mobile", {"width": 390, "height": 664}) == "mobile · iPhone 13 · chromium · 390x664"
    assert profiles.describe("desktop", None) == "desktop · chromium"
