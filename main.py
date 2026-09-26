"""
Web Agent CLI — entry point for invoking the agent from the shell or another process.

Usage
-----
  python main.py run <flow.md>             Run a flow file.
  python main.py run --inline '<md>'       Run inline Markdown.
  python main.py run <flow.md> --json      Emit FlowResult JSON to stdout.
  python main.py run <flow.md> --env qa1   Override ENVIRONMENT (report dir).
  python main.py run <flow.md> --profile mobile   Run under the mobile device profile.
  python main.py agent-test https://example.com/members   Autonomous test of one page.
  python main.py lint [paths…] [--report report.json]    Static flow checks; healed steps.

Exit codes
----------
  0  flow passed
  1  flow failed (one or more steps failed)
  2  invocation error (bad args, missing file, parse error, runtime crash)

Multi-agent contract
--------------------
With ``--json``, stdout is exactly one ``FlowResult`` JSON object followed by a
newline, and nothing else. Logs go to stderr. Parent agents can:

    proc = subprocess.run([...], capture_output=True, text=True)
    result = json.loads(proc.stdout)

For in-process orchestration (faster — no browser re-launch), import
``app.agent.orchestrator.Orchestrator`` directly and skip the CLI.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
from pathlib import Path


def _preset_environment(argv: list[str]) -> None:
    """Apply ``--env`` before any ``app.*`` import.

    ENVIRONMENT is read once when ``app.config.settings`` loads (it also loads
    ``.env``), so the override has to be in place before that import runs.
    """
    for i, arg in enumerate(argv):
        if arg == "--env" and i + 1 < len(argv):
            os.environ["ENVIRONMENT"] = argv[i + 1]
        elif arg.startswith("--env="):
            os.environ["ENVIRONMENT"] = arg.partition("=")[2]


_preset_environment(sys.argv[1:])

from app.agent.orchestrator import Orchestrator  # noqa: E402
from app.schemas.actions import FlowResult  # noqa: E402


def _flow_result_to_dict(result: FlowResult) -> dict:
    """JSON-safe dict for a FlowResult, with computed counts merged in."""
    d = dataclasses.asdict(result)
    d["passed"] = result.passed
    d["failed"] = result.failed
    d["skipped"] = result.skipped
    d["last_screenshot"] = result.last_screenshot
    return d


def _configure_logging(json_mode: bool) -> None:
    """Route logs to stderr in JSON mode so stdout stays a single JSON document."""
    handler = logging.StreamHandler(sys.stderr if json_mode else sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web-agent",
        description="Markdown-driven web automation agent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Execute a flow.")
    run.add_argument("flow_file", nargs="?", help="Path to a .md flow file.")
    run.add_argument("--inline", metavar="MARKDOWN", help="Inline Markdown flow content.")
    run.add_argument("--json", dest="as_json", action="store_true",
                     help="Emit FlowResult JSON to stdout; logs go to stderr.")
    run.add_argument("--env", help="Override ENVIRONMENT (report directory).")
    run.add_argument("--name", default="inline",
                     help="Flow name for --inline (default: inline).")
    run.add_argument("--profile", default="desktop",
                     help="Device profile: desktop (default) or mobile.")

    agent = sub.add_parser("agent-test", help="Autonomous test of one page (goto + test_page).")
    agent.add_argument("url", help="Page to test (http:// or https://).")
    agent.add_argument("--depth", type=int, default=1, help="Link hops explore_page may follow (default 1).")
    agent.add_argument("--max-actions", type=int, default=12, help="Clicks the agent may perform (default 12).")
    agent.add_argument("--max-ai-calls", type=int, default=3, help="LLM calls when a provider is configured.")
    agent.add_argument("--destructive", action="store_true",
                       help="Allow controls the safety policy blocks (needs ALLOW_DESTRUCTIVE=true).")
    agent.add_argument("--json", dest="as_json", action="store_true", help="Emit FlowResult JSON to stdout.")
    agent.add_argument("--env", help="Override ENVIRONMENT (report directory).")
    agent.add_argument("--profile", default="desktop", help="Device profile: desktop (default) or mobile.")

    lint = sub.add_parser("lint", help="Static checks over flow files (no browser).")
    lint.add_argument("paths", nargs="*", default=["tests"], help="Flow files or folders (default: tests).")
    lint.add_argument("--report", nargs="+", default=[], metavar="JSON",
                      help="Report JSON file(s): also list steps healed by L2/L3.")
    lint.add_argument("--strict", action="store_true", help="Exit 1 when there are findings.")
    lint.add_argument("--json", dest="as_json", action="store_true", help="Emit findings as JSON.")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    if args.flow_file and args.inline is not None:
        print("error: pass either a flow file or --inline, not both", file=sys.stderr)
        return 2
    if not args.flow_file and args.inline is None:
        print("error: provide a flow file path or --inline <markdown>", file=sys.stderr)
        return 2

    _configure_logging(json_mode=args.as_json)

    try:
        orchestrator = Orchestrator(profile=args.profile)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.inline is not None:
            result = orchestrator.run_markdown(args.inline, name=args.name)
        else:
            path = Path(args.flow_file)
            if not path.exists():
                msg = f"flow file not found: {path}"
                if args.as_json:
                    json.dump({"error": msg, "type": "FileNotFoundError"}, sys.stdout)
                    sys.stdout.write("\n")
                else:
                    print(f"error: {msg}", file=sys.stderr)
                return 2
            result = orchestrator.run_file(path)
    except Exception as exc:
        if args.as_json:
            json.dump({"error": str(exc), "type": type(exc).__name__}, sys.stdout)
            sys.stdout.write("\n")
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        json.dump(_flow_result_to_dict(result), sys.stdout, default=str)
        sys.stdout.write("\n")
    else:
        status = "PASSED" if result.success else "FAILED"
        print(f"\n[{status}] {result.flow_name} — "
              f"{result.passed}/{len(result.steps)} steps passed")
        for step in result.steps:
            if step.evidence and step.evidence.files.get("generated flow"):
                print(f"generated flow: {step.evidence.files['generated flow']}")
        if result.error:
            print(f"error: {result.error}", file=sys.stderr)

    return 0 if result.success else 1


def _cmd_agent_test(args: argparse.Namespace) -> int:
    """Build the two-step flow (goto + test_page) and run it like `run --inline`."""
    url = args.url.strip()
    if not url.startswith(("http://", "https://", "file://")):
        print(f"error: agent-test needs an http(s) URL, got {url!r}", file=sys.stderr)
        return 2
    options = " | ".join(f'"{o}"' for o in (
        f"depth={args.depth}", f"max_actions={args.max_actions}", f"max_ai_calls={args.max_ai_calls}",
        *(["destructive=true"] if args.destructive else []),
    ))
    args.inline = f'# Agent test — {url}\n\n## Steps\n- goto: "{url}"\n- test_page: {options}\n'
    args.flow_file, args.name = None, "agent-test"
    return _cmd_run(args)


def _cmd_lint(args: argparse.Namespace) -> int:
    from app.flow.lint import flow_files, healings, lint, to_dict

    paths = [Path(p) for p in args.paths]
    missing = [str(p) for p in paths if not p.exists()]
    reports = [Path(r) for r in args.report]
    missing += [str(r) for r in reports if not r.is_file()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    findings = lint(paths)
    healed = healings(reports) if reports else []

    if args.as_json:
        json.dump({"findings": to_dict(findings), "healings": healed}, sys.stdout)
        sys.stdout.write("\n")
    else:
        for f in findings:
            print(f)
        for h in healed:
            print(f"{h['file']} › {h['test']}: {h['step']} — healed by {h['healed_by']} "
                  f"in {h['reports']} report(s); update the flow target")
        n_files = len(flow_files(paths))
        print(f"\n{len(findings)} finding(s) in {n_files} flow file(s)"
              + (f", {len(healed)} healed step(s)" if reports else ""))
    return 1 if args.strict and (findings or healed) else 0


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "agent-test":
        return _cmd_agent_test(args)
    if args.command == "lint":
        return _cmd_lint(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
