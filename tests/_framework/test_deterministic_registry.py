"""L1/L2 dispatch tables and locate(): every keyword has its handler."""

from __future__ import annotations

from types import SimpleNamespace

from app.layers.deterministic import DeterministicRunner
from app.schemas.actions import AI_ONLY_ACTIONS, SKILL_ACTIONS, ActionType, FlowAction

_NOT_L1 = AI_ONLY_ACTIONS | SKILL_ACTIONS | {ActionType.RUN_FLOW}


class _Loc:
    def __init__(self, n):
        self.n = n
        self.first = self

    def count(self):
        return self.n


class _Page:
    """Exact-match resolvers only ever call count(); answer for one name."""
    def __init__(self, present: str):
        self.present = present

    def _loc(self, name=None, **_):
        return _Loc(1 if name == self.present else 0)

    def get_by_role(self, role, name=None, **kw):
        return self._loc(name)

    def get_by_text(self, text, **kw):
        return self._loc(text)

    def get_by_label(self, text, **kw):
        return self._loc(text)

    def get_by_placeholder(self, text, **kw):
        return self._loc(text)

    def locator(self, sel):
        return self._loc(sel)


def _runner(tmp_path, present="Save"):
    return DeterministicRunner(_Page(present), artifacts_dir=tmp_path)


def test_every_deterministic_action_has_an_l1_handler(tmp_path):
    runner = _runner(tmp_path)
    missing = [t.value for t in ActionType if t not in _NOT_L1 and t not in runner._l1_handlers]
    assert missing == []
    assert not any(t in runner._l1_handlers for t in _NOT_L1)


def test_l2_handlers_are_a_subset_of_l1(tmp_path):
    runner = _runner(tmp_path)
    assert set(runner._l2_handlers) <= set(runner._l1_handlers)


def test_locate_uses_the_l1_resolver_for_the_action_kind(tmp_path):
    runner = _runner(tmp_path, present="Save")
    hit = FlowAction(type=ActionType.CLICK, args=["Save"])
    miss = FlowAction(type=ActionType.CLICK, args=["Nope"])
    assert runner.locate(hit) is not None
    assert runner.locate(miss) is None
    assert runner.locate(FlowAction(type=ActionType.FILL, args=["Save"])) is not None
    assert runner.locate(FlowAction(type=ActionType.GOTO, args=["https://x"])) is None   # no element
    assert runner.locate(FlowAction(type=ActionType.WAIT, args=[])) is None


def test_locate_never_raises(tmp_path):
    runner = DeterministicRunner(SimpleNamespace(), artifacts_dir=tmp_path)   # page with no locators
    assert runner.locate(FlowAction(type=ActionType.CLICK, args=["x"])) is None
