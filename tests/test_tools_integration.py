"""AI-tool integration: registry, REST, MCP, manifests, and the human-approval gate."""
import json

from fastapi.testclient import TestClient

from q2e import integrations, mcp_server, tools
from q2e.server import app
from conftest import requires_r

client = TestClient(app)


def test_registry_has_no_approval_tool():
    names = {t["name"] for t in tools.TOOLS}
    assert "request_approval" in names and not ({"approve", "signoff", "approve_protocol"} & names)


def test_manifests_are_consistent(tmp_path):
    files = integrations.write_all("https://q2e.example.org", tmp_path)
    oa = json.loads((tmp_path / "openapi_tools.json").read_text())
    assert len(oa["paths"]) == len(tools.TOOLS) and oa["servers"][0]["url"] == "https://q2e.example.org"
    br = json.loads((tmp_path / "bedrock_converse_tools.json").read_text())
    assert br["tools"][0]["toolSpec"]["inputSchema"]["json"]["type"] == "object"
    assert len(files) == 5


def test_mcp_handshake_and_list():
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["protocolVersion"] == "2025-03-26" and r["result"]["capabilities"]["tools"]
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    lst = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in lst} == {t["name"] for t in tools.TOOLS}
    bad = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "approve", "arguments": {}}})
    assert bad["result"]["isError"]


def test_rest_assess_and_hard_stop():
    r = client.post("/api/tools/assess_question", json={"question": "Is waist circumference associated with HbA1c?"})
    assert r.status_code == 200 and "verdict" in r.json()
    r = client.post("/api/tools/design_study", json={"question": "What is the incidence of C. difficile infection after allogeneic HCT?", "data_source": "synthetic"})
    assert r.status_code == 200 and r.json().get("hard_stop")


@requires_r
def test_ai_cannot_run_until_human_approves():
    d = client.post("/api/tools/design_study", json={"question": "Is waist circumference associated with HbA1c in adults?", "data_source": "synthetic"}).json()
    pid = d["project_id"]
    r = client.post("/api/tools/run_analysis", json={"project_id": pid})
    assert r.status_code == 400 and "not approved" in r.json()["error"]
    plan = client.get(f"/api/projects/{pid}").json()["plan"]
    for i in plan["review"]:
        if (i.get("fix") or {}).get("op") == "acknowledge":
            client.post(f"/api/projects/{pid}/edit", json={"fix": {**i["fix"], "by": "Human PI"}})
    a = client.post(f"/api/projects/{pid}/approve", json={"by": "Human PI"})
    assert a.status_code == 200, a.text
    r = client.post("/api/tools/run_analysis", json={"project_id": pid})
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    res = client.post("/api/tools/get_results", json={"project_id": pid}).json()
    assert res["primary"]["est"] is not None and res["synthetic_data"] is True
    ledger = client.get(f"/api/projects/{pid}/provenance").json()
    assert any(str(e.get("actor", "")).startswith("ai-tool:") for e in (ledger.get("events") or ledger))
