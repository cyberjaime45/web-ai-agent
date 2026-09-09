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

```bash
uv sync                                   # dependencies (or: pip install -r requirements.txt)
uv run playwright install chromium        # browser
cp .env.example .env                      # configuration (see below)

uv run pytest                             # run every flow under tests/
uv run pytest tests/fms/flows/production_smoke.md   # one flow
open reports/staging/report.html          # the report
```

Flows live beside the suite for the application they exercise —
`tests/<app>/flows/*.md`, shared sub-flows in `components/` — and pytest picks
them up without any `test_*.py`. Run one inline with `--flow "<markdown>"`, or
any file anywhere with `--flow_file=path.md`.

## Documentation

| Guide | What it covers |
|-------|----------------|
| [docs/FLOWS.md](docs/FLOWS.md) | Flow file format, sections, sub-flows, complete examples |
| [docs/ACTIONS.md](docs/ACTIONS.md) | Every action keyword (44) with examples, selectors and XPath, placeholders |
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
| `VIEWPORT` | `1920x1080` | Viewport size (`WIDTHxHEIGHT`) |
| `SLOW_MO` | `0` | Milliseconds between actions, for debugging |
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
| **L2 — Fallback** | L1 fails | Looser Playwright strategies polled for 5 s, then a selectolax similarity match |
| **L3 — AI** | L1 + L2 fail on an element interaction | LLM suggests a locator; also runs `ai_*` actions |

Most flows finish on L1 with zero API calls. Steps that needed L2 or L3 are
counted as *healed* in the console summary and listed in the report so the
flow can be tightened up.

## Development

```bash
uv run pytest tests/_framework        # the runtime's own tests (no browser)
uv run ruff check app conftest.py main.py tests
```

See [.claude/CLAUDE.md](.claude/CLAUDE.md) for the rules that keep the
L1 → L2 → L3 chain intact when touching the core.
