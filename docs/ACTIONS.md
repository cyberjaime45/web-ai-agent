# Supported Actions — Full Reference

Every keyword a flow step can use, grouped by purpose. 44 actions in total.
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

## Waits (4)

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
