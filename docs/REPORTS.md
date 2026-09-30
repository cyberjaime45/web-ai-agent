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
Flows:         2 (in 2 files)
Passed:        8
Failed:        1
Skipped:       0
Healed steps:  3 (resolved by L2/L3)
Duration:      3m41s
Slowest:       production_smoke.md » FMS MVC Smoke Tests  3m00s
               booking_flow.md » One Way Booking  41s
================================= Report ==================================
HTML : .../reports/staging/report.html
JSON : .../reports/staging/summary.json
JSON : .../reports/staging/test_cases.json
JUnit: .../reports/staging/junit.xml
```

*Flows* counts the Markdown flows that ran. A flow with `## sections` is
split into one test case per section; *Passed*, *Failed* (errors included)
and *Skipped* count those test cases and are read from `summary.json`, so the
console, the JSON and `junit.xml` always agree. *Warnings* (shown only when
there are some) counts passed test cases with at least one warning — they are
also in *Passed*. *Not verified* (shown only when there are some) counts test
cases with checks the agent could not judge — coverage gaps, not defects;
they never make a test "with warnings". *Interrupted* appears when the run stopped before every flow
finished (Ctrl-C); the counts then cover what completed.

The process exit code comes from the same model (`summary.json` →
`exit_code`): `1` when any test case failed, `2` when the run was interrupted,
otherwise `0`. A usage or internal error (any other pytest code), or a pytest
failure outside the test cases (a teardown error), is status `error` with an
*Error* row and a *Run error* banner — the report never calls it passed.
Warnings never change the exit code; a test that passed on retry counts as
*passed on retry*, not as *with warnings*.

*Healed steps* counts steps that L1 could not resolve and L2/L3 recovered.
Pass `-v` or `-q` to get pytest's stock output instead.

A failed flow also prints its step list, one line per step with the layer
that resolved it, so the failure site is visible without opening the report.

## HTML report

After each run, a full HTML report is generated at `reports/<ENVIRONMENT>/report.html`.

```
reports/staging/
├── report.html          # Interactive UI (summary, failures, tests, suites, timeline, console, network)
├── summary.json         # Run metadata, totals, status, exit_code (no tests) for CI/tooling
├── test_cases.json      # {"run_id", "tests": [...]}: every test, full detail inline
│                        # (steps, failures, attachments, console, network); summary
│                        # totals are counted from this list
├── junit.xml            # The same test cases as JUnit XML (one <testsuite> per file)
│                        # for CI test tabs, e.g. Azure PublishTestResults
├── assets/
│   ├── report.css
│   ├── report.js         # Summary, tests, suites, timeline
│   ├── report-logs.js    # Console and network views (drawer panes and execution tabs)
│   ├── report-detail.js  # Per-test drawer
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
The drawer sizes to the screen: about 83% of a desktop window (never less than
768px, never more than 1300px), 92% on a tablet, the full width on a phone.
It is written for reviewers first and engineers second, top to bottom:

- **Execution summary** — build name, environment, browser, device, duration,
  run type and date; a verdict banner (`6 tests failed` / `Passed with
  warnings` / `All tests passed` / `Run interrupted`) with a one-line
  explanation (`Both tests passed, both with warnings to review.`); the pass
  rate; what needs attention — failures in red (`1 test failed, 2 more with
  warnings`), warnings alone in amber (`2 tests have warnings`); the tests by
  status as parts that add up to the total — *passed*, *with warnings*,
  *passed on retry*, *failed*, *skipped* — in words, a bar and its key; and
  the number of test cases and suites
- **All tests** — tests grouped by suite (a flow file, named by its `# H1`, with
  the path underneath; each `## section` is its own test). Suites with failures
  come first and stay open; passing suites fold away. Search (`/`), status
  filters (All / Failed / Passed / With warnings / Passed on retry / Skipped —
  the same parts as the summary, so they add up to All), area and tag filters.
  Row badges are coloured only when they carry status: console errors in red;
  the test's warnings in amber (the amber dot says the same, so no status
  badge repeats it); console warnings (browser messages, not checks) and
  failed requests in grey — a cancelled request (`net::ERR_ABORTED`: a beacon,
  a request cut off by leaving the page) is not a failure, here or in the
  Network views, where it shows as `CANCEL`; a lightning icon marks a self-healed test (a
  fallback locator was needed — the tooltip says so); *Autonomous* (`test_page`, `explore_page`) in blue; tags in grey. Each
  test name ends with its device icon (monitor for desktop, phone for mobile),
  and a test's profiles sit together — `Login Page 🖥`, `Login Page 📱`, then
  the next test — in the order the tests first ran
