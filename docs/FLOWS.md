# Writing Flows

Flow files are plain Markdown. By convention they live beside the suite for
the application they exercise: `tests/<app>/flows/*.md`, with shared sub-flows
in that app's `components/` folder. The location is not enforced: pytest
collects every `.md` it traverses — everything under `tests/` on a plain
`pytest`, or any file you pass by path — no `test_*.py` needed.

For every keyword a step can use, see [ACTIONS.md](ACTIONS.md).

## File format

```markdown
# Login Flow

## Config
- timeout: 30000

## Steps
1. goto: "https://example.com/login"
2. wait_load
3. fill: "Username" | "admin"
4. fill: "Password" | "<APP_PASSWORD>"
5. click: "Sign In"
6. assert_url: "dashboard"
7. assert_text: "Welcome back"
8. screenshot: "dashboard_loaded"

## Expected Outcome
- User is redirected to the dashboard
- Page displays "Welcome back"
```

- **`# Title`** — the suite name: the console shows it, and the report groups
  the file's tests under it with the path as secondary text. Without an H1
  the file name is used.
- **`## Config`** — `timeout` (ms) sets the page's default timeout for waits
  and assertions (default 30000). `profiles: desktop, mobile` runs every
  section of the file under each listed device profile; the report shows one
  test per section and profile (`Home Page` and `Home Page[mobile]`). Without
  the line, flows run under `PROFILE` from `.env` (`desktop`), and
  `pytest --profile …` overrides both. `ignore_console: "ResizeObserver" | "third-party"`
  and `ignore_network: "/analytics/"` list substrings of console messages
  and request URLs that the automatic checks and `check_console_network`
  leave out. `allow_destructive: true` lets autonomous skills press controls
  the safety policy blocks (delete, pay, send… — only for disposable
  environments), and `allow_actions: "Send message" | "Publish"` whitelists
  named controls. `rerun: false` keeps `RERUN_FAILED` from running the file a
  second time — for flows whose steps create or submit data.
- **Every other `## section`** is a run of steps. Section names are free-form
  (`## Login`, `## Home Page`, `## Steps`); each section becomes its own test
  in the report, and a failure stops the rest of that section only — execution
  resumes at the next section.
- **`markers: smoke, regression`** — a plain line (not a list item) tagging
  tests for the report's marker filter and drawer. Before the first `##` it
  applies to every test in the file; under a `##` heading it applies to that
  test only. Markers are report metadata: they do not drive `pytest -m`.
- **`## Credentials`, `## Expected Outcome`, `## Error Scenarios`, `## Notes`**
  are metadata sections kept for humans; the runner does not execute them.
  Put real secrets in `.env` and reference them with `<NAME>` placeholders,
  never in the flow file.

## Reusable sub-flows

A component flow is an ordinary flow file under `components/`:

`tests/fms/flows/components/sso_login.md`

```markdown
# SSO Login Page

## Login
- goto: "https://one.wheelsup.com/"
- fill: "input[type='email']" | "<FMS_EMAIL>"
- click: "Next"
- fill: "Password" | "<FMS_PASSWORD>"
- click: "Sign in"
```

A parent flow calls it with `run_flow`, resolved relative to the parent's directory:

`tests/fms/flows/production_smoke.md`

```markdown
# FMS Smoke

## Login Page
- run_flow: "components/sso_login"
- wait_load

## Home Page
- goto: "https://one.wheelsup.com/home"
- assert_text: "My Tasks"
```

The sub-flow runs on the same browser page, its steps appear nested under the
parent step in the report, and nesting may go ten levels deep.

## Complete examples

### E-commerce checkout

```markdown
# Checkout Flow

## Config
- timeout: 30000

## Steps
1. goto: "https://shop.example.com"
2. wait_load
3. click: "Products"
4. wait_for_text: "All Products"
5. click: "Add to Cart"
6. hover: "Cart Icon"
7. click: "View Cart"
8. assert_text: "Your Cart"
9. assert_url: "/cart"
10. fill: "Promo Code" | "SAVE20"
11. click: "Apply"
12. assert_text: "Discount applied"
13. click: "Checkout"
14. fill: "Email" | "buyer@example.com"
15. fill: "Full Name" | "Jane Smith"
16. select: "Country" | "United States"
17. check: "I agree to the Terms"
18. screenshot: "before_payment"
19. click: "Place Order"
20. wait_for_url: "/confirmation"
21. assert_text: "Order placed successfully"
22. screenshot: "order_confirmed"
```

### Form with custom selectors

```markdown
# Contact Form

## Config
- timeout: 15000

## Steps
1. goto: "https://example.com/contact"
2. wait_load
3. fill: "First Name" | "John"
4. fill: "Last Name" | "Doe"
5. fill: "Email" | "john@example.com"
6. fill: ".textarea-box" | "I have a question about your services."
7. select: "Department" | "Sales"
8. check: "YES"
9. click: ".dropdown-field"
10. click: "Personal"
11. screenshot: "form_filled"
12. click: "Submit"
13. wait_for_text: "Thank you"
14. assert_text: "We will get back to you"
```

### Table verification

```markdown
# User Management

## Config
- timeout: 20000

## Steps
1. goto: "https://admin.example.com/users"
2. wait_load
3. assert_text: "User Management"
4. find_row: "john@example.com"
5. read_row: "john@example.com"
6. table_click: "john@example.com" | "Edit"
7. wait_for_text: "Edit User"
8. fill: "Display Name" | "John Updated"
9. click: "Save Changes"
10. wait_for_text: "User updated"
11. count_elements: "tr.user-row"
12. screenshot: "users_updated"
```

