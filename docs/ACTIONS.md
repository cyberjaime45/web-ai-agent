# Supported Actions — Full Reference

Every keyword a flow step can use, grouped by purpose. 52 keywords in total (45 actions + 7 QA skills).
For the file format around the steps, see [FLOWS.md](FLOWS.md).

## Step syntax

```
keyword: "arg1" | "arg2"
```

- The keyword is followed by `:` and one or more quoted arguments separated by `|`.
- Actions with no arguments omit the colon: `wait_load`, `reload`, `back`.
- Arguments that are bare values (e.g. milliseconds for `wait`) can omit quotes: `wait: 2000`.
- Steps may be numbered (`1.`) or bulleted (`-`); numbering is not significant.

## CSS selector & XPath support

Any action that targets an element can accept a **CSS selector** or **XPath expression** instead of a label or text.

**CSS selectors** are detected when the argument starts with `.`, `#`, `[`, or is a tag-prefixed selector (e.g. `div[...]`, `input.class`):

```markdown
1. fill: ".textarea-box" | "Some text"
2. click: "#submit-btn"
3. check: "[name='agree']"
4. wait_for_element: ".loading-spinner"
5. click: "div[class='listinputselect'] input[value='YES']"
6. fill: "textarea.comment-box" | "Hello world"
7. check: "input[name='haveyoupreviouslypurchased'][value='YES']"
```

**XPath expressions** are detected when the argument starts with `//` or `/`:

```markdown
1. click: "//button[@id='submit']"
2. click: "//div[@class='listinputselect']//input[@value='YES']"
3. fill: "//input[@name='email']" | "user@example.com"
4. check: "//input[@type='radio' and @value='YES']"
5. assert_visible: "//span[text()='Success']"
```

## Environment placeholders

Any argument written as `<NAME>` (uppercase, underscores) is replaced with the
value of that environment variable at run time — `fill: "Password" | "<FMS_PASSWORD>"`.
Names containing `PASSWORD`, `SECRET`, `KEY` or `TOKEN` are masked as `******`
in the console and the report. An unset variable fails the step with a message
naming it.

---

## Navigation (6)

#### `goto`
Navigate to a URL.

```markdown
1. goto: "https://example.com"
2. goto: "https://app.example.com/dashboard?tab=overview"
```

#### `reload`
Reload the current page.

```markdown
1. reload
```

#### `back`
Go back to the previous page in browser history.

```markdown
1. back
```

#### `wait_load`
Wait for the page to reach a load state. Defaults to `domcontentloaded`; accepts `domcontentloaded`, `load`, or `networkidle`.

```markdown
1. wait_load
2. wait_load: "networkidle"
3. wait_load: "load"
```

#### `switch_tab`
Switch to a different browser tab by index (0-based).

```markdown
1. switch_tab: "0"
2. switch_tab: "1"
```

#### `scroll`
Scroll the page. Accepts a direction (`up`, `down`, `top`, `bottom`), a pixel amount, text to scroll into view, or a CSS selector / XPath.

```markdown
1. scroll: "down"
2. scroll: "top"
3. scroll: "500"
4. scroll: "Contact Us"
5. scroll: "#footer"
6. scroll: "//div[@id='section-3']"
```

---

## Click (5)

#### `click`
Click a button or link by its visible text, or an element by CSS selector / XPath. Tries `role="button"` first, then `role="link"`, then exact text.

```markdown
1. click: "Sign In"
2. click: "Accept All Cookies"
3. click: "#submit-btn"
4. click: ".close-modal"
5. click: "div[class='listinputselect'] input[value='YES']"
6. click: "//button[@id='submit']"
```

#### `click_link_text`
Click a link by its exact text.

```markdown
1. click_link_text: "Privacy Policy"
2. click_link_text: "View All Products"
```

#### `double_click`
Double-click an element by text or CSS selector / XPath.

```markdown
1. double_click: "Edit Cell"
2. double_click: "file_report.pdf"
3. double_click: ".editable-cell"
4. double_click: "//td[@class='editable']"
```

#### `right_click`
Right-click an element to open a context menu. Accepts text or CSS selector / XPath.

```markdown
1. right_click: "Document Title"
2. right_click: "Row Item"
3. right_click: "#context-target"
4. right_click: "//div[@class='file-item']"
```

#### `hover`
Hover over an element to trigger tooltips, dropdowns, or other hover effects. Accepts text or CSS selector / XPath.

```markdown
1. hover: "User Profile"
2. hover: "Products"
3. hover: ".dropdown-trigger"
4. hover: "//div[@class='tooltip-target']"
```

