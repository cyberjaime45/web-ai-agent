# Web Agent MCP

The Web Agent MCP (`mcp_server/`) is the standardized interface that exposes
the Web Agent's capabilities to JANUS, the QA Orchestrator Agent, and to any
other MCP client. It is an interface, not an agent: the Web Agent is the
specialized autonomous testing agent and does all the testing. Running flows
with `pytest` or `main.py` needs none of it, and nothing in `app/` imports it.

```
JANUS — QA Orchestrator Agent      (or any MCP client)
        ↓  MCP (stdio)
Web Agent MCP                      mcp_server: 5 tools; validates and delegates
        ↓  pytest <flow.md>        one process per execution
Web Agent                          the existing runtime, unchanged
        ↓
Playwright

The Web Agent MCP reads results from reports/_executions/<id>/report/{summary,test_cases}.json
```

The Web Agent MCP adds no testing behaviour. An execution is the same
`pytest <flow.md>` run a developer or the pipeline starts, in its own process,
writing the usual report into a folder of its own. Results are read from that
report's JSON, never from console output.

## Run it

```bash
uv sync --extra mcp                      # once: adds the MCP SDK (not needed to run flows)
uv run --extra mcp python -m mcp_server  # serves over stdio; an MCP client normally starts it itself
```

A client configuration looks like:

```json
{ "command": "uv", "args": ["run", "--directory", "/path/to/WebAgent", "--extra", "mcp", "python", "-m", "mcp_server"] }
```

Logs go to stderr (stdout is the MCP channel), one `key=value` line per
event, with `execution_id` and the caller's `task_id` when it sent one.

## Tools

| Tool | Arguments | Returns |
|------|-----------|---------|
| `list_flows` | `environment?` | The flows that can be run (id, title, test cases, expected outcome, sites opened, environments) and the known environments |
| `run_flow` | `flow`, `environment`, `profile?`, `metadata?` | An execution id and `QUEUED`, at once |
| `get_status` | `execution_id` | `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` or `TIMED_OUT`, plus progress |
| `get_result` | `execution_id` | Test totals, each failure with its step, message, likely cause and evidence files, warnings, report paths |
| `cancel_execution` | `execution_id` | The status after stopping |

Every answer has an `error` field: `null`, or `{code, message, details}`.
Codes: `INVALID_REQUEST`, `ENVIRONMENT_NOT_ALLOWED`, `EXECUTION_NOT_FOUND`,
`EXECUTION_START_FAILED`, `EXECUTION_TIMEOUT`, `RESULT_NOT_AVAILABLE`,
`WEB_AGENT_ERROR`. MCP protocol errors are left for transport problems.

There is no tool that runs a command, reads a file or executes code. A flow
can only be started by an id from `list_flows`.

### Test failure vs execution failure

| What happened | `status` | `error` | Where to look |
|---------------|----------|---------|---------------|
| The flow ran; every test passed | `COMPLETED` | `null` | `summary`, `verdict: passed` |
| The flow ran; some tests failed | `COMPLETED` | `null` | `failures[]`, each `kind: test_failure` |
| The Web Agent could not run the flow (no report, crash, browser did not start) | `FAILED` | `WEB_AGENT_ERROR` | `error.details`: exit code, console log path and tail |
| Stopped after the time limit | `TIMED_OUT` | `EXECUTION_TIMEOUT` | whatever was reported before the stop |
| `cancel_execution` | `CANCELLED` | `null` | — |

A test that broke without a failed step (setup or teardown error) inside an
otherwise completed run is listed in `failures` with `kind: execution_error`.

### Progress

`get_status.progress` is `{unit: "flows", completed, total, current}`, counted
by pytest itself through `mcp_server/progress_plugin.py`. It is absent until
the run has collected its flows. Steps inside a flow are not counted.

## Environments

`mcp_server/environments.toml` lists the environments the Web Agent MCP may run
against and the hosts that belong to each. A flow may run against an
environment only when that environment owns **every** site the flow opens
(its `goto` steps and those of its `run_flow` components), so asking for a
flow "against qa2" cannot reach another environment's site.

