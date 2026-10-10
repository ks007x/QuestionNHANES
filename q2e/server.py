"""Q2E web API + single-page UI.

    uvicorn q2e.server:app --port 8000      (or: python -m q2e serve)
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, agents, answerability, expertise, expressions, generic, literature, novelty, planner, privacy, protocol_chat, report, tools as qtools, venues, voice
from .bundle import build_bundle
from .compiler import CompileError, compile_plan, plan_hash
from .config import settings
from .knowledge import get_knowledge
from .llm import LLMClient, LLMError
from .matcher import BM25Index, entries_from_nhanes
from .runner import RunError, get_run, load_results, run_probe, start_run
from .store import store

settings.ensure_dirs()
app = FastAPI(title="Q2E - Question to Evidence", version=__version__)
WEB = settings.root / "web"
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _bad(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def _project(pid: str) -> dict:
    try:
        return store.get(pid)
    except (KeyError, ValueError):
        _bad("Project not found", 404)


def _public(proj: dict) -> dict:
    proj = dict(proj)
    proj["plan_hash"] = plan_hash(proj["plan"])
    proj["approved_current"] = any(a.get("plan_hash") == proj["plan_hash"] and a.get("stage", "protocol") == "protocol"
                                   for a in proj["plan"].get("approvals", []))
    proj["stats_signed_current"] = any(a.get("plan_hash") == proj["plan_hash"] and a.get("stage") == "statistics"
                                       for a in proj["plan"].get("approvals", []))
    proj["chain"] = store.verify_chain(proj)
    return proj


# ------------------------------------------------------------------ UI
@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text()


# ------------------------------------------------------------------ meta
@app.get("/api/meta")
def meta():
    k = get_knowledge()
    client = LLMClient()
    local = Path(settings.nhanes_dir)
    return {"version": __version__, "knowledge": k.public_summary(), "llm": client.status(),
            "boundary": privacy.boundary_summary(client.provider.name), "voice": voice.enabled(),
            "data": {"local_dir": str(local), "local_files": len(list(local.glob("*.xpt")) + list(local.glob("*.XPT"))) if local.exists() else 0,
                     "synthetic_ready": (settings.synthetic_dir / "P_DEMO.xpt").exists(), "allow_download": settings.allow_download},
            "datasets": generic.list_datasets()}


# ------------------------------------------------------------------ projects
class NewProject(BaseModel):
    question: str = Field(min_length=8, max_length=2000)
    cycles: list[str] | None = None
    source: str = "auto"
    provider: str | None = None
    dataset_id: str | None = None
    actor: str = "investigator"
    # answers to the Interviewer's follow-up questions: {question_id: {"option": id, "text": str}}
    answers: dict[str, dict[str, str]] | None = None
    level: str | None = None


class ClarifyQ(BaseModel):
    question: str = Field(min_length=4, max_length=2000)
    cycles: list[str] | None = None
    level: str | None = None     # optional override of the detected expertise level


@app.post("/api/clarify")
def clarify(body: ClarifyQ):
    """Detect the user's expertise from their wording and return adaptive follow-up questions."""
    return expertise.clarify(body.question, body.cycles, body.level)


