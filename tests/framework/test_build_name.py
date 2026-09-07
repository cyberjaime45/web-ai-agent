"""BUILD_NAME resolution — value when set, fallback when unset or blank."""

from app.utils.build import DEFAULT_BUILD_NAME, get_build_name


def test_build_name_uses_the_env_value(monkeypatch):
    monkeypatch.setenv("BUILD_NAME", "  Release 4.2 smoke ")
    assert get_build_name() == "Release 4.2 smoke"


def test_build_name_falls_back_when_unset(monkeypatch):
    monkeypatch.delenv("BUILD_NAME", raising=False)
    assert get_build_name() == DEFAULT_BUILD_NAME == "Web Test Report"


def test_build_name_falls_back_when_blank(monkeypatch):
    for blank in ("", "   "):
        monkeypatch.setenv("BUILD_NAME", blank)
        assert get_build_name() == DEFAULT_BUILD_NAME
