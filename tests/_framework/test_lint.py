"""Flow lint rules and the healed-steps report (no browser)."""

from __future__ import annotations

import json
from pathlib import Path

from app.flow.lint import healings, lint


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _rules(findings) -> list[tuple[str, int, str]]:
    return [(f.path, f.line, f.rule) for f in findings]


def test_step_rules(tmp_path):
    _write(tmp_path, "flows/a.md", """# A

## Login
- goto: "https://x.test"
- goto: "https://x.test"
- fill: "Password" | "hunter2"
- fill: "API key" | "<API_KEY>"
- wait: 3000
- wait: 0
- clikc: "Save"
- click: "+"
- click: "+"
- assert_text: "Welcome"
- assert_text: "Welcome"
""")
    got = _rules(lint([tmp_path], root=tmp_path))
    assert got == [
        ("flows/a.md", 5, "duplicate-step"),     # goto twice; the two "+" clicks are fine
        ("flows/a.md", 6, "literal-secret"),     # the <API_KEY> placeholder is fine
        ("flows/a.md", 8, "fixed-wait"),         # wait: 0 is not flagged
        ("flows/a.md", 10, "unknown-step"),
        ("flows/a.md", 14, "duplicate-step"),
    ]


def test_sections_without_checks_but_not_components(tmp_path):
    _write(tmp_path, "flows/a.md", """# A

## Open
- goto: "https://x.test"
- click: "Members"

## Check
- goto: "https://x.test"
- check_links
""")
    _write(tmp_path, "flows/components/login.md", '# Login\n\n## Steps\n- goto: "https://x.test/login"\n')
    got = _rules(lint([tmp_path], root=tmp_path))
    assert ("flows/a.md", 4, "no-assertion") in got
    assert not any(r == "no-assertion" and p.endswith("login.md") for p, _, r in got)
    assert ("flows/a.md", 8, "no-assertion") not in got      # a skill counts as a check


def test_run_flow_references(tmp_path):
    _write(tmp_path, "flows/a.md", """# A

## Steps
- run_flow: "components/login"
- run_flow: "components/nope"
- assert_text: "Home"
""")
    _write(tmp_path, "flows/components/login.md", '# Login\n\n## Steps\n- goto: "https://x.test/login"\n')
    _write(tmp_path, "flows/components/old.md", '# Old\n\n## Steps\n- goto: "https://x.test/old"\n')
    got = _rules(lint([tmp_path], root=tmp_path))
    assert ("flows/a.md", 5, "missing-component") in got
    assert ("flows/components/old.md", 1, "unused-component") in got
    assert not any(p.endswith("login.md") and r == "unused-component" for p, _, r in got)


def test_repeated_steps_point_at_the_first_flow(tmp_path):
    login = '- goto: "https://x.test"\n- fill: "Email" | "<EMAIL>"\n- click: "Next"\n- click: "Sign in"\n'
    _write(tmp_path, "flows/a.md", f"# A\n\n## Steps\n{login}- assert_text: \"A\"\n")
    _write(tmp_path, "flows/b.md", f"# B\n\n## Steps\n{login}- assert_text: \"B\"\n")
    repeated = [f for f in lint([tmp_path], root=tmp_path) if f.rule == "repeated-steps"]
    assert len(repeated) == 1
    assert (repeated[0].path, repeated[0].line) == ("flows/b.md", 4)
    assert repeated[0].message.startswith("4 steps also in flows/a.md:4")


def test_parse_error_is_a_finding(tmp_path):
    _write(tmp_path, "flows/bad.md", '# Bad\n\n## Steps\n- goto: "a" | "b"\n')
    assert _rules(lint([tmp_path], root=tmp_path)) == [("flows/bad.md", 4, "parse-error")]


def test_healings_count_reports(tmp_path):
    test = {"file": "tests/a.md", "name": "Home",
            "healings": [{"description": 'click: "Save"', "healed_by": "L2 (fuzzy match)"}]}
    for name in ("r1.json", "r2.json"):
        (tmp_path / name).write_text(json.dumps({"tests": [test, {"file": "x", "healings": []}]}))
    assert healings([tmp_path / "r1.json", tmp_path / "r2.json"]) == [{
        "file": "tests/a.md", "test": "Home", "step": 'click: "Save"',
        "healed_by": "L2 (fuzzy match)", "reports": 2}]
