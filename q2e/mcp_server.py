"""Model Context Protocol server for Q2E (stdio, JSON-RPC 2.0, no third-party dependency).

Lets MCP-capable assistants (Claude Desktop/Code, VS Code/GitHub Copilot agents, Azure AI Foundry and AWS agents via
their MCP connectors) use the Q2E tools. Run:  python -m q2e mcp
Messages are newline-delimited JSON on stdin/stdout; logs go to stderr.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import __version__, tools

SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = ("Q2E turns clinical research questions into reproducible, survey-weighted NHANES studies. Typical flow: "
                "assess_question -> design_study -> check_novelty / feasibility_probe / apply_review_fix -> request_approval "
                "(a human must approve in the app) -> run_analysis -> get_results -> where_next. Never describe results as causal.")


def _tool_list() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "inputSchema": tools.json_schema(t)} for t in tools.TOOLS]


def handle(msg: dict, client: str = "mcp") -> dict | None:
    mid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}
    if mid is None:                       # notification (e.g. notifications/initialized)
        return None
    try:
        if method == "initialize":
            want = params.get("protocolVersion")
            return _ok(mid, {"protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                             "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": {"name": "q2e", "title": "Q2E AI Research Copilot", "version": __version__},
                             "instructions": INSTRUCTIONS})
        if method == "ping":
            return _ok(mid, {})
        if method == "tools/list":
            return _ok(mid, {"tools": _tool_list()})
        if method == "tools/call":
            name = params.get("name")
            try:
                result = tools.call(name, params.get("arguments") or {}, client=client)
                return _ok(mid, {"content": [{"type": "text", "text": tools.as_text(result)}],
                                 "structuredContent": result if isinstance(result, dict) else {"result": result}, "isError": False})
            except tools.ToolError as e:
                return _ok(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            except Exception as e:  # noqa: BLE001
                return _ok(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
        return _err(mid, -32601, f"Method not found: {method}")
    except Exception as e:  # noqa: BLE001
        return _err(mid, -32603, str(e))


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve_stdio() -> None:
    client = "mcp"
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_err(None, -32700, "Parse error")) + "\n")
            sys.stdout.flush()
            continue
        if msg.get("method") == "initialize":
            client = "mcp:" + str(((msg.get("params") or {}).get("clientInfo") or {}).get("name", "client"))
        msgs = msg if isinstance(msg, list) else [msg]
        for m in msgs:
            resp = handle(m, client)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, default=str) + "\n")
                sys.stdout.flush()
