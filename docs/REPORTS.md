# Console Output & Reports

## Console output

The session opens with the banner — version, author, build name, and the
environment label — then pytest's own header. Every finished test prints one
named line under its file with its duration and the running completion
percentage on the right, and the run ends with an execution summary and the
report paths:

```
                     Version: 1.2.0
                 Created by: Cyberjaime45
                 Build: Web Test Report
              staging · chromium · headless

============================ test session starts ===========================
...
tests/fms/flows/production_smoke.md
  ✓ production_smoke.md » FMS MVC Smoke Tests  3m00s                     [ 50%]

tests/members_site/flows/booking_flow.md
  ✗ booking_flow.md » One Way Booking  41s                                [100%]

============================ Execution summary =============================
Build:         Web Test Report
Environment:   staging · chromium · headless
Python tests:  0
Flows:         2 (in 2 files)
Passed:        1
Failed:        1
Skipped:       0
Healed steps:  3 (resolved by L2/L3)
Duration:      3m41s
Slowest:       production_smoke.md » FMS MVC Smoke Tests  3m00s
               booking_flow.md » One Way Booking  41s
================================= Report ==================================
HTML : .../reports/staging/report.html
JSON : .../reports/staging/report_web_test_report.json
```

*Healed steps* counts steps that L1 could not resolve and L2/L3 recovered.
Pass `-v` or `-q` to get pytest's stock output instead.

A failed flow also prints its step list, one line per step with the layer
that resolved it, so the failure site is visible without opening the report.

## HTML report

After each run, a full HTML report is generated at `reports/<ENVIRONMENT>/report.html`.

```
reports/staging/
├── report.html          # Interactive UI (summary, failures, tests, suites, timeline, console, network)
├── report_<build>.json  # Raw structured data, full detail inline (for CI/tooling);
│                        # <build> = BUILD_NAME slug, e.g. report_web_test_report.json
├── assets/
│   ├── report.css
│   ├── report.js         # Summary, attention list, tests, suites, timeline
│   ├── report-detail.js  # Per-test drawer, console and network views
│   ├── nunito.woff2      # Dashboard font, bundled so the report works offline
│   ├── data.js          # Slim payload: run meta + per-test steps/errors/counts
│   └── data/
│       └── t-<i>.js     # Per-test console/network detail, lazy-loaded on demand
├── images/
│   ├── 001_<name>.png   # `screenshot` steps
│   └── <flow>__<profile>__<n>__{viewport,full,element}.png   # failure evidence
├── traces/
│   └── <flow>__<profile>[__retry].zip   # Playwright trace of each failed flow (TRACE=on-failure)
├── generated/
│   └── <flow>__<profile>__test_page.md   # deterministic flow written by test_page / explore_page
└── baselines/
    └── <name>__<profile>.json   # snapshot_page baselines of flows from outside the project
                                 # (a project flow keeps its own in <flow folder>/baselines/)
```

The UI loads only the slim payload upfront; a test's console/network detail
shard is fetched (via `<script>` injection, so `file://` works) the first time
its drawer opens, and the execution-level Console/Network tabs load the rest on
first open. Large runs stay fast to open, and the folder remains fully portable —
zip it and it opens anywhere.

The report uses the UP QA Dashboard's design system (colours, Nunito, cards,
badges, verdict banner, side drawer), so it reads as part of the same product.
It is written for reviewers first and engineers second, top to bottom:

- **Execution summary** — build name, environment, browser, device, duration,
  run type and date; a verdict banner (`6 tests failed` / `All tests passed`)
  with a one-line explanation; the pass rate, the passed / failed / skipped
  counts with a bar, and the number of suites
- **Tests requiring attention** — shown only when something failed. One row
  per failure: the test, a plain-English explanation (`Expected text "Book now"
  was not found on the page within 5 seconds.`), the failed step, duration, and
  a thumbnail of the screen at the failure that opens full size
