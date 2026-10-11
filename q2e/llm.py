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

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

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
        self.model = _env("Q2E_BEDROCK_MODEL_ID")
        self.region = _env("AWS_REGION", "us-east-1")

    def available(self):
        try:
            import boto3
        except ImportError:
            return False, "boto3 not installed (pip install boto3)"
        if not self.model:
            return False, "Q2E_BEDROCK_MODEL_ID not set (run: python -m q2e bedrock-check)"
        if not _env("AWS_BEARER_TOKEN_BEDROCK") and boto3.Session().get_credentials() is None:
            return False, ("No AWS credentials (set AWS_BEARER_TOKEN_BEDROCK, or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / "
                           "AWS_SESSION_TOKEN in .env)")
        return True, ""

    def complete(self, system, user, max_tokens=2000):
        import boto3
        from botocore.config import Config
        client = boto3.client("bedrock-runtime", region_name=self.region,
                              config=Config(read_timeout=120, retries={"max_attempts": 2}))
        cfg = {"maxTokens": max_tokens, "temperature": 0.1}
        # hidden "thinking" makes newer Claude models slow and uses up maxTokens before the JSON answer is written
        extra = {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}} if "anthropic" in self.model else {}
        for _ in range(4):
            try:
                kw = {"additionalModelRequestFields": extra} if extra else {}
                resp = client.converse(modelId=self.model, system=[{"text": system}],
                                       messages=[{"role": "user", "content": [{"text": user}]}], inferenceConfig=cfg, **kw)
                break
            except Exception as e:  # noqa: BLE001 - botocore raises many types; show the AWS message
                err = str(e)
                if "temperature" in err and "temperature" in cfg:
                    cfg = {"maxTokens": max_tokens}     # newer models reject a temperature setting
                    continue
                if extra and "ValidationException" in err and any(f in err for f in ("thinking", "output_config", "effort", "Extra inputs")):
                    extra = {k: v for k, v in extra.items() if k not in err} if any(k in err for k in extra) else {}
                    continue
                raise LLMError(f"Bedrock: {e}") from e
        else:
            raise LLMError("Bedrock: the model rejected every request setting")
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


def bedrock_check() -> int:
    """Print what this AWS login can use on Bedrock and test the model in Q2E_BEDROCK_MODEL_ID."""
    try:
        import boto3
    except ImportError:
        print("boto3 is not installed. Run: pip install boto3")
        return 1
    region = _env("AWS_REGION", "us-east-1")
    if not _env("AWS_BEARER_TOKEN_BEDROCK") and boto3.Session().get_credentials() is None:
        print("No AWS credentials found. In the .env file, put either your Bedrock API key in AWS_BEARER_TOKEN_BEDROCK, "
              "or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN if given), then run this again.")
        return 1
    print(f"AWS region: {region}")
    bed = boto3.client("bedrock", region_name=region)
    try:
        profiles = bed.list_inference_profiles().get("inferenceProfileSummaries", [])
        print("\nModels to use through an inference profile (copy the id into Q2E_BEDROCK_MODEL_ID):")
        for p in profiles:
            print(f"  {p['inferenceProfileId']:<60} {p.get('inferenceProfileName', '')}")
    except Exception as e:  # noqa: BLE001
        print(f"(could not list inference profiles: {e})")
    try:
        models = bed.list_foundation_models(byOutputModality="TEXT").get("modelSummaries", [])
        on_demand = [m for m in models if "ON_DEMAND" in m.get("inferenceTypesSupported", [])]
        print("\nModels that can be called directly:")
        for m in on_demand:
            print(f"  {m['modelId']:<60} {m.get('providerName', '')} {m.get('modelName', '')}")
    except Exception as e:  # noqa: BLE001
        print(f"(could not list models: {e})")
    model = _env("Q2E_BEDROCK_MODEL_ID")
    if not model:
        print("\nQ2E_BEDROCK_MODEL_ID is empty. Pick an id above (a Claude model is best), put it in .env, run this again.")
        return 1
    print(f"\nTesting {model} ...")
    try:
        text = BedrockProvider().complete("Reply with JSON only.", 'Return {"ok": true}.', max_tokens=50)
        print("Model replied:", text.strip()[:200])
        print("Bedrock works. Set Q2E_LLM_PROVIDER=bedrock in .env and restart the server.")
        return 0
    except LLMError as e:
        print(f"The test call failed: {e}\nIf it says 'access denied', enable this model under Bedrock > Model access in "
              "the AWS console, or try another id from the list.")
        return 1


