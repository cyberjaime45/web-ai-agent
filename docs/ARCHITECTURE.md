# Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     conftest.py                          │
│   pytest_collect_file → FlowFile → FlowItem.runtest()    │
│   --flow / --flow_file  (inline & explicit path modes)   │
│   one browser per session, one context per flow          │
└─────────────────────────┬────────────────────────────────┘
                          │ FlowDefinition
                          ▼
┌──────────────────────────────────────────────────────────┐
│                  FlowRunner  (engine)                    │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Layer 1 — DeterministicRunner                   │   │
│  │  Dispatch-table driven. Exact Playwright         │   │
│  │  role / label / placeholder locators, 5 s cap.   │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 2 — FallbackLocator                       │   │
│  │  Fuzzy Playwright strategies polled for 5 s,     │   │
│  │  then one selectolax similarity pass (≥ 0.6).    │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 3 — AIResolver  (LLM, optional)           │   │
│  │  Invoked only when L1 + L2 both fail on an       │   │
│  │  element interaction; runs AI-native actions.    │   │
│  │  Pluggable provider: OpenAI / Gemini / Claude.   │   │
│  │  Skipped automatically if no provider set.       │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
             reports/<ENVIRONMENT>/
               report.html  report_<build>.json
               assets/      images/
```

## Layer behaviour

| Layer | Trigger | Strategy |
|-------|---------|----------|
| **L1 — Deterministic** | Always tried first | Dispatch-table driven. Exact Playwright `get_by_role`, `get_by_label`, `get_by_placeholder` locators, capped at 5 s per action so failover stays fast. |
| **L2 — Fallback** | L1 fails | Four looser Playwright strategies per element type (clickable, input, checkbox) polled for up to 5 s, then a single selectolax pass over the page HTML picking the most similar text (≥ 0.6). |
| **L3 — AI** | L1 + L2 fail on an element interaction, or an AI-native action | LLM call with page context via a pluggable provider (OpenAI, Gemini, or Claude). Only actions L3 can execute with a locator (click, fill, select, check…) are sent; assertions and waits never reach it. Skipped if `AI_PROVIDER`/`LLM_KEY`/`LLM_MODEL` are not set. |

Most flows run entirely on L1 with zero API calls. L2 handles case variations,
extra whitespace, and partial text matches. L3 is the last resort for complex
or dynamic pages, and the exclusive runtime for AI-native actions
(`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`).

## Configuration and browser lifecycle

`app/config/settings.py` loads `.env` and is the only place environment
variables are read; pytest and the CLI therefore see identical configuration.
Partial L3 configuration (one or two of the three AI variables) is a startup
error, not a per-test one.

Under pytest, one Playwright driver and browser serve the whole session and
each flow gets a fresh `BrowserContext` — that is where cookie and storage
isolation comes from. With `RUNNING_MODE=lambda` every flow opens its own grid
session, because the LambdaTest dashboard names and grades tests per session.

## Parser pipeline

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

An unknown keyword (prose, a comment line) becomes a `WAIT(0)` placeholder so
the line still shows in the report. A known keyword with the wrong number of
arguments raises `FlowParseError` — a malformed step is never silently turned
into a no-op that passes.

## Project structure

```
web-agent/
├── conftest.py                     # pytest plugin: flow discovery, session browser, report plugin
├── main.py                         # CLI entry point
├── pytest.ini                      # testpaths=tests, pythonpath=.
├── pyproject.toml / requirements.txt
│
├── app/
│   ├── schemas/actions.py          # ActionType enum (44), FlowAction, StepResult, FlowResult
│   ├── flow/parser.py              # 4-stage pipeline: tokenize → normalize → validate → build
│   ├── layers/
│   │   ├── deterministic.py        # L1 + L2 dispatch-table runner
│   │   ├── locator.py              # FallbackLocator — polled strategies + selectolax
│   │   ├── ai_resolver.py          # L3 resolver + AI-native actions
│   │   └── providers/              # LLMProvider ABC, factory, OpenAI / Gemini / Claude adapters
│   ├── execution/engine.py         # FlowRunner: orchestrates L1 → L2 → L3, run_flow
│   ├── agent/
│   │   ├── orchestrator.py         # CLI runtime (one flow, own browser)
│   │   └── prompts/resolver.py     # LLM prompt templates
│   ├── browser/session.py          # Browser creation (local + LambdaTest)
│   ├── config/settings.py          # Typed settings from environment (.env loaded here)
│   ├── integrations/database/      # MySQL/MariaDB client (optional, unused by flows)
│   ├── observability/
│   │   ├── assets/                 # Static report shell, CSS, and JS
│   │   ├── console.py              # Live terminal output + execution summary
│   │   ├── recorder.py             # Per-test console + network capture
│   │   └── reporter.py             # HTML + JSON report generator
│   └── utils/
│       ├── banner.py               # Terminal startup banner (Rich)
│       └── build.py                # BUILD_NAME resolution + slug
│
├── tests/
│   ├── framework/                  # The runtime's own self-tests (no browser)
│   ├── wheelsup_site/flows/        # One suite per application under test
│   ├── members_site/flows/         #   … with shared sub-flows in components/
│   └── fms/flows/
│
├── docs/                           # These guides
└── reports/<ENVIRONMENT>/          # report.html, report_<build>.json, assets/, images/
```

Adding a new LLM provider means one new file under `app/layers/providers/`
plus one mapping entry in the factory — no changes to `AIResolver` or the
engine.

## Terminal banner

Displayed at the start of every pytest session, including the build name.
Customise in `app/utils/banner.py`:

```python
BANNER_CONFIG = {
    "version":     "1.0",
    "author":      "Cyberjaime45",
    "ascii_title": "...",      # any multi-line ASCII art string
    "title_color": "dark_cyan",
    "meta_color":  "dark_cyan",
}
```