- **Suites** — one row per suite with pass rate, results and duration; select a
  row to list its tests
- **Timeline** — when each test ran, in lanes for parallel runs
- **Console / Network** — every test's browser console messages and the
  requests to the site under test, with level/type filters, search, source
  test, expandable headers and bodies, and Copy cURL / Copy URL

Only the site under test is recorded: requests whose host is the site domain
or one of its subdomains — the domain of the flow's first `goto` step
(`goto: "https://memberssitestaging.wheelsup.com/"` → `wheelsup.com`) — and
never prefetches — Chromium's Speculation Rules prefetches (type
`prefetch`, as Cloudflare Speed Brain issues them) or any request carrying a
`Purpose` / `Sec-Purpose: prefetch` or `Next-Router-Prefetch` header. What is
left out is never counted, checked or shown, so a failed prefetch or a
third-party beacon cannot fail a step; a real navigation to the same URL is
recorded as usual. A drawer's Network tab says how many requests were left out
(`network_untracked` in `test_cases.json`). A classic `<link rel="prefetch">`
reaches the framework as an ordinary request (type `other`, no prefetch
header in the browser's event data), so it is recorded like one
- **Run details** — timing, environment (devices, OS, run type), tool versions,
  run ID, the slowest tests, and the tests with self-healed steps

Selecting a test opens a side drawer, which reads the same way:

- **Facts** (always first, no heading) — duration, start time, suite, area,
  device (a monitor or phone icon for the profile, then browser and viewport:
  `🖥 chromium · 1920x1080`), reruns and tags — the result is the badge in the
  drawer's header — laid out side by side and wrapping onto a second line when narrow; a
  test rerun by `RERUN_FAILED` also shows the first attempt's error with
  its likely cause, so a pass after a server failure reads differently from
  a locator that was slow once
- **What went wrong** (failures) — one card per failed step, in the order they
  ran: its number and action (`Step 3.3 · Explore page`), the flow or skill it
  ran in (`in Test page`), what happened in plain words — a failed check is a
  finding block: a headline (`Pages that broke after a press`) and one row per
  affected element, the selector or request as a badge and what the evidence
  shows beside it; a failed action reads
  `Could not find "Sign in" on the page to click within 5 seconds.` — the
  likely cause (`Likely application defect`, `Likely timing: page still
  loading`, `Likely test issue`, `Likely environment or session`, `Flow or
  setup problem`, `Cause unclear`) with its signals — and, when a provider is
  configured and the cause was unclear, an `AI diagnosis · unverified` line:
  a model's one-sentence reading of the same evidence and what to check
  first, never a result — that step's
  screenshots, and links to the step in the list and to its error details.
  A group whose step failed inside it (`Test page` above) is failed too, but
  only the step where it happened gets a card
- **Warnings** (when the test has any) — each finding that did not fail the
  test as the same kind of block: a severity icon, a plain-language headline
  (`Form labels are not associated with their inputs`, `“Welcome!” appears as
  a heading but uses a <div>`), one row per affected element with the
  selector as a badge (`input[name=email]` — The Email input's visible label
  is not associated with the field), and the step link in its own column on
  the right. Rows never add findings: the count and severity are the check's.
  Besides the automatic page checks these include the engine's verify stage:
  `action changed the page` (a click that changed nothing visible), `control
  holds the value` (a field that reads differently after `fill`) and `page
  settled in time` (a step that passed only after the engine waited for a
  loading page)
  The same finding on several steps (a nested skill, the automatic checks
  after each step) is one entry linking each step (`Step 3.2 · 4.1`)
- **Autonomous run** (when present) — page type and how it was classified,
  components, plan, actions executed, plan steps the validator rejected,
  controls skipped by the safety policy, the assertions added to the generated
  flow, AI calls, and a link to the generated flow under `generated/`. Each
  value is compact rows rather than a paragraph: a component row is its kind,
  its count and the control names as badges (`buttons 3 Request Info ·
  LOG IN`), the plan is numbered with an `AI` badge on steps the planner
  added, a skipped control is the control and the policy's reason, and the
  actions executed are the count followed by the first steps as `click:
  "Request Info"` chips
- **Steps** — the execution order, numbered by position: `3` is the third
  step of the test, `3.3` the third step inside it, and a group shows how many
  steps it holds (`Explore page · 21 steps`). Every row uses the same columns
  — expand control, status (✓, ✕, skipped), step number, the readable action
  (`Check text is shown "Book now"`, the keyword on hover) with its details,
  duration — so a plain step and an expandable one line up; only expandable
  rows show a chevron and the step count, and a group's children indent
  beneath it without moving its header. The self-healed lightning icon marks
  a step L2/L3 found. The failed step is the red row, with its one-line reason; the
  groups it ran in keep a red ✕ and stay open, every other group folds. Each
  group's child steps share one background, a different colour per nesting
  level (blue, violet, teal, then again), so the steps of each group read as
  one block. A
  passed step's own screenshots (a `screenshot` step, a skill's viewports) sit
  on its row; a failed step's are on its card. A step with warnings keeps its
  passed status but shows an amber ⚠ with each finding's headline under it
  (`Form labels are not associated with their inputs (2)`), the same entries
  as the test's Warnings section, and the groups on the way to it open. A skill step
  whose failure the skill judged (a control it could not press) is passed —
  the skill reports it as a check, shown on the skill's step. Passed checks
  are not listed per step; they are in `test_cases.json`
