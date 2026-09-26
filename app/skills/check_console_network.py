"""check_console_network — browser diagnostics since the last check.

Reads the flow's PageRecorder (events already captured for the report);
nothing is re-fetched. The window starts at the previous
``check_console_network`` step, or at the start of the flow.

    - check_console_network                 page errors / 5xx / 401 / 403 fail the step,
                                            console errors and other 4xx are warnings
    - check_console_network: "console=strict"   console errors fail it too

Flow-level ``ignore_console`` / ``ignore_network`` (``## Config``) drop
known noise before anything is judged.
"""

from __future__ import annotations

from app.execution import oracle
from app.schemas.actions import ActionType, Check
from app.skills.base import SkillContext, skill

_MARK_KEY = "_check_console_network_seq"


@skill(ActionType.CHECK_CONSOLE_NETWORK)
def check_console_network(sc: SkillContext) -> list[Check]:
    if sc.recorder is None:
        return [Check("browser diagnostics available", False, "warn",
                      "no PageRecorder attached to this run, so console and network were not captured")]
    since = int(sc.ctx.data.get(_MARK_KEY, "0"))
    checks = oracle.diagnostics_checks(sc.recorder, since, sc.ignore)
    if sc.option("console") == "strict":
        for c in checks:
            if c.name == "no console errors":
                c.severity = "error"
    sc.ctx.store(_MARK_KEY, str(sc.recorder.seq))
    return checks
