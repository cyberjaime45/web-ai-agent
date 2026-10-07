# Supported Actions — Full Reference

Every keyword a flow step can use, grouped by purpose. 58 keywords in total (45 actions + 13 QA skills).
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

A `{NAME}` placeholder (uppercase, digits, underscores) anywhere in any
argument is replaced with the value of that environment variable (`.env` or CI
variables) before the step runs; the rest of the argument is kept as written:

```markdown
- goto: "{FMS_URL}/calendar/scheduleboard/"
- goto: "{FMS_URL}/operations?tab=dashboard"
- fill: "Password" | "{FMS_PASSWORD}"
```

When the value ends in `/` and the text after the placeholder starts with one,
the doubled slash is dropped, so `FMS_URL` may be set with or without a
trailing `/`. Resolution is deterministic — no LLM is involved.
Names containing `PASSWORD`, `SECRET`, `KEY` or `TOKEN` are masked as `******`
in the console and the report. A variable that is unset or empty fails the step
before it runs — nothing is navigated or typed — with a message naming the
variable, the step number and its section. The older `<NAME>` spelling is
still read the same way; new flows use `{NAME}`.

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
Assert that specific text is visible on the page (case-insensitive, part of an
element's text is enough). Waits up to 5 seconds for a **visible** match: copies
of the text in hidden elements — a collapsed mobile menu, a closed dialog — are
ignored, and so is text that exists only in the page source.

```markdown
1. assert_text: "Welcome back, Admin"
2. assert_text: "Order placed successfully"
```

#### `assert_not_text`
Assert that specific text is not visible on the page. Hidden copies do not count.

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
Assert that no visible element matches — every match is hidden, or none exists.
Accepts text, CSS selector, or XPath.

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
requests open longer than 15 s (polling, streaming), never block it. Prefer it to a fixed `wait: <ms>`.

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
Capture the visible part of the page (the viewport). Optionally provide a name.
Add the option `"full_page"` to capture the whole scrollable page instead.
Saved to `reports/<env>/images/` and shown on the step in the report.

```markdown
1. screenshot                               # the viewport, named after the step
2. screenshot: "after_login"                # the viewport, named
3. screenshot: "results" | "full_page"      # the whole page, named
4. screenshot: "full_page"                  # the whole page, named after the step
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

## QA skills (13)

Skills are higher-level checks that orchestrate ordinary actions. The engine
runs one as a group: a marker step carrying the skill's **checks**, followed
by the child steps it executed — every `fill`, `click` or `select` a skill
performs goes through the same L1 → L2 → L3 path as a hand-written step and
shows up nested under it in the report. Options are `key=value` arguments.

None of them needs an LLM; `explore_page` and `test_page` can use one
within a call budget.

**Check outcomes.** Each check has one:

| Outcome | Severity | Meaning |
|---------|----------|---------|
| passed | `error` / `warn` | Verified |
| failed | `error` | A required behaviour or explicit expectation failed, with the expected result, what happened and the evidence |
| warning | `warn` | A confirmed issue that degrades the experience or accessibility while the flow stays usable, with the affected element |
| info | `info` | An observation, never judged — not in the warning totals |
| inconclusive | `inconclusive` | The agent could not judge: it could not press, type into or read something, a press had no result it could explain, or a time limit stopped it. Coverage, not a defect: listed under *Not verified* in the report, never as a warning |
| skipped | `skipped` | Not done, with the reason: nothing to exercise on the page, or a limit reached |
| blocked | `blocked` | The safety policy withheld an action (the `blocked by safety` check lists each one with its reason) |

Severity and confidence stay separate: a finding the agent cannot confirm is
`inconclusive`, not a weaker warning. The same finding on several viewports
is one check naming each viewport; on several steps it is one report entry
linking each step.

A skill that finds nothing to test (no table for `test_table`) reports that
check as skipped — unless the flow named the target (`form=`, `table=`,
`search=`, `dialog=`), which makes a missing target a failure. An option that
is not a non-negative number is an `options valid` failure; the default is used.

**Child steps.** Each child step is one of three kinds:

| Kind | Examples | A failure… |
|------|----------|------------|
| action | none of the built-in skills need one today | fails the skill — it needed the step to work |
| probe | a tab, sort header or submit button pressed to see what happens; a field filled; an AI-planned step | is the skill's finding: it becomes a check (usually a warning, "could not press …"); the step itself counts as passed (its message is kept) and never stops the section |
| cleanup | `back`, Escape, the return `goto`, putting a tab or viewport back | adds one `page restored after the skill` warning |

**Skill result.** A skill step *fails* when it crashed, an `error` check
failed, an action child failed, or a skill it started failed. Otherwise it
*passes* — *with warnings* when a `warn` check, a probe or a cleanup failed.
A failed skill fails the section like any failed step (the rest of the
section is skipped, the next section runs); warnings never do.

**Run result.** Test cases are sections (see [REPORTS.md](REPORTS.md)); the
steps a skill ran are steps inside them, never extra test cases. A test case
passes with warnings when any check in it was flagged but nothing failed. The
run is *failed* when any test case failed (exit code 1), *passed with
warnings* or *passed* otherwise (exit 0), and *interrupted* (exit 2) when it
stopped before every flow finished.

**Limits.** Every skill has a time budget, `timeout` (seconds, default
300), and a press budget, `max_actions` (clicks, key presses, ticks and
selections; unlimited unless given, `20` for `explore_page` and `test_page`).
A skill started by another skill — including the AI-planned steps of
`test_page` — spends from the caller's budget too, so the caller's limit
bounds everything under it. When a budget runs out the skill stops, keeps the
checks it made and adds `finished within limits`: skipped for `max_actions`,
a warning for `timeout`. Cleanup is always allowed.

**Safety.** Every click a skill makes — chosen by the skill or planned by a
model — passes the [safety policy](#explore_page) first; a refused click is
not run and appears under `blocked by safety`. A model never passes options
to a skill it plans (`test_form` always runs without `submit=true`).

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
responses of the site under test (prefetches and other sites are never
recorded — see [REPORTS.md](REPORTS.md)) since the previous `check_console_network` step (or the
start of the flow). A request is judged by what it was for:

| Finding | Here | Automatic checks after a step |
|---------|------|-------------------------------|
| JavaScript page error | failed | failed |
| page, script or stylesheet that failed; API call with 5xx or no connection (`no failed requests`) | failed | failed |
| console error from the site's own scripts | warning | info |
| API 401 / 403 (`no 401/403 responses`) — often "not signed in" | warning | info |
| other API 4xx (`no 4xx responses`) — often an expected "not found" | warning | info |
| image, font or media that failed (`no failed resources`) | warning | info |
| console error from another site's script | info | info |
| cancelled request (`net::ERR_ABORTED` — beacons, requests cut off by leaving the page) | info | info |

Here the flow asked for the check, so the lesser rows are warnings; after
every other step a log level or a status code alone is no demonstrated
impact, so they are information, and rows that found nothing are left out.
`console=strict` makes console errors fail it. Noise is excluded with
`ignore_console` / `ignore_network` in `## Config`.

```markdown
1. goto: "https://example.com/dashboard"
2. wait_load
3. check_console_network
4. check_console_network: "console=strict"
```

#### `test_responsive`
Layout checks at several viewport widths — the current one plus `390x664`
and `768x1024` by default, or `viewports=…`. Per viewport: no horizontal
overflow (the page scrolls sideways; content the viewport clips with
`overflow-x: hidden` / `clip` does not count), controls on screen, form fields
fit, dialog fits. Controls inside an off-canvas panel or carousel, and skip
links, are not "off screen". On narrow widths also tap targets ≥ 24px and
text ≥ 12px (warnings). Tap targets follow WCAG 2.5.8: the area includes the
control's content, and a smaller target passes when it sits inline in a
sentence or has 24px of room around it; a finding lists each target with its
size (`"Help" 16×16`).

The mobile menu is checked only where navigation is expected: a navigation
landmark with links to other pages that a wide viewport shows and a narrow
one hides. A sign-in page whose navigation holds only a phone number is not
checked. The toggle — a button, anything with `aria-expanded` /
`aria-controls`, or an element named or classed like a menu — is clicked to
check the menu opens (a failure when it does not). A toggle that is not a
button (a `div` with no role) is a `menu toggle is a button` warning:
keyboard and screen-reader users cannot open the menu. A toggle the agent
could not press is inconclusive. The same result at several widths is one
check (`[440x763, 390x664] tap targets ≥ 24px`). A screenshot per viewport
is kept on the step and the original viewport is restored — failing to
restore it is an inconclusive `page restored after the skill`.

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
the outcome (no error messages, no failed requests).

*Rejected* means the browser or the app flagged a field (`:invalid`,
`aria-invalid`) or showed a message. The form staying on the page with no
such signal is a warning (the skill cannot tell); the form going away means
bad input was accepted — a failure. The invalid-email and too-short checks
submit only when that cannot save anything: the browser flags the bad value
itself, or the empty submission already showed validation. Otherwise they are
skipped. A field that cannot be filled skips the check that needed it (a
warning for the valid-input check). The submit button passes the safety
policy with its form as context, so a destructive button — or any button of a
form named like "Delete account", named or not — is never pressed. Generated
flows never replay `test_form`'s submit presses.

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
place, or nothing observable. A press with no visible change is looked at
before it is reported: a new tab (closed again), a `tel:` / `mailto:` link
handing off to another app, a link to the page already open, or a state
change the accessibility tree does not show (an input's type,
`aria-expanded` / `pressed` / `checked`) is an outcome, listed under
`outcomes found on a closer look`. The result is a page/action graph on the
step, plus checks: `no broken pages` (4xx/5xx documents, error pages, error
checks after a click — a failure), `linked pages open` (a warning),
`controls respond` (inconclusive for presses nothing explains — the agent
cannot tell a broken control from one that needs data or a signed-in user),
`controls pressable` (inconclusive, with the cause: covered by another
element, not visible, timed out), the controls `blocked by safety`, the
external links found, and — skipped — the form buttons left alone and the
pages still queued when a limit was reached.
Buttons that submit or confirm a form (inside a form, or named `Save`,
`Submit`, `Apply`, `OK`…) are never pressed here: that is `test_form`'s job,
and pressing them while exploring could change data. Going back (`back`,
Escape, `goto`) is cleanup.

```markdown
1. goto: "{APP_URL}/members"
2. explore_page
3. explore_page: "depth=2" | "max_actions=20" | "max_pages=8" | "max_ai_calls=3"
```

| Option | Default | Meaning |
|--------|---------|---------|
| `depth` | `2` | Link hops from the start page |
| `max_actions` | `20` | Presses in total (shared with the caller's budget under `test_page`) |
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
1. goto: "{APP_URL}/members"
2. test_page
3. test_page: "depth=1" | "max_actions=20" | "max_ai_calls=3" | "submit=false"
```

| Page type | What runs (besides `check_console_network`, `check_accessibility` and `test_responsive`) |
|-----------|--------------------------------------------------------------------|
| `LOGIN` | `test_form` without submitting; password field masked (a field labelled like a password that is not `type=password` fails; no password field — an email-first sign-in — is skipped); no sign-in attempted |
| `FORM`, `WIZARD` | `test_form` (`submit=true` only when passed through) |
| `TABLE`, `LIST`, `SEARCH`, `DASHBOARD`, `DETAIL`, `CONTENT` | `test_table` when there is a table (else a pager pressed once), `test_search` when there is a search field, then `explore_page` within `depth` / `max_actions` |
| `SETTINGS` | nothing that changes data: toggles and save buttons are left alone |

With an LLM provider, `max_ai_calls` bounds two uses: a classification
tie-break when the deterministic type is `CONTENT` or `UNKNOWN`, and an
adaptive plan of a few extra steps — each validated against the observation
and the safety policy before it runs; rejected steps are listed in the report.
Planned steps are probes: one that fails is an `AI-planned steps completed`
warning and ends the plan, never the flow. `max_actions` (default 20) bounds
every press under `test_page` — table, search, pager, exploration and planned
steps together. Without a provider everything above still runs.

The report's **Agent** panel shows the page type, discovered components, the
plan, actions executed, controls skipped by safety, AI calls and a link to
the generated flow. Run one page without writing a flow:

```bash
uv run pytest --agent-test https://example.com/members            # with the HTML report
uv run python main.py agent-test https://example.com/members      # CLI, --depth / --max-actions / --profile
```

The generated flow replays the actions that ran (`fill`, `click`, `select`,
`press`, `back`…) with an `assert_url` after each navigation and an
`assert_text` for each new page heading, dialog title or alert a step brought
up — skipping text that changes between runs (dates, times, amounts, long
numbers, emails). The steps `test_responsive` performed at other viewports are
left out. The Agent panel lists the assertions under *Suggested assertions*.
`test_form`'s submit presses are never written to the generated flow: replayed
outside the skill they could submit the form on every run.

`profiles=` is not a `test_page` option: list profiles under `## Config` (or
pass `--profile`) to run the whole flow on desktop and mobile.

#### `check_links`
Request every link on the page and report the broken ones, without clicking
anything. Links are collected from `a[href]` (fragments ignored, duplicates
removed) and requested through the browser context, so they carry the page's
cookies: `HEAD` first, `GET` when `HEAD` is refused. Visible images that
failed to load are reported too.

```markdown
1. goto: "{APP_URL}/members"
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

Logout links, and links whose path or query looks destructive (delete,
unsubscribe, checkout…), are never requested unless the flow allows
destructive actions; they are listed under `blocked by safety`. Links over
`max_links`, or left when the time budget runs out, are a skipped `links not
checked` check. The requests are not part of the report's network log.

#### `check_accessibility`
A basic accessibility pass in one page evaluation; nothing is clicked. Each
rule is a check with a count and the offending elements (`img src=…`,
`input[name=email] (placeholder "Email" only)`, `button.icon`):

| Check | Flags |
|-------|-------|
| `images have alt text` | content images with no `alt` attribute (`alt=""` marks a decorative image and is fine). Images that look decorative — positioned behind the content, spacer-sized, not interactive — are an info check, `decorative images without alt=""`; images hidden from assistive tech are not listed; an image inside a link or button is judged by `controls have names` |
| `fields have labels` | inputs, selects and textareas with no accessible name — label, `aria-label`, `aria-labelledby` or `title`; a placeholder is not a label. Each field shows the text next to it (`input[name=email] (shows "Email", not linked as its label)`) |
| `controls have names` | buttons and links with no text, `aria-label`, `title` or image alt |
| `page language set` | `<html>` without `lang` |
| `visual headings marked up` | on a page with no heading at all, text styled as one (large, own text): `"Welcome!" (div, 36px)`. A page with headings but no `<h1>` is an info `page has an h1`; a page with neither is an info note |
| `heading levels in order` | a skipped level such as `h2 → h4` (`role="heading"` counts) |
| `referenced ids are unique` | an id used twice that a label or ARIA reference points to |
| `no positive tabindex` | `tabindex` above 0 |
| `dialog holds focus` | an open modal dialog that does not contain keyboard focus |

```markdown
1. check_accessibility
2. check_accessibility: "level=strict"
```

Findings are warnings; `level=strict` makes them fail the step. It is not a
WCAG audit — colour contrast and the rest need a dedicated tool — but a
control without a name is also one a flow cannot target by name.

#### `test_table`
Exercise the first visible table (`<table>`, `role=grid` or `role=table`;
`table=2` for another) through ordinary child steps:

- **structure** — a header row with text; rows, or an empty-state message
- **sorting** — click the first sortable header (`aria-sort`, a button inside
  it, a sort class or a pointer cursor) and check that column is now in
  ascending or descending order, comparing numbers, dates and text as such
- **pagination** — press *Next*: the rows change; press *Previous*: the first
  page comes back
- **row details** — press the first link or button in the first row: the URL
  changes or a dialog opens; then *Back* or *Escape*

```markdown
1. goto: "{APP_URL}/members"
2. test_table
3. test_table: "table=2" | "sort=false" | "paginate=false" | "open=false"
```

Every finding is a warning: equal values, server-side paging and virtualised
rows can look unchanged, and are reported as such; a header or pager that
cannot be pressed is a warning too, and one that does not exist is skipped. No
table is skipped — a failure when `table=` named one. A control the safety
policy blocks (a row's *Delete*) is never pressed and is listed under
`blocked by safety`.

#### `test_search`
Search for a value the page already shows — the first cell of the first table
row, else the first list item — so no test data is needed:

- **finds a visible value** — the term is on the page afterwards; an
  `assert_text` step is added so the generated flow keeps the check
- **narrows the results** — the result count did not grow
- **no match shows no results** — a nonsense term leaves no rows, or an
  empty-state message
- **clearing restores the results** — clearing the field brings back the count

```markdown
1. goto: "{APP_URL}/members"
2. test_search
3. test_search: "term=John Smith" | "search=Find a member"
```

`term=` searches for a given value; `search=` names the field when there are
several. Findings are warnings: a search can match on fields the page does not
show, and a field that cannot be typed into is a `search usable` warning. No
search field is skipped — a failure when `search=` named one. When searching
opens another page, the skill returns to the start page (cleanup) before the
next search.

#### `snapshot_page`
Structural regression without pixels: save what the page is made of, and on
later runs report what disappeared.

```markdown
1. goto: "{APP_URL}/members"
2. snapshot_page: "members_list"
3. snapshot_page: "members_list" | "update=true"
4. snapshot_page: "members_list" | "strict=true" | "ignore=Promo,Chat"
```

The structure is a list of `role: name` items — headings, buttons, links,
tabs, menu items, form fields (`field: Email (email)`), table columns
(`column: Name`). Controls inside table rows and names that look like data
(numbers, dates, amounts) are left out: they change with the data, not the UI.
The first run saves `<flow folder>/baselines/<name>__<profile>.json`
(`reports/<ENVIRONMENT>/baselines/` for a flow from outside the project); later
runs compare against it. Removed items are a warning — an error with
`strict=true` — and added ones are listed. `update=true` saves the current page
as the new baseline; `ignore=` drops items containing any of the given words.
Commit the baselines with the flows so a reviewer sees structural changes.

#### `test_widgets`
Check that tabs, disclosures and dialogs behave as their ARIA roles promise,
through ordinary child steps:

- **tabs** — each tab that is not selected: after a click it is
  `aria-selected` and the panel it controls is visible; the original tab is
  selected again at the end
- **disclosures** — buttons with `aria-expanded` (accordions, *show more*,
  menus): a click flips the state and shows or hides the region it controls; a
  second click restores it
- **dialogs** — buttons with `aria-haspopup="dialog"` or Bootstrap's
  `data-bs-toggle="modal"`: the dialog opens, holds keyboard focus, Escape
  closes it, and focus returns to the button

```markdown
1. test_widgets
2. test_widgets: "max=3" | "dialog=Edit profile"
```

`max=` limits the widgets of each kind (default 5); `dialog=` names an opener
that has no ARIA hint — if it is not on the page, `dialog opener found` fails.
Disabled controls and controls the safety policy blocks are left alone.
Findings are warnings; a page without ARIA widgets is skipped rather than
failed. Putting a widget back (the original tab, a second disclosure click)
is cleanup.

#### `check_performance`
Read the browser's own timing for the current document and compare it with
budgets. Nothing is clicked, and nothing fails: over-budget metrics are
warnings, because test machines and networks are noisy.

```markdown
1. goto: "{APP_URL}/members"
2. wait_load: "load"
3. check_performance
4. check_performance: "lcp=4000" | "load=8000"
```

| Option | Default | Metric |
|--------|---------|--------|
| `ttfb` | `800` | Time to first byte (ms) |
| `dcl` | `3000` | DOMContentLoaded finished (ms) |
| `load` | `5000` | Load event finished (ms) |
| `lcp` | `2500` | Largest Contentful Paint (ms) |
| `cls` | `0.1` | Cumulative Layout Shift (a score) |

The `performance` check lists every value plus the number and size of the
resources fetched, so the report doubles as a trend record. The timings
describe the last full page load: after in-page navigation in a single-page
app they still show the initial load.
