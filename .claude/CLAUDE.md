# Project

Markdown-driven web automation agent with a 3-layer deterministic + AI runtime.
Flows are written in Markdown, discovered by pytest, and executed through:
L1 (DeterministicRunner) → L2 (FallbackLocator) → L3 (AIResolver, optional).

See @README.md for project overview.

## Stack

- Language: Python
- Browser automation: Playwright (Python)
- Test runner: pytest + custom conftest.py
- AI layer: pluggable LLM provider (OpenAI, Gemini, or Anthropic — Layer 3, optional)
- Reporting: HTML + JSON under `reports/<ENVIRONMENT>/`

## Commands

```bash
# Run all flows (auto-discovered .md files in flows/)
pytest

# Run a specific flow file
pytest --flow_file=flows/login/sso_login.md

# Run an inline flow
pytest --flow='click: "Login"'

# Run against a specific environment
ENVIRONMENT=staging pytest

# Run with visible browser (full screen)
HEADLESS=false pytest

# Custom viewport
VIEWPORT=1440x900 pytest

# Slow motion for debugging
SLOW_MO=500 pytest

# Show last HTML report
open reports/<env>/report.html

# Install Playwright browsers
playwright install

# Install dependencies
pip install -r requirements.txt
```

## Architecture — read before touching core files

| File | Role |
|------|------|
| `conftest.py` | pytest plugin — flow discovery, FlowFile, FlowItem, report plugin |
| `app/execution/engine.py` | FlowRunner — orchestrates L1 → L2 → L3 + `run_flow` sub-flows |
| `app/layers/deterministic.py` | L1 + L2 — dispatch-table, exact Playwright locators, fallback dispatch |
| `app/layers/locator.py` | L2 — 5 fuzzy strategies per resolve method, selectolax similarity ≥ 0.6 |
| `app/layers/ai_resolver.py` | L3 — consumes `LLMProvider`, only when L1+L2 fail, skipped if no provider configured |
| `app/layers/providers/` | Provider abstraction — base ABC, factory, and adapters for OpenAI / Gemini / Claude |
| `app/flow/parser.py` | Markdown parser — 4-stage pipeline, flow path resolution for `run_flow` |
| `app/schemas/actions.py` | ActionType enum (42 types), FlowAction, StepResult, FlowResult |
| `app/browser/session.py` | Browser factory — local (Playwright) or LambdaTest |
| `app/observability/reporter.py` | HTML/JSON report generation |
| `reports/` | Output per environment: report.html, report.json, assets/, images/ |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `staging` | Report output directory, environment badge |
| `HEADLESS` | `true` | Set `false` for visible browser |
| `BROWSER` | `chromium` | Browser engine: chromium, firefox, webkit |
| `VIEWPORT` | `1920x1080` | Viewport size (WIDTHxHEIGHT) |
| `SLOW_MO` | `0` | Delay between actions (ms) |
| `AI_PROVIDER` | — | LLM provider for L3: `openai` \| `gemini` \| `anthropic` (required when L3 is enabled) |
| `LLM_KEY` | — | API key for the selected provider (required when L3 is enabled) |
| `LLM_MODEL` | — | Model id for the selected provider (required when L3 is enabled, no default) |
| `RUNNING_MODE` | `local` | `local` or `lambda` (LambdaTest cloud) |

## Rules

- Never break the L1 → L2 → L3 fallback chain — each layer must signal failure cleanly for the next to activate
- L1 uses `_L1_TIMEOUT = 5000ms` for action calls — keeps fast failover to L2 while preserving Playwright's auto-wait
- L3 is optional by design — all flows must be runnable without `AI_PROVIDER`/`LLM_KEY`/`LLM_MODEL`. Partial config raises `ConfigError` at startup (fail fast)
- Adding a new LLM provider means one new file under `app/layers/providers/` plus one mapping entry in the factory — no changes to `AIResolver` or the engine
- Never use `time.sleep()` — use Playwright `wait_for*` methods
- L1 supports CSS selectors and XPath directly via `_is_selector()` — no need to fall to L2 for selector-based targeting
- `run_flow` is intercepted at the execution layer (engine.py), not the action dispatch — it's a flow-level directive
- Minimal impact: only touch code relevant to the task
- Find root causes — no temporary fixes
- Verify before marking done: `pytest` passes, report generates, no console errors
- On corrections: update `tasks/lessons.md`

## Reference Docs

Read only when relevant — do not load all upfront.

| File | When to read |
|------|-------------|
| @~/.claude/docs/planning.md | Starting any non-trivial task (3+ steps) |
| @~/.claude/docs/git.md | Before any git operations |
| @.claude/docs/architecture.md | Touching FlowRunner, layers, or conftest |
| @.claude/docs/playwright.md | Writing or debugging Playwright/locator code |
| @.claude/docs/flows.md | Writing or parsing Markdown flow files |
| @.claude/docs/bugs.md | Given a bug report or failing flow |
| @tasks/lessons.md | Session start, and after any correction |
