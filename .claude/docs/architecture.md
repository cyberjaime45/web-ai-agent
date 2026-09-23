# Architecture Reference

## Execution flow

```
conftest.py
  pytest_sessionstart  → banner, images dir, get_provider() once (UsageError when AI_PROVIDER is set without key/model),
                         _SessionBrowser (Playwright driver + browser shared by the session)
  pytest_collect_file  → FlowFile (any .md pytest traverses) → one FlowItem per device profile
                         (--profile > flow `## Config profiles:` > PROFILE; non-desktop items are named `flow[mobile]`)
  FlowItem.runtest()   → _SessionBrowser.page(name, profile): fresh BrowserContext shaped by profiles.context_options()
                         + Page (own grid session under lambda); context tracing started when TRACE=on-failure
                       → PageRecorder.attach(page)
                       → FlowRunner(provider=<session provider>, profile=…).run(flow, page, recorder=recorder)
                            for each action (grouped by ## section; a failure skips the rest of that section):
                              RUN_FLOW  → resolve_flow_path (relative to the calling file) → parse → recurse, same page
                              SKILL_ACTIONS → skills.run_skill(): marker StepResult(group=True, checks) + child steps
                                              the skill ran through execute(), tagged sub_flow=<skill>
                              else      → execute(): recorder seq mark → <ENV> placeholders → _run_step
                                          → on success after ORACLE_AFTER steps: oracle.run_checks → sr.checks
                                            (ORACLE=strict turns a failed error check into a failed step) → timing
                                            AI_ONLY → L3 AIResolver.resolve_ai_action()
                                            L1 DeterministicRunner.execute()   (raises on failure)
                                            L2 _layer2() → FallbackLocator     (RuntimeError when exhausted)
                                            L3 only if provider set AND AIResolver.supports(action.type):
                                               resolve(), then one re-prompt with page URL/title, then fail
                                          → on failure: attach_evidence() (evidence.collect: shots, URL/title,
                                            profile, console/network since the mark) → ctx.record
                       finally → _keep_trace (kept as traces/<flow>__<profile>.zip only when the flow failed,
                                 attached to the last failed step's evidence), record steps/error/capture for
                                 the report, LambdaTest status, close context
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

- Dispatch tables `_l1_handlers` / `_l2_handlers` keyed by `ActionType`. `_l1_handlers` is built by convention — every `ActionType` whose value has a `_h_<value>` method — and `tests/_framework/test_deterministic_registry.py` fails when a deterministic keyword has no handler.
- Exact Playwright locators; CSS/XPath go straight to `page.locator()` via `_is_selector()` (in `locator.py`).
- Shared resolvers: `_resolve_clickable_l1` (button → link → exact text), `_resolve_input_l1` (label → placeholder), `_resolve_text_target`, `_assert_disabled_state`. Add a new handler on top of these, not beside them.
- `_L1_TIMEOUT = 5000` caps action auto-wait; `_MAX_L1_RETRIES = 1` (a second identical window rarely changes the outcome and doubled failover latency).
- `settings.dismiss_blockers` (`DISMISS_BLOCKERS`, default off) runs `blockers.dismiss_blockers(page)` before each attempt.

Adding a new action type:
1. Enum value in `app/schemas/actions.py` + entry in `ACTION_ARG_SPEC` (arity is validated at parse time; a wrong count raises `FlowParseError`).
2. L1 handler `_h_<keyword>` in `deterministic.py` (picked up by name; the registry test enforces it).
3. L2 handler `_l2_<name>` in `deterministic_l2.py`, registered in `_build_l2_handlers`, if a fuzzy fallback makes sense.
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

- `execute` (public) is the one place a step is resolved, timed, recorded and given evidence — top-level, sub-flow and (later) skill steps all use it.
- Failed results are built by `_fail(action, message, layer, layers)`, where `layers` says what each layer did (`L1 exact` / `L2 fuzzy` / `L3 AI` → `failed`, `skipped: …`, `not attempted (…)`). `attach_evidence(sr, page, runner, since_seq)` completes the bundle through `app/observability/evidence.py` and is idempotent (conftest reuses it for the flow-end fallback). Skipped steps never get evidence.
- Evidence files are `images/<flow slug>__<profile>__<n>__{viewport,full,element}.png`; `n` counts failures per run.
- `run_flow`: `_seen_flows` (circular detection), `_MAX_NESTING_DEPTH = 10`, sub-flow `StepResult`s tagged with `sub_flow`.
- `RunContext.history` feeds the L3 prompt; `RunContext.data` holds values from `read_row` / `count_elements` / `get_attribute` / `ai_extract`.

## Skills — `app/skills/`

- `run_skill(engine, action, page, runner, ctx, recorder=, ignore=, profile=)` builds a `SkillContext`, calls the registered function, and returns `[marker, *children]`. The marker carries `checks`, `group=True`, the verdict (`success` = no error-severity failure, no failed child, no crash) and, when the skill took screenshots (`sc.screenshot(label)`), an `Evidence` with them. A crash inside a skill is a failed marker, never an exception out of the engine.
- `SkillContext.run(ActionType, *args)` builds the `FlowAction` (raw = `keyword: "a" | "b"`, same step_num/section as the skill step) and calls `engine.execute` — child steps get timing, evidence and oracle checks like any step.
- `parse_skill_args`: `key=value` → dict; a bare argument is `target`.
- `test_form`: `_STATE_JS` reports `native` (`:invalid`) and `aria` (`aria-invalid=true`) separately. Rejection = either, or a visible message, or same URL with the form present. "valid input accepted" uses `native` only (app validation is stale until the next submit); "submission accepted" uses `aria` + messages only (a reset form is natively invalid again). Field targets: label text unless the label wraps the control (composite accessible name) → selector.
- `test_responsive`: `set_viewport_size` per viewport (layout-only), `_LAYOUT_JS` probe, menu toggle clicked through `sc.run` only when nav links are hidden below 768px; original viewport restored in `finally`.

- `explore_page`: BFS by URL (`_plain` strips fragments); per page `_candidates` (safe, named, first-of-name, enabled clickable roles; nav first) optionally reordered by the planner; each press is `sc.run(CLICK, name)`; outcome from URL/origin change, `dialogs` delta, or `Observation.fingerprint()` (URL, title, controls, dialogs, visible-text hash). Broken pages come from the recorder's document status ≥ 400 and error-severity oracle checks on the child steps.

- `test_page`: nested skills through `SkillContext.run_skill` → `engine.run_group`; nested results are re-tagged `sub_flow="test_page"` (marker) / `"test_page/<skill>"` (children) so the reporter nests two levels. Only `sc.leaf_steps` (non-group, successful, `REPLAYABLE`) go into the generated flow. `explore_page` inside `test_page` runs with `generate=false` (one generated file per test_page).
- Reporter nesting is recursive on `sub_flow` levels (`_nest_sub_flows(steps, …, prefix)`): a step belongs to a level when its `sub_flow` equals the prefix; a marker owns every following step of other levels until its own level resumes.

## Planner and safety — `app/agent/planner.py`, `app/agent/safety.py`

- `Planner.plan` → `USER_TEMPLATE` (goal, `ob.to_prompt()`, history, allowed actions) → `parse_plan(raw, ob, policy, max_steps)`; fenced/prefixed JSON is tolerated, anything else is a rejected plan. `Plan.rejected` carries one reason per dropped step — keep them human-readable, they go to the report in Phase 4.
- `SafetyPolicy` is frozen; `with_destructive(True)` returns a copy. `Node.container` (`dialog:Name`, `form:Name`, …) is what gives confirm buttons their context — the observer's `CONTAINER_ROLES` stack in `parse_aria` maintains it.

## Observer — `app/agent/observer.py`

- `parse_aria(text)`: `- role "name" [attr] …` lines → `Node(ref, role, name, nth, attrs)` for headings + `INTERACTIVE_ROLES` (options excluded); counts for structural roles. Capped at 600 lines (`truncated`).
- `Node.locator(page)` = `get_by_role(role, name=name, exact=True).nth(nth)`.
- `_FORMS_JS`: visible forms (≤10) × fields (≤40) with label (own words only), type, required, minlength/maxlength, options, submit names, `wrapped`.
- `classify`: LOGIN (password field) → FORM (≥2 fields) → TABLE → LIST (≥10 links, ≤3 headings) → CONTENT → UNKNOWN.

## Oracle — `app/execution/oracle.py`

- `diagnostics_checks(recorder, since_seq, ignore)`: page errors (error), console errors (warn), 5xx/aborted (error), 401/403 (error), other 4xx (warn). `probe_checks(page)`: page rendered (error), spinner / dialog / overflow (warn).
- `IgnoreRules` from the flow's `## Config` (`ignore_console`, `ignore_network` substrings) are built once per `FlowRunner.run`.

## Evidence — `app/observability/evidence.py`

- `collect(page, images_dir, stem, evidence=, profile=, recorder=, since_seq=, locator=)`: every capture wrapped, logged at DEBUG, never raises. Full-page shots are capped at 10 s, element shots at 2 s.
- The element comes from `DeterministicRunner.locate(action)` — one `count()`, no waiting.
- `PageRecorder.seq` is the mark; `errors_since` / `failures_since` give the step's diagnostics (capped at 20 each; the full lists still go to the shards).

## Device profiles — `app/browser/profiles.py`

- `context_options(name, base, devices)`: desktop = the session's options; mobile = `playwright.devices[MOBILE_DEVICE]` minus `default_browser_type`, `no_viewport` dropped, `is_mobile` dropped on Firefox.
- `describe(name, viewport)` → the label in the report (`mobile · iPhone 13 · chromium · 390x664`).
- Under lambda the device is emulated inside the grid browser; no real-device mapping yet.

## conftest.py — pytest plugin

- `ProfessionalReportPlugin`: collects `TestReport`s, per-nodeid steps/errors/captures (steps serialize `evidence` via `dataclasses.asdict`), calls `generate_report` at session end, remembers `report_path`/`json_path` for the summary.
- `_SessionBrowser.page(test_name, profile)`: context manager yielding a page; local mode shares one browser, lambda mode opens a browser per call. Starts context tracing when `TRACE=on-failure`.
- `_flow_items(parent, config, flow)` yields one `FlowItem(profile=…)` per profile (`_profiles_for`: unknown names are a `UsageError`).
- `FlowItem.runtest` stamps `webagent_flow_file` / `webagent_flow_name` (item name, includes `[profile]`) / `webagent_healings` on `user_properties` for the console reporter; `_backfill_evidence` only when the engine could not shoot; `_keep_trace` stops the trace and, on failure, hangs it on the last failed step.
- `--flow` / `--flow_file` items are appended in `pytest_collection_modifyitems`, parented to the session (no file part in the console line). Note: they are appended to normal collection, so `pytest --flow …` with no path still collects `testpaths`.
- Thin integration layer only — no business logic here.

## Reporting — `app/observability/`

- `recorder.py`: console (error/warn vs info caps), network (cap 1500, rich headers/bodies for xhr/fetch/document, redaction), request-start map bounded at 2× the network cap. Everything here runs per browser event.
- `reporter.py`: `_build_tests` splits a flow into one test per `## section` when timestamps allow, routes console/network events to sections and steps (`_attribute_steps`, bisect), then writes `report.html`, `assets/{report.css,report.js,report-detail.js,nunito.woff2,data.js}`, one shard per test under `assets/data/`, and `report_<build slug>.json` (older `report*.json` removed). Each test carries `profile` and `artifacts` (`screenshot`, `screenshots` [{kind, path}], `trace`); a failed leaf carries `evidence` with report-relative paths (`_relative_evidence`).
- Report UI follows the Dashboard design system (the Dashboard project's `static/css/main.css`, "Cobalt Light"): same tokens and class names (`qa-card`, `run-verdict`, `run-hero`, `qa-badge-*`, `qa-tabs`, `side-drawer`, `drawer-step-callout`); Nunito ships in `assets/` and icons are inline SVG, so nothing loads from the network. Page order: summary card (verdict, pass rate, run bar) → Tests requiring attention (plain-English `explain(t)`, failed step via `actionLabel`, failure screenshot) → tabs All tests (suite groups, failing first, passing folded) / Suites / Timeline / Console / Network / Run details (facts, slowest, self-healed). `report.js` = summary + lists; `report-detail.js` = drawer (What went wrong → Summary → Steps → folded Technical details: error output, `evidenceHtml` layer attempts/page/trace/diagnostics, related activity, healed steps, Console/Network) and the shared console/network views. Rows open the drawer via one delegated `[data-open]` click handler.
- Never write outside `reports/<ENVIRONMENT>/` (`settings.report_dir`, project-root anchored).
