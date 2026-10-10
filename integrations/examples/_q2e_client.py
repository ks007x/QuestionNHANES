"""Shared helper: call a Q2E tool over REST (the same tools the MCP server exposes)."""
import json
import os

import httpx

Q2E_URL = os.environ.get("Q2E_URL", "http://127.0.0.1:8000").rstrip("/")
HEADERS = {"X-Q2E-Key": os.environ.get("Q2E_TOOL_KEY", ""), "X-Q2E-Client": os.environ.get("Q2E_CLIENT_NAME", "example-agent")}


def tool_specs() -> list[dict]:
    return httpx.get(f"{Q2E_URL}/api/tools", timeout=30).json()["tools"]


def call_tool(name: str, args: dict) -> str:
    r = httpx.post(f"{Q2E_URL}/api/tools/{name}", json=args, headers=HEADERS, timeout=900)
    return json.dumps(r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.text})[:20000]


SYSTEM = ("You are a research assistant using Q2E to turn clinical questions into reproducible NHANES studies. "
          "Assess the question, design the study, check novelty, apply the reviewer's fixes when sensible, then call "
          "request_approval and tell the user to approve in the Q2E app - you cannot approve. Only call run_analysis after "
          "the user confirms approval. Report associations, never causal claims.")