# ------------------------------------------------------------------ connect Bedrock with an API key (web app or CLI)
_BEDROCK_ENV = ("AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "Q2E_BEDROCK_MODEL_ID", "Q2E_LLM_PROVIDER")
# tried in order when no model id is given and the account's model list cannot be read (geo prefix added per region)
BEDROCK_MODEL_CANDIDATES = ("anthropic.claude-sonnet-4-5-20250929-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0",
                            "anthropic.claude-sonnet-4-20250514-v1:0", "anthropic.claude-3-7-sonnet-20250219-v1:0",
                            "anthropic.claude-3-5-haiku-20241022-v1:0")
_REGION_RX = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d$")


def mask_secret(v: str) -> str:
    v = v or ""
    return f"...{v[-4:]}" if len(v) > 8 else "***"


def _geo(region: str) -> str:
    return {"us": "us", "eu": "eu", "ap": "apac", "ca": "us", "sa": "us"}.get(region.split("-")[0], "us")


def _bedrock_models(region: str) -> list[str]:
    """Claude models this key can call: the account's inference profiles when they can be listed, else known ids."""
    found: list[str] = []
    try:
        import boto3
        profiles = boto3.client("bedrock", region_name=region).list_inference_profiles().get("inferenceProfileSummaries", [])
        ids = [p["inferenceProfileId"] for p in profiles if "anthropic.claude" in p.get("inferenceProfileId", "")]
        found = sorted(ids, key=lambda i: (0 if "sonnet" in i else 1 if "haiku" in i else 2, i), reverse=False)
    except Exception:  # noqa: BLE001 - listing is optional; some keys may only call models
        pass
    geo = _geo(region)
    return found + [f"{geo}.{m}" for m in BEDROCK_MODEL_CANDIDATES if f"{geo}.{m}" not in found]


def _write_env(updates: dict[str, str | None]) -> Path:
    """Set (or with None, blank) keys in the local .env file, which git ignores. Other lines are kept as they are."""
    from .config import ROOT
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8-sig").splitlines() if env.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in updates:
            lines[i] = f"{k}={updates[k] or ''}"
            seen.add(k)
    lines += [f"{k}={v or ''}" for k, v in updates.items() if k not in seen]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env, 0o600)       # readable by this user only
    except OSError:
        pass
    return env


