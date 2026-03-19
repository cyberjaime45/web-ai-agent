# Web Agent

A Markdown-driven web automation agent that executes flows through a 3-layer deterministic + AI runtime, with automatic pytest discovery, environment-based reporting, and a polished terminal UI.

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
│                  FlowRunner  (engine)                    │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Layer 1 — DeterministicRunner                   │   │
│  │  Dispatch-table driven. Exact Playwright         │   │
│  │  role / label / placeholder locators.            │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 2 — FallbackLocator                       │   │
│  │  7+ fuzzy strategies + selectolax similarity     │   │
│  │  matching (threshold ≥ 0.6).                     │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 3 — AIResolver  (OpenAI, optional)        │   │
│  │  Invoked only when L1 + L2 both fail.            │   │
│  │  Also handles AI-native actions directly.        │   │
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
uv run pytest flows/wheelsup_explore.md -v
```

---

## Running Flows

### Auto-discovery (default)
Drop a `.md` file inside the `flows/` directory — pytest picks it up automatically, no `test_*.py` needed.

```bash
uv run pytest flows/login.md -v
```

### Inline Markdown via `--flow`
Pass a complete flow as a raw Markdown string directly on the command line:

```bash
uv run pytest --flow "# My Flow
## Config
- url: https://example.com
- timeout: 10000
## Steps
1. goto: \"https://example.com\"
2. assert_text: \"Example Domain\"
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

Flow files are plain Markdown. Place them in `flows/`.

```markdown
# Login Flow

## Config
- url: https://example.com/login
- timeout: 30000

## Credentials
- username: admin
- password: secret123

## Steps
1. goto: "https://example.com/login"
2. wait_for_load
3. fill: "Username" | "admin"
4. fill: "Password" | "secret123"
5. click: "Sign In"
6. assert_url: "dashboard"
7. assert_text: "Welcome back"
8. screenshot: "dashboard_loaded"

## Expected Outcome
- User is redirected to the dashboard
- Page displays "Welcome back"
```

### Step syntax

```
keyword: "arg1" | "arg2"
```

- The keyword is followed by `:` and one or more quoted arguments separated by `|`.
- Actions with no arguments omit the colon: `wait_for_load`, `reload`, `back`.
- Arguments that are bare values (e.g. milliseconds for `wait`) can omit quotes: `wait: 2000`.

---

## Supported Actions

### Navigation (6)

| Action | Syntax |
|--------|--------|
| `goto` | `goto: "https://url"` |
| `reload` | `reload` |
| `back` | `back` |
| `wait_load` | `wait_load` or `wait_load: "networkidle"` |
| `switch_tab` | `switch_tab: "1"` |
| `scroll` | `scroll: "down"` / `scroll: "up"` / `scroll: "500"` / `scroll: "Footer Text"` |

### Click (7)

| Action | Syntax |
|--------|--------|
| `click` | `click: "Button Text"` |
| `click_link_text` | `click_link_text: "Link Text"` |
| `click_id` | `click_id: "#submit-btn"` |
| `click_button` | `click_button: "Submit"` |
| `double_click` | `double_click: "Element"` |
| `right_click` | `right_click: "Menu Item"` |
| `hover` | `hover: "User Profile"` |

### Input (7)

| Action | Syntax | Notes |
|--------|--------|-------|
| `fill` | `fill: "Label" \| "value"` | Atomic set via `.fill()` |
| `type` | `type: "Label" \| "value"` | Character-by-character via `.press_sequentially()` — use for autocomplete/masked fields |
| `clear` | `clear: "Field Label"` | |
| `focus` | `focus: "Field Label"` | |
| `select` | `select: "Dropdown" \| "Option"` | |
| `check` | `check: "Checkbox Label"` | |
| `uncheck` | `uncheck: "Checkbox Label"` | |

### Advanced Interaction (2)