---

## Input (7)

#### `fill`
Set an input field's value atomically via Playwright's `.fill()`. Resolves the input by label, placeholder, CSS selector, or XPath.

```markdown
1. fill: "Email" | "user@example.com"
2. fill: "Search" | "web agent"
3. fill: ".textarea-box" | "This is a message"
4. fill: "#phone-input" | "+1 555-0100"
5. fill: "input[name='email']" | "user@example.com"
6. fill: "//input[@name='email']" | "user@example.com"
```

#### `type`
Type text character-by-character via `.press_sequentially()`. Use this for autocomplete fields, masked inputs, or when keystroke events matter. Accepts label, placeholder, CSS selector, or XPath.

```markdown
1. type: "Address" | "123 Main Street"
2. type: "#search-input" | "New York"
3. type: "//input[@id='autocomplete']" | "San Francisco"
```

#### `clear`
Clear an input field's value. Accepts label, placeholder, CSS selector, or XPath.

```markdown
1. clear: "Email"
2. clear: ".search-field"
3. clear: "//input[@name='query']"
```

#### `focus`
Move focus to an input field without changing its value. Accepts label, placeholder, CSS selector, or XPath.

```markdown
1. focus: "Username"
2. focus: "#otp-field"
3. focus: "//input[@name='code']"
```

#### `select`
Select an option from a `<select>` dropdown by label and option text. Accepts label, CSS selector, or XPath for the dropdown.

```markdown
1. select: "Country" | "United States"
2. select: "#billing-state" | "California"
3. select: "//select[@name='country']" | "Canada"
```

#### `check`
Check a checkbox or radio button. Resolves by label text, `role="radio"`, `role="checkbox"`, CSS selector, or XPath.

```markdown
1. check: "I agree to the Terms"
2. check: "YES"
3. check: "[name='newsletter']"
4. check: "input[name='haveyoupreviouslypurchased'][value='YES']"
5. check: "div[class='ng-star-inserted'] span.square"
6. check: "//input[@type='radio' and @value='YES']"
```

#### `uncheck`
Uncheck a checkbox. Accepts label, CSS selector, or XPath.

```markdown
1. uncheck: "Subscribe to updates"
2. uncheck: "#marketing-opt-in"
3. uncheck: "//input[@name='newsletter']"
```

---

## Advanced interaction (2)

#### `drag_to`
Drag one element to another. Each argument accepts text, CSS selector, or XPath.

```markdown
1. drag_to: "Task Card" | "Done Column"
2. drag_to: "Item A" | "Drop Zone"
3. drag_to: "#draggable" | "#drop-zone"
4. drag_to: "//div[@class='card']" | "//div[@class='column-done']"
```

#### `upload`
Upload a file to a file input. First argument is the CSS selector or XPath for the file input, second is the file path.

```markdown
1. upload: "input[type=file]" | "/path/to/document.pdf"
2. upload: "#avatar-upload" | "./images/profile.jpg"
3. upload: "//input[@type='file']" | "./report.pdf"
```

---

## Table & data (5)

#### `read_row`
Find a table row containing the given text and read all cell values. The cell contents are logged in the step result.

```markdown
1. read_row: "John Doe"
2. read_row: "INV-2024-001"
```

#### `table_click`
Click within a table row. With one argument, clicks the row itself. With two arguments, clicks a specific cell or element within the row.

```markdown
1. table_click: "John Doe"
2. table_click: "Order #1234" | "View Details"
```

#### `find_row`
Assert that a table row containing the given text exists. Fails if no matching row is found.

```markdown
1. find_row: "Active Subscription"
2. find_row: "admin@example.com"
```

#### `count_elements`
Count the number of elements matching a CSS selector. The count is logged in the step result.

```markdown
1. count_elements: ".product-card"
2. count_elements: "tr.data-row"
```

#### `get_attribute`
Get an attribute value from the first element matching a CSS selector.

```markdown
1. get_attribute: "#hero-image" | "src"
2. get_attribute: ".download-link" | "href"
```

---

## Assertions (8)

#### `assert_text`
Assert that specific text is visible on the page. Waits up to 5 seconds.

```markdown
1. assert_text: "Welcome back, Admin"
2. assert_text: "Order placed successfully"
```

#### `assert_not_text`
Assert that specific text is NOT visible or present on the page.

```markdown
1. assert_not_text: "Error"
2. assert_not_text: "Access Denied"
```

#### `assert_visible`
Assert that an element with the given text, CSS selector, or XPath is visible on the page.

