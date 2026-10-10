# Plugging Q2E into the sponsors' AI tools

Q2E exposes one governed tool set (`q2e/tools.py`) through three doors, so any AI platform can drive a study
end to end while a human keeps the approval keys.

```
 Azure OpenAI / AI Foundry ─┐                      ┌─ assess_question      ┌─ design_study
 AWS Bedrock (Converse/Agents)┤   REST /api/tools/* │  check_novelty        │  feasibility_probe (blinded)
 ElevenLabs voice agent ─────┤──────────────────────┤  apply_review_fix     │  request_approval  ──► human approves in app
 Anakin / any HTTP workflow ─┤   MCP (stdio)        │  run_analysis (approved plans only)
 Claude / VS Code / Copilot ─┘   python -m q2e mcp  └─ get_results          └─ where_next
```

## Governance (why sponsors can trust it)
- **No approval tool exists.** AI can draft, assess, probe, fix and run *approved* plans; protocol approval,
  statistical sign-off and final sign-off are human-only actions in the app. `run_analysis` refuses unapproved plan hashes.
- **Every AI call is in the ledger** as `ai-tool:<client>` in the project's hash-chained provenance.
- **Privacy scrub** runs on question text before storage; the GitHub/CLI paths force `Q2E_LLM_PROVIDER=offline`.
- **Optional key**: set `Q2E_TOOL_KEY` and clients must send `X-Q2E-Key`.

## Generate the manifests
```bash
python -m q2e integrations --base-url https://YOUR-Q2E-HOST --out integrations/generated
```
| File | Use it in |
|---|---|
| `openai_tools.json` | Azure OpenAI / OpenAI chat-completions `tools=` (see `integrations/examples/azure_openai_agent.py`) |
| `bedrock_converse_tools.json` | AWS Bedrock Converse `toolConfig=` (see `integrations/examples/bedrock_agent.py`) |
| `openapi_tools.json` | Azure AI Foundry agent **OpenAPI tool**; AWS Bedrock **Agents action group** (OpenAPI schema; execute via a Lambda proxy or "return control"); Anakin HTTP nodes; Postman |
| `elevenlabs_server_tools.json` | Template for ElevenLabs Conversational AI webhook tools - a voice research assistant |
| `mcp_config.json` | MCP clients (Claude Desktop/Code, VS Code). Command: `python -m q2e mcp` |

## Hosting the endpoint
The tools need a reachable Q2E server: GitHub Codespaces (make port 8000 public), `docker compose up`, or a
container service (Azure Container Apps / AWS App Runner) built from the repo's `Dockerfile`. Set
`Q2E_PUBLIC_URL` so approval links point at the right host.

## Tested here
- MCP server: handshake (protocol 2025-06-18), `tools/list`, `tools/call` with the official MCP Python client.
- REST: `tests/test_tools_integration.py` designs a study via tools, shows `run_analysis` is refused before human
  approval, approves as a human, runs, reads results, and checks the ledger records the AI actor.
- Azure/Bedrock example agents are provided but need your keys; they were syntax-checked, not run against the clouds.