| Action | Syntax |
|--------|--------|
| `drag_to` | `drag_to: "Source Element" \| "Target Element"` |
| `upload` | `upload: "input[type=file]" \| "/path/to/file.pdf"` |

### Table & Row Logic (5)

| Action | Syntax | Description |
|--------|--------|-------------|
| `read_row` | `read_row: "Row Text"` | Reads all cell contents from the matching row |
| `table_click` | `table_click: "Row Text" \| "Cell Text"` | Clicks within a matching table row |
| `find_row` | `find_row: "Row Text"` | Asserts a row with that text exists |
| `count_elements` | `count_elements: ".css-selector"` | Returns and logs the element count |
| `get_attribute` | `get_attribute: ".selector" \| "attr-name"` | Returns an element attribute value |

### Assertions (8)

| Action | Syntax |
|--------|--------|
| `assert_text` | `assert_text: "expected text"` |
| `assert_not_text` | `assert_not_text: "text that must be absent"` |
| `assert_visible` | `assert_visible: "Element Text or .selector"` |
| `assert_hidden` | `assert_hidden: "Element Text or .selector"` |
| `assert_url` | `assert_url: "url-fragment"` |
| `assert_enabled` | `assert_enabled: "Button or Input Label"` |
| `assert_disabled` | `assert_disabled: "Button or Input Label"` |
| `assert_checked` | `assert_checked: "Checkbox Label"` |

### Waits (5)

| Action | Syntax |
|--------|--------|
| `wait` | `wait: 2000` |
| `wait_for_load` | `wait_for_load` |
| `wait_for_element` | `wait_for_element: ".css-selector"` |
| `wait_for_text` | `wait_for_text: "expected text"` |
| `wait_for_url` | `wait_for_url: "url-fragment"` |

### AI-Native Actions (4) — requires `OPENAI_API_KEY`, runs on L3 only

| Action | Syntax | Description |
|--------|--------|-------------|
| `ai_click` | `ai_click: "the small red X in the corner"` | LLM resolves the element from natural language and clicks it |
| `ai_extract` | `ai_extract: "What is the total balance shown?"` | LLM extracts data from page content; result in step message |
| `ai_assert` | `ai_assert: "the user is currently logged in"` | LLM evaluates a natural-language assertion; failure sets step failed |
| `ai_summarize` | `ai_summarize` | LLM generates a 2–4 sentence summary of the current page |

### Utilities (2)

| Action | Syntax |
|--------|--------|
| `screenshot` | `screenshot: "step_name"` |
| `press` | `press: "Enter"` / `press: "Tab"` / `press: "Escape"` |

---

## Project Structure

```
web-agent/
├── conftest.py                     # Pytest hooks, fixtures, flow auto-discovery
├── main.py                         # CLI entry point
├── pytest.ini                      # testpaths=flows, pythonpath=.
├── pyproject.toml
│
├── app/
│   ├── schemas/
│   │   └── actions.py              # ActionType enum, FlowAction, StepResult, FlowResult
│   ├── flow/
│   │   └── parser.py               # 4-stage pipeline: tokenize → normalize → validate → build
│   ├── layers/
│   │   ├── deterministic.py        # L1 + L2 dispatch-table runner
│   │   ├── locator.py              # FallbackLocator — fuzzy strategies + selectolax
│   │   └── ai_resolver.py          # L3 OpenAI resolver + AI-native actions
│   │
│   ├── execution/
│   │   └── engine.py               # FlowRunner: orchestrates L1 → L2 → L3
│   ├── agent/
│   │   ├── orchestrator.py         # High-level agent runtime
│   │   └── prompts/
│   │       └── resolver.py         # LLM prompt templates
│   │
│   ├── browser/
│   │   ├── session.py              # Browser/context creation (local + LambdaTest)
│   │   ├── driver.py               # BrowserDriver (navigation + element + utils)
│   │   ├── navigation.py           # URL navigation, history, wait helpers
│   │   ├── element.py              # Element extraction and interaction
│   │   └── screenshot.py           # Screenshot and artifact capture
│   │
│   ├── config/
│   │   └── settings.py             # Typed settings from environment variables
│   │
│   ├── integrations/
│   │   └── database/               # MySQL/MariaDB client, config, models, queries
│   │
│   ├── memory/
│   │   └── session.py              # Agent short-term session memory
│   │
│   ├── observability/
│   │   └── reporter.py             # HTML + JSON report generator
│   │
│   ├── skills/
│   │   └── base.py                 # Abstract Skill base class
│   │
│   └── utils/
│       └── banner.py               # Terminal startup banner (Rich)
│
├── flows/                          # Flow definition files (.md)
│   ├── login.md
│   ├── wheelsup_explore.md
│   ├── wheelsup_homepage.md
│   └── wheelsup_signin.md
│
└── reports/
    └── <ENVIRONMENT>/              # e.g. staging/, qa1/, uat/
        ├── report.html
        ├── report.json
        ├── assets/                 # CSS + JS for the HTML report
        └── images/                 # Screenshots from test runs
```