```markdown
1. assert_visible: "Submit Button"
2. assert_visible: ".success-banner"
3. assert_visible: "//span[text()='Success']"
```

#### `assert_hidden`
Assert that an element is hidden or does not exist. Accepts text, CSS selector, or XPath.

```markdown
1. assert_hidden: "Loading Spinner"
2. assert_hidden: ".error-modal"
3. assert_hidden: "//div[@class='loading']"
```

#### `assert_url`
Assert that the current URL contains a specific fragment (case-insensitive).

```markdown
1. assert_url: "/dashboard"
2. assert_url: "checkout/confirmation"
3. assert_url: "tab=settings"
```

#### `assert_enabled`
Assert that a button or input is enabled (not disabled). Accepts text, CSS selector, or XPath.

```markdown
1. assert_enabled: "Submit"
2. assert_enabled: "#submit-btn"
3. assert_enabled: "//button[@type='submit']"
```

#### `assert_disabled`
Assert that a button or input is disabled. Accepts text, CSS selector, or XPath.

```markdown
1. assert_disabled: "Delete Account"
2. assert_disabled: "#delete-btn"
3. assert_disabled: "//button[@id='next']"
```

#### `assert_checked`
Assert that a checkbox or radio button is checked. Accepts label, CSS selector, or XPath.

```markdown
1. assert_checked: "I agree to the Terms"
2. assert_checked: "#terms-checkbox"
3. assert_checked: "//input[@name='agree']"
```

---

## Waits (5)

#### `wait`
Pause execution for a given number of milliseconds. Defaults to 1000ms if no argument is provided.

```markdown
1. wait
2. wait: 2000
```

#### `wait_for_element`
Wait for a specific element (by CSS selector or XPath) to become visible. Times out after 10 seconds.

```markdown
1. wait_for_element: ".results-container"
2. wait_for_element: "//div[@class='loaded']"
```

#### `wait_for_text`
Wait for specific text to appear on the page. Times out after 10 seconds.

```markdown
1. wait_for_text: "Results loaded"
2. wait_for_text: "Payment confirmed"
```

#### `wait_for_url`
Wait for the URL to contain a specific fragment. Times out after 10 seconds.

```markdown
1. wait_for_url: "/success"
2. wait_for_url: "order-complete"
```

#### `wait_stable`
Wait until the page has settled after a click or navigation: no page, XHR or
fetch request in flight, no visible loading indicator (spinner, `aria-busy`,
progress bar), and no DOM change for 300 ms. The optional argument is the
budget in milliseconds (default 10000). It never fails the step: a page still
busy when the budget runs out passes with a `page settled` warning naming what
was still going on. Requests matching `ignore_network` in `## Config`, and
requests open longer than 15 s (polling, streaming), never block it. Under the
CLI there is no network recorder, so only the indicators and the DOM are
watched. Prefer it to a fixed `wait: <ms>`.

```markdown
1. click: "Search"
2. wait_stable
3. assert_text: "3 members found"
4. wait_stable: 20000
```

