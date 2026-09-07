# Bug Fixing — 3-Layer Playwright Agent

## Default behavior

When given a bug report or failing flow: fix it. Read the logs, reproduce, find root cause.

## Diagnosis order

1. **Read the full error message** — which layer raised it? Check for `PlaywrightTimeout`, `RuntimeError` (L2 exhausted), or AI resolver failure
2. **Open the HTML report** — `open reports/<env>/report.html`
3. **Check failure screenshot** — `reports/<env>/images/`
4. **Run with headed browser** — `HEADLESS=false pytest --flow_file=tests/<app>/flows/failing.md`
5. **Check which layer failed** — step results show `[L1]`, `[L2]`, or `[L3]`
6. **Reproduce the exact step** — isolate it with `--flow='<single step>'`

## Failure by layer

### L1 fails unexpectedly (DeterministicRunner)

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Action times out at 5s | Element not found by exact locator | Check if role/label/placeholder changed; consider CSS selector |
| Action not dispatched | New action type not in `_l1_handlers` | Add handler + register in dispatch table |
| Works headed, fails headless | Viewport or timing difference | Check `VIEWPORT` env var; add explicit `wait_for` before action |
| CSS/XPath selector fails | Selector syntax wrong or element structure changed | Inspect DOM; verify selector in DevTools |

### L2 fails (FallbackLocator)

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| All strategies exhausted (RuntimeError) | Element truly not on page | Check flow step — wrong page state? |
| Similarity score < 0.6 | DOM structure changed significantly | Review selectolax strategy for this element type |
| Flaky — passes sometimes | Race condition in DOM render | Add `wait_load` or `wait_for_element` before the step |

### L3 fails (AIResolver)

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Returns None | `OPENAI_API_KEY` not set or LLM error | Check env — expected behavior if key missing |
| Correct element found but wrong action | Prompt missing action type context | Check prompt structure in ai_resolver.py |
| Inconsistent results across runs | Temperature too high | Lower temperature for action decisions |

### Flow-level failures

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `FlowParseError` | Invalid action keyword or wrong arg count | Check syntax: `keyword: "arg1" \| "arg2"` |
| pytest can't discover flow | File not under `tests/<app>/flows/` | Check `conftest.py` collection — needs `flows` in path and `tests` in `testpaths` |
| Sub-flow not found | Wrong `run_flow` reference | Resolved relative to the calling flow's directory: `"components/sso_login"` → `tests/fms/flows/components/sso_login.md` |
| Circular flow reference | Flow A calls B which calls A | Break the cycle; restructure shared steps |
| Report not generated | `ENVIRONMENT` not set / write permission | Set env var; check `reports/` dir exists |

## Checklist before marking fixed

- [ ] Reproduced the failure locally
- [ ] Identified which layer raised the error
- [ ] Root cause found (not just symptom)
- [ ] Fix is minimal — only touches what's broken
- [ ] `pytest --flow_file=tests/<app>/flows/failing.md` passes
- [ ] Full `pytest` run passes (no regressions)
- [ ] Report generates cleanly
- [ ] No `time.sleep()` introduced
- [ ] L3 still skips gracefully without `OPENAI_API_KEY`