---

## Configuration

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `staging` | Report output directory (`reports/<ENVIRONMENT>/`) |
| `BASE_URL` | — | Optional base URL override |
| `RUNNING_MODE` | `local` | `local` or `lambda` (LambdaTest cloud) |
| `BROWSER` | `chromium` | `chromium`, `firefox`, or `webkit` |
| `HEADLESS` | `true` | `true` or `false` |
| `SLOW_MO` | `0` | Milliseconds between actions |
| `OPENAI_API_KEY` | — | Enables Layer 3 AI resolver and AI-native actions |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for L3 and AI-native actions |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, or `error` |
| `COVERAGE` | `0` | `1` to enable coverage tracking in report |
| `COVERAGE_TARGET` | `80` | Coverage % target shown in report |
| `THEME_STYLE` | `system` | Report theme: `light`, `dark`, or `system` |

### Multi-environment reports

```bash
ENVIRONMENT=qa1 uv run pytest flows/login.md
# → writes to reports/qa1/
```

### LambdaTest cloud execution

```bash
RUNNING_MODE=lambda LT_USERNAME=... LT_ACCESS_KEY=... uv run pytest
```

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
    └── *.png       # Screenshots from the run
```

```bash
open reports/staging/report.html
# or serve it:
python -m http.server 8080 --directory reports/staging
```

---

## Layer Behaviour

| Layer | Trigger | Strategy |
|-------|---------|----------|
| **L1 — Deterministic** | Always tried first | Dispatch-table driven. Exact Playwright `get_by_role`, `get_by_label`, `get_by_placeholder` locators. |
| **L2 — Fallback** | L1 fails | 7+ fuzzy strategies per element type (clickable, input, checkbox, ID, table row) + selectolax HTML similarity (≥ 0.6). |
| **L3 — AI** | L1 + L2 fail, or AI-native action | OpenAI call with page context. Handles both element fallback and AI-native actions (`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`). Skipped if no `OPENAI_API_KEY`. |

Most flows run entirely on L1 with zero API calls. L2 handles case variations, extra whitespace, and partial text matches. L3 is the last resort for complex or dynamic pages, and the exclusive runtime for AI-native actions.

---

## Parser Pipeline

Each flow step is processed through a 4-stage pipeline:

```
raw step text
    │
    ▼
tokenize   — extracts keyword and raw argument string
    │
    ▼
normalize  — resolves ActionType, splits pipe-separated args, strips quotes
    │
    ▼
validate   — checks argument count; raises FlowParseError with step number on failure
    │
    ▼
build      — constructs FlowAction dataclass
```

Unknown keywords produce a `FlowParseError` (strict mode) or a `WAIT(0)` placeholder (lenient mode, default) so the AI planner can still consume the raw step text.

---

## Terminal Banner

Displayed at the start of every pytest session. Customise in `app/utils/banner.py`:

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
