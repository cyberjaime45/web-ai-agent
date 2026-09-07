# Architecture Reference

## Execution flow

```
conftest.py
  pytest_collect_file()
    → FlowFile (collection node)
      → FlowItem.runtest()
        → FlowDefinition (parsed Markdown)
          → FlowRunner.run(flow, page)
            → for each action:
                if RUN_FLOW:
                  → resolve_flow_path() → parse sub-flow
                  → execute sub-flow actions recursively (same page)
                  → tag StepResults with sub_flow name
                else if AI_ONLY:
                  → L3: AIResolver.resolve_ai_action()
                else:
                  → L1: DeterministicRunner.execute(action)
                    → success: next step
                    → fail (any exception):
                  → L2: FallbackLocator.resolve_*() via _layer2()
                    → success: next step
                    → fail (RuntimeError):
                  → L3: AIResolver.resolve()   [if OPENAI_API_KEY set]
                    → success: next step
                    → fail: mark step failed, stop flow
```

## Layer contracts

Each layer signals failure via standard exceptions. FlowRunner catches exceptions to trigger the next layer.

| Layer | Success | Failure signal |
|-------|---------|---------------|
| L1 DeterministicRunner | Returns `StepResult` | Raises `PlaywrightTimeout`, `AssertionError`, or `Exception` |
| L2 FallbackLocator | Returns `StepResult` (via L2 handler) | Raises `RuntimeError` (all strategies exhausted) |
| L3 AIResolver | Returns `StepResult` | Returns `None` (missing API key or LLM error) |

## L1 — DeterministicRunner

- Dispatch-table driven: `ActionType` → handler function
- Uses exact Playwright role/label/placeholder locators
- Supports CSS selectors and XPath directly via `_is_selector()` (shared function in `locator.py`)
- `_L1_TIMEOUT = 5000ms` — caps Playwright's auto-wait on action calls (click, fill, etc.) for fast failover to L2
- The page's `default_timeout` (30s) is preserved for explicit waits and assertions
- Handles ~80% of steps in a healthy flow

Adding a new action type:
1. Add enum value in `app/schemas/actions.py`
2. Add arg spec in `ACTION_ARG_SPEC`
3. Add L1 handler function in `deterministic.py`
4. Register in `_l1_handlers` dispatch table
5. Add L2 handler if fuzzy fallback makes sense
6. Update README.md

## L2 — FallbackLocator

- Activated only when L1 fails
- Resolution methods (current strategy counts):
  - `resolve_clickable`: 5 strategies (fuzzy role, text exact/partial, selectolax)
  - `resolve_input`: 5 strategies (label, placeholder, textbox role, selectolax)
  - `resolve_checkbox`: 3 strategies (label, checkbox role, radio role)
- Uses selectolax for DOM similarity matching (threshold ≥ 0.6, hardcoded)
- CSS/XPath selectors shortcut at the top of `resolve_clickable` and `resolve_input`

When adding a new fuzzy strategy:
- Add it at the END of the strategy list (least disruptive)
- Document why it's needed and what L1/L2 gaps it fills

## L3 — AIResolver

- Activated only when L1 + L2 both fail
- Optional: skipped automatically if `OPENAI_API_KEY` not set
- Also handles AI-native actions directly (`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`)
- Must never be required for a flow to pass — flows must degrade gracefully without it

When modifying AIResolver:
- Keep the prompt structure stable — changes here affect all flows
- Test with `OPENAI_API_KEY` unset to confirm graceful skip

## FlowRunner — `app/execution/engine.py`

- Orchestrates the L1 → L2 → L3 fallback chain
- Handles `run_flow` actions: resolves flow path, parses sub-flow, executes recursively on the same page
- Circular dependency detection (`_seen_flows` set)
- Max nesting depth: 10 levels (`_MAX_NESTING_DEPTH`)
- Sub-flow `StepResult` objects are tagged with `sub_flow` name for report grouping

## conftest.py — pytest plugin

- `pytest_collect_file`: hooks into pytest collection, returns `FlowFile` for `.md` files in `flows/` directories (`tests/<app>/flows/`)
- `FlowFile`: collection node, parses Markdown into `FlowDefinition`
- `FlowItem`: individual test item, calls `FlowRunner.run()` in `runtest()`
- `ProfessionalReportPlugin`: collects results, generates HTML report at session end
- `pytest_collection` (tryfirst): adopts `WebAgentTerminalReporter` from `app/observability/console.py` — per-file headers, one `✓/✗ file » flow` line per test with duration; only when verbosity is 0 (`-v`/`-q` keep stock output)
- `pytest_terminal_summary`: prints the *Execution summary* section (build name, counts, healed L2/L3 steps, duration, slowest tests) and the report paths
- `FlowItem.runtest` stamps `webagent_flow_file` / `webagent_flow_name` / `webagent_healings` on `user_properties` for the console reporter
- `--flow`: inline flow string mode
- `--flow_file`: explicit path mode

Do not add business logic to conftest.py — it's a thin integration layer only.

## Reporting

Reports written to `reports/<ENVIRONMENT>/`:
- `report.html` — self-contained HTML shell with inline data
- `report_<build>.json` — machine-readable data; `<build>` is the BUILD_NAME slug, stale ones removed on regeneration
- `assets/report.css` — all CSS
- `assets/report.js` — all JavaScript
- `images/` — captured page screenshots

Report sections: Result Distribution, Code Coverage, Pass Rate Trend, Test Results table.
Sub-flow steps appear grouped with collapsible accordion UI and accent-colored left border.

`ENVIRONMENT` defaults to `staging` if not set.
Never write reports outside this directory structure.
