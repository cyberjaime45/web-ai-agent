# Project

Markdown-driven web automation agent with a 3-layer deterministic + AI runtime.
Flows are Markdown files under `tests/<app>/flows/`, discovered by pytest, and
executed through L1 (DeterministicRunner) → L2 (FallbackLocator) → L3 (AIResolver, optional).

Python 3.13 · Playwright · pytest 8 (custom plugin in `conftest.py`) · pluggable LLM
provider (OpenAI / Gemini / Anthropic) · HTML + JSON report under `reports/<ENVIRONMENT>/`.

## Commands

```bash
uv sync && uv run playwright install chromium   # setup (or: pip install -r requirements.txt)
pytest                                           # every flow under tests/ + framework tests
pytest tests/fms/flows/production_smoke.md       # one flow
pytest --flow_file=path/to/any.md                # any .md, anywhere
pytest --flow=$'# Quick\n## Steps\n- goto: "https://example.com"\n- assert_text: "Example Domain"'
pytest tests/framework                           # runtime self-tests only (no browser, ~1 s)
ruff check app conftest.py main.py tests         # lint (ruff lives in the venv, not requirements)
python main.py run tests/fms/flows/production_smoke.md --json   # CLI, machine-readable result
HEADLESS=false pytest …                          # watch the browser (maximized)
LLM_KEY= LLM_MODEL= pytest …                     # force L3 off for a run regardless of .env
open reports/<env>/report.html                   # last report
```

Plain `pytest` prints one named line per test plus an execution summary; `-v`/`-q`
restore stock pytest output.

## Architecture — read before touching core files

| File | Role |
|------|------|
| `conftest.py` | pytest plugin: flow discovery (`FlowFile`/`FlowItem`), `_SessionBrowser` (one browser per session, one context per flow), provider built once at session start, report plugin, terminal summary |
| `app/config/settings.py` | The only env reader. Loads `.env`, frozen `settings` singleton, `report_dir`/`images_dir`, `run_label()` |
| `app/execution/engine.py` | `FlowRunner` — `_execute_one` runs every step (placeholders, timing, history), L1→L2→L3, `run_flow` sub-flows, section semantics |
| `app/layers/deterministic.py` | L1 + L2 handlers keyed by `ActionType`; `_L1_TIMEOUT = 5000`, `_MAX_L1_RETRIES = 1` |
| `app/layers/locator.py` | L2 `FallbackLocator`: 4 Playwright strategies polled for 5 s, then one selectolax similarity pass (≥ 0.6); `_is_selector()` |
| `app/layers/ai_resolver.py` | L3. `supports(action_type)` gates which actions reach it (`_LOCATOR_ACTIONS`); AI-native actions |
| `app/layers/providers/` | `LLMProvider` ABC, `get_provider()` factory (fail-fast on partial config), OpenAI / Gemini / Claude adapters |
| `app/flow/parser.py` | Markdown → `FlowDefinition(name, timeout, actions)`; 4-stage step pipeline; `resolve_flow_path` |
| `app/schemas/actions.py` | `ActionType` (44), `ACTION_ARG_SPEC`, `FlowAction`, `StepResult`, `FlowResult`, `RunContext` |
| `app/browser/session.py` | `create_browser()` — local launch or LambdaTest CDP connect |
| `app/observability/recorder.py` | Per-page console + network capture with caps and redaction (runs on every event — keep it cheap) |
| `app/observability/reporter.py` | `generate_report()` → `report.html`, slim `assets/data.js`, per-test shards `assets/data/t-<i>.js`, `report_<build>.json` |
| `app/observability/console.py` | Terminal reporter takeover + `execution_summary` |
| `app/observability/assets/` | Report shell, CSS, JS (one `consoleView`/`networkView` shared by drawer and execution tabs) |
| `app/utils/build.py` | `BUILD_NAME` → `get_build_name()` / `build_slug()` |
| `tests/framework/` | Runtime self-tests. `tests/<app>/flows/` — flows per application (`wheelsup_site`, `members_site`, `fms`), shared sub-flows in `components/` |

## Environment variables

`ENVIRONMENT` (staging) · `BUILD_NAME` (Web Test Report) · `RUNNING_MODE` (local | lambda, needs
`LT_USERNAME`/`LT_ACCESS_KEY`) · `BROWSER` (chromium) · `HEADLESS` (true) · `VIEWPORT` (1920x1080) ·
`SLOW_MO` (0) · `AI_PROVIDER` + `LLM_KEY` + `LLM_MODEL` (all three or none) · `REPORT_REDACT`.
Full table with descriptions: `README.md` → Configuration. Add a new one to `Settings` and `.env.example`,
comment on its own line (an inline comment after an empty value becomes the value).

## Rules

- Never break the L1 → L2 → L3 chain: L1 signals failure by raising, L2 by `RuntimeError`, L3 by returning `None`. A failure stops the current `## section`; the next section still runs.
- L1 caps action calls at `_L1_TIMEOUT` (5 s) so failover is fast; explicit waits/assertions use their own timeouts. Never `time.sleep()` — Playwright `wait_for*`.
- L3 is optional. Every flow must pass with no provider; partial AI config is a startup `UsageError`. Only actions in `_LOCATOR_ACTIONS` are sent to L3 (`AIResolver.supports`) — never let an assertion be "resolved" by the LLM.
- New action = enum value + `ACTION_ARG_SPEC` + L1 handler in `_l1_handlers` (+ L2 handler if fuzzy makes sense, + `_LOCATOR_ACTIONS` if L3 can perform it) + `docs/ACTIONS.md`.
- New LLM provider = one adapter file + one factory entry; `AIResolver` and the engine don't change.
- Configuration is read through `settings` only — no `os.getenv` in app code. `.env` loads there, for pytest and the CLI alike; `main.py` applies `--env` before importing `app`.
- One browser per session locally; flows get a fresh `BrowserContext`. Under `lambda`, one grid session per flow (dashboard grades per session). Teardown/reporting live in `finally`.
- Hot paths are the per-step loop and the recorder's event handlers: no `page.content()`/`page.title()` per step, no per-event regex compiles, `%`-style logging for Playwright exceptions (they carry multi-KB call logs).
- `run_flow` is handled in `engine.py`, not the action dispatch; references resolve relative to the calling flow's directory.
- Framework tests never depend on the developer's `.env`: pass `provider=None` to `FlowRunner`, `monkeypatch.delenv`, fake pages. Keep `tests/framework` under a few seconds.
- Minimal impact, root causes, no temporary fixes. Verify before marking done: `pytest tests/framework`, a real flow run when the runtime changed, report opens with no console errors (Playwright headless check), `ruff` clean.
- User-facing behaviour changes go to `docs/` (ACTIONS, FLOWS, REPORTS, CLI, ARCHITECTURE) in the same commit.
- On corrections from the user: record the lesson in `tasks/lessons.md` (gitignored; create if missing).

## Reference docs — open only when relevant

| File | When |
|------|------|
| `.claude/docs/architecture.md` | Touching FlowRunner, layers, conftest, or the report writer |
| `.claude/docs/playwright.md` | Writing or debugging Playwright / locator code |
| `.claude/docs/flows.md` | Parsing rules and runtime facts about flow files |
| `.claude/docs/bugs.md` | Given a bug report or a failing flow |
| `docs/ACTIONS.md`, `docs/FLOWS.md`, `docs/REPORTS.md`, `docs/CLI.md`, `docs/ARCHITECTURE.md` | User-facing guides — keep in sync with behaviour changes |
| `README.md` | Front page: quick start, configuration table, documentation index |