def bedrock_connect(api_key: str, region: str = "", model_id: str = "", remember: bool = False) -> dict:
    """Use a Bedrock API key for this server. The key is tested with one tiny request before it is kept; on failure the
    previous settings are restored. It is never returned, logged or written anywhere except (if asked) the local .env."""
    key = (api_key or "").strip().strip('"').strip("'")
    region = (region or _env("AWS_REGION", "us-east-1")).strip()
    model_id = (model_id or "").strip()
    if len(key) < 20 or any(c.isspace() for c in key):
        raise LLMError("That does not look like a Bedrock API key (one long value, no spaces). Create one in the AWS "
                       "console: Amazon Bedrock > API keys.")
    if key.startswith("AKIA") or key.startswith("ASIA"):
        raise LLMError("That is an AWS access key ID, not a Bedrock API key. Paste the Bedrock API key (from Amazon Bedrock > "
                       "API keys), or put access keys in the .env file.")
    if not _REGION_RX.match(region):
        raise LLMError(f"'{region}' is not an AWS region (for example us-east-1).")
    if model_id and not re.match(r"^[A-Za-z0-9.:\-/_]{3,200}$", model_id):
        raise LLMError("The model id has unexpected characters.")
    allowed, msg = privacy.provider_allowed("bedrock")
    if not allowed:
        raise LLMError(msg)
    try:
        import boto3  # noqa: F401
    except ImportError as e:
        raise LLMError("boto3 is not installed on this computer (pip install boto3).") from e
    old = {k: os.environ.get(k) for k in _BEDROCK_ENV}

    def restore() -> None:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    os.environ.update({"AWS_BEARER_TOKEN_BEDROCK": key, "AWS_REGION": region})
    tried, last = [], ""
    try:
        for m in ([model_id] if model_id else _bedrock_models(region))[:8]:
            os.environ["Q2E_BEDROCK_MODEL_ID"] = m
            tried.append(m)
            try:
                BedrockProvider().complete("Reply with JSON only.", 'Return {"ok": true}.', max_tokens=20)
            except LLMError as e:
                last = str(e).replace(key, "***")
                kind = _bedrock_error_kind(last)
                if kind != "model":
                    break   # the key or the network failed: other models will not help
                continue
            os.environ["Q2E_LLM_PROVIDER"] = "bedrock"
            saved = _write_env({"AWS_BEARER_TOKEN_BEDROCK": key, "AWS_REGION": region, "Q2E_BEDROCK_MODEL_ID": m,
                                "Q2E_LLM_PROVIDER": "bedrock"}) if remember else None
            return {"connected": True, "provider": "bedrock", "model": m, "region": region, "key": mask_secret(key),
                    "remembered": bool(saved), "tried": tried}
    except BaseException:
        restore()
        raise
    restore()                          # every attempt failed: put the previous settings back
    kind = _bedrock_error_kind(last)
    if kind == "network":
        raise LLMError(f"Could not reach Amazon Bedrock from this computer. Check the internet connection, VPN or proxy, "
                       f"then try again. ({last[:200]})")
    if kind == "key":
        raise LLMError(f"AWS did not accept this key: it may be mistyped, expired (short-term keys last hours) or deleted. "
                       f"Generate a new one under Amazon Bedrock > API keys. ({last[:200]})")
    raise LLMError(f"The key works, but no model answered ({last[:240] or 'no reply'}). Tried: {', '.join(tried) or '-'}. "
                   f"Enable an Anthropic Claude model under Amazon Bedrock > Model access in {region}, or paste a model id "
                   "from: python -m q2e bedrock-check.")


def _bedrock_error_kind(msg: str) -> str:
    m = msg.lower()
    if any(w in m for w in ("failed to connect", "could not connect", "endpointconnectionerror", "timed out", "timeout",
                            "proxy", "name resolution", "connection refused", "connection reset")):
        return "network"
    if any(w in m for w in ("unrecognizedclient", "security token", "expired", "invalid api key", "bearer token",
                            "signature", "invalidclienttokenid")):
        return "key"
    return "model"


def bedrock_disconnect(forget: bool = False) -> dict:
    """Stop using Bedrock on this server (back to rule-based agents); with forget, also blank the key in .env."""
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    os.environ["Q2E_LLM_PROVIDER"] = "offline"
    if forget:
        _write_env({"AWS_BEARER_TOKEN_BEDROCK": None, "Q2E_LLM_PROVIDER": "offline"})
    return {"connected": False, "provider": "offline", "forgotten": forget}


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

    def _cache_file(self, fp: str, max_tokens: int):
        from .config import settings
        key = hashlib.sha256(f"{self.provider.name}|{self.provider.model}|{max_tokens}|{fp}".encode()).hexdigest()[:32]
        return settings.workspace / "llm_cache" / f"{key}.json"

    def complete_json(self, agent: str, system: str, user: str, max_tokens: int = 2000) -> dict:
        if not self.enabled:
            raise LLMError("LLM disabled")
        user_clean, _ = privacy.scrub(user)
        fp = privacy.payload_fingerprint({"system": system, "user": user_clean})
        cache = self._cache_file(fp, max_tokens)
        if cache.exists():          # the exact same request was answered before: reuse it instead of waiting again
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                self.calls.append(LLMCall(self.provider.name, self.provider.model, agent, fp, 0.0, True))
                return data
            except (OSError, ValueError):
                pass
        t0 = time.time()
        try:
            out = self.provider.complete(system, user_clean, max_tokens=max_tokens)
            data = extract_json(out)
            self.calls.append(LLMCall(self.provider.name, self.provider.model, agent, fp, round(time.time() - t0, 2), True))
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
            return data
        except Exception as e:  # noqa: BLE001
            self.calls.append(LLMCall(self.provider.name, self.provider.model, agent, fp, round(time.time() - t0, 2), False, str(e)[:300]))
            raise LLMError(str(e)) from e
