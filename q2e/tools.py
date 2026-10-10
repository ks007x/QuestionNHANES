"""One tool registry for every AI integration (MCP, OpenAI/Azure function calling, Bedrock, ElevenLabs, Anakin, REST).

Governance is built into the registry, not left to each client:
  * AI agents can draft, assess, probe, check novelty, apply the Reviewer's suggested fixes, run APPROVED plans
    and read results.
  * AI agents can NOT approve a protocol, sign off statistics or sign off results - there is no tool for it.
    `request_approval` returns a link for the human investigator instead.
  * Free text is privacy-scrubbed before it is stored; every call is written to the project's hash-chained ledger.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import agents, answerability, novelty as _novelty, planner, privacy, venues
from .config import settings
from .runner import approved_for_current_plan, get_run, load_results, run_probe, start_run
from .store import store


class ToolError(Exception):
    pass


def _summary(proj: dict) -> dict:
    p = proj["plan"]
    from .compiler import plan_hash
    h = plan_hash(p)
    return {
        "project_id": proj["id"], "title": p["title"], "refined_question": p["refined_question"],
        "study_type": p["study_type"], "outcome": p["outcome"]["label"], "exposure": (p.get("exposure") or {}).get("label"),
        "population": [c["label"] for c in p["population"] if c.get("enabled")], "covariates": p["covariates"],
        "feasibility": {"score": p["feasibility"]["score"], "label": p["feasibility"]["label"]},
        "novelty": p.get("novelty"), "answerability": (p.get("answerability") or {}).get("verdict"),
        "design_audit": {"grade": p.get("design_audit", {}).get("grade"),
                         "flags": [f"{c['status']}: {c['area']} - {c['title']}" for c in p.get("design_audit", {}).get("checks", []) if c["status"] != "pass"]},
        "open_review_items": [{"id": i["id"], "severity": i["severity"], "title": i["title"], "has_fix": bool(i.get("fix"))}
                              for i in p.get("review", []) if i["severity"] in ("blocker", "major")],
        "plan_hash": h, "approved_by_human": approved_for_current_plan(proj),
        "approval_url": f"{settings.public_url.rstrip('/')}/#/p/{proj['id']}/plan",
    }


def _log(proj: dict, client: str, tool: str, detail: dict) -> None:
    store.event(proj, f"ai-tool:{client}", f"tool_{tool}", detail)
    store.save(proj)


# ------------------------------------------------------------------ handlers
def assess_question(question: str, cycles: list[str] | None = None, client: str = "ai") -> dict:
    q, _ = privacy.scrub(question)
    return answerability.assess_question(q, cycles)


def design_study(question: str, cycles: list[str] | None = None, data_source: str = "auto", client: str = "ai") -> dict:
    q, redactions = privacy.scrub(question)
    if data_source not in ("auto", "cdc", "synthetic"):
        raise ToolError("data_source must be auto, cdc or synthetic")
    try:
        plan = agents.design_study(q, cycles, {"type": "nhanes", "cycles": cycles or ["P"], "source": data_source}, None)
    except planner.HardStop as e:
        return {"hard_stop": True, "message": str(e), "assessment": answerability.assess_question(q, cycles)}
    proj = store.create(q, plan, f"ai-tool:{client}")
    _log(proj, client, "design_study", {"redactions": len(redactions)})
    return _summary(proj)


def get_plan(project_id: str, client: str = "ai") -> dict:
    proj = store.get(project_id)
    out = _summary(proj)
    out["review"] = proj["plan"].get("review", [])
    out["sensitivity"] = [s["label"] for s in proj["plan"].get("sensitivity", []) if s.get("enabled")]
    return out


def apply_review_fix(project_id: str, issue_id: str, client: str = "ai") -> dict:
    proj = store.get(project_id)
    issue = next((i for i in proj["plan"].get("review", []) if i["id"] == issue_id), None)
    if not issue or not issue.get("fix"):
        raise ToolError(f"No applicable fix for review item '{issue_id}'.")
    if issue["fix"].get("op") == "acknowledge":
        raise ToolError("Operational assumptions must be acknowledged by the human investigator in the app.")
    proj["plan"] = agents.refresh_plan(planner.apply_fix(proj["plan"], issue["fix"]))
    _log(proj, client, "apply_review_fix", {"issue": issue_id, "op": issue["fix"].get("op")})
    return _summary(proj)


def check_novelty(project_id: str, client: str = "ai") -> dict:
    proj = store.get(project_id)
    nv = _novelty.novelty(proj["plan"])
    proj["novelty"] = {**nv, "plan_version": proj["plan"].get("version")}
    if nv.get("score") is not None:
        proj["plan"]["novelty"] = {"score": nv["score"], "label": nv["label"], "summary": nv["summary"], "checked": nv["checked"]}
        proj["plan"] = agents.refresh_plan(proj["plan"])
    _log(proj, client, "check_novelty", {"score": nv.get("score")})
    return {k: nv.get(k) for k in ("score", "label", "summary", "suggestions", "levers", "error")} | \
        {"closest": [{"title": c["title"], "journal": c["journal"], "url": c["url"]} for c in nv.get("closest") or []]}


def feasibility_probe(project_id: str, client: str = "ai") -> dict:
    out = run_probe(project_id, f"ai-tool:{client}")
    return {k: v for k, v in out.items() if k not in ("trace",)}


def request_approval(project_id: str, client: str = "ai") -> dict:
    proj = store.get(project_id)
    _log(proj, client, "request_approval", {})
    s = _summary(proj)
    return {"approved_by_human": s["approved_by_human"], "approval_url": s["approval_url"],
            "message": "Only the human investigator can approve. Open the link, review the protocol, design audit and "
                       "reviewer critique, acknowledge operational assumptions, then approve. The approval locks the plan hash."}


def run_analysis(project_id: str, client: str = "ai") -> dict:
    proj = store.get(project_id)
    if not approved_for_current_plan(proj):
        raise ToolError("This plan version is not approved by a human investigator. Call request_approval and wait.")
    run = start_run(project_id, f"ai-tool:{client}", wait=True)
    run = get_run(project_id, run["id"])
    return {"run_id": run["id"], "status": run["status"], "error": run.get("error")}


def get_results(project_id: str, run_id: str | None = None, client: str = "ai") -> dict:
    proj = store.get(project_id)
    runs = [r for r in proj.get("runs", []) if r.get("status") == "completed"]
    if not runs:
        raise ToolError("No completed run yet.")
    rid = run_id or runs[-1]["id"]
    R = load_results(project_id, rid)
    pe = R.get("primary_estimate") or {}
    base = f"{settings.public_url.rstrip('/')}/api/projects/{project_id}/runs/{rid}"
    return {"run_id": rid, "primary": {k: pe.get(k) for k in ("label", "effect", "est", "lcl", "ucl", "n")},
            "n_analytic": next((f["n"] for f in reversed(R.get("flow", [])) if f.get("n")), None),
            "qc": [{"status": c["status"], "title": c["title"]} for c in R.get("checks", []) if c["status"] != "pass"],
            "synthetic_data": any(f.get("synthetic") for f in (R.get("meta") or {}).get("files", [])),
            "manuscript_url": f"{base}/report.html", "bundle_url": f"{base}/bundle.zip",
            "note": "Associations from cross-sectional data; do not describe as causal."}


def where_next(project_id: str, client: str = "ai") -> dict:
    proj = store.get(project_id)
    runs = [r for r in proj.get("runs", []) if r.get("status") == "completed"]
    res = load_results(project_id, runs[-1]["id"]) if runs else None
    w = venues.where_next(proj["plan"], res)
    return {"journals": [{"journal": j["journal"], "score": j["score"], "why": j["why"]} for j in w["journals"][:5]],
            "conferences": [{k: c[k] for k in ("conference", "deadline_estimate", "days_until_estimate", "url")} for c in w["conferences"]],
            "nih_institutes": [i["ic"] for i in w["funding"]["institutes"]],
            "funded_projects": (w["funding"].get("reporter") or {}).get("examples", [])[:3],
            "open_opportunities": ((w["funding"].get("opportunities") or {}).get("opportunities") or [])[:3],
            "errors": w["errors"]}


# ------------------------------------------------------------------ registry
S = {"type": "string"}
PID = {"project_id": {**S, "description": "Project id returned by design_study"}}
CYC = {"cycles": {"type": "array", "items": S, "description": "NHANES cycles, e.g. ['P'] (2017-Mar 2020) or ['L'] (2021-2023)"}}

TOOLS: list[dict[str, Any]] = [
    {"name": "assess_question", "fn": assess_question, "required": ["question"],
     "properties": {"question": {**S, "description": "Research question in plain English"}, **CYC},
     "description": "Check whether NHANES can answer a research question (design fit, coverage, eligibility) without creating a project."},
    {"name": "design_study", "fn": design_study, "required": ["question"],
     "properties": {"question": {**S, "description": "Clinical observation or research question"}, **CYC,
                    "data_source": {**S, "enum": ["auto", "cdc", "synthetic"],
                                    "description": "auto/cdc = real NHANES (local files or CDC download); synthetic = offline demo data"}},
     "description": "Turn a research idea into a draft NHANES protocol (PICO, variables, analysis plan, feasibility, design audit). Returns project_id. Hard-stops questions NHANES cannot answer."},
    {"name": "get_plan", "fn": get_plan, "required": ["project_id"], "properties": PID,
     "description": "Read the current protocol, reviewer critique and design-audit flags for a project."},
    {"name": "apply_review_fix", "fn": apply_review_fix, "required": ["project_id", "issue_id"],
     "properties": {**PID, "issue_id": {**S, "description": "id of a review item that has a suggested fix"}},
     "description": "Apply the Reviewer's or Design auditor's suggested fix to the draft plan (cannot acknowledge assumptions or approve)."},
    {"name": "check_novelty", "fn": check_novelty, "required": ["project_id"], "properties": PID,
     "description": "Score novelty from PubMed/MEDLINE: how many NHANES papers already answer this question, the closest prior work, and how to differentiate."},
    {"name": "feasibility_probe", "fn": feasibility_probe, "required": ["project_id"], "properties": PID,
     "description": "Blinded feasibility probe: sample counts and outcome-rate band only (no effect estimates), allowed before approval."},
    {"name": "request_approval", "fn": request_approval, "required": ["project_id"], "properties": PID,
     "description": "Ask the human investigator to approve the protocol. Returns the approval link. AI cannot approve."},
    {"name": "run_analysis", "fn": run_analysis, "required": ["project_id"], "properties": PID,
     "description": "Run the human-approved plan in the R engine (survey-weighted models and QC). Fails if the plan is not approved."},
    {"name": "get_results", "fn": get_results, "required": ["project_id"],
     "properties": {**PID, "run_id": {**S, "description": "Optional run id; latest completed run by default"}},
     "description": "Headline estimate, analytic n, QC warnings and links to the manuscript and reproducibility bundle."},
    {"name": "where_next", "fn": where_next, "required": ["project_id"], "properties": PID,
     "description": "Journal match scores, upcoming conference abstract windows and NIH funding leads for the study."},
]
BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}


def json_schema(t: dict) -> dict:
    return {"type": "object", "properties": t["properties"], "required": t["required"], "additionalProperties": False}


def call(name: str, args: dict | None, client: str = "ai") -> dict:
    t = BY_NAME.get(name)
    if not t:
        raise ToolError(f"Unknown tool '{name}'.")
    args = {k: v for k, v in (args or {}).items() if k in t["properties"]}
    missing = [r for r in t["required"] if not args.get(r)]
    if missing:
        raise ToolError(f"Missing required argument(s): {', '.join(missing)}")
    fn: Callable = t["fn"]
    try:
        return fn(**args, client=client)
    except KeyError as e:
        raise ToolError(f"Not found: {e}") from e


def as_text(result: Any) -> str:
    return json.dumps(result, default=str, indent=1)[:60000]