```toml
[environments.staging]
description = "Staging"
hosts = ["memberssitestaging.wheelsup.com"]

[environments.production]
production = true          # refused unless WEB_AGENT_MCP_ALLOW_PRODUCTION=true
hosts = ["one.wheelsup.com", "wheelsup.com", "www.wheelsup.com"]
```

Hosts match exactly; `*.example.com` matches any subdomain. A flow whose
sites span two environments, or cannot be worked out (an unset `<PLACEHOLDER>`
URL), runs against none and `list_flows` shows it with no environments.
`ENVIRONMENT` for the run is set to the environment's name.

To add QA2: add `[environments.qa2]` with its hosts, and flows that open those
hosts. An orchestrator can supply environments too: `JANUS_ENVIRONMENTS_FILE`
names a second file in the same format, merged with this one (hosts are
combined; an environment is production when either file says so). Both files
are re-read on every call, so a change needs no restart.

### Inputs: one flow, every environment

A `goto` written as `<NAME>` (for example `goto: "<MEMBERS_SITE_URL>"`) takes
its URL from the run: `run_flow(inputs={"MEMBERS_SITE_URL": "https://..."})`,
or else from the environment the Web Agent MCP runs in. `list_flows` reports
such names as the flow's `inputs`. The environment named in `run_flow` must
own the site the input points at, like any other site the flow opens. Inputs
are upper-case names; a name that looks like a credential (`PASSWORD`,
`SECRET`, `KEY`, `TOKEN`) is refused — secrets stay in the Web Agent's `.env`.

## Configuration

Read by the Web Agent MCP only; the Web Agent's own settings are unchanged.

| Variable | Default | Meaning |
|----------|---------|---------|
| `WEB_AGENT_MCP_FLOWS_DIR` | `tests` | Folder whose flows may be run (inside the project). `_framework`, `components`, `fixtures`, `baselines`, `generated` are skipped |
| `WEB_AGENT_MCP_ENVIRONMENTS_FILE` | `mcp_server/environments.toml` | The environment allow-list |
| `JANUS_ENVIRONMENTS_FILE` | — | A second allow-list supplied by the orchestrator, merged with the first |
| `WEB_AGENT_MCP_EXECUTIONS_DIR` | `reports/_executions` | One folder per execution |
| `WEB_AGENT_MCP_TIMEOUT_SECONDS` | `1800` | An execution is stopped after this |
| `WEB_AGENT_MCP_STOP_GRACE_SECONDS` | `20` | Time to finish after the interrupt, before terminate and kill |
| `WEB_AGENT_MCP_MAX_CONCURRENT` | `1` | Executions running at once; others wait as `QUEUED` |
| `WEB_AGENT_MCP_HEADLESS` | `true` | Executions run headless whatever `.env` says |
| `WEB_AGENT_MCP_ALLOW_PRODUCTION` | `false` | Allow environments marked `production = true` |

Each execution runs with `ENVIRONMENT=<name>`, `REPORT_DIR=<its folder>/report`,
`BUILD_NAME=<flow title · environment>` (or `metadata.build_name`) and the
run's `inputs` as environment variables.
Everything else — browser, LLM layer, reruns, flow secrets — comes from `.env`
as in any other run.

## An execution's folder

```
reports/_executions/web-2676df41967b/
├── execution.json     the execution's record: flow, environment, state, times, exit code, error
├── progress.json      flows finished / collected (written by pytest)
├── console.log        the run's console output — for debugging, never read for results
└── report/            the normal report: report.html, summary.json, test_cases.json, junit.xml, images/, traces/
```

A finished execution can be read by a later server process. One that was
running when its server stopped is reported `FAILED`: stopping the server
stops its runs.

## Limits (Phase 1)

- stdio transport, one client per server process.
- Progress is per flow, not per step.
- Only catalog flows can be run: no inline Markdown, no `--agent-test` URL.
- Execution folders are not cleaned up automatically.
- If the server process is killed outright (`kill -9`), a run in progress
  finishes on its own and is not tracked.

## Tests

```bash
uv run --extra mcp pytest tests/_framework/test_mcp_adapter.py   # catalog, environments, outcome and result mapping
uv run --extra mcp pytest tests/_framework/test_mcp_server.py    # a real MCP client → server → pytest → Chromium
```

Both are skipped when the `mcp` extra is not installed.
