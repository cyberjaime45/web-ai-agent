# CLI

The CLI in `main.py` is the agent entry point — a thin wrapper around
`app.agent.orchestrator.Orchestrator`. Use it for shell invocations and for
agent-to-agent calls from other processes. For in-process orchestration,
import `Orchestrator` directly.

`.env` is loaded the same way as under pytest, so the CLI sees the same
browser, LambdaTest and AI configuration.

```bash
# Run a flow file
uv run python main.py run tests/wheelsup_site/flows/home_page.md

# Run inline Markdown
uv run python main.py run --inline '# Smoke
## Steps
1. goto: "https://example.com"
2. assert_text: "Example Domain"
'

# Override the report environment (screenshots go to reports/qa1/images)
uv run python main.py run tests/wheelsup_site/flows/home_page.md --env qa1
```

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
    ["uv", "run", "python", "main.py", "run", "tests/wheelsup_site/flows/home_page.md", "--json"],
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
