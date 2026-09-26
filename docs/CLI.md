# CLI

The CLI in `main.py` is the agent entry point — a thin wrapper around
`app.agent.orchestrator.Orchestrator`. Use it for shell invocations and for
agent-to-agent calls from other processes. For in-process orchestration,
import `Orchestrator` directly.

`.env` is loaded the same way as under pytest, so the CLI sees the same
browser, LambdaTest and AI configuration.

```bash
# Run a flow file
uv run python main.py run tests/marketing_site/flows/home_page.md

# Run inline Markdown
uv run python main.py run --inline '# Smoke
## Steps
1. goto: "https://example.com"
2. assert_text: "Example Domain"
'

# Override the report environment (screenshots go to reports/qa1/images)
uv run python main.py run tests/marketing_site/flows/home_page.md --env qa1

# Run under the mobile device profile (MOBILE_DEVICE, default iPhone 13)
uv run python main.py run tests/marketing_site/flows/home_page.md --profile mobile
```

Failed steps get the same evidence as under pytest — screenshots under
`reports/<ENVIRONMENT>/images/` and, in the `--json` output, an `evidence`
object per failed step (layers, URL, title, profile, screenshot paths). The
CLI keeps no Playwright trace; that belongs to the pytest report.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Flow passed |
| `1` | Flow failed (one or more steps failed) |
| `2` | Invocation error (bad args, missing file, parse error, runtime crash) |

## Multi-agent contract — `--json`

With `--json`, stdout is exactly one `FlowResult` JSON document followed by a
newline, and nothing else. All logs go to stderr. This is the calling contract
for parent agents in a multi-agent system:

```python
import json, subprocess

proc = subprocess.run(
    ["uv", "run", "python", "main.py", "run", "tests/marketing_site/flows/home_page.md", "--json"],
    capture_output=True, text=True,
)
result = json.loads(proc.stdout)   # FlowResult dict
# result["success"]          → bool
# result["passed"]           → int (computed)
# result["failed"]           → int (computed)
# result["skipped"]          → int (computed)
# result["steps"]            → list[StepResult dict]
# result["flow_name"]        → str
```

On invocation error in JSON mode, stdout is `{"error": "...", "type": "..."}`
and exit is `2`.

## CLI vs pytest

| Use | Choose |
|-----|--------|
| Single flow invoked by another agent or service | **CLI** — `main.py run ... --json` |
| Local dev, debugging a single flow | **CLI** — pretty stdout, faster startup |
| Full suite, HTML report, CI | **pytest** — collection, one shared browser, HTML report |

The CLI runs a flow without the HTML report; pytest produces the report
described in [REPORTS.md](REPORTS.md).

## Autonomous page test — `agent-test`

```bash
uv run python main.py agent-test https://example.com/members
uv run python main.py agent-test https://example.com/members --depth 2 --max-actions 20 --profile mobile
uv run python main.py agent-test https://example.com/members --json
```

Runs a two-step flow — `goto` the URL, then `test_page` — and prints the
path of the generated Markdown flow. Options map to `test_page`'s
`depth`, `max_actions`, `max_ai_calls` and `destructive`; `--destructive`
only has effect with `ALLOW_DESTRUCTIVE=true`. Under pytest the same is
`pytest --agent-test URL`, with the HTML report and its Agent panel.

## Flow lint — `lint`

```bash
uv run python main.py lint                               # every flow under tests/
uv run python main.py lint tests/fms --strict            # exit 1 when there are findings
uv run python main.py lint --report reports/production/report_*.json   # + steps healed by L2/L3
uv run python main.py lint --json
```

Static checks over flow files: no browser, no LLM. Each finding is
`path:line: rule: message`.

| Rule | Finds |
|------|-------|
| `unknown-step` | A line whose keyword is not an action — it runs as a no-op |
| `fixed-wait` | `wait: <ms>`; prefer `wait_stable`, `wait_for_text` or `wait_for_element` |
| `duplicate-step` | The same check, wait or `goto` twice in a row (a repeated click can be deliberate) |
| `no-assertion` | A section that never checks anything (component flows are exempt) |
| `literal-secret` | A literal typed into a password, token or API-key field instead of a `<PLACEHOLDER>` |
| `missing-component` | A `run_flow` reference that does not resolve from the calling flow's folder |
| `unused-component` | A flow under `components/` that no scanned flow calls |
| `repeated-steps` | Three or more steps, in order, already in another flow — a component candidate |
| `parse-error` | A file the parser rejects |

`--report` reads report JSON files and lists the steps that passed only
through L2 or L3, with how many reports they appear in: the UI changed and
the flow's target is due an update. The exit code is `0` unless `--strict`
is given and something was found; `2` when a path does not exist.
