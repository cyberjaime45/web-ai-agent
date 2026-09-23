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
  `pytest --profile …` overrides both.
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
