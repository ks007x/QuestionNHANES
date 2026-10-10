"""Data-governance guardrails.

* Row-level data never leave the R engine: LLM payloads are built only from the
  question, the study plan, data-dictionary metadata and (optionally) aggregate,
  NCHS-reliable results.
* Free text is scrubbed for identifiers before any LLM call.
* Under Q2E_DATA_POLICY=restricted, only providers in Q2E_APPROVED_PROVIDERS
  (e.g. a local Ollama model or an enterprise Azure/Bedrock tenant covered by a
  BAA/DUA) can be used, and aggregate results are withheld from LLMs.
Every outbound payload is hashed and logged in the provenance trail.
"""
from __future__ import annotations

import hashlib
import json
import re

from .config import settings

_RULES: list[tuple[str, str]] = [
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("phone", r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"),
    ("mrn", r"\b(?:mrn|medical record(?: number)?|patient id|pt id)\s*[:#]?\s*[A-Za-z0-9-]{4,}\b"),
    ("date", r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    ("long_number", r"\b\d{7,}\b"),
    ("name_title", r"\b(?i:mr|mrs|ms|dr|patient)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"),
]


def scrub(text: str) -> tuple[str, list[dict]]:
    findings = []
    out = text or ""
    for kind, pat in _RULES:
        flags = re.IGNORECASE if kind in ("mrn",) else 0
        for m in re.finditer(pat, out, flags):
            findings.append({"type": kind, "text": m.group(0)})
        out = re.sub(pat, f"[{kind.upper()} REDACTED]", out, flags=flags)
    return out, findings


def provider_allowed(provider: str) -> tuple[bool, str]:
    if provider == "offline":
        return True, "Offline rule-based agents - nothing leaves this machine."
    if settings.data_policy == "restricted" and provider not in settings.approved_providers:
        return False, (f"Data policy is 'restricted': provider '{provider}' is not in Q2E_APPROVED_PROVIDERS "
                       f"({', '.join(settings.approved_providers)}).")
    return True, f"Provider '{provider}' permitted under '{settings.data_policy}' policy (metadata only; no row-level data)."


def aggregates_allowed() -> bool:
    return settings.data_policy != "restricted" and settings.send_aggregates_to_llm


def payload_fingerprint(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def boundary_summary(provider: str) -> dict:
    ok, msg = provider_allowed(provider)
    return {"provider": provider, "policy": settings.data_policy, "allowed": ok, "message": msg,
            "row_level_data_to_llm": False, "aggregates_to_llm": aggregates_allowed() and provider != "offline",
            "approved_providers": settings.approved_providers}
