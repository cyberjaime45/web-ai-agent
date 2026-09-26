# Architecture

## Execution pipeline

One path, whichever entry point starts it:

```
pytest (conftest.py)          CLI / other agents (main.py → app.agent.orchestrator)
        │                                   │
        └──────────── flow.md ──────────────┘
                         │ app/flow/parser.py        Markdown → FlowDefinition (FlowAction per step)
                         ▼
              BrowserSession.page(profile)            app/browser/session.py + profiles.py
                         │ one browser per session, a fresh context per flow; PageRecorder attached
                         ▼
              FlowRunner.run  (app/execution/engine.py)
                         │ per ## section; a failure skips the rest of that section only
                         ▼
              FlowRunner.run_action(line)             one line → [step] or a group
                 ├─ run_flow  → _run_sub_flow → run_action for each sub-flow line
                 ├─ skill     → app/skills/base.run_skill → marker step + child steps (SkillContext.run)
                 └─ action    → FlowRunner.execute
                                  placeholders → L1 → L2 → L3 → oracle (on success)
                                  → evidence + diagnosis (on failure) → RunContext history
                         │ FlowResult (steps, checks, evidence)
                         ▼
              pytest: report_plugin → report_model.build_tests → reporter.generate_report
              CLI:    FlowResult JSON on stdout
```

Every step, whether written in Markdown or chosen by a skill, goes through
`FlowRunner.execute`. That keeps timing, the layer chain, automatic checks and
failure evidence identical everywhere.

## Layer behaviour

| Layer | Trigger | Strategy |
|-------|---------|----------|
| **L1 — Deterministic** | Always tried first | `_h_<keyword>` handlers in `app/layers/deterministic.py`: exact Playwright `get_by_role`, `get_by_label`, `get_by_placeholder` locators, capped at 5 s (`_L1_TIMEOUT`) so failover stays fast. Text checks match **visible** elements only, so a hidden duplicate never hides the visible one. When a click, fill or other interaction fails, a covering cookie banner or modal is dismissed and L1 is retried once (a `dismissed blocker` info check); assertions are never retried this way. |
| **L2 — Fallback** | L1 fails | `_l2_<keyword>` handlers in `deterministic_l2.py`. Element actions: looser Playwright strategies polled for up to 5 s, then one similarity pass over the DOM (≥ 0.6). Text checks: the page's rendered, visible text (case-insensitive, whitespace collapsed) — never the raw HTML, where hidden elements and scripts would make an absent text look present. |
| **L3 — AI** | L1 + L2 fail on an element interaction, or an AI-native action | One LLM call with page context via a pluggable provider (OpenAI, Gemini, Claude). Only actions L3 can perform with a locator (`_LOCATOR_ACTIONS`: click, fill, select, check…) are sent; assertions and waits never reach it. Off when `AI_PROVIDER` is empty. |

L1 signals failure by raising, L2 by `RuntimeError`, L3 by returning `None`.
Most flows run entirely on L1 with no API calls.

## Failure and recovery

```
L1 fails ─► blocker dismissed? (interactions) ─► L1 once more
        └─► L2 ─► L3 (element interactions, provider set) ─► failed StepResult (_fail: what each layer did)
                                                                  │
                     FlowRunner.attach_evidence ◄─────────────────┘
                       evidence.collect   screenshots, URL/title, console + network since the step
                       diagnosis.diagnose likely cause: application / test / environment / unclassified
                                                                  │
                     section stops; next section runs            ▼
                     RERUN_FAILED (pytest): whole flow once more, merged per section (execution/rerun.py)
                                                                  │
                     report: failed / passed on retry / consistent failure, with evidence and cause
```

Nothing on this path runs for a passing step. The per-step cost of a passing
step is the L1 call, one `page.url` read and, after navigation-class steps
only, the oracle (in-memory recorder reads plus one `evaluate`). Screenshots,
the DOM observation behind the diagnosis, and L2/L3 only run on failure.
Tracing (`TRACE=on-failure`) records every flow and keeps the zip only for
flows that fail.

## State

| State | Lives in | Lifetime |
|-------|----------|----------|
| Configuration | `app/config/settings.py` — `settings`, frozen, the only env reader | process |
| Browser, driver | `BrowserSession` (one per pytest session / CLI run) | session |
| Context, page, `PageRecorder` | opened per flow attempt | one flow attempt |
| `FlowRunner` | per flow attempt: recorder mark, safety policy, ignore rules, evidence numbering | one flow attempt |
| `RunContext` | step history and extracted values (`ai_extract`, `read_row`…) | one run |
| `SkillContext` | one skill step: its child steps, shots, agent facts | one skill step |
| Registries | `ActionType` (vocabulary), L1/L2 handlers by name, `SKILLS` (filled by `@skill`) | process, read-only after import |
| Report data | `report_plugin` (pytest) until session end | session |

