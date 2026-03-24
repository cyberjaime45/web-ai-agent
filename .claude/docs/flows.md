# Flow File Format

## Overview

Flows are Markdown files discovered by pytest via `conftest.py`.
Each flow is a sequence of steps parsed through a 4-stage pipeline:
`_tokenize` → `_normalize` → `_validate` → `_build` → `FlowAction`

## File location & naming

```
flows/
  home_page.md
  booking_flow.md
  charter_up.md
  login/              ← subdirectories for reusable flows
    sso_login.md
    ms_login.md
```

pytest discovers all `.md` files under `flows/` (including subdirectories if they contain `flows` in the path).
Use `--flow_file=flows/login/sso_login.md` to run a single file explicitly.

## Step syntax

```markdown
# Flow Name

## Steps
- keyword: "arg1"
- keyword: "arg1" | "arg2"
- keyword                       ← no-arg actions (reload, back, wait_load)
```

Arguments are pipe-separated (`|`) and optionally quoted.

### Full example

```markdown
# SSO Login Page

## Steps
- goto: "https://example.com/"
- wait_for_text: "Sign in"
- click: "Sign in with SSO"
- fill: "Email" | "user@example.com"
- click: "Next"
- fill: "Password" | "secret"
- click: "Sign in"
- assert_text: "My Dashboard"
```

## Supported actions

### Navigation (6)
`goto`, `reload`, `back`, `wait_load`, `switch_tab`, `scroll`

### Click (5)
`click`, `click_link_text`, `double_click`, `right_click`, `hover`

### Input (7)
`fill`, `type`, `clear`, `focus`, `select`, `check`, `uncheck`

### Advanced (2)
`drag_to`, `upload`

### Table/Data (5)
`read_row`, `table_click`, `find_row`, `count_elements`, `get_attribute`

### Assertions (8)
`assert_text`, `assert_not_text`, `assert_visible`, `assert_hidden`, `assert_url`, `assert_enabled`, `assert_disabled`, `assert_checked`

### Waits (4)
`wait`, `wait_for_element`, `wait_for_text`, `wait_for_url`

### AI-native (4) — L3 only
`ai_click`, `ai_extract`, `ai_assert`, `ai_summarize`

AI-native steps are skipped gracefully if `OPENAI_API_KEY` is not set.

### Flow Composition (1)
`run_flow` — execute another flow file inline (see below)

### Utilities (2)
`screenshot`, `press`

## CSS selectors and XPath

All element-targeting actions support CSS selectors and XPath expressions directly:

```markdown
- click: "#submit-btn"
- click: "div[data-testid='cta'] button"
- click: "//button[@type='submit']"
- fill: "[data-testid='email-input']" | "user@example.com"
- check: "input[type='checkbox'][name='agree']"
```

Detection: `_is_selector()` in `locator.py` identifies CSS (`#`, `.`, `[`, tag-prefixed) and XPath (`//`, `/`).

## Reusable flows — `run_flow`

Call another flow file from within a flow:

```markdown
# Dashboard Tests

## Steps
- run_flow: "login/sso_login"
- assert_text: "My Dashboard"
- click: "Settings"
```

Path resolution (relative to `flows/` directory):
- `"sso_login"` → `flows/sso_login.md`
- `"login/sso_login"` → `flows/login/sso_login.md`
- `"login/sso_login.md"` → `flows/login/sso_login.md`

Sub-flows execute on the same browser page. Max nesting depth: 10. Circular references are detected.

## Optional sections

```markdown
## Config
- url: https://example.com
- timeout: 30000
- description: Login flow test

## Credentials
- username: admin
- password: secret123

## Expected Outcome
- User lands on dashboard

## Error Scenarios
- Invalid credentials show error banner

## Notes
- Requires VPN access
```

## Inline flow mode

For quick one-off runs without a file:

```bash
pytest --flow='click: "Login"'
```

## Writing good flows

- One logical user journey per file
- Keep files under ~30 steps — split longer journeys
- Use text-based locators where possible — more resilient
- Use CSS/XPath for elements that lack accessible names
- Put reusable sequences (login, setup) in subdirectories and call via `run_flow`
- Add a `screenshot` step after critical state changes for debugging
