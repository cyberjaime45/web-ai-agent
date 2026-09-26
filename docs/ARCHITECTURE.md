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
| **L1 — Deterministic** | Always tried first | Dispatch-table driven. Exact Playwright `get_by_role`, `get_by_label`, `get_by_placeholder` locators, capped at 5 s per action so failover stays fast. When a click, fill or other interaction fails, a covering cookie banner or modal is dismissed and L1 is retried once (recorded as a `dismissed blocker` info check); assertions are never retried this way. |
| **L2 — Fallback** | L1 fails | Four looser Playwright strategies per element type (clickable, input, checkbox) polled for up to 5 s, then a single selectolax pass over the page HTML picking the most similar text (≥ 0.6). |
| **L3 — AI** | L1 + L2 fail on an element interaction, or an AI-native action | LLM call with page context via a pluggable provider (OpenAI, Gemini, or Claude). Only actions L3 can execute with a locator (click, fill, select, check…) are sent; assertions and waits never reach it. Skipped if `AI_PROVIDER`/`LLM_KEY`/`LLM_MODEL` are not set. |

Most flows run entirely on L1 with zero API calls. L2 handles case variations,
extra whitespace, and partial text matches. L3 is the last resort for complex
or dynamic pages, and the exclusive runtime for AI-native actions
(`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`).

## Configuration and browser lifecycle

`app/config/settings.py` loads `.env` and is the only place environment
variables are read; pytest and the CLI therefore see identical configuration.
L3 is switched on by `AI_PROVIDER` alone: empty or missing disables it, and a
named provider without `LLM_KEY`/`LLM_MODEL` is a startup error, not a per-test one.

Under pytest, one Playwright driver and browser serve the whole session and
each flow gets a fresh `BrowserContext` — that is where cookie and storage
isolation comes from. With `RUNNING_MODE=lambda` every flow opens its own grid
session, because the LambdaTest dashboard names and grades tests per session.

## Device profiles

A profile (`app/browser/profiles.py`) is a set of `BrowserContext` options:
`desktop` is the session's own viewport, `mobile` is Playwright's device
descriptor named by `MOBILE_DEVICE`. Profiles are applied at context creation
only — the browser, the flow and every step are shared. pytest collects one
`FlowItem` per profile a flow runs under (`--profile`, the flow's `## Config`
`profiles:` line, or `PROFILE`), and the report labels each test with it.

## Skills, observer and oracle

A skill (`app/skills/`) is a function that looks at the page and acts only
through `FlowRunner.execute`, the same L1 → L2 → L3 path a Markdown step
takes. The engine runs a skill keyword like `run_flow`: a marker step carrying
the skill's checks, then the child steps it executed, nested in the report.
Skills never enter the layer chain themselves, so a skill as a whole cannot
be "healed".

The observer (`app/agent/observer.py`) turns Playwright's accessibility
snapshot plus one form-metadata `evaluate` into a small structured
`Observation`: headings and interactive controls with stable refs, forms with
field types and required flags, counts of tables, dialogs and navigation, and
a coarse page type. Deterministic skills consume it directly; its `to_prompt`
rendering (a few KB, never the DOM) is what the Phase 3 planner will send to
an LLM.

The planner (`app/agent/planner.py`) is the only place an LLM decides *what*
to do. It receives the observation's prompt rendering, a goal and what was
already done, and returns JSON steps that are validated before anything runs:
known flow keywords only, element targets that exist in the observation (by
ref or name), and the safety policy applied to each. Rejected steps are kept
for the report. `explore_page` uses it only to order the controls the
observer found; without a provider every skill runs deterministically.

`test_page` (`app/skills/test_page.py`) composes the rest: it classifies the
page from the observation (deterministic signals; an LLM tie-break only for
`CONTENT` / `UNKNOWN`), runs the skills that fit the type as nested groups,
optionally executes a short validated AI plan, and writes what ran as a plain
flow through `app/flow/writer.py` — the path from autonomous exploration to
deterministic regression. `explore_page` writes its graph the same way.

