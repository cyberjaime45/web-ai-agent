"""Run validated planner steps through a skill context.

Kept apart from the planner (which must not know how to execute) and from
the skills' base (which must not know about plans). A planned step is a
flow keyword with arguments; skills nest as groups, everything else is one
``SkillContext.run`` call. Stops at ``max_actions`` or the first failure.
"""

from __future__ import annotations

from app.agent.planner import PlannedStep
from app.schemas.actions import SKILL_ACTIONS, ActionType


def run_planned_steps(sc, steps: list[PlannedStep], max_actions: int) -> list[PlannedStep]:
    """Execute *steps* in order; returns the ones that ran."""
    executed: list[PlannedStep] = []
    for step in steps:
        if len(executed) >= max_actions:
            break
        try:
            action_type = ActionType(step.action)
        except ValueError:
            continue
        if action_type in SKILL_ACTIONS:
            result = sc.run_skill(action_type, *step.args)
        else:
            result = sc.run(action_type, *step.args)
        executed.append(step)
        if not result.success:
            break
    return executed
