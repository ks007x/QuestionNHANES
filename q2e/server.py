"""Q2E web API + single-page UI.

    uvicorn q2e.server:app --port 8000      (or: python -m q2e serve)
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, agents, answerability, expressions, generic, literature, planner, privacy, report, voice
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
    proj["approved_current"] = any(a.get("plan_hash") == proj["plan_hash"] for a in proj["plan"].get("approvals", []))
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


@app.post("/api/projects")
def create_project(body: NewProject):
    k = get_knowledge()
    cycles = body.cycles or list(k.default_cycles)
    for c in cycles:
        if c not in k.cycles:
            _bad(f"Unknown cycle {c}")
    dataset = None
    if body.dataset_id:
        rec = generic.get_dataset(body.dataset_id)
        dataset = generic.dataset_spec(rec)
    else:
        dataset = {"type": "nhanes", "cycles": cycles, "source": body.source}
    try:
        plan = agents.design_study(body.question, cycles, dataset, body.provider)
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
    proj = store.create(body.question, plan, body.actor)
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
    proj["plan"] = new_plan
    store.snapshot(proj, body.actor, body.note or f"edit: {body.fix.get('op')}")
    store.event(proj, body.actor, "plan_edited", {"fix": body.fix})
    store.save(proj)
    return _public(proj)


class Approve(BaseModel):
    by: str = Field(min_length=2, max_length=120)
    statement: str = "I have reviewed the protocol, variable mappings, operational assumptions and analysis plan."


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
    plan.setdefault("approvals", []).append({"stage": "protocol", "by": body.by, "at": _now(), "plan_hash": h,
                                              "plan_version": plan.get("version"), "statement": body.statement})
    plan["status"] = "approved"
    store.event(proj, body.by, "protocol_approved", {"plan_hash": h, "statement": body.statement})
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
        idx = BM25Index(entries_from_nhanes(k.dictionary))
    hits = idx.search(body.query, top_k=body.top_k)
    for h in hits:
        if not body.dataset_id and h["variable"] in k.dictionary:
            h["cycles"] = k.dictionary[h["variable"]]["cycles"]
    return hits


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
