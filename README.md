# Web Agent

A Markdown-driven web automation framework that executes test flows through a 3-layer deterministic + AI runner, with automatic pytest discovery, environment-based reporting, and a polished terminal UI.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     conftest.py                          │
│   pytest_collect_file → FlowFile → FlowItem.runtest()    │
│   --flow / --flow_file  (inline & explicit path modes)   │
└─────────────────────────┬────────────────────────────────┘
                          │ FlowDefinition
                          ▼
┌──────────────────────────────────────────────────────────┐
│                  FlowRunner  (runner/)                   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Layer 1 — DeterministicRunner                   │   │
│  │  Exact Playwright role / label / placeholder     │   │
│  │  locators.  Handles all 17 action types.         │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 2 — FallbackLocator                       │   │
│  │  7 fuzzy strategies + selectolax similarity      │   │
│  │  matching (threshold ≥ 0.6).                     │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 3 — AIResolver  (OpenAI, optional)        │   │
│  │  Invoked only when L1 + L2 both fail.            │   │
│  │  Skipped automatically if no OPENAI_API_KEY.     │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
             reports/<ENVIRONMENT>/
               report.html  report.json
               assets/      images/
```

---

## Quick Start

```bash
# 1. Install dependencies (uv recommended)
uv sync

# 2. Install Playwright browser
uv run playwright install chromium

# 3. Copy and configure environment
cp .env.example .env

# 4. Run all flows
uv run pytest

# 5. Run a specific flow file
uv run pytest tests/flows/wheelsup_explore.md -v
```

---

## Running Flows

### Auto-discovery (default)
Drop a `.md` file inside any `tests/flows/` directory — pytest picks it up automatically, no `test_*.py` needed.

```bash
uv run pytest tests/flows/wheelsup_explore.md -v
```

### Inline Markdown via `--flow`
Pass a complete flow as a raw Markdown string directly on the command line:

```bash
uv run pytest --flow "# My Flow
## Config
- url: https://example.com
- timeout: 10000
## Steps
1. open \"https://example.com\"
2. assert_text \"Example Domain\"
" -v
```

### Explicit file path via `--flow_file`
Point to any `.md` file regardless of its location:

```bash
uv run pytest --flow_file path/to/any_flow.md -v
```

> `--flow` and `--flow_file` are mutually exclusive.

---

## Flow File Format

Flow files are plain Markdown. Place them in `tests/flows/`.

```markdown
# Flow Name

## Config
- url: https://example.com
- timeout: 30000

## Steps
1. open "https://example.com"
2. wait_for_load
3. assert_text "Expected text"
4. click "Button label"
5. fill "Field label" with "value"
6. assert_url "expected-path"
7. screenshot "step_name"