No component writes to another's state: skills act through
`SkillContext.run`, results flow back as `StepResult`s, and the report plugin
only reads what `FlowItem` hands it.

## Skills, observer, oracle, planner

A skill (`app/skills/`) is a function that looks at the page (`observe`,
`evaluate`) and acts only through `SkillContext.run` → `FlowRunner.execute`.
The engine runs a skill keyword like `run_flow`: a marker step carrying the
skill's checks, then the child steps it executed. Skills never enter the layer
chain themselves, so a skill as a whole cannot be "healed". Checks carry a
severity: `error` fails the skill step, `warn` never does, `info` observes.

The observer (`app/agent/observer.py`) turns Playwright's accessibility
snapshot plus one form-metadata `evaluate` into an `Observation`: headings and
interactive controls with refs, forms with field types, counts of tables,
dialogs and navigation, and a coarse page type. `landmarks()` reads the
heading, dialog title and alert after a skill's navigation steps — the raw
material for the assertions `test_page` writes into generated flows.

The oracle (`app/execution/oracle.py`) runs after successful navigation-class
steps: recorder checks (page errors, console errors, failed / 401 / 403 / 4xx
requests since the step's mark) plus one render probe (blank page, stuck
spinner, blocking dialog, overflow). `ORACLE=warn` records; `strict` fails the
step on an error check; `off` skips it.

The planner (`app/agent/planner.py`) is the only place an LLM decides *what*
to do: it returns JSON steps validated before anything runs — known keywords
only, targets present in the observation, the safety policy applied to each.
`SkillContext.run_planned` executes the accepted steps. The safety policy
(`app/agent/safety.py`) is deterministic and consulted before every click a
skill chose by itself; configuration is the only override, never AI.

## Extending the framework

| To add | Change | Nothing else |
|--------|--------|--------------|
| **An action** | `ActionType` value + `ACTION_ARG_SPEC` in `app/schemas/actions.py`; a `_h_<keyword>` method in `app/layers/deterministic.py`; optionally `_l2_<keyword>` in `deterministic_l2.py` and an entry in `_LOCATOR_ACTIONS` (`ai_resolver.py`) if L3 can perform it; `docs/ACTIONS.md` | Handlers register by name; the parser, lint and registry test pick the keyword up from the enum |
| **A skill** | `ActionType` value + `ACTION_ARG_SPEC` + `SKILL_ACTIONS`; a module in `app/skills/` with `@skill(ActionType.X)`; `docs/ACTIONS.md` | The package imports every module in it; the engine dispatches skills generically |
| **An assertion** | It is an action (above); raise to fail. Text checks should use `.filter(visible=True)` | — |
| **A diagnostic signal** | A rule in `app/observability/diagnosis.py` (reads `Evidence`, one probe, one observation) | Runs from `attach_evidence` on failures only |
| **A browser capability / profile** | `app/browser/profiles.py` (context options) | Flows, actions and the engine never branch on the profile |
| **An execution environment** | A `create_browser` branch + helper in `app/browser/session.py`, its status call in `report_status` | `BrowserSession` serves both pytest and the CLI |
| **An LLM provider** | One adapter under `app/layers/providers/` + one factory entry | `AIResolver`, the planner and the engine are unchanged |
| **A report section** | Data in `app/observability/report_model.py`, rendering in `assets/report*.js` | `reporter.py` only writes files |

## Configuration and browser lifecycle

`app/config/settings.py` loads `.env` and is the only place environment
variables are read, so pytest and the CLI see identical configuration. L3 is
switched on by `AI_PROVIDER` alone; a named provider without
`LLM_KEY`/`LLM_MODEL` is a startup error, not a per-test one.

`BrowserSession` keeps one Playwright driver and browser for the whole pytest
session (or CLI run) and opens a fresh `BrowserContext` per flow — that is
where cookie and storage isolation comes from. With `RUNNING_MODE=lambda`
every flow opens its own grid session, because the LambdaTest dashboard names
and grades tests per session. Contexts close in `finally`, whatever the flow
did.

A profile (`app/browser/profiles.py`) is a set of `BrowserContext` options:
`desktop` is the session's own viewport, `mobile` is Playwright's device
descriptor named by `MOBILE_DEVICE`. pytest collects one `FlowItem` per
profile a flow runs under (`--profile`, the flow's `## Config` `profiles:`
line, or `PROFILE`).

