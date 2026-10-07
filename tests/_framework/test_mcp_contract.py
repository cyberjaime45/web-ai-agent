"""The MCP contract (execution/1) does not break by accident.

Every tool's inputs and outputs are compared with the committed snapshot in
``contract/<contract>.json``. Adding is compatible: a new tool, a new optional
input, a new output field. Breaking fails here: a tool, input or output field
removed or renamed, a type changed, an input made required, or the value list
of an output enum (an execution status, an error code) changed — a client may
switch on those. A deliberate breaking change is a new contract version
(docs/MCP.md → Compatibility). After an additive change, refresh the snapshot:

    WEB_AGENT_UPDATE_CONTRACT=1 pytest tests/_framework/test_mcp_contract.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the Web Agent MCP needs the `mcp` extra (uv sync --extra mcp)")

from mcp_server.config import load_config
from mcp_server.models import Capabilities
from mcp_server.server import build_server

CONTRACT = Capabilities.model_fields["contract"].default          # "execution/1"
SNAPSHOT = Path(__file__).parent / "contract" / f"{CONTRACT.replace('/', '-')}.json"


def _type(node: dict, defs: dict) -> str:
    node = defs.get(node["$ref"].rsplit("/", 1)[-1], {}) if "$ref" in node else node
    if "enum" in node:
        return "enum[" + ",".join(map(str, node["enum"])) + "]"
    if "anyOf" in node:
        return "|".join(sorted({_type(n, defs) for n in node["anyOf"]}))
    return node.get("type", "any")


def _fields(node: dict, defs: dict, prefix: str = "", seen: frozenset = frozenset()) -> dict[str, str]:
    """Every output path → its type: ``summary.passed: integer``, ``tests[].status: string``."""
    out: dict[str, str] = {}
    ref = node.get("$ref", "").rsplit("/", 1)[-1]
    if ref in seen:
        return out
    node, seen = (defs[ref], seen | {ref}) if ref else (node, seen)
    for option in node.get("anyOf", []):
        out.update(_fields(option, defs, prefix, seen))
    for name, child in node.get("properties", {}).items():
        path = f"{prefix}{name}"
        out[path] = _type(child, defs)
        out.update(_fields(child, defs, path + ".", seen))
        for item in [child.get("items")] + [o.get("items") for o in child.get("anyOf", [])]:
            if item:
                out.update(_fields(item, defs, path + "[].", seen))
    return out


def _contract() -> dict:
    tools = asyncio.run(build_server(load_config()).list_tools())
    contract = {}
    for tool in sorted(tools, key=lambda t: t.name):
        schema, required = tool.inputSchema or {}, set((tool.inputSchema or {}).get("required", []))
        defs = schema.get("$defs", {})
        out = tool.outputSchema or {}
        contract[tool.name] = {
            "inputs": {name: {"type": _type(p, defs), "required": name in required}
                       for name, p in sorted(schema.get("properties", {}).items())},
            "outputs": dict(sorted(_fields(out, out.get("$defs", {})).items())),
        }
    return contract


def test_the_mcp_interface_keeps_its_contract():
    now = _contract()
    if os.environ.get("WEB_AGENT_UPDATE_CONTRACT"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps({"contract": CONTRACT, "tools": now}, indent=2) + "\n", encoding="utf-8")
    assert SNAPSHOT.is_file(), f"no snapshot for {CONTRACT}: run with WEB_AGENT_UPDATE_CONTRACT=1 and commit it"
    then = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["tools"]

    broken: list[str] = []
    for tool, was in then.items():
        if tool not in now:
            broken.append(f"tool {tool} removed")
            continue
        inputs, outputs = now[tool]["inputs"], now[tool]["outputs"]
        for name, spec in was["inputs"].items():
            if name not in inputs:
                broken.append(f"{tool}: input {name} removed")
            elif inputs[name]["type"] != spec["type"]:
                broken.append(f"{tool}: input {name} is {inputs[name]['type']}, was {spec['type']}")
            elif inputs[name]["required"] and not spec["required"]:
                broken.append(f"{tool}: input {name} became required")
        broken += [f"{tool}: new input {name} is required" for name, spec in inputs.items()
                   if name not in was["inputs"] and spec["required"]]
        for path, kind in was["outputs"].items():
            if path not in outputs:
                broken.append(f"{tool}: output {path} removed")
            elif outputs[path] != kind:
                broken.append(f"{tool}: output {path} is {outputs[path]}, was {kind}")
    assert not broken, (f"breaking changes to {CONTRACT} — keep them compatible, or release a new contract "
                        f"version (docs/MCP.md → Compatibility):\n  " + "\n  ".join(broken))