Page load states are covered by [`wait_load`](#wait_load) under Navigation.

---

## AI-native actions (4)

These actions bypass Layer 1 and Layer 2 entirely and go directly to Layer 3. They require `AI_PROVIDER`, `LLM_KEY`, and `LLM_MODEL` to be set (see the configuration table in the [README](../README.md#configuration)).

#### `ai_click`
Describe the element to click in natural language. The LLM analyzes the page and resolves the element.

```markdown
1. ai_click: "the small red X button in the top right corner"
2. ai_click: "the third product's Add to Cart button"
```

#### `ai_extract`
Ask a question about the page content. The LLM extracts and returns the answer in the step result.

```markdown
1. ai_extract: "What is the total balance shown?"
2. ai_extract: "How many items are in the cart?"
```

#### `ai_assert`
Make a natural-language assertion about the page state. The LLM evaluates whether it's true or false.

```markdown
1. ai_assert: "the user is currently logged in"
2. ai_assert: "the shopping cart contains at least 2 items"
```

#### `ai_summarize`
Generate a 2-4 sentence summary of the current page content.

```markdown
1. ai_summarize
```

---

## Utilities (2)

#### `screenshot`
Capture a screenshot of the current page. Optionally provide a name. Saved to `reports/<env>/images/`.

```markdown
1. screenshot
2. screenshot: "after_login"
```

#### `press`
Press a keyboard key. Accepts any Playwright key name.

```markdown
1. press: "Enter"
2. press: "Tab"
3. press: "Escape"
4. press: "ArrowDown"
```

---

## Flow composition (1)

#### `run_flow`
Execute another flow file inline. Enables reuse of common sequences (e.g., login) across multiple test flows. The sub-flow runs on the **same browser session** — no new page or context is created.

```markdown
1. run_flow: "components/sso_login"
```

**Path resolution** — references are resolved relative to the directory of the flow file
that contains the `run_flow` step. Shared sub-flows go in that app's `components/` folder:

| Reference (from `tests/fms/flows/production_smoke.md`) | Resolves to |
|-----------|-------------|
| `"sso_login"` | `tests/fms/flows/sso_login.md` |
| `"components/sso_login"` | `tests/fms/flows/components/sso_login.md` |
| `"components/sso_login.md"` | `tests/fms/flows/components/sso_login.md` |

**Report display** — nested steps are prefixed with `↳ [flow_name]`:

```
✓ Step  1 [L0]  run_flow: "components/sso_login"
✓ Step  1 [L1]  ↳ [SSO Login Page]  goto: "https://one-staging..."     (1.2s)
✓ Step  2 [L1]  ↳ [SSO Login Page]  wait_for_text: "Sign in"           (0.3s)
...
✓ Step  2 [L1]  assert_text: "This is my Dashboard"                    (0.2s)
```

**Limitations:**
- Max nesting depth: 10 levels
- Circular references are detected and reported as errors
- Sub-flows can call other sub-flows (nested `run_flow` supported)

See [FLOWS.md](FLOWS.md#reusable-sub-flows) for a worked login example.

---

## QA skills (7)

Skills are higher-level checks that orchestrate ordinary actions. The engine
runs one as a group: a marker step carrying the skill's **checks** (each
passed / failed with a severity), followed by the child steps it executed —
every `fill`, `click` or `select` a skill performs goes through the same
L1 → L2 → L3 path as a hand-written step and shows up nested under it in the
report. A skill step fails when a child step failed or an `error`-severity
check did not pass; `warn` checks never fail it. Options are `key=value`
arguments.

None of them needs an LLM; `explore_page` and `test_page` can use one
within a call budget.

#### `inspect_page`
Describe what is on the page: type (`LOGIN`, `FORM`, `TABLE`, `LIST`,
`CONTENT`), headings, buttons, links, inputs, forms with their fields,
tables, dialogs, navigation. Every finding is an info check; the compact
observation is kept in the run context for later skills.

```markdown
1. goto: "https://example.com/members"
2. inspect_page
```

#### `check_console_network`
JavaScript page errors, console errors, failed requests and 4xx/5xx
responses recorded since the previous `check_console_network` step (or the
start of the flow). Page errors, 5xx, aborted requests and 401/403 fail the
step; console errors and other 4xx are warnings. `console=strict` makes
console errors fail it too. Noise is excluded with `ignore_console` /
`ignore_network` in `## Config`.

```markdown
1. goto: "https://example.com/dashboard"
2. wait_load
3. check_console_network
4. check_console_network: "console=strict"
```

#### `test_responsive`
Layout checks at several viewport widths — the current one plus `390x664`
and `768x1024` by default, or `viewports=…`. Per viewport: no horizontal
overflow, controls on screen, form fields fit, dialog fits; on narrow widths
also tap targets ≥ 24px and text ≥ 12px (warnings). When a navigation
landmark hides its links on a narrow width, the menu toggle is clicked to
check the mobile menu opens. A screenshot per viewport is kept on the step
and the original viewport is restored.

```markdown
1. goto: "https://example.com/members"
2. test_responsive
3. test_responsive: "viewports=390x664,1024x768"
```

Viewport switching is layout-only. For real device emulation (user agent,
touch) run the flow under the `mobile` profile — see [FLOWS.md](FLOWS.md).

#### `test_form`
Inspect the first visible form (or `form=<name>`) and run the usual
validation checks: empty submission rejected, invalid email rejected, value
shorter than `minlength` rejected, valid sample input accepted. By default
the valid input is **not** submitted; `submit=true` submits it and checks
the outcome (no error messages, no failed requests). A submit button whose
name looks destructive (pay, send, delete…) is never pressed.

```markdown
1. goto: "https://example.com/contact"
2. test_form
3. test_form: "form=Newsletter" | "submit=true"
```

#### `explore_page`
Bounded, safe exploration from the current page. Every control the observer
reports — links on the same site, buttons, tabs, menu items — is pressed once
as a `click` child step and the outcome recorded: navigates to a page (queued
for the next depth), opens a dialog (closed with Escape), changes the page in
place, or nothing observable. The result is a page/action graph on the step,
plus checks: `no broken pages` (4xx/5xx documents, failed render), `controls
respond`, `controls pressable`, the controls skipped by the safety policy and
the external links found.

```markdown
1. goto: "<APP_URL>/members"
2. explore_page
3. explore_page: "depth=2" | "max_actions=20" | "max_pages=8" | "max_ai_calls=3"
```

| Option | Default | Meaning |
|--------|---------|---------|
| `depth` | `2` | Link hops from the start page |
| `max_actions` | `20` | Clicks in total |
| `max_pages` | `8` | Distinct pages visited |
| `max_ai_calls` | `3` | Planner calls when an LLM provider is configured; `0` keeps it deterministic |
| `destructive` | `false` | `true` presses controls the safety policy would block — only with `allow_destructive` in `## Config` or `ALLOW_DESTRUCTIVE=true` |

Without a provider the order is deterministic (navigation, tabs, buttons,
links). With one, the planner only *orders* the observed controls; it can
never add a target the observer did not see, and the safety policy is applied
to every plan step. Controls whose name carries a destructive verb (delete,
remove, pay, send, publish, cancel…), neutral confirm buttons inside a
destructive or payment dialog / form, and confirm buttons on delete /
checkout / unsubscribe pages are never pressed unless configuration allows it.

#### `test_page`
The autonomous page test: give it a page and it decides what to check.
Observe → classify (`LOGIN`, `FORM`, `WIZARD`, `SETTINGS`, `TABLE`, `LIST`,
`SEARCH`, `DASHBOARD`, `DETAIL`, `CONTENT`) → plan by type → run the other
skills and ordinary actions → judge → write a deterministic Markdown flow of
what ran under `reports/<ENVIRONMENT>/generated/`.

```markdown
1. goto: "<APP_URL>/members"
2. test_page
3. test_page: "depth=1" | "max_actions=12" | "max_ai_calls=3" | "submit=false"
```

| Page type | What runs (besides `check_console_network` and `test_responsive`) |
|-----------|--------------------------------------------------------------------|
| `LOGIN` | `test_form` without submitting; password field masked; no sign-in attempted |
| `FORM`, `WIZARD` | `test_form` (`submit=true` only when passed through) |
| `TABLE`, `LIST`, `SEARCH`, `DASHBOARD`, `DETAIL`, `CONTENT` | search field exercised, pagination pressed once, then `explore_page` within `depth` / `max_actions` |
| `SETTINGS` | nothing that changes data: toggles and save buttons are left alone |

With an LLM provider, `max_ai_calls` bounds two uses: a classification
tie-break when the deterministic type is `CONTENT` or `UNKNOWN`, and an
adaptive plan of a few extra steps — each validated against the observation
and the safety policy before it runs; rejected steps are listed in the report.
Without a provider everything above still runs.

The report's **Agent** panel shows the page type, discovered components, the
plan, actions executed, controls skipped by safety, AI calls and a link to
the generated flow. Run one page without writing a flow:

```bash
uv run pytest --agent-test https://example.com/members            # with the HTML report
uv run python main.py agent-test https://example.com/members      # CLI, --depth / --max-actions / --profile
```

The generated flow replays the actions that ran (`fill`, `click`, `select`,
`press`, `back`…) with an `assert_url` after each navigation; the steps
`test_responsive` performed at other viewports are left out.

`profiles=` is not a `test_page` option: list profiles under `## Config` (or
pass `--profile`) to run the whole flow on desktop and mobile.

#### `check_links`
Request every link on the page and report the broken ones, without clicking
anything. Links are collected from `a[href]` (fragments ignored, duplicates
removed) and requested through the browser context, so they carry the page's
cookies: `HEAD` first, `GET` when `HEAD` is refused. Visible images that
failed to load are reported too.

```markdown
1. goto: "<APP_URL>/members"
2. check_links
3. check_links: "external=true" | "max_links=100"
4. check_links: "images=false"
```

| Result | Severity |
|--------|----------|
| 404 / 410, 5xx, unreachable | `no broken links` — error |
| 401 / 403 / 429, other 4xx, redirect to a login page | `no restricted links` — warning |
| Image that failed to load | `no broken images` — error |

| Option | Default | Meaning |
|--------|---------|---------|
| `external` | `false` | Also check links to other sites |
| `max_links` | `50` | Links requested at most; the rest are counted in `links checked` |
| `images` | `true` | Check images too |

Logout links, and links whose path looks destructive (delete, unsubscribe,
checkout…), are never requested unless the flow allows destructive actions;
they are listed under `links not requested`. The requests are not part of
the report's network log.