## Running a single flow

```bash
uv run pytest tests/fms/flows/production_smoke.md      # by path
uv run pytest --flow_file=path/to/any_flow.md           # any .md, even outside the repo
uv run pytest --flow "# Smoke
## Steps
1. goto: \"https://example.com\"
2. assert_text: \"Example Domain\"
"                                                        # inline Markdown
```

`--flow` and `--flow_file` are mutually exclusive. For a single flow driven
from a script or another agent, prefer the CLI — see [CLI.md](CLI.md).

## Desktop and mobile profiles

A profile only changes how the browser context is created; the flow and every
step stay the same.

| Profile | Context |
|---------|---------|
| `desktop` | The session's own viewport (`VIEWPORT`, or the maximized window in headed Chromium) |
| `mobile` | Playwright's device descriptor named by `MOBILE_DEVICE` (default `iPhone 13`: 390×664, touch, mobile user agent) |

```bash
uv run pytest --profile mobile                          # every collected flow, on a phone
uv run pytest --profile desktop,mobile                  # both — one test per section and profile
uv run pytest tests/members_site/flows/booking_flow.md --profile mobile
```

Which profiles a flow runs under is decided in this order: `--profile`, then
the flow's `## Config` `profiles:` line, then `PROFILE` in `.env`. Under
`RUNNING_MODE=lambda` the mobile profile emulates the device inside the grid
browser; it does not pick a real device.

## Automatic checks and QA skills

After every navigation-class step (`goto`, `click`, `select`, `press`…) the
runner records a few checks without an assertion in the flow: page rendered,
no page errors, no console errors, no failed or 401/403/4xx requests, no
stuck spinner, no blocking dialog, no horizontal overflow. They appear as a
collapsed row under the step. `ORACLE=warn` (default) only records them;
`ORACLE=strict` fails the step on an error-severity check; `ORACLE=off`
disables them.

QA skills go further and can replace a page of hand-written assertions:

```markdown
# Members

## Config
- profiles: desktop, mobile
- ignore_console: "ResizeObserver loop"

## Overview
- goto: "<APP_URL>/members"
- inspect_page
- check_console_network
- check_accessibility
- check_links

## Table and search
- goto: "<APP_URL>/members"
- test_table
- test_search

## Add member form
- click: "Add Member"
- test_form: "submit=false"

## Layout
- goto: "<APP_URL>/members"
- test_responsive
- test_widgets

## Regression
- goto: "<APP_URL>/members"
- wait_load: "load"
- snapshot_page: "members"
- check_performance

## Explore
- goto: "<APP_URL>/members"
- explore_page: "depth=2" | "max_actions=20"

## Autonomous
- goto: "<APP_URL>/members"
- test_page: "depth=1" | "max_actions=12"
```

Each skill is a group in the report: its checks on the group row, the
`fill` / `click` steps it ran nested underneath. `explore_page` presses every
safe control once and records a page/action graph; it never presses anything
the safety policy blocks. `test_page` classifies the page, runs the skills
that fit it, and writes what it did as a plain flow under
`reports/<ENVIRONMENT>/generated/` for review — the intended lifecycle is:
the agent explores once, QA reviews the generated Markdown, and from then on
it runs deterministically. See [ACTIONS.md → QA skills](ACTIONS.md#qa-skills-13)
for what each one checks and its options.

## What a failed step leaves behind

No `screenshot` step is needed for failures. When a step fails, the runner
collects evidence on the spot and the report shows it under that step:

- viewport, full-page and (when the element can still be located) element
  screenshots — `images/<flow>__<profile>__<n>__viewport.png`, `…__full.png`, `…__element.png`
- the page URL and title, and the profile (`mobile · iPhone 13 · chromium · 390x664`)
- what each layer did — `L1 exact failed · L2 fuzzy failed · L3 AI skipped: provider not configured`
- the console errors and failed requests that happened during the step
- a Playwright trace of the whole flow, `traces/<flow>__<profile>.zip`
  (`TRACE=on-failure`, the default; open it with `npx playwright show-trace <file>`)
- a **likely cause**: `application` (a 5xx or failed request, a JavaScript
  error, a blank page or a stuck loading indicator during the step or earlier
  in its section), `test` (the target was covered, ambiguous or disabled, or a
  control with a very similar name is on the page — the text changed),
  `environment` (network or browser errors, an unset `<PLACEHOLDER>`, a
  sign-in page or a 401/403 — the session is gone) or `unclassified`, with the
  signals behind it. It is a hint for triage, not a result; no LLM is involved

### Flaky or consistent? — `RERUN_FAILED`

With `RERUN_FAILED=true` (pytest runs), a flow with a failed section runs once
more, whole, in a fresh browser context — sections often depend on earlier
ones, such as a login section. Each section then keeps one outcome:

| First run | Rerun | Report |
|-----------|-------|--------|
| passed | — | the first run (a rerun never turns a pass into a failure) |
| failed | passed | **Passed on retry**: the rerun's steps, with the first attempt's error |
| failed | failed | **Failed**, with 1 rerun: a consistent failure |

A flow whose sections all passed on retry passes the pytest run; the console
summary counts them under `Passed on retry`. The rerun's screenshots and trace
carry a `__retry` suffix. A flow opts out with `rerun: false` in `## Config`.
