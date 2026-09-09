"""Startup banner: plain centered text with version, author, build, environment."""

from __future__ import annotations

from app.utils import banner
from app.utils.banner import banner_text


def test_banner_lists_version_author_build_and_environment(monkeypatch):
    monkeypatch.setenv("BUILD_NAME", "Release 4.2 Smoke")
    text = banner_text(width=100)
    lines = [ln.strip() for ln in text.splitlines()]
    assert f"Version: {banner.APP_VERSION}" in lines
    assert f"Created by: {banner.CREATED_BY}" in lines
    assert "Build: Release 4.2 Smoke" in lines
    assert lines[-1] == banner.settings.run_label()   # same label the summary ends with


def test_banner_is_centered_and_plain_without_color():
    text = banner_text(width=120)
    assert "\033[" not in text
    for line in text.splitlines():
        assert len(line) <= 120
        # centered: leading indent roughly half the free space, never flush-left
        if line.strip():
            assert line.startswith(" ")


def test_banner_wraps_in_green_when_colored():
    text = banner_text(color=True, width=100)
    assert text.startswith("\033[32m") and text.endswith("\033[0m")
