"""Connecting Amazon Bedrock with an API key: tested before use, never echoed, saved only to the local .env on request."""
import sys
import types

import pytest
from fastapi.testclient import TestClient

from q2e import config, llm, server

KEY = "ABSK" + "Q" * 60 + "wxyz"
ENV = ("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "Q2E_BEDROCK_MODEL_ID", "Q2E_LLM_PROVIDER", "Q2E_DATA_POLICY")


@pytest.fixture
def bedrock(monkeypatch, tmp_path):
    for k in ENV:                         # setenv first so teardown restores the real values (or absence)
        monkeypatch.setenv(k, "x")
        monkeypatch.delenv(k)
    monkeypatch.setenv("Q2E_LLM_PROVIDER", "offline")
    monkeypatch.setitem(sys.modules, "boto3", types.ModuleType("boto3"))      # no AWS SDK or network needed
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(llm, "_bedrock_models", lambda region: ["us.anthropic.bad-model", "us.anthropic.good-model"])
    calls = []

    def complete(self, system, user, max_tokens=2000):
        calls.append(self.model)
        if self.model != "us.anthropic.good-model":
            raise llm.LLMError("ValidationException: The provided model identifier is invalid.")
        return '{"ok": true}'

    monkeypatch.setattr(llm.BedrockProvider, "complete", complete)
    return {"calls": calls, "root": tmp_path}


def test_connect_picks_working_model_and_hides_key(bedrock):
    c = TestClient(server.app)
    r = c.post("/api/ai/bedrock", json={"api_key": KEY, "region": "us-east-1", "remember": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] and body["model"] == "us.anthropic.good-model" and body["key"] == "...wxyz"
    assert KEY not in r.text
    assert bedrock["calls"] == ["us.anthropic.bad-model", "us.anthropic.good-model"]
    assert body["llm"]["enabled"] and body["llm"]["provider"] == "bedrock"
    meta = c.get("/api/meta").text
    assert KEY not in meta and '"provider":"bedrock"' in meta.replace(" ", "")
    assert not (bedrock["root"] / ".env").exists()              # not remembered


def test_remember_writes_local_env_only(bedrock):
    (bedrock["root"] / ".env").write_text("NCBI_EMAIL=me@example.org\nAWS_BEARER_TOKEN_BEDROCK=\n", encoding="utf-8")
    out = llm.bedrock_connect(KEY, "us-west-2", "", remember=True)
    text = (bedrock["root"] / ".env").read_text(encoding="utf-8")
    assert out["remembered"] and f"AWS_BEARER_TOKEN_BEDROCK={KEY}" in text
    assert "NCBI_EMAIL=me@example.org" in text and "AWS_REGION=us-west-2" in text and "Q2E_LLM_PROVIDER=bedrock" in text
    assert text.count("AWS_BEARER_TOKEN_BEDROCK=") == 1
    llm.bedrock_disconnect(forget=True)
    text = (bedrock["root"] / ".env").read_text(encoding="utf-8")
    assert KEY not in text and "Q2E_LLM_PROVIDER=offline" in text
    assert llm.os.environ.get("AWS_BEARER_TOKEN_BEDROCK") is None


def test_failed_key_restores_previous_settings(bedrock, monkeypatch):
    def refuse(self, system, user, max_tokens=2000):
        raise llm.LLMError(f"UnrecognizedClientException: The security token {KEY} is invalid")
    monkeypatch.setattr(llm.BedrockProvider, "complete", refuse)
    with pytest.raises(llm.LLMError) as e:
        llm.bedrock_connect(KEY, "us-east-1", "")
    assert KEY not in str(e.value)                               # never echoed, even inside AWS's message
    assert "did not accept this key" in str(e.value)            # a refused key stops after the first model
    assert llm.os.environ.get("AWS_BEARER_TOKEN_BEDROCK") is None
    assert llm.os.environ.get("Q2E_LLM_PROVIDER") == "offline"


@pytest.mark.parametrize("key,region,msg", [
    ("short", "us-east-1", "422"),
    ("AKIA" + "A" * 30, "us-east-1", "access key ID"),
    (KEY, "mars-1", "not an AWS region"),
    ("ABSK with spaces in the middle of it", "us-east-1", "no spaces"),
])
def test_rejects_bad_input(bedrock, key, region, msg):
    r = TestClient(server.app).post("/api/ai/bedrock", json={"api_key": key, "region": region})
    assert r.status_code in (400, 422) and (msg in r.text or str(r.status_code) == msg)
    assert bedrock["calls"] == []


def _req(host, **headers):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=host), headers=headers)


