"""`screenshot` captures the viewport; with "full_page" the whole scrollable page."""

from __future__ import annotations

import pytest
from PIL import Image

from app.execution.engine import FlowRunner
from app.flow.parser import FlowParseError, parse_flow_markdown

_TALL = '<body style="margin:0"><div style="height:1800px;background:linear-gradient(#fff,#000)">top</div></body>'


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    from app.layers.deterministic import DeterministicRunner
    monkeypatch.setattr(DeterministicRunner, "_L1_TIMEOUT", 600)


def _run(page, tmp_path, steps: str):
    page.set_viewport_size({"width": 800, "height": 600})
    page.set_content(_TALL)
    runner = FlowRunner(artifacts_dir=str(tmp_path), flows_dir=tmp_path, provider=None)
    return runner.run(parse_flow_markdown("# T\n\n## Steps\n" + steps), page)


def _height(step) -> int:
    with Image.open(step.screenshot_path) as image:
        return image.height


def test_the_viewport_by_default_and_the_whole_page_with_full_page(page, tmp_path):
    result = _run(page, tmp_path, '- screenshot\n- screenshot: "named"\n'
                                  '- screenshot: "whole" | "full_page"\n- screenshot: "full_page"\n')
    assert result.success, [s.error for s in result.steps]
    viewport, named, whole, unnamed_whole = result.steps
    assert _height(viewport) == _height(named) == 600
    assert _height(whole) == _height(unnamed_whole) == 1800
    assert named.screenshot_path.endswith("_named.png") and whole.screenshot_path.endswith("_whole.png")
    assert unnamed_whole.screenshot_path.endswith("_step_4.png")          # the option is not taken as the name


def test_a_second_argument_must_be_the_option(page, tmp_path):
    result = _run(page, tmp_path, '- screenshot: "a" | "b"\n')
    assert not result.success and 'option "full_page"' in (result.steps[0].error or result.steps[0].message)
    with pytest.raises(FlowParseError):
        parse_flow_markdown('# T\n\n## Steps\n- screenshot: "a" | "full_page" | "x"\n')