## Parser pipeline

```
raw step text → tokenize (keyword, raw args) → normalize (ActionType, pipe-split args)
              → validate (ACTION_ARG_SPEC; FlowParseError with the step number) → build (FlowAction)
```

An unknown keyword (prose, a comment line) becomes a `WAIT(0)` placeholder so
the line still shows in the report — `main.py lint` flags it as
`unknown-step`. A known keyword with the wrong number of arguments raises
`FlowParseError`: a malformed step is never silently turned into a pass.

## Project structure

```
web-agent/
├── conftest.py                     # pytest entry: flow discovery, FlowItem (attempts, rerun merge)
├── main.py                         # CLI: run, agent-test, lint
├── pytest.ini                      # testpaths=tests, pythonpath=.
│
├── app/
│   ├── schemas/actions.py          # ActionType (58) + arg spec, FlowAction, StepResult, Check, Evidence,
│   │                               # FlowResult, section_runs, summarize
│   ├── flow/
│   │   ├── parser.py               # Markdown → FlowDefinition; resolve_flow_path
│   │   ├── writer.py               # StepResults / explore graph → deterministic Markdown flow
│   │   └── lint.py                 # Static flow checks + healed-steps report (main.py lint)
│   ├── execution/
│   │   ├── engine.py               # FlowRunner: sections, run_action, execute (L1 → L2 → L3), evidence
│   │   ├── oracle.py               # Automatic checks after navigation-class steps
│   │   └── rerun.py                # RERUN_FAILED: merge a failed flow with its rerun per section
│   ├── layers/
│   │   ├── deterministic.py        # L1: _h_<keyword> handlers, locate(), blocker recovery
│   │   ├── deterministic_l2.py     # L2: _l2_<keyword> fallbacks
│   │   ├── locator.py              # FallbackLocator: polled loose strategies + similarity pass
│   │   ├── blockers.py             # Cookie banner / modal dismissal
│   │   ├── stability.py            # wait_stable: in-flight requests, loading indicators, DOM quiet
│   │   ├── ai_resolver.py          # L3 + AI-native actions
│   │   └── providers/              # LLMProvider ABC, factory, OpenAI / Gemini / Claude adapters
│   ├── skills/                     # One module per QA skill, registered by @skill
│   │   └── base.py                 # SkillContext (observe, run, run_skill, run_planned), run_skill
│   ├── agent/
│   │   ├── observer.py             # Structured page observation (accessibility tree + forms), landmarks
│   │   ├── planner.py              # LLM plan → validated steps on observed targets
│   │   ├── safety.py               # Deterministic safety policy
│   │   ├── orchestrator.py         # Run one flow outside pytest (CLI, in-process callers)
│   │   └── prompts/                # LLM prompt templates
│   ├── browser/
│   │   ├── session.py              # BrowserSession, create_browser (local / LambdaTest), report_status
│   │   └── profiles.py             # desktop / mobile context options
│   ├── observability/
│   │   ├── recorder.py             # Per-page console + network capture (redacted, capped)
│   │   ├── evidence.py             # Failure screenshots, page state, trace
│   │   ├── diagnosis.py            # Likely cause of a failed step
│   │   ├── console.py              # Terminal reporter + execution summary
│   │   ├── report_plugin.py        # pytest plugin collecting results for the report
│   │   ├── report_model.py         # Results → report test / step records
│   │   ├── reporter.py             # Writes report.html, assets, data shards, JSON
│   │   └── assets/                 # Report shell, CSS, JS
│   ├── config/settings.py          # Typed settings (.env loaded here)
│   ├── integrations/database/      # MySQL/MariaDB client (optional, unused by flows)
│   └── utils/                      # banner, build name, URL helpers
│
├── tests/
│   ├── _framework/                 # The runtime's own tests (fake pages + local fixture pages)
│   └── <app>/flows/                # One suite per application, shared sub-flows in components/
│
├── docs/                           # These guides
└── reports/<ENVIRONMENT>/          # report.html, JSON, assets/, images/, traces/, generated/, baselines/
```

## Terminal banner

Displayed once at the start of every pytest session, before pytest's own
`test session starts` header: the art plus `Version`, `Created by`, `Build`
(the `BUILD_NAME` label) and the environment label `env · browser ·
mode[ · lambda]`, centered and green on a TTY. Change the art,
`APP_VERSION` or `CREATED_BY` in `app/utils/banner.py`.