def test_remote_browser_needs_the_terminal_setup_code(bedrock, monkeypatch):
    monkeypatch.setitem(server._SETUP, "fails", 0)
    monkeypatch.setenv("Q2E_SETUP_CODE", "4821-0937")
    server._may_set_keys(_req("127.0.0.1"))                                   # same computer: no code needed
    for req in (_req("203.0.113.9"), _req("127.0.0.1", **{"x-forwarded-for": "203.0.113.9"})):   # remote / Codespaces proxy
        with pytest.raises(Exception) as e:
            server._may_set_keys(req)
        assert e.value.status_code == 403 and "python -m q2e setup-code" in e.value.detail
    for typed in ("4821-0937", "48210937", " 4821 0937 "):                    # dash and spaces do not matter
        server._may_set_keys(_req("203.0.113.9", **{"x-bedside-setup-code": typed}))
    with pytest.raises(Exception) as e:
        server._may_set_keys(_req("203.0.113.9", **{"x-bedside-setup-code": "1234-5678"}))
    assert "9 tries left" in e.value.detail
    for _ in range(9):
        with pytest.raises(Exception):
            server._may_set_keys(_req("203.0.113.9", **{"x-bedside-setup-code": "0000-0000"}))
    with pytest.raises(Exception) as e:                                         # locked after 10 wrong tries
        server._may_set_keys(_req("203.0.113.9", **{"x-bedside-setup-code": "4821-0937"}))
    assert e.value.status_code == 429


def test_setup_code_is_stable(tmp_path, monkeypatch):
    from q2e import access
    monkeypatch.delenv("Q2E_SETUP_CODE", raising=False)
    monkeypatch.setattr(access.settings, "workspace", tmp_path)
    first = access.setup_code()
    assert first == access.setup_code() and (tmp_path / ".setup_code").read_text() == first   # same after a restart
    assert access.check(first.replace("-", "")) and not access.check("")


def test_meta_says_when_a_code_is_needed(bedrock):
    from q2e import access
    c = TestClient(server.app)
    assert c.get("/api/meta").json()["ai_setup"]["needs_code"] is False
    assert c.get("/api/meta", headers={"x-forwarded-for": "203.0.113.9"}).json()["ai_setup"]["needs_code"] is True
    assert access.setup_code() not in c.get("/api/meta").text


def test_example_env_holds_no_key():
    text = (config.ROOT / ".env.example").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("AWS_BEARER_TOKEN_BEDROCK="))
    assert line.strip() == "AWS_BEARER_TOKEN_BEDROCK="


def test_error_kinds_and_messages(bedrock, monkeypatch):
    assert llm._bedrock_error_kind("Bedrock: Failed to connect to proxy URL") == "network"
    assert llm._bedrock_error_kind("UnrecognizedClientException: invalid security token") == "key"
    assert llm._bedrock_error_kind("AccessDeniedException: You don't have access to the model") == "model"
    monkeypatch.setattr(llm, "_bedrock_models", lambda region: ["us.anthropic.bad-model", "us.anthropic.bad2"])
    with pytest.raises(llm.LLMError) as e:
        llm.bedrock_connect(KEY, "us-east-1", "")
    assert "The key works, but no model answered" in str(e.value) and "us.anthropic.bad2" in str(e.value)
