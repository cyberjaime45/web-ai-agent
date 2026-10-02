"""REPORT_DIR: one run's report can go to a folder of its own."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import PROJECT_ROOT, Settings


def test_the_report_folder_follows_the_environment_by_default(monkeypatch):
    monkeypatch.delenv("REPORT_DIR", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "qa1")
    settings = Settings()
    assert settings.report_dir == PROJECT_ROOT / "reports" / "qa1"
    assert settings.images_dir == PROJECT_ROOT / "reports" / "qa1" / "images"


def test_report_dir_overrides_it_for_this_run(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ENVIRONMENT", "qa1")
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "run-7"))
    settings = Settings()
    assert settings.environment == "qa1"                          # the label is unchanged
    assert settings.report_dir == (tmp_path / "run-7").resolve()
    assert settings.images_dir == settings.report_dir / "images"
    assert settings.traces_dir == settings.report_dir / "traces"


def test_a_relative_report_dir_is_taken_from_the_project_root(monkeypatch):
    monkeypatch.setenv("REPORT_DIR", "reports/_runs/7")
    assert Settings().report_dir == PROJECT_ROOT / "reports" / "_runs" / "7"
