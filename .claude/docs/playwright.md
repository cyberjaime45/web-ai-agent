# Playwright (Python) Patterns

## Locator priority — matches L1 dispatch table order

```python
# 1. Role (most resilient)
page.get_by_role("button", name="Submit")

# 2. Label (forms)
page.get_by_label("Email")

# 3. Placeholder
page.get_by_placeholder("Search...")

# 4. Text
page.get_by_text("Sign in")

# 5. CSS selector (supported in L1 via _is_selector())
page.locator("#submit-btn")
page.locator("div[data-testid='cta'] button")

# 6. XPath (supported in L1 via _is_selector())
page.locator("//button[@type='submit']")
```

L1 supports all 6 locator types. CSS/XPath are detected by `_is_selector()` in `locator.py`.

## L1 timeout — fast failover

```python
# L1 action calls use _L1_TIMEOUT = 5000ms
# This caps Playwright's auto-wait — returns immediately when element is ready,
# only hits 5s ceiling when element is truly missing.
loc.click(timeout=self._L1_TIMEOUT)
loc.fill(value, timeout=self._L1_TIMEOUT)

# The page's default_timeout (30s) is preserved for explicit waits:
page.wait_for_url(pattern, timeout=10000)  # intentional wait — full timeout
```

Handlers that intentionally wait (assert_text, wait_for_element, wait_for_text, wait_for_url) use their own explicit timeouts, NOT `_L1_TIMEOUT`.

## Waiting — never use sleep

```python
# Never
import time; time.sleep(2)

# Wait for element
page.get_by_role("button").wait_for(state="visible")

# Wait for navigation
page.wait_for_url("**/dashboard")

# Wait for load state
page.wait_for_load_state("networkidle")

# Wait for response
with page.expect_response(lambda r: "/api/result" in r.url) as resp:
    page.get_by_role("button").click()
```

## Actionability checks

Playwright's action methods (`.click()`, `.fill()`, `.check()`, etc.) perform auto-waiting:
- Visible, stable, enabled, editable, receives events
- Returns as soon as element is actionable
- Only hits timeout ceiling when element is truly missing

`loc.count()` returns immediately — no waiting, no timeout.

## Browser configuration

```python
# Env vars (app/browser/session.py):
# HEADLESS=true/false  (default: true)
# BROWSER=chromium/firefox/webkit  (default: chromium)
# VIEWPORT=1920x1080  (default: 1920x1080, WIDTHxHEIGHT format)
# SLOW_MO=0  (default: 0, milliseconds between actions)

# Headed mode: --start-maximized + no_viewport: True (chromium only)
# Headless mode: explicit viewport from VIEWPORT env var
```

## Shadow DOM & iframes

```python
# iframes — must use frame_locator
frame = page.frame_locator("#my-iframe")
frame.get_by_role("button").click()

# Shadow DOM — Playwright pierces shadow roots automatically for most locators
# If a locator fails, check DevTools for shadow-root boundary
```

## Screenshot on step failure

```python
from pathlib import Path

def save_failure_screenshot(page, step_name: str, env: str):
    path = Path(f"reports/{env}/images/failure-{step_name}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=True)
```

## selectolax similarity (L2)

```python
from selectolax.parser import HTMLParser

# Used by FallbackLocator for fuzzy DOM matching
# Threshold for L2 acceptance: ≥ 0.6 (hardcoded in locator.py)
```
