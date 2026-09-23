"""Planner: JSON validation against the observation and the policy, call budget."""

from __future__ import annotations

from app.agent.observer import Field, Form, Observation, parse_aria
from app.agent.planner import Plan, Planner, parse_plan
from app.agent.safety import SafetyPolicy

SNAPSHOT = """\
- navigation "Main":
  - link "Members"
- heading "Members" [level=1]
- button "Add Member"
- textbox "Search"
- dialog "Delete member?":
  - button "OK"
- button "Delete member"
"""


def _ob() -> Observation:
    nodes, _, _ = parse_aria(SNAPSHOT)
    ob = Observation(url="https://x.test/members", title="Members", nodes=nodes)
    ob.forms = [Form("search", [Field("Search", "search", "Search")], ["Go"])]
    return ob


def test_valid_steps_by_ref_and_name():
    raw = '''```json
{"steps": [
  {"action": "click", "ref": "e3", "reason": "open the form"},
  {"action": "fill", "target": "search", "value": "Smith"},
  {"action": "assert_text", "target": "Member Details"},
  {"action": "test_form"}
]}
```'''
    plan = parse_plan(raw, _ob(), SafetyPolicy())
    assert [(s.action, s.target, s.value) for s in plan.steps] == [
        ("click", "Add Member", ""), ("fill", "Search", "Smith"),
        ("assert_text", "Member Details", ""), ("test_form", "", "")]
    assert plan.rejected == []
    assert plan.steps[1].args == ["Search", "Smith"] and plan.steps[0].args == ["Add Member"]


def test_invalid_steps_are_rejected_with_reasons():
    raw = '''{"steps": [
      {"action": "evaluate", "target": "document.cookie"},
      {"action": "click", "target": "Nonexistent"},
      {"action": "click", "ref": "e6"},
      {"action": "click", "ref": "e5"},
      {"action": "assert_text"},
      "garbage"
    ]}'''
    plan = parse_plan(raw, _ob(), SafetyPolicy())
    assert plan.steps == []
    assert plan.rejected == [
        "unknown action 'evaluate'",
        "click: target 'Nonexistent' is not on the page",
        "click 'Delete member' blocked by safety: name contains 'delete'",
        "click 'OK' blocked by safety: confirms dialog 'Delete member?' (delete)",
        "assert_text: missing target",
        "not an object: 'garbage'",
    ]


def test_unparseable_and_oversized_plans():
    assert parse_plan("Sure! Here is the plan.", _ob(), SafetyPolicy()).rejected == [
        "unparseable plan: no JSON object in the response"]
    assert parse_plan("{not json", _ob(), SafetyPolicy()).rejected[0].startswith("unparseable plan")
    many = '{"steps": [' + ",".join('{"action": "click", "ref": "e3"}' for _ in range(5)) + "]}"
    plan = parse_plan(many, _ob(), SafetyPolicy(), max_steps=2)
    assert len(plan.steps) == 2 and "plan cut at max_steps" in plan.rejected
    assert not Plan()


class FakeProvider:
    def __init__(self, response):
        self.response, self.calls = response, []

    def complete(self, system, user, *, temperature=0.0, max_tokens=500):
        self.calls.append(user)
        return self.response


def test_planner_budget_and_prompt():
    provider = FakeProvider('{"steps": [{"action": "click", "ref": "e3"}]}')
    planner = Planner(provider, max_calls=1)
    assert planner.available
    plan = planner.plan(_ob(), "explore", SafetyPolicy(), history=["click Members"])
    assert plan and plan.steps[0].target == "Add Member" and planner.calls == 1
    assert not planner.available and planner.plan(_ob(), "explore", SafetyPolicy()) is None
    prompt = provider.calls[0]
    assert "Goal: explore" in prompt and "- click Members" in prompt
    assert 'button "Add Member" [ref=e3]' in prompt and "<" not in prompt


def test_planner_without_provider_or_with_a_failing_one():
    assert Planner(None).plan(_ob(), "x", SafetyPolicy()) is None

    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("rate limited")
    plan = Planner(Boom()).plan(_ob(), "x", SafetyPolicy())
    assert plan is not None and not plan and plan.rejected == ["provider error: rate limited"]


def test_ai_classification_is_validated_and_budgeted():
    planner = Planner(FakeProvider('{"type": "dashboard", "reason": "cards"}'), max_calls=1)
    assert planner.classify(_ob()) == "DASHBOARD"
    assert planner.classify(_ob()) is None                      # budget spent
    assert Planner(FakeProvider('{"type": "SPACESHIP"}')).classify(_ob()) is None
    assert Planner(FakeProvider("nope")).classify(_ob()) is None
