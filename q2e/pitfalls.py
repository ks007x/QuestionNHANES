"""Anticipate where an NHANES analysis is likely to go wrong, before it runs.

Rules live in knowledge/pitfalls.yaml (measurement changes across cycles, recalibrations, weights for pooled
cycles, top-coded age, race categories by cycle, pandemic-era files). Each rule that applies to the plan becomes
a review item with what to do about it. Unlike QC checks, these fire at the protocol stage, so the investigator
decides before any data are analysed.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .knowledge import CYCLE_ORDER

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def rules() -> list[dict]:
    return yaml.safe_load((ROOT / "knowledge" / "pitfalls.yaml").read_text(encoding="utf-8")).get("pitfalls", [])


def _raw_used(plan: dict, k) -> set[str]:
    from .planner import _raw_dependencies
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    names = [plan["outcome"]["variable"]] + ([plan["exposure"]["variable"]] if plan.get("exposure") else [])
    names += list(plan.get("covariates", [])) + list(plan.get("prevalence_by", []))
    out: set[str] = set()
    for n in names:
        try:
            out |= _raw_dependencies(n, k, custom)
        except Exception:  # noqa: BLE001
            pass
    return out


def check(plan: dict, k) -> list[dict]:
    if (plan.get("dataset") or {}).get("type", "nhanes") != "nhanes":
        return []
    cycles = [c for c in CYCLE_ORDER if c in (plan["dataset"].get("cycles") or [])]
    raw = _raw_used(plan, k)
    trend = bool((plan.get("trend") or {}).get("enabled"))
    hits = []
    for r in rules():
        kind = r["kind"]
        fire = False
        if kind == "spans_boundary" and raw & set(r["vars"]) and len(cycles) > 1:
            b = CYCLE_ORDER.index(r["boundary"])
            idx = [CYCLE_ORDER.index(c) for c in cycles]
            fire = min(idx) < b <= max(idx)
        elif kind == "in_cycles":
            need = set(r.get("applies_to") or r["vars"])
            fire = bool(set(r["cycles"]) & set(cycles)) and (not need or bool(raw & need))
            if r["id"] == "pandemic_cycles":
                fire = bool(set(r["cycles"]) & set(cycles)) and len(cycles) > 1
        elif kind == "pooled_cycles":
            fire = set(r["cycles"]) <= set(cycles) and not trend
        elif kind == "uses_variable":
            fire = bool(raw & set(r["vars"])) and any(CYCLE_ORDER.index(c) < CYCLE_ORDER.index(r["before"]) for c in cycles) and len(cycles) > 1
        sev = "minor"
        if kind == "age_over":
            for c in plan.get("population", []):
                m = re.search(r"age\s*(>=?)\s*(\d+)", c.get("expr", ""))
                if c.get("enabled", True) and m and c.get("kind") != "exclusion":
                    lo = int(m.group(2)) + (1 if m.group(1) == ">" else 0)
                    if lo >= r["age"]:
                        fire = True
                    if lo > r["age"]:
                        sev = "blocker"     # nobody is recorded above the top code
        if fire:
            hits.append({"id": f"pitfall_{r['id']}", "severity": sev, "agent": "Methods auditor", "title": r["title"],
                         "detail": f"{r['detail']} What to do: {r['action']}", "fix": None})
    return hits
