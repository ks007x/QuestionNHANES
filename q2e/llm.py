"""Pluggable LLM providers. All return plain text; `complete_json` extracts a JSON object.

Providers
  offline       - no LLM; rule-based agents only (default, nothing leaves the machine)
  anthropic     - Anthropic Messages API            (ANTHROPIC_API_KEY, Q2E_ANTHROPIC_MODEL)
  azure_openai  - Azure OpenAI chat completions     (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT)
  bedrock       - AWS Bedrock Converse API (boto3)  (AWS credentials, Q2E_BEDROCK_MODEL_ID, AWS_REGION)
  openai        - any OpenAI-compatible endpoint    (OPENAI_API_KEY, OPENAI_BASE_URL, Q2E_OPENAI_MODEL)
  ollama        - local model via Ollama's OpenAI-compatible API (OLLAMA_BASE_URL, Q2E_OLLAMA_MODEL)
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

import httpx

from . import privacy


class LLMError(RuntimeError):
    pass


@dataclass
class LLMCall:
    provider: str
    model: str
    agent: str
    payload_sha256: str
    seconds: float
    ok: bool
    error: str | None = None


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k, d).strip()


class BaseProvider:
    name = "base"
    model = ""

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, ""


class OfflineProvider(BaseProvider):
    name = "offline"
    model = "rules"

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        raise LLMError("Offline mode - rule-based agents only")


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self):
        self.key = _env("ANTHROPIC_API_KEY")
        self.model = _env("Q2E_ANTHROPIC_MODEL", "claude-sonnet-5-5")

    def available(self):
        return (bool(self.key), "ANTHROPIC_API_KEY not set")

    def complete(self, system, user, max_tokens=2000):
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120,
                       headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": self.model, "max_tokens": max_tokens, "system": system,
                             "messages": [{"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise LLMError(f"Anthropic API {r.status_code}: {r.text[:300]}")
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


class AzureOpenAIProvider(BaseProvider):
    name = "azure_openai"

    def __init__(self):
        self.endpoint = _env("AZURE_OPENAI_ENDPOINT").rstrip("/")
        self.key = _env("AZURE_OPENAI_API_KEY")
        self.model = _env("AZURE_OPENAI_DEPLOYMENT")
        self.version = _env("AZURE_OPENAI_API_VERSION", "2024-10-21")

    def available(self):
        ok = bool(self.endpoint and self.key and self.model)
        return ok, "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / AZURE_OPENAI_DEPLOYMENT not set"

    def complete(self, system, user, max_tokens=2000):
        url = f"{self.endpoint}/openai/deployments/{self.model}/chat/completions?api-version={self.version}"
        r = httpx.post(url, timeout=120, headers={"api-key": self.key, "content-type": "application/json"},
                       json={"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                             "max_tokens": max_tokens, "temperature": 0.1})
        if r.status_code >= 400:
            raise LLMError(f"Azure OpenAI {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


class BedrockProvider(BaseProvider):
    name = "bedrock"

    def __init__(self):
        self.model = _env("Q2E_BEDROCK_MODEL_ID", "anthropic.claude-sonnet-5-5")
        self.region = _env("AWS_REGION", "us-east-1")

    def available(self):
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False, "boto3 not installed (pip install boto3)"
        return True, ""

    def complete(self, system, user, max_tokens=2000):
        import boto3
        client = boto3.client("bedrock-runtime", region_name=self.region)
        resp = client.converse(modelId=self.model, system=[{"text": system}],
                               messages=[{"role": "user", "content": [{"text": user}]}],
                               inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1})
        return "".join(c.get("text", "") for c in resp["output"]["message"]["content"])


class OpenAICompatibleProvider(BaseProvider):
    name = "openai"

    def __init__(self, base_url: str | None = None, key: str | None = None, model: str | None = None, name: str = "openai"):
        self.name = name
        self.base = (base_url or _env("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.key = key if key is not None else _env("OPENAI_API_KEY")
        self.model = model or _env("Q2E_OPENAI_MODEL", "gpt-4o-mini")

    def available(self):
        return (bool(self.key) or self.name == "ollama", "OPENAI_API_KEY not set")

    def complete(self, system, user, max_tokens=2000):
        headers = {"content-type": "application/json"}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        r = httpx.post(f"{self.base}/chat/completions", timeout=180, headers=headers,
                       json={"model": self.model, "temperature": 0.1, "max_tokens": max_tokens,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise LLMError(f"{self.name} {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


def get_provider(name: str | None = None) -> BaseProvider:
    name = (name or _env("Q2E_LLM_PROVIDER", "offline")).lower()
    if name == "anthropic":
        return AnthropicProvider()
    if name in ("azure", "azure_openai"):
        return AzureOpenAIProvider()
    if name == "bedrock":
        return BedrockProvider()
    if name == "openai":
        return OpenAICompatibleProvider()
    if name == "ollama":
        return OpenAICompatibleProvider(base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434/v1"), key="",
                                        model=_env("Q2E_OLLAMA_MODEL", "llama3.1"), name="ollama")
    return OfflineProvider()


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise LLMError("No JSON object in model output")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise LLMError("Unterminated JSON object in model output")


class LLMClient:
    """Governed LLM access: policy check, identifier scrubbing, audit log."""

    def __init__(self, provider: str | None = None):
        self.provider = get_provider(provider)
        self.calls: list[LLMCall] = []

    @property
    def enabled(self) -> bool:
        if self.provider.name == "offline":
            return False
        ok, _ = self.provider.available()
        allowed, _ = privacy.provider_allowed(self.provider.name)
        return ok and allowed

    def status(self) -> dict:
        ok, why = self.provider.available()
        allowed, msg = privacy.provider_allowed(self.provider.name)
        return {"provider": self.provider.name, "model": self.provider.model, "configured": ok, "why": "" if ok else why,
                "policy_allowed": allowed, "policy_message": msg, "enabled": self.enabled}

    def complete_json(self, agent: str, system: str, user: str, max_tokens: int = 2000) -> dict:
        if not self.enabled:
            raise LLMError("LLM disabled")
        user_clean, _ = privacy.scrub(user)
        fp = privacy.payload_fingerprint({"system": system, "user": user_clean})
        t0 = time.time()
        try:
            out = self.provider.complete(system, user_clean, max_tokens=max_tokens)
            data = extract_json(out)
            self.calls.append(LLMCall(self.provider.name, self.provider.model, agent, fp, round(time.time() - t0, 2), True))
            return data
        except Exception as e:  # noqa: BLE001
            self.calls.append(LLMCall(self.provider.name, self.provider.model, agent, fp, round(time.time() - t0, 2), False, str(e)[:300]))
            raise LLMError(str(e)) from e
