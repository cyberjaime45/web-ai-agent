# Web Agent

A Markdown-driven web automation agent. Flows are written in Markdown,
discovered by pytest, and executed through a 3-layer runtime — exact
Playwright locators first, fuzzy fallback second, and an optional LLM as the
last resort — with a live console and a portable HTML report per environment.

```markdown
# Login

## Steps
- goto: "https://example.com/login"
- fill: "Email" | "<APP_EMAIL>"
- fill: "Password" | "<APP_PASSWORD>"
- click: "Sign in"
- assert_text: "Welcome back"
```

## Quick start

**Requirements:** [uv](https://docs.astral.sh/uv/) (it downloads Python 3.14 from
`.python-version` by itself), `curl`, and on Linux the Chromium system libraries
(installing them needs root, once per machine). No LLM key is needed: Layer 3 stays
off unless `AI_PROVIDER` is set.

```bash
# 1. Install (once per machine / agent)
curl -LsSf https://astral.sh/uv/install.sh | sh       # skip if uv is already installed
uv sync --locked                                       # Python 3.14 + dependencies
uv run playwright install --with-deps chromium         # browser + OS libs (drop --with-deps without root)

# 2. Configure
cp .env.example .env                                   # defaults work for the sample below; in CI export variables instead

# 3. Run a sample test (public site, no credentials)
uv run pytest tests/marketing_site/sample_run.md

# 4. Results
open reports/staging/report.html                       # HTML report under reports/<ENVIRONMENT>/
```

pytest exits `0` when every flow passes and non-zero otherwise, so the same
command is the CI gate. Add `--junitxml=reports/junit.xml` to publish results,
and pass `ENVIRONMENT`, `BUILD_NAME` and flow secrets (for example `FMS_EMAIL`
and `FMS_PASSWORD` for `tests/fms/production_smoke.md`) as pipeline variables.
`azure_pipelines.yml` is a working reference.

Flows live beside the suite for the application they exercise —
`tests/<app>/*.md`, shared sub-flows in `components/` — and pytest picks them
up without any `test_*.py`. Run one inline with `--flow "<markdown>"`, or any
file anywhere with `--flow_file=path.md`. The same flow runs on a phone with
`--profile mobile` (or `--profile desktop,mobile` for both).

When a step fails, the report gets the evidence without any `screenshot` step
in the flow: viewport, full-page and failed-element screenshots, the page URL
and title, what each layer (L1 / L2 / L3) did, the console errors and failed
requests of that step, and a Playwright trace of the flow.

Thirteen QA skills replace pages of hand-written assertions — `inspect_page`,
`check_console_network`, `check_links`, `check_accessibility`,
`check_performance`, `snapshot_page` (structural baselines), `test_responsive`,
`test_form`, `test_table`, `test_search`, `test_widgets`, `explore_page`
(bounded, safe exploration that maps a page's controls and pages) and
`test_page` (classify the page, run what fits, write the result as a plain
flow with the assertions it observed) — and every navigation step gets automatic checks (page rendered, no
page errors, no failed requests, no stuck spinner…). None of it needs an LLM;
with one configured, the planner only adds validated steps on controls the
observer already found, behind a deterministic safety policy. See
[docs/ACTIONS.md](docs/ACTIONS.md#qa-skills-13).

```bash
uv run pytest --agent-test https://example.com/members     # one page, no flow file, full report
```

## Documentation

| Guide | What it covers |
|-------|----------------|
| [docs/FLOWS.md](docs/FLOWS.md) | Flow file format, sections, sub-flows, complete examples |
| [docs/ACTIONS.md](docs/ACTIONS.md) | Every action keyword (45) and QA skill (13) with examples, selectors and XPath, placeholders |
| [docs/REPORTS.md](docs/REPORTS.md) | Console output, the HTML/JSON report, multi-environment and LambdaTest runs |
| [docs/CLI.md](docs/CLI.md) | `main.py run`, exit codes, the `--json` contract for other agents |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The three layers, parser pipeline, browser lifecycle, project structure |

## Configuration

Copy `.env.example` to `.env`. Every variable is read once by
`app/config/settings.py`, for pytest and the CLI alike.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `staging` | Report output directory (`reports/<ENVIRONMENT>/`) and environment badge |
| `BUILD_NAME` | `Web Test Report` | Run label: report title, banner, console summary, `report_<slug>.json`, LambdaTest build |
| `RUNNING_MODE` | `local` | `local` or `lambda` (LambdaTest cloud; needs `LT_USERNAME`, `LT_ACCESS_KEY`) |
| `BROWSER` | `chromium` | `chromium`, `firefox`, or `webkit` |
| `HEADLESS` | `true` | `false` shows the browser, maximized |
| `VIEWPORT` | `1920x1080` | Viewport size (`WIDTHxHEIGHT`) of the `desktop` profile |
| `SLOW_MO` | `0` | Milliseconds between actions, for debugging |
| `PROFILE` | `desktop` | Device profile(s) flows run under by default: `desktop`, `mobile`, or both (comma-separated). `pytest --profile …` and a flow's `## Config` `profiles:` line override it |
| `MOBILE_DEVICE` | `iPhone 13` | Playwright device descriptor behind the `mobile` profile |
| `TRACE` | `on-failure` | Keep a Playwright trace under `reports/<ENVIRONMENT>/traces/` for every failed flow; `off` disables recording |
| `ORACLE` | `warn` | Automatic checks after navigation steps: `warn` records them, `strict` fails the step on an error-severity check, `off` disables them |
| `ALLOW_DESTRUCTIVE` | `false` | `true` lets `explore_page` and the planner press controls that look destructive (delete, pay, send…) — disposable environments only |
| `DISMISS_BLOCKERS` | `false` | Dismiss cookie banners and modals before each step (a failed click or fill is always retried once after a dismissal) |
| `RERUN_FAILED` | `false` | Run a flow with a failed section once more (pytest); sections that pass then are reported as *passed on retry* |
| `AI_PROVIDER` | — | Layer 3 provider: `openai`, `gemini`, or `anthropic`; empty disables L3 |
| `LLM_KEY` | — | API key for the selected provider |
| `LLM_MODEL` | — | Model id for the selected provider |
| `REPORT_REDACT` | — | Extra sensitive key substrings (comma-separated) masked in report network data |

Layer 3 is optional: it is enabled only when `AI_PROVIDER` is set, and then `LLM_KEY` and `LLM_MODEL` are required. An empty or missing `AI_PROVIDER` disables it.
Setting only some is a startup error. Flow secrets never go in the flow file —
reference environment variables as `<NAME>` in any step argument.

## How a step runs

| Layer | When | How |
|-------|------|-----|
| **L1 — Deterministic** | Always first | Exact Playwright role / label / placeholder locators, 5 s cap |
| **L2 — Fallback** | L1 fails | Looser Playwright strategies polled for 5 s, then a similarity match; text checks read the page's visible text |
| **L3 — AI** | L1 + L2 fail on an element interaction | LLM suggests a locator; also runs `ai_*` actions |

Most flows finish on L1 with zero API calls. Steps that needed L2 or L3 are
counted as *healed* in the console summary and listed in the report so the
flow can be tightened up.

## Development

```bash
uv run pytest tests/_framework        # the runtime's own tests (no browser)
uv run ruff check app conftest.py main.py tests
```
