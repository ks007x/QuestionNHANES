"""Covariate suggestions: which additional variables to adjust for, and why.

For each library variable not already in the model the agent decides a role from the plan's outcome and exposure
domains and the curated causal flags:
  confounder     common cause of exposure and outcome -> suggest adding to the primary model
  mediator       may lie on the path from exposure to outcome -> do NOT add to the primary model; offer
                 "additionally adjusted" as a sensitivity analysis
  both           plausible confounder AND mediator (e.g. asthma for parasites -> eosinophilia) -> sensitivity analysis
Variables that share source items with the outcome or exposure are never suggested (definitional overlap), and
variables not measured in the selected cycles are reported as unavailable.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .knowledge import Knowledge, get_knowledge

ROOT = Path(__file__).resolve().parent.parent
DEMO = {"RIAGENDR", "RIDAGEYR", "RIDEXPRG"}


@lru_cache(maxsize=1)
def library() -> list[dict]:
    return yaml.safe_load((ROOT / "knowledge" / "covariates.yaml").read_text(encoding="utf-8"))["covariates"]


def _domains(v: dict | None, k: Knowledge) -> set[str]:
    if not v:
        return set()
    from .planner import _concept
    out = {v.get("domain") or "default"}
    if v.get("arms"):
        for a in v["arms"]["arms"]:
            try:
                out.add(_concept(a["concept"], k).get("domain", "default"))
            except KeyError:
                pass
    try:
        out.add(_concept(v.get("concept", ""), k).get("domain", "default"))
    except KeyError:
        pass
    return out


def suggest(plan: dict, k: Knowledge | None = None, provider: str | None = None, use_llm: bool = True) -> dict:
    k = k or get_knowledge()
    from .planner import _raw_dependencies, available_cycles
    y, x = plan["outcome"], plan.get("exposure")
    if not x:
        return {"suggestions": [], "note": "Prevalence studies report crude and subgroup estimates; covariate adjustment applies to association analyses."}
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    ydom, xdom = _domains(y, k), _domains(x, k)
    covs = set(plan.get("covariates", []))
    sens_extra = {c for s in plan.get("sensitivity", []) if s.get("type") == "add_covariates" for c in s.get("covariates", [])}
    core_raw = set(_raw_dependencies(y["variable"], k, custom)) | (set(_raw_dependencies(x["variable"], k, custom)) if x else set())
    core_raw -= DEMO
    cycles = set(plan.get("dataset", {}).get("cycles") or [])
    adults_only = any("age >= 18" in c.get("expr", "") or "age >= 20" in c.get("expr", "") for c in plan.get("population", []) if c.get("enabled", True))
    flags = {(f["exposure"], f["outcome"], f["variable"]): f for f in k.causal_flags}
    out = []
    for item in library():
        n = item["name"]
        if n in covs or n == y["variable"] or (x and n == x["variable"]):
            continue
        if n not in k.blocks and n not in k.definitions:
            continue
        raw = set(_raw_dependencies(n, k, custom)) - DEMO
        if raw & core_raw:
            continue                              # shares items with the outcome/exposure: definitional overlap
        if x and x.get("arms") and n in {a["concept"] for a in x["arms"]["arms"]}:
            continue
        conf = "all" in item.get("confounder_for", []) or bool(set(item.get("confounder_for", [])) & (ydom | xdom))
        med = bool(set(item.get("mediator_after", [])) & xdom)
        flag = flags.get((x.get("concept"), y.get("concept"), n)) if x else None
        if flag and flag.get("role") in ("mediator_or_outcome", "possible_mediator"):
            med = True
        if not conf and not med:
            continue
        if item.get("adults_only") and not adults_only:
            continue
        role = "both" if conf and med else ("mediator" if med else "confounder")
        avail = available_cycles(n, k, custom)
        ok = not cycles or cycles <= avail
        if role == "confounder":
            fix = {"op": "add_covariate", "name": n}
            action = "Add to the model"
        else:
            fix = {"op": "add_sensitivity", "item": {"type": "add_covariates", "covariates": [n],
                                                     "label": f"Additionally adjusted for {k.label(n).lower()} ({'possible mediator' if role == 'mediator' else 'confounder or mediator'})"}}
            action = "Add as a sensitivity analysis"
        out.append({"variable": n, "label": k.label(n), "role": role, "why": item["why"], "available": ok,
                    "missing_cycles": sorted(cycles - avail) if not ok else [], "fix": fix if ok and n not in sens_extra else None,
                    "action": action if ok else "Not measured in the selected cycle(s)",
                    "already_in_sensitivity": n in sens_extra})
    order = {"confounder": 0, "both": 1, "mediator": 2}
    out.sort(key=lambda s: (not s["available"], order[s["role"]]))
    ai = _ai_review(plan, out, provider) if use_llm and out else None
    return {"suggestions": out, "ai": ai,
            "note": "Confounders (common causes) belong in the primary model. Mediators sit on the causal path - adjusting for them "
                    "removes part of the effect - so they are offered as sensitivity analyses only."}


AI_SYSTEM = ("You are the epidemiologist on BEDSIDE, which designs survey-weighted NHANES analyses. You see study metadata only, "
             "never data. Classify candidate adjustment variables by causal role. Respond with one JSON object only.")


def _ai_review(plan: dict, out: list[dict], provider: str | None) -> dict | None:
    """Amazon Bedrock (or another approved model) reviews the rule-based candidates. It can only comment on listed
    variables and flag one as a likely confounder or mediator; it cannot add variables or change the plan itself."""
    import json
    from .llm import LLMClient
    client = LLMClient(provider)
    if not client.enabled:
        return None
    x = plan.get("exposure") or {}
    slim = {"question": plan.get("refined_question"), "outcome": plan["outcome"]["label"], "exposure": x.get("label"),
            "already_adjusted": plan.get("covariates", []),
            "candidates": [{"variable": o["variable"], "label": o["label"], "rule_role": o["role"]} for o in out[:20]]}
    user = (json.dumps(slim, default=str) + "\n\nReturn JSON {picks: [{variable, role: 'confounder'|'mediator'|'both'|'not needed', "
            "why: one sentence}], summary: one sentence on the adjustment strategy}. Use only listed variable names.")
    try:
        data = client.complete_json("Epidemiologist", AI_SYSTEM, user, max_tokens=900)
    except Exception:  # noqa: BLE001
        return None
    names = {o["variable"]: o for o in out}
    n = 0
    for pick in (data.get("picks") or [])[:20] if isinstance(data, dict) else []:
        if not isinstance(pick, dict) or pick.get("variable") not in names:
            continue
        role = pick.get("role") if pick.get("role") in ("confounder", "mediator", "both", "not needed") else None
        if role:
            names[pick["variable"]]["ai"] = {"role": role, "why": str(pick.get("why") or "")[:240],
                                             "agrees": role == names[pick["variable"]]["role"]}
            n += 1
    return {"provider": client.provider.name, "model": client.provider.model, "reviewed": n,
            "summary": str((data or {}).get("summary") or "")[:400]} if n else None