- **All tests** — tests grouped by suite (a flow file, named by its `# H1`, with
  the path underneath; each `## section` is its own test). Suites with failures
  come first and stay open; passing suites fold away. Search (`/`), status
  filters (All / Failed / Passed / Passed on retry / Skipped), area and tag
  filters. Row badges are coloured only when they carry status: console errors
  in red; console warnings and flagged checks in amber; failed requests (mostly
  third-party beacons) in grey; a lightning icon marks a self-healed test (a
  fallback locator was needed — the tooltip says so); *Autonomous* (`test_page`, `explore_page`) and the device
  (when a run used several) in blue; tags in grey
- **Suites** — one row per suite with pass rate, results and duration; select a
  row to list its tests
- **Timeline** — when each test ran, in lanes for parallel runs
- **Console / Network** — every test's browser console messages and requests,
  with level/type filters, search, source test, expandable headers and bodies,
  and Copy cURL / Copy URL
- **Run details** — timing, environment (devices, OS, run type), tool versions,
  run ID, the slowest tests, and the tests with self-healed steps

Selecting a test opens a side drawer, which reads the same way:

- **What went wrong** (failures) — the failed step as a red callout, the
  plain-English explanation, the likely cause (`Likely application defect`,
  `Likely test issue`, `Likely environment or session`, `Cause unclear`) with
  the signals behind it, and the viewport / full-page / element screenshots
- **Summary** — result, duration, start time, suite, area, device, reruns and
  tags, laid out side by side and wrapping onto a second line when narrow; a
  test rerun by `RERUN_FAILED` also shows the first attempt's error
- **Autonomous run** (when present) — page type and how it was classified,
  components, plan, actions executed, plan steps the validator rejected,
  controls skipped by the safety policy, the assertions added to the generated
  flow, AI calls, and a link to the generated flow under `generated/`
- **Steps** — each step as a readable action (`Check text is shown "Book now"`,
  the keyword on hover), its duration, the self-healed lightning icon when L2/L3
  found the element, screenshots, and automatic checks / skill findings as one
  collapsed line (`9 checks passed`, `1 warning in 9 checks`, `1 of 8 checks
  failed`) that expands to one row per check. The list is a
  summary: a passed check keeps its wording (`No failed requests`), a flagged
  one names what was found with a count (`Failed requests 9`, `Console errors
  2`); the messages are in the tooltip, and **Details** opens Technical
  details on the Console or Network tab. In a failing test, passing
  groups fold so the failing one stands out
- **Technical details** (folded; stays open across tests once opened) — the raw
  error output and full traceback, how each layer attempted the step
  (`L1 exact: failed · L2 fuzzy: failed · L3 AI: skipped: …`), the page URL
  and title at the failure, the Playwright trace download, console errors and
  failed requests logged during the step, browser activity near the failure
  (hints, not a confirmed cause), self-healed steps, and the test's Console and
  Network views

`✕`, `Esc` or the backdrop closes the drawer; filters are untouched. A moon
button in the header switches to dark mode (remembered per browser). The JSON
carries each failed step's `evidence` (with `diagnosis`: `verdict`, `summary`,
`signals`), the test's `artifacts` (`screenshot`, `screenshots`, `trace`),
`retries` and `retry_error` for tests rerun by `RERUN_FAILED`, and `checks` on
each step. Sensitive headers and fields
(Authorization, cookies, tokens…) are redacted automatically; extend the list
with `REPORT_REDACT`.

```bash
open reports/staging/report.html
```

One JSON report is kept per environment folder, named for the current
`BUILD_NAME`; a JSON left over from a previous build name is removed when the
report regenerates. `pytest --collect-only` and fully deselected runs leave the
previous report untouched.

## Multi-environment reports

```bash
ENVIRONMENT=qa1 uv run pytest tests/fms/flows/production_smoke.md
# → writes to reports/qa1/
```

## LambdaTest cloud execution

```bash
RUNNING_MODE=lambda LT_USERNAME=... LT_ACCESS_KEY=... uv run pytest
```

Each flow gets its own LambdaTest session, named after the flow and grouped
under the build `<BUILD_NAME> -> <ENVIRONMENT>`; pass/fail status is reported
to the dashboard automatically. Locally, one browser is shared for the whole
run and every flow gets a fresh browser context.
