# Web Agent

A Markdown-driven web automation agent that executes flows through a 3-layer deterministic + AI runtime, with automatic pytest discovery, environment-based reporting, and a polished terminal UI.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     conftest.py                          │
│   pytest_collect_file → FlowFile → FlowItem.runtest()    │
│   --flow / --flow_file  (inline & explicit path modes)   │
└─────────────────────────┬────────────────────────────────┘
                          │ FlowDefinition
                          ▼
┌──────────────────────────────────────────────────────────┐
│                  FlowRunner  (engine)                    │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Layer 1 — DeterministicRunner                   │   │
│  │  Dispatch-table driven. Exact Playwright         │   │
│  │  role / label / placeholder locators.            │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 2 — FallbackLocator                       │   │
│  │  7+ fuzzy strategies + selectolax similarity     │   │
│  │  matching (threshold ≥ 0.6).                     │   │
│  └────────────────────┬─────────────────────────────┘   │
│                       │ fails                            │
│  ┌────────────────────▼─────────────────────────────┐   │
│  │  Layer 3 — AIResolver  (OpenAI, optional)        │   │
│  │  Invoked only when L1 + L2 both fail.            │   │
│  │  Also handles AI-native actions directly.        │   │
│  │  Skipped automatically if no OPENAI_API_KEY.     │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
             reports/<ENVIRONMENT>/
               report.html  report.json
               assets/      images/
```

---

## Quick Start

```bash
# 1. Install dependencies (uv recommended)
uv sync

# 2. Install Playwright browser
uv run playwright install chromium

# 3. Copy and configure environment
cp .env.example .env

# 4. Run all flows
uv run pytest

# 5. Run a specific flow file
uv run pytest flows/home_page.md -v
```

---

## Running Flows

### Auto-discovery (default)
Drop a `.md` file inside the `flows/` directory — pytest picks it up automatically, no `test_*.py` needed.

```bash
uv run pytest flows/login.md -v
```

### Inline Markdown via `--flow`
Pass a complete flow as a raw Markdown string directly on the command line:

```bash
uv run pytest --flow "# My Flow
## Config
- url: https://example.com
- timeout: 10000
## Steps
1. goto: \"https://example.com\"
2. assert_text: \"Example Domain\"
" -v
```

### Explicit file path via `--flow_file`
Point to any `.md` file regardless of its location:

```bash
uv run pytest --flow_file path/to/any_flow.md -v
```

> `--flow` and `--flow_file` are mutually exclusive.

---

## Flow File Format

Flow files are plain Markdown. Place them in `flows/`.

```markdown
# Login Flow

## Config
- url: https://example.com/login
- timeout: 30000

## Credentials
- username: admin
- password: secret123

## Steps
1. goto: "https://example.com/login"
2. wait_for_load
3. fill: "Username" | "admin"
4. fill: "Password" | "secret123"
5. click: "Sign In"
6. assert_url: "dashboard"
7. assert_text: "Welcome back"
8. screenshot: "dashboard_loaded"

## Expected Outcome
- User is redirected to the dashboard
- Page displays "Welcome back"
```

### Step Syntax

```
keyword: "arg1" | "arg2"
```

- The keyword is followed by `:` and one or more quoted arguments separated by `|`.
- Actions with no arguments omit the colon: `wait_for_load`, `reload`, `back`.
- Arguments that are bare values (e.g. milliseconds for `wait`) can omit quotes: `wait: 2000`.

### CSS Selector Support

Any action that targets an element can accept a CSS selector instead of a label or text. A CSS selector is detected when the argument starts with `.`, `#`, or `[`:

```markdown
1. fill: ".textarea-box" | "Some text"
2. click: "#submit-btn"
3. check: "[name='agree']"
4. wait_for_element: ".loading-spinner"
```

---

## Supported Actions — Full Reference

### Navigation (6)

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
Wait for the page to reach a specific load state. Defaults to `domcontentloaded`.

```markdown
1. wait_load
2. wait_load: "networkidle"
```

#### `switch_tab`
Switch to a different browser tab by index (0-based).

```markdown
1. switch_tab: "0"
2. switch_tab: "1"
```

#### `scroll`
Scroll the page. Accepts a direction (`up`, `down`, `top`, `bottom`), a pixel amount, or text to scroll into view.

