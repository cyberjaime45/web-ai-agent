# Console Output & Reports

## Console output

The session opens with the banner — version, author, build name, and the
environment label — then pytest's own header. Every finished test prints one
named line under its file with its duration and the running completion
percentage on the right, and the run ends with an execution summary and the
report paths:

```
                     Version: 1.0.0
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
├── report.html          # Interactive UI (overview, tests, timeline, console, network)
├── report_<build>.json  # Raw structured data, full detail inline (for CI/tooling);
│                        # <build> = BUILD_NAME slug, e.g. report_web_test_report.json
├── assets/
│   ├── report.css
│   ├── report.js
│   ├── data.js          # Slim payload: run meta + per-test steps/errors/counts
│   └── data/
│       └── t-<i>.js     # Per-test console/network detail, lazy-loaded on demand
└── images/
    └── *.png            # Screenshots from the run
```

The UI loads only the slim payload upfront; a test's console/network detail
shard is fetched (via `<script>` injection, so `file://` works) the first time
its drawer opens, and the execution-level Console/Network tabs load the rest on
first open. Large runs stay fast to open, and the folder remains fully portable —
zip it and it opens anywhere.

The report includes:

- A flow file shown as a suite named by its `# H1` (`Home Page`), with the
  source path underneath as secondary text; a file without an H1 is labelled
  by its path. Each `## section` is its own test row under that header, with
  status, markers, duration, and steps — totals count these tests, not files
- A right-side drawer per test: status, then suite, file, test, duration,
  start time, reruns, and markers, then the steps in order — action verb and
  argument, L2/L3 chip when the fallback chain resolved the step, duration,
  the error card at the failing step, and a clickable screenshot thumbnail —
  followed by Console and Network tabs. Clicking another test updates the
  same drawer; `✕`, `Esc`, or the backdrop closes it, and search/filter state
  is untouched
- Console messages (all levels) with level filters, search, repeat grouping, and source locations
- Network requests with method/status/type/duration/size, filters (Failed/XHR/Doc/JS/CSS/Img), search, sorting, expandable headers/payloads, and Copy cURL/URL actions
- Console errors and network activity routed to the section and step where they occurred
- "Likely related activity" hints next to failures (nearby console errors and failed requests)
- Execution-level Console and Network tabs aggregating all tests with per-test attribution
- Healed-locator tracking (L2/L3 usage) and failure screenshots
- Sensitive headers/fields (Authorization, cookies, tokens…) redacted automatically; extend via `REPORT_REDACT`

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
