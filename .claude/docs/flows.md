# Flow Files — parser and runtime facts

User-facing guide: `docs/FLOWS.md`; action reference with examples: `docs/ACTIONS.md`.
This file records what the parser and runner actually do.

## Location and discovery

`tests/<app>/flows/*.md`, shared sub-flows in `tests/<app>/flows/components/`.
`pytest_collect_file` collects any `.md` whose path contains a `flows` directory
(components included — a component file is also a test on its own).
`--flow_file` runs any `.md` anywhere; `--flow` takes inline Markdown and needs at
least one `## section` with steps, otherwise pytest exits with code 4.

## What the parser reads (`app/flow/parser.py`)

- `# H1` → flow name (falls back to the file stem, or `inline`).
- `## Config` → only `timeout` (ms; page default timeout, default 30000). Other keys are ignored.
- Every other `## heading` **except** the metadata sections `config`, `credentials`,
  `expected outcome`, `error scenarios`, `notes` is a run of steps. The section name is
  stored on each `FlowAction.section` and becomes a test of its own in the report.
- List items (`-`, `*`, `1.`) inside a section are steps; `<!-- comments -->` and prose
  lines with an unknown keyword become `WAIT(0)` placeholders (still shown in the report).
- Step pipeline: `_tokenize` (`keyword: rest` or bare keyword) → `_normalize`
  (`ActionType(keyword)`, split on `|`, unquote) → `_validate` (`ACTION_ARG_SPEC` arity —
  a known keyword with the wrong count **raises** `FlowParseError`) → `_build`.
- `FlowDefinition` has exactly `name`, `timeout`, `actions`.

## Runtime semantics

- A failed step marks the rest of its section skipped; the next section runs.
- `<NAME>` arguments resolve from the environment in `_resolve_env_placeholders`
  (engine.py); unset → step fails naming the variable; names containing
  PASSWORD/SECRET/KEY/TOKEN are masked as `******` in `raw` (console + report).
- `run_flow: "ref"` resolves `ref[.md]` relative to the calling file's directory,
  runs on the same page, nests up to 10 levels, detects cycles.
- Sub-flow steps carry `sub_flow=<name>` and render nested under the marker step.

## Writing good flows

- One journey per file; each `## section` a checkable unit (it is a separate test in the report).
- Prefer text/role/label targets; use CSS/XPath (`_is_selector`) when there is no accessible name.
- Secrets only via `<ENV>` placeholders, never literal in the file.
- Put shared sequences in `components/` and call them with `run_flow`.
- `screenshot` after critical state changes.
