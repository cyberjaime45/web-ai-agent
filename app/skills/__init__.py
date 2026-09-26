"""QA skills — higher-level checks that orchestrate ordinary actions.

    inspect_page           what is on the page (deterministic, no browser actions)
    check_console_network  JS errors, console errors, failed / 4xx / 5xx requests
    test_responsive        layout checks across viewports, mobile menu
    test_form              field inventory, required / invalid / valid input, optional submit
    explore_page           bounded safe exploration building a page/action graph
    test_page              observe → classify → plan → run the skills above → generate a flow
    check_links            broken links (HEAD/GET, nothing clicked) and broken images
    check_accessibility    alt text, labels, control names, lang, headings, ids, tabindex, dialog focus
    test_table             headers and rows, sorting, pagination, a row opens its details
    test_search            search for a value the page shows, no-match, clear
    snapshot_page          structural baseline: what disappeared since it was saved
    test_widgets           tabs, disclosures and dialogs behave as their ARIA roles promise
    check_performance      TTFB, DOM ready, load, LCP, CLS against budgets (warnings)

Importing this package imports every module in it, and each module's
``@skill(ActionType.X)`` registers it in ``SKILLS``: adding a skill is a new
module here plus its ``ActionType`` (see ``base.py``). The engine dispatches
``SKILL_ACTIONS`` through ``run_skill``.
"""

import importlib
import pkgutil

from app.skills.base import SKILLS, SkillContext, parse_skill_args, run_skill

for _module in pkgutil.iter_modules(__path__):
    if _module.name != "base":
        importlib.import_module(f"{__name__}.{_module.name}")

__all__ = ["SKILLS", "SkillContext", "parse_skill_args", "run_skill"]
