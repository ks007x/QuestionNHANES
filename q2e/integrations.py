"""Generate tool manifests so the sponsors' AI platforms can call BEDSIDE.

  python -m q2e integrations --base-url https://YOUR-Q2E-HOST --out integrations/generated

Writes, from the single tool registry in q2e/tools.py:
  openai_tools.json              Azure OpenAI / OpenAI chat-completions `tools` (function calling)
  bedrock_converse_tools.json    AWS Bedrock Converse API `toolConfig`
  openapi_tools.json             OpenAPI 3.0 for Azure AI Foundry agents (OpenAPI tool), AWS Bedrock Agents
                                 action groups, Anakin HTTP nodes and any REST client
  elevenlabs_server_tools.json   template for ElevenLabs Conversational AI webhook "server tools" (voice assistant);
                                 field names follow ElevenLabs' tool editor - adjust if their schema changes
  mcp_config.json                MCP client config (Claude Desktop/Code, VS Code) for the stdio server
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__, tools

ROOT = Path(__file__).resolve().parent.parent


def openai_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": tools.json_schema(t)}} for t in tools.TOOLS]


def bedrock_tools() -> dict:
    return {"tools": [{"toolSpec": {"name": t["name"], "description": t["description"],
                                    "inputSchema": {"json": tools.json_schema(t)}}} for t in tools.TOOLS]}


def openapi(base_url: str) -> dict:
    paths = {}
    for t in tools.TOOLS:
        paths[f"/api/tools/{t['name']}"] = {"post": {
            "operationId": t["name"], "summary": t["description"][:120], "description": t["description"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": tools.json_schema(t)}}},
            "responses": {"200": {"description": "Tool result", "content": {"application/json": {"schema": {"type": "object"}}}},
                          "400": {"description": "Tool error (e.g., plan not approved by a human)"}},
            "security": [{"q2eKey": []}]}}
    return {"openapi": "3.0.3",
            "info": {"title": "BEDSIDE AI Research Copilot tools", "version": __version__,
                     "description": "Clinical question -> reproducible NHANES study. Humans approve; AI drafts, checks and runs approved plans."},
            "servers": [{"url": base_url.rstrip("/")}], "paths": paths,
            "components": {"securitySchemes": {"q2eKey": {"type": "apiKey", "in": "header", "name": "X-Q2E-Key"}}}}


def elevenlabs_tools(base_url: str) -> list[dict]:
    voice = ["assess_question", "design_study", "check_novelty", "get_plan", "request_approval", "get_results", "where_next"]
    out = []
    for t in tools.TOOLS:
        if t["name"] not in voice:
            continue
        out.append({"type": "webhook", "name": t["name"], "description": t["description"],
                    "api_schema": {"url": f"{base_url.rstrip('/')}/api/tools/{t['name']}", "method": "POST",
                                   "request_headers": {"X-Q2E-Key": "REPLACE_WITH_Q2E_TOOL_KEY (store as a secret in ElevenLabs)"},
                                   "request_body_schema": {"type": "object", "required": t["required"],
                                                           "properties": {k: {"type": v.get("type", "string"), "description": v.get("description", k)}
                                                                          for k, v in t["properties"].items()}}}})
    return out


def mcp_config() -> dict:
    return {"mcpServers": {"q2e": {"command": "python3", "args": ["-m", "q2e", "mcp"], "cwd": "<absolute path to your clone of this repo>",
                                   "env": {"Q2E_PUBLIC_URL": "http://127.0.0.1:8000"}}}}


def write_all(base_url: str, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {"openai_tools.json": openai_tools(), "bedrock_converse_tools.json": bedrock_tools(),
             "openapi_tools.json": openapi(base_url), "elevenlabs_server_tools.json": elevenlabs_tools(base_url),
             "mcp_config.json": mcp_config()}
    written = []
    for name, obj in files.items():
        p = out / name
        p.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        written.append(p)
    return written
