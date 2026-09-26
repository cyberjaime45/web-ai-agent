"""QA skills — higher-level checks that orchestrate ordinary actions.

    inspect_page           what is on the page (deterministic, no browser actions)
    check_console_network  JS errors, console errors, failed / 4xx / 5xx requests
    test_responsive        layout checks across viewports, mobile menu
    test_form              field inventory, required / invalid / valid input, optional submit
    explore_page           bounded safe exploration building a page/action graph
    test_page              observe → classify → plan → run the skills above → generate a flow
    check_links            broken links (HEAD/GET, nothing clicked) and broken images

Importing this package registers every skill in ``SKILLS``; the engine
dispatches ``SKILL_ACTIONS`` through ``run_skill``.
"""

from app.skills import (  # noqa: F401  (registration)
    check_console_network, check_links, explore_page, inspect_page, test_form, test_page,
    test_responsive,
)
from app.skills.base import SKILLS, SkillContext, parse_skill_args, run_skill

__all__ = ["SKILLS", "SkillContext", "parse_skill_args", "run_skill"]