@app.post("/api/projects")
def create_project(body: NewProject):
    k = get_knowledge()
    cycles = body.cycles or list(k.default_cycles)
    for c in cycles:
        if c not in k.cycles:
            _bad(f"Unknown cycle {c}")
    clar = None
    if body.answers is not None:
        clar = expertise.apply_answers(body.question, body.answers, body.level, cycles)
        clar.update(original_question=body.question, answers=body.answers)   # lets the user reopen and change them later
        body.question = clar["question"]
    dataset = None
    if body.dataset_id:
        rec = generic.get_dataset(body.dataset_id)
        dataset = generic.dataset_spec(rec)
    else:
        dataset = {"type": "nhanes", "cycles": cycles, "source": body.source}
    try:
        plan = agents.design_study(body.question, body.cycles or None, dataset, body.provider)   # no cycles = automatic choice
    except planner.HardStop as e:
        from .privacy import scrub
        return JSONResponse(status_code=422, content={"error": str(e), "hard_stop": True,
                                                      "assessment": answerability.assess_question(scrub(body.question)[0], cycles)})
    except ValueError as e:
        _bad(str(e), 422)
    if body.dataset_id:
        sug = generic.suggest_mapping(plan, rec, k)
        plan["generic_mapping"] = sug["mapping"]
        plan["generic_status"] = sug["status"]
        plan = generic.prune_unavailable(plan, k)
        plan = agents.refresh_plan(plan)
    if clar:
        try:
            plan = agents.refresh_plan(expertise.apply_fixes(plan, clar["fixes"]))
        except (ValueError, KeyError, expressions.ExpressionError) as e:
            _bad(f"Could not apply your answers: {e}", 422)
        ex = clar["expertise"]
        plan["clarification"] = {k2: clar[k2] for k2 in ("record", "expertise", "level_used", "original_question", "answers", "understood")}
        read = "; ".join(f"{u['label']}: {u['value']}" for u in clar["understood"])
        asked = ("; ".join(f"{r['question']} → {r['answer']}" for r in clar["record"])
                 if clar["record"] else "none were needed")
        plan["agent_dialogue"].insert(0, {"agent": "Interviewer", "source": "rules", "message":
                                          f"From the wording I estimated your experience as {clar['level_used']} (score {ex['score']}/100). "
                                          f"Read from your idea: {read or 'nothing specific'}. Follow-up questions: {asked}."})
    proj = store.create(body.question, plan, body.actor)
    if clar:
        store.event(proj, body.actor, "clarification_answered", plan["clarification"])
        store.save(proj)
    return _public(proj)


@app.get("/api/projects")
def list_projects():
    return store.list()


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _public(_project(pid))


class Edit(BaseModel):
    fix: dict[str, Any]
    actor: str = "investigator"
    note: str | None = None
    step: str | None = Field(default=None, max_length=120)
    step_title: str | None = Field(default=None, max_length=160)


@app.post("/api/projects/{pid}/edit")
def edit_project(pid: str, body: Edit):
    proj = _project(pid)
    if proj.get("signoff"):
        _bad("Project is signed off; create a new version to change the plan")
    try:
        new_plan = planner.apply_fix(proj["plan"], body.fix)
    except (ValueError, expressions.ExpressionError, KeyError) as e:
        _bad(str(e), 422)
    new_plan = agents.refresh_plan(new_plan)
    if new_plan.get("dataset", {}).get("type") == "generic" and new_plan["dataset"].get("dataset_id"):
        rec = generic.get_dataset(new_plan["dataset"]["dataset_id"])
        new_plan["generic_status"] = generic.suggest_mapping(new_plan, rec)["status"]
    new_plan["status"] = "draft"
    old_plan, v_before = proj["plan"], proj["plan"].get("version")
    proj["plan"] = new_plan
    store.snapshot(proj, body.actor, body.note or f"edit: {body.fix.get('op')}")
    store.event(proj, body.actor, "plan_edited", {"fix": body.fix})
    _record_edit(proj, body.actor, body.fix, old_plan, v_before, body.step, body.step_title)
    store.save(proj)
    return _public(proj)


# ------------------------------------------------------------------ protocol agent + amendment history
EDIT_NAMES = {"title": "Title", "refined_question": "Refined research question", "hypothesis": "Hypothesis"}


def _record_edit(proj: dict, actor: str, fix: dict, old_plan: dict, v_before: int | None,
                 step: str | None = None, step_title: str | None = None) -> None:
    """Every manual edit also goes into the readable amendment history."""
    changes = protocol_chat.diff_plans(old_plan, proj["plan"])
    if not changes:
        path = str(fix.get("path") or "")
        what = EDIT_NAMES.get(path.split(".")[-1], (fix.get("op") or "edit").replace("_", " ").capitalize())
        changes = [{"what": what, "before": "-", "after": "edited"}]
    am = protocol_chat.new_amendment(actor, "Edited on the protocol page", changes, v_before, proj["plan"].get("version"),
                                     [], None, _now(), source="edit", edit_ops=[fix], step=step, step_title=step_title)
    proj.setdefault("amendments", []).append(am)