```markdown
1. scroll: "down"
2. scroll: "top"
3. scroll: "500"
4. scroll: "Contact Us"
```

---

### Click (6)

#### `click`
Click a button or link by its visible text, or an element by CSS selector. Tries `role="button"` first, then `role="link"`. When the argument starts with `#`, `.`, or `[`, it is treated as a CSS selector.

```markdown
1. click: "Sign In"
2. click: "Accept All Cookies"
3. click: "Learn More"
4. click: "#submit-btn"
5. click: ".close-modal"
6. click: "[data-testid='cta']"
```

#### `click_link_text`
Click a link by its exact text.

```markdown
1. click_link_text: "Privacy Policy"
2. click_link_text: "View All Products"
```

#### `click_button`
Click a button by its name. Identical to `click` but more explicit.

```markdown
1. click_button: "Submit"
2. click_button: "Next Step"
```

#### `double_click`
Double-click an element by text.

```markdown
1. double_click: "Edit Cell"
2. double_click: "file_report.pdf"
```

#### `right_click`
Right-click an element to open a context menu.

```markdown
1. right_click: "Document Title"
2. right_click: "Row Item"
```

#### `hover`
Hover over an element to trigger tooltips, dropdowns, or other hover effects.

```markdown
1. hover: "User Profile"
2. hover: "Products"
3. hover: "More Options"
```

---

### Input (7)

#### `fill`
Set an input field's value atomically via Playwright's `.fill()`. Resolves the input by label, placeholder, or CSS selector.

```markdown
1. fill: "Email" | "user@example.com"
2. fill: "Search" | "web agent"
3. fill: ".textarea-box" | "This is a message"
4. fill: "#phone-input" | "+1 555-0100"
```

#### `type`
Type text character-by-character via `.press_sequentially()`. Use this for autocomplete fields, masked inputs, or when keystroke events matter.

```markdown
1. type: "Address" | "123 Main Street"
2. type: "#search-input" | "New York"
```

#### `clear`
Clear an input field's value.

```markdown
1. clear: "Email"
2. clear: ".search-field"
```

#### `focus`
Move focus to an input field without changing its value.

```markdown
1. focus: "Username"
2. focus: "#otp-field"
```

#### `select`
Select an option from a `<select>` dropdown by label and option text.

```markdown
1. select: "Country" | "United States"
2. select: "#billing-state" | "California"
```

#### `check`
Check a checkbox or radio button. Resolves by label text, `role="radio"`, or `role="checkbox"`.

```markdown
1. check: "I agree to the Terms"
2. check: "YES"
3. check: "[name='newsletter']"
```

#### `uncheck`
Uncheck a checkbox.

```markdown
1. uncheck: "Subscribe to updates"
2. uncheck: "#marketing-opt-in"
```

---

### Advanced Interaction (2)

#### `drag_to`
Drag one element to another by their visible text.

```markdown
1. drag_to: "Task Card" | "Done Column"
2. drag_to: "Item A" | "Drop Zone"
```

#### `upload`
Upload a file to a file input. First argument is the CSS selector for the file input, second is the file path.

```markdown
1. upload: "input[type=file]" | "/path/to/document.pdf"
2. upload: "#avatar-upload" | "./images/profile.jpg"
```

---

### Table & Data (5)

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

### Assertions (8)

#### `assert_text`
Assert that specific text is visible on the page. Waits up to 5 seconds.

```markdown
1. assert_text: "Welcome back, Admin"
2. assert_text: "Order placed successfully"
3. assert_text: "Ready to learn even more about Wheels Up?"
```

#### `assert_not_text`
Assert that specific text is NOT visible or present on the page.

```markdown
1. assert_not_text: "Error"
2. assert_not_text: "Access Denied"
```

#### `assert_visible`
Assert that an element with the given text or selector is visible on the page.

```markdown
1. assert_visible: "Submit Button"
2. assert_visible: ".success-banner"
```

#### `assert_hidden`
Assert that an element is hidden or does not exist.

```markdown
1. assert_hidden: "Loading Spinner"
2. assert_hidden: ".error-modal"
```

#### `assert_url`
Assert that the current URL contains a specific fragment (case-insensitive).

