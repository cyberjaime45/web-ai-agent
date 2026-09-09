"""Flow discovery is location-agnostic: any .md pytest traverses is a flow.

Runs a real `pytest --collect-only` in a subprocess so the root conftest's
``pytest_collect_file`` hook is exercised as-is. No browser is launched for
collection. The temporary flow lives under the gitignored ``reports/`` tree:
inside the repo (so the root conftest loads) but outside ``tests/`` and
outside any ``flows/`` directory — the case the old rule rejected.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

_FLOW = """# Home Page

## Test One
- goto: "https://example.com/"
- assert_text: "Example Domain"
"""


def test_md_outside_a_flows_directory_is_collected():
    root = _REPO / "reports" / "_discovery_test"
    scratch = root / uuid.uuid4().hex / "anywhere"
    scratch.mkdir(parents=True)
    flow = scratch / "home.md"
    flow.write_text(_FLOW, encoding="utf-8")
    env = {**os.environ, "AI_PROVIDER": "", "LLM_KEY": "", "LLM_MODEL": ""}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
             str(flow.relative_to(_REPO))],
            cwd=_REPO, env=env, capture_output=True, text=True, timeout=120, check=False,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "home.md::Home Page" in proc.stdout
    assert "1 test collected" in proc.stdout