- **Diagnostics** (when there is any) — for each failed step, under the same
  `Step 3.3 · …` heading as its card: the full error and every failed check,
  how each layer attempted the step (`L1 exact: failed · L2 fuzzy: failed ·
  L3 AI: skipped: …`), the page URL and title, the Playwright trace download,
  and the console errors and failed requests logged during the step. Then the
  full test output, browser activity near the first failed step (hints, not a
  confirmed cause) and self-healed steps. *Not verified* (grey, when there are
  some) lists the checks the agent could not judge — a control it could not
  press, with the cause, a press whose result it could not explain, a time
  limit — each linked to its step; the fact strip shows their count
- **Console** / **Network** — two tabs with their counts, shown as soon as the
  drawer opens (nothing to unfold): Console is selected first, Network on its
  tab, with the same search, filter chips and sorting as the execution-level
  tabs

`✕`, `Esc` or the backdrop closes the drawer; filters are untouched. A moon
button in the header switches to dark mode (remembered per browser). The JSON
carries each failed step's `evidence` (with `diagnosis`: `verdict`, `summary`,
`signals`, `expected` — the step's postcondition in words — and `observed` —
the page at the failure; the drawer shows the two before the verdict), the
test's `expected` (the flow's `## Expected Outcome` lines), the test's `artifacts` (`screenshot`, `screenshots`, `trace`),
`retries`, `retry_error` and `retry_verdict` (the first attempt's likely cause) for tests rerun by `RERUN_FAILED`, and `checks` on
each step.

Each step record in `test_cases.json` has a stable `id` — its position path
(`"2.1.3"`: the third step of the first group in the second top-level step) —
and `parent` (the enclosing group's id, `null` at the top), `status` (`passed`, `failed`, `skipped`),
`started_at`, `duration_ms` (a skill group's own clock), `error` for a step
that did not succeed, and `evidence` when there is some. A check is `{name, passed,
severity, detail, count, outcome}`: `name` states the expected result
(`empty submission rejected`), `detail` what was observed, `outcome` one of
`passed` / `failed` / `warning` / `info` / `inconclusive` / `skipped` /
`blocked`. Each test lists its `warnings` — `{step, step_name, check, detail,
severity, also?}`, one per flagged finding that did not fail the test, `also`
holding the other steps that recorded the same one — and its `unverified`
(the inconclusive checks, same shape). `summary.json` has `totals.warnings`
(passed test cases with warnings), `totals.unverified` (test cases with
checks not verified), `status` (`passed`,
`passed_with_warnings`, `failed`, `error`, `interrupted`) and `exit_code`.
Step ids start at `1` in each test; a test that holds several sections it
could not split (steps without timings) has the sections as its top level, so
its steps read `1.1`, `2.1`…; each profile's tests have their own ids
(`…::Home Page[mobile]::s1`), and `junit.xml` names carry the profile
(`Home Page [mobile]`) when it is not desktop. Sensitive headers and fields
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