```markdown
1. assert_url: "/dashboard"
2. assert_url: "checkout/confirmation"
3. assert_url: "tab=settings"
```

#### `assert_enabled`
Assert that a button or input is enabled (not disabled).

```markdown
1. assert_enabled: "Submit"
2. assert_enabled: "Next Step"
```

#### `assert_disabled`
Assert that a button or input is disabled.

```markdown
1. assert_disabled: "Submit"
2. assert_disabled: "Delete Account"
```

#### `assert_checked`
Assert that a checkbox or radio button is checked.

```markdown
1. assert_checked: "I agree to the Terms"
2. assert_checked: "Remember Me"
```

---

### Waits (5)

#### `wait`
Pause execution for a given number of milliseconds. Defaults to 1000ms if no argument is provided.

```markdown
1. wait
2. wait: 2000
3. wait: 5000
```

#### `wait_for_load`
Wait for the page to reach `DOMContentLoaded` state.

```markdown
1. wait_for_load
```

#### `wait_for_element`
Wait for a specific element (by CSS selector) to become visible. Times out after 10 seconds.

```markdown
1. wait_for_element: ".results-container"
2. wait_for_element: "#dashboard-widget"
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

---

### AI-Native Actions (4)

These actions bypass Layer 1 and Layer 2 entirely and go directly to Layer 3 (OpenAI). They require `OPENAI_API_KEY` to be set.

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

### Utilities (2)

#### `screenshot`
Capture a screenshot of the current page. Optionally provide a name. Saved to `reports/<env>/images/`.

```markdown
1. screenshot
2. screenshot: "after_login"
3. screenshot: "checkout_page"
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

## Complete Flow Examples

### Example 1: E-commerce Checkout

```markdown
# Checkout Flow

## Config
- url: https://shop.example.com
- timeout: 30000

## Steps
1. goto: "https://shop.example.com"
2. wait_for_load
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

## Expected Outcome
- Order confirmation page is displayed
- Discount code was applied successfully
```

### Example 2: Form with Custom Selectors

```markdown
# Contact Form

## Config
- url: https://example.com/contact
- timeout: 15000

## Steps
1. goto: "https://example.com/contact"
2. wait_for_load
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

## Expected Outcome
- Form is submitted successfully
- Confirmation message is displayed
```

### Example 3: Table Verification

```markdown
# User Management

## Config
- url: https://admin.example.com/users
- timeout: 20000

## Steps
1. goto: "https://admin.example.com/users"
2. wait_for_load
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

## Expected Outcome
- User row exists and can be edited
- Changes are saved successfully
```

---

## Project Structure

```
web-agent/
├── conftest.py                     # Pytest hooks, fixtures, flow auto-discovery
├── main.py                         # CLI entry point
├── pytest.ini                      # testpaths=flows, pythonpath=.
├── pyproject.toml
│
├── app/
│   ├── schemas/
│   │   └── actions.py              # ActionType enum, FlowAction, StepResult, FlowResult
│   ├── flow/
│   │   └── parser.py               # 4-stage pipeline: tokenize → normalize → validate → build
│   ├── layers/
│   │   ├── deterministic.py        # L1 + L2 dispatch-table runner
│   │   ├── locator.py              # FallbackLocator — fuzzy strategies + selectolax
│   │   └── ai_resolver.py          # L3 OpenAI resolver + AI-native actions
│   │
│   ├── execution/
│   │   └── engine.py               # FlowRunner: orchestrates L1 → L2 → L3
│   ├── agent/
│   │   ├── orchestrator.py         # High-level agent runtime
│   │   └── prompts/
│   │       └── resolver.py         # LLM prompt templates
│   │
│   ├── browser/
│   │   ├── session.py              # Browser/context creation (local + LambdaTest)
│   │   ├── driver.py               # BrowserDriver (navigation + element + utils)
│   │   ├── navigation.py           # URL navigation, history, wait helpers
│   │   ├── element.py              # Element extraction and interaction
│   │   └── screenshot.py           # Screenshot and artifact capture
│   │
│   ├── config/
│   │   └── settings.py             # Typed settings from environment variables
│   │
│   ├── integrations/
│   │   └── database/               # MySQL/MariaDB client, config, models, queries
│   │
│   ├── memory/
│   │   └── session.py              # Agent short-term session memory
│   │
│   ├── observability/
│   │   └── reporter.py             # HTML + JSON report generator
│   │
│   ├── skills/
│   │   └── base.py                 # Abstract Skill base class
│   │
│   └── utils/
│       └── banner.py               # Terminal startup banner (Rich)
│
├── flows/                          # Flow definition files (.md)
│   ├── home_page.md
│   ├── signature_membership.md
│   └── charter_up.md
│
└── reports/
    └── <ENVIRONMENT>/              # e.g. staging/, qa1/, uat/
        ├── report.html
        ├── report.json
        ├── assets/                 # CSS + JS for the HTML report
        └── images/                 # Screenshots from test runs
```