## Expected Outcome
- Page loads successfully
- Action completes as expected
```

### Supported Step Actions

| Action | Example |
|--------|---------|
| `open` | `open "https://example.com"` |
| `click` | `click "Submit"` |
| `click_link` | `click_link "Learn More"` |
| `click_button` | `click_button "Sign In"` |
| `fill` | `fill "Email" with "user@example.com"` |
| `select` | `select "Country" "United States"` |
| `check` / `uncheck` | `check "Remember me"` |
| `assert_text` | `assert_text "Welcome back"` |
| `assert_title` | `assert_title "Dashboard"` |
| `assert_url` | `assert_url "dashboard"` |
| `wait` | `wait 2000` |
| `wait_for_load` | `wait_for_load` |
| `wait_for_element` | `wait_for_element ".modal"` |
| `screenshot` | `screenshot "after_login"` |
| `scroll` | `scroll down` |
| `hover` | `hover "Membership"` |

**Aliases:** `go_to` / `navigate` / `goto` → `open` · `type` / `enter` → `fill` · `verify_text` / `assert` → `assert_text` · `verify_url` → `assert_url`

---

## Project Structure

```
web-agent/
├── conftest.py                  # Pytest hooks, fixtures, flow auto-discovery
├── report_generator.py          # HTML + JSON report builder
├── pytest.ini                   # testpaths=tests, pythonpath=src
├── pyproject.toml
│
├── src/
│   ├── agent/
│   │   ├── flow_parser.py       # Parses .md → FlowDefinition (markdown-it-py)
│   │   ├── brain.py             # OpenAI-backed AI planner
│   │   ├── executor.py          # Action executor for AI planner
│   │   ├── guardrails.py        # Action validation
│   │   ├── memory.py            # Agent memory
│   │   └── prompts.py           # LLM prompt templates
│   │
│   ├── runner/
│   │   ├── actions.py           # ActionType enum, FlowAction, StepResult, FlowResult
│   │   ├── deterministic.py     # Layer 1 + Layer 2 runner
│   │   ├── locator.py           # FallbackLocator (7 strategies + selectolax)
│   │   ├── flow_runner.py       # Orchestrates L1 → L2 → L3
│   │   └── ai_resolver.py       # Layer 3 OpenAI resolver
│   │
│   ├── tools/
│   │   ├── browser/
│   │   │   ├── driver.py        # BrowserDriver (NavigationMixin + ElementMixin + WebUtilsMixin)
│   │   │   ├── navigation.py    # URL navigation, history, wait helpers
│   │   │   ├── element.py       # Element extraction and interaction
│   │   │   └── web_utils.py     # Screenshot and artifact capture
│   │   └── database/            # Database client and queries
│   │
│   ├── schemas/
│   │   └── models.py            # Pydantic models (PageState, InputField, etc.)
│   │
│   └── utils/
│       └── banner.py            # Terminal startup banner (Rich)
│
├── tests/
│   └── flows/
│       └── wheelsup_explore.md  # WheelsUp smoke flow
│
└── reports/
    └── <ENVIRONMENT>/           # e.g. staging/, qa1/, uat/
        ├── report.html
        ├── report.json
        ├── assets/              # CSS + JS for the report
        └── images/              # Screenshots from test runs
```

---

## Configuration

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `staging` | Report output directory (`reports/<ENVIRONMENT>/`) |
| `BASE_URL` | — | Optional base URL override |
| `OPENAI_API_KEY` | — | Enables Layer 3 AI resolver |
| `LOG_LEVEL` | `info` | Logging verbosity |
| `COVERAGE` | `0` | Enable coverage tracking in report |
| `COVERAGE_TARGET` | `80` | Coverage % target shown in report |
| `THEME_STYLE` | `system` | Report theme: `light`, `dark`, or `system` |

### Multi-environment reports

Set `ENVIRONMENT` before running to route all reports and screenshots to the correct folder:

```bash
ENVIRONMENT=qa1 uv run pytest tests/flows/wheelsup_explore.md
# → writes to reports/qa1/
```

Supported environments: `staging`, `qa1`, `qa2`, `qa5`, `qa10`, `uat` (any string value is accepted).

---

## Reports

After each run, a full HTML report is generated at `reports/<ENVIRONMENT>/report.html`.

```
reports/staging/
├── report.html     # Interactive UI (charts, table, failure details)
├── report.json     # Raw structured data
├── assets/
│   ├── report.css
│   └── report.js
└── images/
    └── *.png       # All screenshots from the run
```

Open the report:
```bash
open reports/staging/report.html
# or serve it:
python -m http.server 8080 --directory reports/staging
```

---

## Terminal Banner

A startup banner is displayed at the beginning of every pytest session. To customise it, edit `BANNER_CONFIG` in `src/utils/banner.py`:

```python
BANNER_CONFIG = {
    "agent_name": "Web Agent",
    "version":    "1.0",
    "author":     "Cyberjaime45",
    "ascii_title": "...",      # any multi-line ASCII art string
    "title_color": "dark_cyan",
    "meta_color":  "dark_cyan",
}
```

---

## Layer Behaviour

| Layer | Trigger | Strategy |
|-------|---------|----------|
| **L1 — Deterministic** | Always tried first | Exact Playwright `get_by_role`, `get_by_label`, `get_by_placeholder` |
| **L2 — Fallback** | L1 fails | 7 fuzzy strategies + selectolax HTML similarity (≥ 0.6) |
| **L3 — AI** | L1 + L2 fail | OpenAI call with page context; skipped if no `OPENAI_API_KEY` |

Most flows run entirely on L1 with zero API calls. L2 handles case variations, extra whitespace, and partial text matches. L3 is the last resort for complex or dynamic pages.
