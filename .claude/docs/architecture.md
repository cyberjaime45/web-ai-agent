# Architecture Reference

## Execution flow

```
conftest.py
  pytest_sessionstart  → banner, images dir, get_provider() once (UsageError on partial AI config),
                         _SessionBrowser (Playwright driver + browser shared by the session)
  pytest_collect_file  → FlowFile (.md under any flows/ dir) → FlowItem
  FlowItem.runtest()   → _SessionBrowser.page(): fresh BrowserContext + Page (own grid session under lambda)
                       → PageRecorder.attach(page)
                       → FlowRunner(provider=<session provider>).run(flow, page)
                            for each action (grouped by ## section; a failure skips the rest of that section):
                              RUN_FLOW  → resolve_flow_path (relative to the calling file) → parse → recurse, same page
                              AI_ONLY   → L3 AIResolver.resolve_ai_action()
                              else      → _execute_one(): <ENV> placeholders → _run_step → timing → ctx.record
                                            L1 DeterministicRunner.execute()   (raises on failure)
                                            L2 _layer2() → FallbackLocator     (RuntimeError when exhausted)
                                            L3 only if provider set AND AIResolver.supports(action.type):
                                               resolve(), then one re-prompt with page URL/title, then fail
                       finally → record steps/error/capture for the report, LambdaTest status, close context
  pytest_sessionfinish → generate_report() (skipped on --collect-only / nothing ran), close session browser
  pytest_terminal_summary → Execution summary + report paths
```

## Layer contracts

| Layer | Success | Failure signal |
|-------|---------|----------------|
| L1 `DeterministicRunner.execute` | `StepResult(layer_used=1)` | raises (any exception) after `_MAX_L1_RETRIES` attempts, each capped at `_L1_TIMEOUT` |
| L2 `_layer2` → `FallbackLocator` | `StepResult(layer_used=2)` | L2 handler returns `None` → `RuntimeError("Layers 1+2 could not resolve …")` |
| L3 `AIResolver.resolve` | `StepResult(layer_used=3)` | returns `None` (no locator match, LLM/parse error); engine re-prompts once, then marks the step failed |

The engine never catches inside a layer's own retry; it catches at the boundary and moves down the chain.

## L1 — DeterministicRunner

- Dispatch tables `_l1_handlers` / `_l2_handlers` keyed by `ActionType`.
- Exact Playwright locators; CSS/XPath go straight to `page.locator()` via `_is_selector()` (in `locator.py`).
- Shared resolvers: `_resolve_clickable_l1` (button → link → exact text), `_resolve_input_l1` (label → placeholder), `_resolve_text_target`, `_assert_disabled_state`. Add a new handler on top of these, not beside them.
- `_L1_TIMEOUT = 5000` caps action auto-wait; `_MAX_L1_RETRIES = 1` (a second identical window rarely changes the outcome and doubled failover latency).
- `_DISMISS_BLOCKERS` (env, default off) runs the cookie/modal dismisser before each attempt.

Adding a new action type:
1. Enum value in `app/schemas/actions.py` + entry in `ACTION_ARG_SPEC` (arity is validated at parse time; a wrong count raises `FlowParseError`).
2. L1 handler in `deterministic.py`, registered in `_l1_handlers`.
3. L2 handler in `_l2_handlers` if a fuzzy fallback makes sense.
4. If L3 can perform it with a locator, add it to `_LOCATOR_ACTIONS` in `ai_resolver.py`; otherwise it never reaches L3.
5. Document it in `docs/ACTIONS.md` (group counts must still add up to the enum size).

## L2 — FallbackLocator

- `resolve_clickable` / `resolve_input`: four looser Playwright strategies polled every 200 ms for up to 5 s (`_resolve_with_poll`), **then** one selectolax pass (`_best_fuzzy`, similarity ≥ `_FUZZY_MIN` = 0.6). The fuzzy pass serialises and parses the whole DOM, which is why it is outside the poll loop — keep it there.
- `resolve_checkbox`: label → checkbox role → radio role, polled.
- Selector-looking targets short-circuit to `page.locator()`.
- L2 assertion handlers check `page.content()` once per call.

## L3 — AIResolver

- Constructed with an `LLMProvider` or `None`; `available` reflects that. The provider is built once per session in conftest and injected (`FlowRunner(provider=…)`); the CLI resolves it from settings.
- `supports(action_type)`: only `_LOCATOR_ACTIONS` (click, fill, select, check…) are sent to L3. Assertions, waits, key presses and navigation have no L3 path and fail at L2.
- Prompts live in `app/agent/prompts/resolver.py`; keep their structure stable.
- Test with `LLM_KEY= LLM_MODEL=` (empty overrides beat `.env`) to confirm graceful skip.

## FlowRunner — `app/execution/engine.py`

- `_execute_one` is the one place a step is resolved, timed and recorded — top-level and sub-flow loops both use it.
- `capture_failure_screenshot(page, dir)` is the single capture routine (conftest reuses it for the flow-end fallback). The engine shoots at the failure site; skipped steps never get a screenshot.
- `run_flow`: `_seen_flows` (circular detection), `_MAX_NESTING_DEPTH = 10`, sub-flow `StepResult`s tagged with `sub_flow`.
- `RunContext.history` feeds the L3 prompt; `RunContext.data` holds values from `read_row` / `count_elements` / `get_attribute` / `ai_extract`.

## conftest.py — pytest plugin

- `ProfessionalReportPlugin`: collects `TestReport`s, per-nodeid steps/errors/captures, calls `generate_report` at session end, remembers `report_path`/`json_path` for the summary.
- `_SessionBrowser.page(test_name)`: context manager yielding a page; local mode shares one browser, lambda mode opens a browser per call.
- `FlowItem.runtest` stamps `webagent_flow_file` / `webagent_flow_name` / `webagent_healings` on `user_properties` for the console reporter; `_backfill_failure_screenshot` only when the engine could not shoot.
- `--flow` / `--flow_file` items are appended in `pytest_collection_modifyitems`, parented to the session (no file part in the console line).
- Thin integration layer only — no business logic here.

## Reporting — `app/observability/`

- `recorder.py`: console (error/warn vs info caps), network (cap 1500, rich headers/bodies for xhr/fetch/document, redaction), request-start map bounded at 2× the network cap. Everything here runs per browser event.
- `reporter.py`: `_build_tests` splits a flow into one test per `## section` when timestamps allow, routes console/network events to sections and steps (`_attribute_steps`, bisect), then writes `report.html`, `assets/{report.css,report.js,data.js}`, one shard per test under `assets/data/`, and `report_<build slug>.json` (older `report*.json` removed).
- Report UI tabs: Overview (result donut, duration histogram with total, healed locators, failures, slowest, suites), Tests (file groups, status chips, search), Timeline (lanes), Console and Network (execution-level, load all shards on first open), Summary. Per-test drawer: steps tree with failure screenshot, related activity, healed locators, Console/Network panes.
- Never write outside `reports/<ENVIRONMENT>/` (`settings.report_dir`, project-root anchored).