class ChatMsg(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    actor: str = "analyst"
    step: str | None = Field(default=None, max_length=120)         # which item it was said on, e.g. "protocol:population:pregnancy"
    step_title: str | None = Field(default=None, max_length=160)


@app.post("/api/projects/{pid}/comments")
def add_comment(pid: str, body: ChatMsg):
    """A comment on one step (no change to the protocol); goes into the timestamped history for the lead investigator."""
    proj = _project(pid)
    text, _ = privacy.scrub(body.message.strip())
    at = _now()
    proj.setdefault("protocol_chat", []).append({"at": at, "who": body.actor, "text": text, "kind": "comment", "step": body.step})
    v = proj["plan"].get("version")
    am = protocol_chat.new_amendment(body.actor, text, [], v, v, [], None, at, source="comment", step=body.step, step_title=body.step_title)
    am["summary"] = [text]
    proj.setdefault("amendments", []).append(am)
    store.event(proj, body.actor, "comment_added", {"amendment": am["id"], "step": body.step, "text": text})
    store.save(proj)
    return _public(proj)


@app.post("/api/projects/{pid}/protocol-chat")
def protocol_chat_send(pid: str, body: ChatMsg):
    """Analyst asks the Protocol agent for a change; it is applied right away (with Undo) and logged."""
    proj = _project(pid)
    if proj.get("signoff"):
        _bad("Project is signed off; create a new version to change the protocol")
    msg, _ = privacy.scrub(body.message)
    chat = proj.setdefault("protocol_chat", [])
    chat.append({"at": _now(), "who": body.actor, "text": msg, "step": body.step})
    pub = _public(proj)
    try:
        r = protocol_chat.respond(pub, msg)
    except (ValueError, KeyError, expressions.ExpressionError) as e:
        r = {"reply": None, "new_plan": None, "changes": [], "ask": {"text": f"I couldn't apply that: {e}", "options": []}}
    if r["new_plan"]:
        v_before = proj["plan"].get("version")
        proj["plan"] = r["new_plan"]
        store.snapshot(proj, body.actor, f"Protocol agent: {msg[:80]}")
        am = protocol_chat.new_amendment(body.actor, msg, r["changes"], v_before, proj["plan"].get("version"),
                                         r["ops"], r["text_request"], _now(), step=body.step, step_title=body.step_title)
        proj.setdefault("amendments", []).append(am)
        if r["text_request"]:
            proj.setdefault("protocol_requests", []).append(r["text_request"])
        chat.append({"at": _now(), "who": "Protocol agent", "text": r["reply"], "summary": am["summary"], "amendment": am["id"], "step": body.step})
        store.event(proj, body.actor, "protocol_amended", {"amendment": am["id"], "request": msg, "summary": am["summary"],
                                                           "version": proj["plan"].get("version")})
    elif r.get("reply"):
        chat.append({"at": _now(), "who": "Protocol agent", "text": r["reply"], "step": body.step})
    else:
        chat.append({"at": _now(), "who": "Protocol agent", "text": r["ask"]["text"], "options": r["ask"]["options"], "step": body.step})
        store.event(proj, body.actor, "protocol_request_not_applied", {"request": msg})
    store.save(proj)
    return _public(proj)


class AmendAction(BaseModel):
    actor: str = "analyst"
    reason: str | None = Field(default=None, max_length=500)


@app.post("/api/projects/{pid}/amendments/{aid}/undo")
def amendment_undo(pid: str, aid: str, body: AmendAction):
    proj = _project(pid)
    if proj.get("signoff"):
        _bad("Project is signed off; create a new version to change the protocol")
    active = [a for a in proj.get("amendments", []) if not a.get("undone") and a.get("source") not in ("undo", "comment")]
    if not active or active[-1]["id"] != aid:
        _bad("Only the most recent change can be undone", 409)
    am = active[-1]
    f = store.path(pid) / "plans" / f"plan_v{am['version_before']}.json"
    if not am.get("version_before") or not f.exists():
        _bad("The earlier version of the protocol was not found", 404)
    old = json.loads(f.read_text())
    for key in ("approvals", "acknowledgements"):
        if key in proj["plan"]:
            old[key] = proj["plan"][key]
    v_from = proj["plan"].get("version")
    proj["plan"] = agents.refresh_plan(old)
    proj["plan"]["status"] = "draft"
    store.snapshot(proj, body.actor, f"Undo: {am['request'][:80]}")
    am["undone"] = True
    if am.get("text_request") and am["text_request"] in proj.get("protocol_requests", []):
        proj["protocol_requests"].remove(am["text_request"])
    undo = protocol_chat.new_amendment(body.actor, f"Undid: {am['request']}",
                                       [{"what": c["what"], "before": c["after"], "after": c["before"]} for c in am["changes"]],
                                       v_from, proj["plan"].get("version"), [], None, _now(), source="undo")
    proj["amendments"].append(undo)
    proj.setdefault("protocol_chat", []).append({"at": _now(), "who": "Protocol agent", "text": "Undone. The protocol is back to how it was.",
                                                 "summary": undo["summary"]})
    store.event(proj, body.actor, "amendment_undone", {"amendment": aid, "version": proj["plan"].get("version")})
    store.save(proj)
    return _public(proj)


@app.post("/api/projects/{pid}/amendments/{aid}/reason")
def amendment_reason(pid: str, aid: str, body: AmendAction):
    proj = _project(pid)
    am = next((a for a in proj.get("amendments", []) if a["id"] == aid), None)
    if not am:
        _bad("Change not found", 404)
    am["reason"] = privacy.scrub((body.reason or "").strip())[0] or None
    store.event(proj, body.actor, "amendment_reason_added", {"amendment": aid, "reason": am["reason"]})
    store.save(proj)
    return _public(proj)


class Approve(BaseModel):
    by: str = Field(min_length=2, max_length=120)
    statement: str = "I have reviewed the protocol, variable mappings, operational assumptions and analysis plan."
    role: str = Field(default="investigator", pattern="^(investigator|statistician)$")


@app.post("/api/projects/{pid}/approve")
def approve(pid: str, body: Approve):
    proj = _project(pid)
    plan = proj["plan"]
    blockers = [i for i in plan.get("review", []) if i["severity"] == "blocker"]
    if blockers:
        _bad("Cannot approve with unresolved blockers: " + "; ".join(b["title"] for b in blockers), 409)
    pending_ack = [i for i in plan.get("review", []) if i["severity"] == "major" and (i.get("fix") or {}).get("op") == "acknowledge"]
    if pending_ack:
        _bad("Acknowledge operational assumptions first: " + "; ".join(i["title"] for i in pending_ack), 409)
    try:
        compile_plan(plan)
    except CompileError as e:
        _bad(f"Plan does not compile: {e}", 422)
    h = plan_hash(plan)
    stage = "statistics" if body.role == "statistician" else "protocol"
    plan.setdefault("approvals", []).append({"stage": stage, "by": body.by, "at": _now(), "plan_hash": h,
                                              "plan_version": plan.get("version"), "statement": body.statement})
    if stage == "protocol":
        plan["status"] = "approved"
    proj["plan"] = plan = agents.refresh_plan(plan)
    store.event(proj, body.by, "protocol_approved" if stage == "protocol" else "statistical_review_signed", {"plan_hash": h, "statement": body.statement})
    store.save(proj)
    return _public(proj)


class AssessQ(BaseModel):
    question: str = Field(min_length=4, max_length=2000)
    cycles: list[str] | None = None


@app.post("/api/assess")
def assess_question(body: AssessQ):
    """Can NHANES answer this? Pre-check from the question alone (no data, no plan stored)."""
    from .privacy import scrub
    q, _ = scrub(body.question)
    return answerability.assess_question(q, body.cycles)


@app.post("/api/projects/{pid}/probe")
def probe(pid: str, actor: str = "investigator"):
    _project(pid)
    try:
        run_probe(pid, actor)
    except (RunError, CompileError) as e:
        _bad(f"Feasibility probe failed: {e}", 409)
    proj = store.get(pid)
    proj["plan"] = agents.refresh_plan(proj["plan"])
    store.save(proj)
    return _public(proj)


@app.post("/api/projects/{pid}/run")
def run(pid: str, actor: str = "investigator"):
    try:
        r = start_run(pid, actor)
    except (RunError, CompileError) as e:
        _bad(str(e), 409)
    return {k: v for k, v in r.items() if k != "log"}


@app.get("/api/projects/{pid}/runs/{rid}")
def run_status(pid: str, rid: str):
    try:
        r = get_run(pid, rid)
    except KeyError:
        _bad("Run not found", 404)
    return {**{k: v for k, v in r.items() if k != "log"}, "log": r.get("log", [])[-200:]}


@app.get("/api/projects/{pid}/runs/{rid}/results")
def run_results(pid: str, rid: str):
    try:
        return load_results(pid, rid)
    except KeyError:
        _bad("Results not available", 404)


@app.get("/api/projects/{pid}/runs/{rid}/files/{name}")
def run_file(pid: str, rid: str, name: str):
    if "/" in name or ".." in name:
        _bad("bad file name")
    r = get_run(pid, rid)
    f = Path(r["dir"]) / "out" / name
    if not f.exists():
        _bad("File not found", 404)
    return FileResponse(f)


def _report(pid: str, rid: str, use_llm: bool) -> tuple[dict, dict, dict, dict | None]:
    proj = _project(pid)
    r = get_run(pid, rid)
    results = load_results(pid, rid)
    narr = None
    cache = Path(r["dir"]) / "narrative.json"
    if use_llm:
        if cache.exists():
            narr = json.loads(cache.read_text())
        else:
            narr = agents.narrative(proj["plan"], results)
            if narr:
                cache.write_text(json.dumps(narr))
                store.event(proj, "agents", "narrative_drafted", {"run_id": rid, "llm_calls": narr.get("llm", {}).get("calls", [])})
                store.save(proj)
    return proj, r, results, narr


@app.get("/api/projects/{pid}/runs/{rid}/report.html", response_class=HTMLResponse)
def report_html(pid: str, rid: str, llm: bool = False):
    proj, r, results, narr = _report(pid, rid, llm)
    return report.build_html(proj, r, results, narr)


@app.get("/api/projects/{pid}/runs/{rid}/report.md", response_class=PlainTextResponse)
def report_md(pid: str, rid: str, llm: bool = False):
    proj, r, results, narr = _report(pid, rid, llm)
    return report.build_markdown(proj, r, results, narr)


@app.get("/api/projects/{pid}/runs/{rid}/summary")
def report_summary(pid: str, rid: str):
    proj, r, results, narr = _report(pid, rid, False)
    return report.build_sections(proj, results, narr)


@app.get("/api/projects/{pid}/runs/{rid}/bundle.zip")
def bundle(pid: str, rid: str):
    proj, r, results, narr = _report(pid, rid, False)
    data = build_bundle(proj, r, report.build_html(proj, r, results, narr), report.build_markdown(proj, r, results, narr), store)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=q2e_{pid}_{rid}.zip"})


class Signoff(BaseModel):
    by: str = Field(min_length=2, max_length=120)
    run_id: str
    overrides: dict[str, str] = {}
    attestations: list[str] = []


@app.post("/api/projects/{pid}/signoff")
def signoff(pid: str, body: Signoff):
    proj = _project(pid)
    r = get_run(pid, body.run_id)
    if r.get("status") != "completed":
        _bad("Run is not complete", 409)
    if r["plan_hash"] != plan_hash(proj["plan"]):
        _bad("The plan changed after this run; re-run before signing off", 409)
    results = load_results(pid, body.run_id)
    fails = [c for c in results.get("checks", []) if c["status"] == "fail"]
    missing = [c["id"] for c in fails if not body.overrides.get(c["id"], "").strip()]
    if missing:
        _bad("Failed checks need a documented override reason: " + ", ".join(missing), 409)
    res_hash = hashlib.sha256((Path(r["dir"]) / "out" / "results.json").read_bytes()).hexdigest()
    proj["signoff"] = {"by": body.by, "at": _now(), "run_id": body.run_id, "plan_hash": r["plan_hash"], "results_sha256": res_hash,
                       "overrides": body.overrides, "attestations": body.attestations,
                       "synthetic": results.get("meta", {}).get("synthetic", False)}
    proj["plan"]["status"] = "signed"
    store.event(proj, body.by, "results_signed_off", proj["signoff"])
    store.save(proj)
    return _public(proj)


@app.get("/api/projects/{pid}/provenance")
def provenance(pid: str):
    proj = _project(pid)
    return {"events": proj["events"], "history": proj["history"], "chain": store.verify_chain(proj)}


@app.get("/api/projects/{pid}/plans/{version}")
def plan_version(pid: str, version: int):
    f = store.path(pid) / "plans" / f"plan_v{version}.json"
    if not f.exists():
        _bad("Version not found", 404)
    return json.loads(f.read_text())


@app.get("/api/projects/{pid}/compiled")
def compiled(pid: str):
    try:
        return compile_plan(_project(pid)["plan"])
    except CompileError as e:
        _bad(str(e), 422)


@app.get("/api/projects/{pid}/literature")
def project_literature(pid: str):
    return literature.prior_literature(_project(pid)["plan"])


# ------------------------------------------------------------------ knowledge / guidelines
@app.get("/api/tools")
def list_tools():
    """Tool registry for AI platforms (OpenAI-style function specs). Approval is deliberately not a tool."""
    from .integrations import openai_tools
    return {"tools": openai_tools(), "governance": "AI may draft, assess, probe, fix, run approved plans and read results; "
                                                  "only a human can approve or sign off."}


@app.post("/api/tools/{name}")
def call_tool(name: str, body: dict, request: Request):
    if settings.tool_key and request.headers.get("x-q2e-key") != settings.tool_key:
        _bad("Missing or invalid X-Q2E-Key header", 401)
    client = (request.headers.get("x-q2e-client") or request.headers.get("user-agent") or "rest")[:60]
    try:
        return qtools.call(name, body, client=client)
    except qtools.ToolError as e:
        _bad(str(e), 400)


@app.post("/api/projects/{pid}/novelty")
def project_novelty(pid: str):
    proj = _project(pid)
    nv = novelty.novelty(proj["plan"])
    proj["novelty"] = {**nv, "plan_version": proj["plan"].get("version")}
    if nv.get("score") is not None:
        proj["plan"]["novelty"] = {"score": nv["score"], "label": nv["label"], "summary": nv["summary"], "checked": nv["checked"]}
        proj["plan"] = agents.refresh_plan(proj["plan"])
    store.event(proj, "agent:Librarian", "novelty_checked", {"score": nv.get("score"), "exact": nv.get("exact"), "error": nv.get("error")})
    store.save(proj)
    return proj["novelty"]


@app.get("/api/projects/{pid}/where-next")
def project_where_next(pid: str, live: bool = True):
    proj = _project(pid)
    results = None
    runs = [r for r in proj.get("runs", []) if r.get("status") == "completed"]
    if runs:
        try:
            results = load_results(pid, runs[-1]["id"])
        except KeyError:
            results = None
    return venues.where_next(proj["plan"], results, live=live)


@app.get("/api/guidelines")
def guidelines():
    k = get_knowledge()
    return [k.definition_card(d) for d in k.definitions.values()]


@app.get("/api/guidelines/watch")
def guidelines_watch():
    return literature.guideline_watch()


class GuidelineText(BaseModel):
    text: str = Field(min_length=40, max_length=20000)
    provider: str | None = None


@app.post("/api/guidelines/import")
def guideline_import(body: GuidelineText):
    try:
        d = agents.import_guideline(body.text, body.provider)
    except (LLMError, expressions.ExpressionError) as e:
        _bad(str(e), 422)
    f = Path(settings.workspace) / "proposed_definitions.json"
    props = json.loads(f.read_text()) if f.exists() else []
    props.append({**d, "proposed_at": _now()})
    f.write_text(json.dumps(props, indent=2))
    return d


class Promote(BaseModel):
    id: str
    by: str


@app.post("/api/guidelines/approve")
def guideline_approve(body: Promote):
    import yaml
    f = Path(settings.workspace) / "proposed_definitions.json"
    props = json.loads(f.read_text()) if f.exists() else []
    d = next((p for p in props if p.get("id") == body.id), None)
    if not d:
        _bad("Proposal not found", 404)
    d = {**d, "status": "investigator-approved", "approved_by": body.by, "approved_at": _now()}
    target = settings.knowledge_dir / "definitions" / "local_approved.yaml"
    data = yaml.safe_load(target.read_text()) if target.exists() else {"definitions": []}
    data["definitions"] = [x for x in data["definitions"] if x["id"] != d["id"]] + [d]
    target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    get_knowledge.cache_clear()
    return d


class MatchQuery(BaseModel):
    query: str
    dataset_id: str | None = None
    top_k: int = 8


@app.post("/api/dictionary/match")
def dictionary_match(body: MatchQuery):
    k = get_knowledge()
    if body.dataset_id:
        from .matcher import DictEntry
        rec = generic.get_dataset(body.dataset_id)
        idx = BM25Index([DictEntry(variable=d["variable"], label=d.get("label", ""), type=d.get("type", ""), units=d.get("units", ""))
                         for d in rec["dictionary"]])
    else:
        idx = k.var_index()
    hits = idx.search(body.query, top_k=body.top_k)
    for h in hits:
        if not body.dataset_id and h["variable"] in k.dictionary:
            h["cycles"] = k.dictionary[h["variable"]]["cycles"]
    return hits


class Learn(BaseModel):
    term: str = Field(min_length=2, max_length=80)
    target: str = Field(min_length=3, max_length=80, description="concept:<id> or var:<NHANES variable>")
    by: str = Field(min_length=2, max_length=120)


@app.get("/api/learn")
def learned_list():
    from .knowledge import load_learned
    return {"learned": load_learned()}


@app.post("/api/learn")
def learn(body: Learn):
    """Teach Q2E a synonym. Human-confirmed (named); applies to every future question on this server."""
    from .knowledge import save_learned
    k = get_knowledge()
    kind, _, target = body.target.partition(":")
    if kind == "concept" and target not in k.concepts:
        _bad(f"Unknown concept '{target}'", 422)
    if kind == "var" and target.upper() not in k.dictionary:
        _bad(f"Unknown dataset variable '{target}'", 422)
    if kind not in ("concept", "var"):
        _bad("target must be concept:<id> or var:<VARIABLE>", 422)
    entry = {"term": body.term.lower().strip(), "target": f"{kind}:{target.upper() if kind == 'var' else target}",
             "by": body.by, "at": _now()}
    items = save_learned(entry)
    return {"saved": entry, "total": len(items)}


class Expr(BaseModel):
    expr: str


@app.post("/api/expressions/validate")
def validate_expr(body: Expr):
    k = get_knowledge()
    try:
        ids = expressions.validate(body.expr, set(k.blocks) | set(k.definitions) | set(k.dictionary))
        return {"ok": True, "identifiers": ids}
    except expressions.ExpressionError as e:
        return {"ok": False, "error": str(e)}


# ------------------------------------------------------------------ datasets
@app.post("/api/datasets")
async def upload_dataset(name: str = Form(...), data: UploadFile = File(...), dictionary: UploadFile | None = File(None)):
    raw = await data.read()
    if len(raw) > 200 * 1024 * 1024:
        _bad("File too large (200 MB max)")
    dct = await dictionary.read() if dictionary else None
    try:
        return generic.register_dataset(name, raw, dct)
    except Exception as e:  # noqa: BLE001
        _bad(f"Could not read dataset: {e}", 422)


@app.get("/api/datasets")
def datasets():
    return generic.list_datasets()


@app.get("/api/datasets/{did}")
def dataset(did: str):
    try:
        return generic.get_dataset(did)
    except KeyError:
        _bad("Dataset not found", 404)


# ------------------------------------------------------------------ voice
class TTS(BaseModel):
    text: str = Field(min_length=1, max_length=2500)


@app.post("/api/voice/tts")
def voice_tts(body: TTS):
    try:
        return Response(voice.tts(body.text), media_type="audio/mpeg")
    except voice.VoiceError as e:
        _bad(str(e), 503)


@app.post("/api/voice/stt")
async def voice_stt(audio: UploadFile = File(...)):
    try:
        text = voice.stt(await audio.read(), audio.filename or "idea.webm", audio.content_type or "audio/webm")
    except voice.VoiceError as e:
        _bad(str(e), 503)
    clean, findings = privacy.scrub(text)
    return {"text": clean, "redactions": len(findings)}


@app.exception_handler(HTTPException)
async def http_exc(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
