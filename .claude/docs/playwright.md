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
# All values come from app/config/settings.py (settings.browser, .headless,
# .viewport, .slow_mo, .running_mode, .lt_username, .lt_access_key).
# create_browser(pw, test_name) in app/browser/session.py launches locally or
# connects to LambdaTest over CDP; it returns (browser, context_kwargs).

# Headed Chromium: --start-maximized + no_viewport=True
# Everything else: explicit viewport from VIEWPORT
```

Under pytest the browser is shared by the session (`_SessionBrowser` in
conftest) and each flow gets `browser.new_context(**context_kwargs)` — never
launch a browser per test.

## Round trips cost time on the per-step path

`page.title()`, `page.content()`, `loc.count()`, `loc.is_visible()` are each a
driver round trip (~1–5 ms locally, more remote). `page.url` is a cached
property. Don't add per-step calls for values nothing reads; batch DOM reads
(one `page.content()` per fuzzy pass, parsed once).

## Shadow DOM & iframes

```python
# iframes — must use frame_locator
frame = page.frame_locator("#my-iframe")
frame.get_by_role("button").click()

# Shadow DOM — Playwright pierces shadow roots automatically for most locators
# If a locator fails, check DevTools for shadow-root boundary
```

## Screenshot on step failure

One routine: `capture_failure_screenshot(page, directory)` in
`app/execution/engine.py` (viewport shot, `fail_<uuid>.png` under
`settings.images_dir`). The engine calls it at the failure site; conftest
calls it only for the flow-end fallback and then annotates error elements.
Do not add another capture path.

## selectolax similarity (L2)

```python
from selectolax.parser import HTMLParser

# Used by FallbackLocator for fuzzy DOM matching
# Threshold for L2 acceptance: ≥ 0.6 (hardcoded in locator.py)
```