The safety policy (`app/agent/safety.py`) is deterministic and consulted before
any click a skill chose by itself: a destructive verb in the control's name, a
neutral confirm button inside a destructive or payment dialog / form (the
observer records each control's landmark), or a confirm button on a delete /
checkout / unsubscribe URL blocks the press. `allow_destructive` and
`allow_actions` in a flow's `## Config`, or `ALLOW_DESTRUCTIVE=true`, are the
only overrides; AI never is.

The oracle (`app/execution/oracle.py`) runs after successful navigation-class
steps: recorder-based checks (page errors, console errors, failed / 401 /
403 / 4xx requests since the step's sequence mark) plus one render-state
probe (blank page, stuck spinner, blocking dialog, horizontal overflow).
`ORACLE=warn` records, `strict` fails the step on an error-severity check,
`off` skips it. `check_console_network` and `test_responsive` reuse the same
functions explicitly.

## Failure evidence

When a step fails, `FlowRunner.execute` calls `attach_evidence`, which fills a
`StepResult.evidence` bundle through `app/observability/evidence.py`: what each
layer did (recorded by the engine as the chain ran), viewport / full-page /
element screenshots, page URL and title, profile, and — via the `PageRecorder`
sequence mark taken before the step — the console errors and failed requests
of that step. Every capture is best-effort and never raises. conftest keeps a
Playwright trace per failed flow (`TRACE=on-failure`) and attaches it to the
failing step; the reporter turns all paths report-relative.

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
│   ├── schemas/actions.py          # ActionType enum (58), FlowAction, StepResult, Check, FlowResult
│   ├── flow/parser.py              # 4-stage pipeline: tokenize → normalize → validate → build
│   ├── flow/lint.py                # Static flow checks + healed-steps report (main.py lint)
│   ├── layers/
│   │   ├── deterministic.py        # L1 dispatch-table runner (+ locate() for evidence)
│   │   ├── deterministic_l2.py     # L2 handlers mixed into the runner
│   │   ├── blockers.py             # Cookie-banner / modal dismissal (after an L1 interaction failure; DISMISS_BLOCKERS)
│   │   ├── stability.py            # wait_stable: in-flight requests, loading indicators, DOM quiet
│   │   ├── locator.py              # FallbackLocator — polled strategies + selectolax
│   │   ├── ai_resolver.py          # L3 resolver + AI-native actions
│   │   └── providers/              # LLMProvider ABC, factory, OpenAI / Gemini / Claude adapters
│   ├── execution/
│   │   ├── engine.py               # FlowRunner: L1 → L2 → L3, run_flow, skills, execute(), evidence
│   │   ├── rerun.py                # RERUN_FAILED: merge a failed flow with its rerun per section
│   │   └── oracle.py               # Automatic checks after steps (diagnostics + render probe)
│   ├── skills/                     # inspect_page, check_console_network, test_responsive, test_form, explore_page, test_page,
│   │                               # check_links, check_accessibility, test_table, test_search,
│   │                               # snapshot_page, test_widgets, check_performance
│   │   └── base.py                 # SkillContext (observe / run / run_skill through the engine), run_skill
│   ├── flow/writer.py              # StepResults / explore graph → deterministic Markdown flow
│   ├── planner_bridge.py           # Execute validated planner steps through a SkillContext
│   ├── agent/
│   │   ├── observer.py             # Structured page observation from the accessibility tree
│   │   ├── planner.py              # LLM plan → validated known actions on observed targets
│   │   ├── safety.py               # Safety policy: destructive names, dialog/form context, URL
│   │   ├── orchestrator.py         # CLI runtime (one flow, own browser)
│   │   └── prompts/                # LLM prompt templates (resolver, planner)
│   ├── browser/
│   │   ├── session.py              # Browser creation (local + LambdaTest)
│   │   └── profiles.py             # desktop / mobile context options
│   ├── config/settings.py          # Typed settings from environment (.env loaded here)
│   ├── integrations/database/      # MySQL/MariaDB client (optional, unused by flows)
│   ├── observability/
│   │   ├── assets/                 # Static report shell, CSS, and JS
│   │   ├── console.py              # Live terminal output + execution summary
│   │   ├── evidence.py             # Failure evidence: screenshots, page state, diagnostics
│   │   ├── diagnosis.py            # Likely cause of a failed step (application / test / environment)
│   │   ├── recorder.py             # Per-test console + network capture
│   │   └── reporter.py             # HTML + JSON report generator
│   └── utils/
│       ├── banner.py               # Terminal startup banner (plain text, green on a TTY)
│       └── build.py                # BUILD_NAME resolution + slug
│
├── tests/
│   ├── framework/                  # The runtime's own self-tests (no browser)
│   ├── marketing_site/flows/        # One suite per application under test
│   ├── members_site/flows/         #   … with shared sub-flows in components/
│   └── fms/flows/
│
├── docs/                           # These guides
└── reports/<ENVIRONMENT>/          # report.html, report_<build>.json, assets/, images/, traces/, generated/
```

Adding a new LLM provider means one new file under `app/layers/providers/`
plus one mapping entry in the factory — no changes to `AIResolver` or the
engine.

## Terminal banner

Displayed once at the start of every pytest session, before pytest's own
`test session starts` header. Same renderer as Astra: the art plus four
lines — `Version`, `Created by`, `Build` (the `BUILD_NAME` label), and the
environment label `env · browser · mode[ · lambda]` — centered to the
terminal width and green when stdout is a TTY. No Rich or other rendering
dependency. Change the art, `APP_VERSION`, or `CREATED_BY` in
`app/utils/banner.py`; the build and environment lines come from
`BUILD_NAME` and `Settings.run_label()`.