---

## Configuration

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `staging` | Report output directory (`reports/<ENVIRONMENT>/`) |
| `BASE_URL` | — | Optional base URL override |
| `RUNNING_MODE` | `local` | `local` or `lambda` (LambdaTest cloud) |
| `BROWSER` | `chromium` | `chromium`, `firefox`, or `webkit` |
| `HEADLESS` | `true` | `true` or `false` |
| `SLOW_MO` | `0` | Milliseconds between actions |
| `OPENAI_API_KEY` | — | Enables Layer 3 AI resolver and AI-native actions |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for L3 and AI-native actions |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, or `error` |
| `COVERAGE` | `0` | `1` to enable coverage tracking in report |
| `COVERAGE_TARGET` | `80` | Coverage % target shown in report |
| `THEME_STYLE` | `system` | Report theme: `light`, `dark`, or `system` |

### Multi-environment reports

```bash
ENVIRONMENT=qa1 uv run pytest flows/login.md
# → writes to reports/qa1/
```

### LambdaTest cloud execution

```bash
RUNNING_MODE=lambda LT_USERNAME=... LT_ACCESS_KEY=... uv run pytest
```

The browser window is automatically maximized for both local and LambdaTest runs. Test pass/fail status is reported to the LambdaTest dashboard automatically.

---

## Reports

After each run, a full HTML report is generated at `reports/<ENVIRONMENT>/report.html`.

```
reports/staging/
├── report.html     # Interactive UI (charts, table, failure details, PDF export)
├── report.json     # Raw structured data
├── assets/
│   ├── report.css
│   └── report.js
└── images/
    └── *.png       # Screenshots from the run
```

The report includes:
- Result distribution doughnut chart
- Pass rate trend across last 8 runs
- Test duration bars
- Category breakdown
- Expandable test details with per-step duration and execution layer
- Failure screenshots with lightbox zoom
- PDF export (2-page report with failure details and embedded screenshots)

```bash
open reports/staging/report.html
```

---

## Layer Behaviour

| Layer | Trigger | Strategy |
|-------|---------|----------|
| **L1 — Deterministic** | Always tried first | Dispatch-table driven. Exact Playwright `get_by_role`, `get_by_label`, `get_by_placeholder` locators. |
| **L2 — Fallback** | L1 fails | 7+ fuzzy strategies per element type (clickable, input, checkbox, ID, table row) + selectolax HTML similarity (≥ 0.6). |
| **L3 — AI** | L1 + L2 fail, or AI-native action | OpenAI call with page context. Handles both element fallback and AI-native actions (`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`). Skipped if no `OPENAI_API_KEY`. |

Most flows run entirely on L1 with zero API calls. L2 handles case variations, extra whitespace, and partial text matches. L3 is the last resort for complex or dynamic pages, and the exclusive runtime for AI-native actions.

---

## Parser Pipeline

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

Unknown keywords produce a `FlowParseError` (strict mode) or a `WAIT(0)` placeholder (lenient mode, default) so the AI planner can still consume the raw step text.

---

## Terminal Banner

Displayed at the start of every pytest session. Customise in `app/utils/banner.py`:

```python
BANNER_CONFIG = {
    "agent_name": "Web Agent",
    "version":    "1.0",
    "author":     "Cyberjaime45",
    "ascii_title": "...",      # any multi-line ASCII art string
    "title_color": "dark_cyan",
    "meta_color":  "dark_cyan",
}
```
