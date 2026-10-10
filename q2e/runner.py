"""Executes an approved plan with the R engine in a background thread."""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
import threading
import uuid
from pathlib import Path

from .compiler import compile_plan, plan_hash, write_compiled
from .config import settings
from .store import store

RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class RunError(RuntimeError):
    pass


def ensure_synthetic() -> Path:
    d = settings.synthetic_dir
    demo = d / "P_DEMO.xpt"
    stale = demo.exists() and settings.synth_script.exists() and settings.synth_script.stat().st_mtime > demo.stat().st_mtime
    if not demo.exists() or stale:
        subprocess.run([settings.rscript, str(settings.synth_script), str(d), "12000"], check=True,
                       capture_output=True, text=True, timeout=300)
    return d


def approved_for_current_plan(proj: dict) -> bool:
    h = plan_hash(proj["plan"])
    return any(a.get("plan_hash") == h for a in proj["plan"].get("approvals", []))


def start_run(pid: str, actor: str = "investigator", wait: bool = False) -> dict:
    proj = store.get(pid)
    if not approved_for_current_plan(proj):
        raise RunError("The current plan version has not been approved. Approve the protocol before running.")
    blockers = [i for i in proj["plan"].get("review", []) if i["severity"] == "blocker"]
    if blockers:
        raise RunError("Resolve reviewer blockers first: " + "; ".join(b["title"] for b in blockers))
    compiled = compile_plan(proj["plan"])
    if compiled["dataset"].get("source") == "synthetic":
        ensure_synthetic()
    rid = "run_" + uuid.uuid4().hex[:8]
    run_dir = store.path(pid) / "runs" / rid
    write_compiled(compiled, run_dir / "compiled_plan.json")
    run = {"id": rid, "status": "running", "started": _now(), "finished": None, "plan_hash": compiled["plan_hash"],
           "plan_version": proj["plan"].get("version"), "dir": str(run_dir), "log": [], "error": None,
           "data_source": compiled["dataset"].get("source", compiled["dataset"]["type"])}
    with _LOCK:
        RUNS[rid] = run
    proj["runs"].append({k: v for k, v in run.items() if k != "log"})
    store.event(proj, actor, "run_started", {"run_id": rid, "plan_hash": compiled["plan_hash"], "data_source": run["data_source"]})
    store.save(proj)
    t = threading.Thread(target=_execute, args=(pid, rid, run_dir), daemon=True)
    t.start()
    if wait:
        t.join()
    return run


def _execute(pid: str, rid: str, run_dir: Path) -> None:
    run = RUNS[rid]
    cmd = [settings.rscript, str(settings.engine_script), "--plan", str(run_dir / "compiled_plan.json"), "--out", str(run_dir / "out")]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(settings.root))
        for line in proc.stdout:  # type: ignore[union-attr]
            run["log"].append(line.rstrip())
        proc.wait(timeout=settings.run_timeout)
        if proc.returncode != 0:
            err = run_dir / "out" / "error.json"
            msg = json.loads(err.read_text())["error"] if err.exists() else "\n".join(run["log"][-5:])
            raise RunError(msg)
        run["status"] = "completed"
    except Exception as e:  # noqa: BLE001
        run["status"] = "failed"
        run["error"] = str(e)
    run["finished"] = _now()
    (run_dir / "run_log.txt").write_text("\n".join(run["log"]))
    proj = store.get(pid)
    for r in proj["runs"]:
        if r["id"] == rid:
            r.update({k: v for k, v in run.items() if k != "log"})
    detail = {"run_id": rid, "status": run["status"], "error": run["error"]}
    res = run_dir / "out" / "results.json"
    if res.exists():
        results = json.loads(res.read_text())
        checks = results.get("checks", [])
        detail.update({"results_sha256": __import__("hashlib").sha256(res.read_bytes()).hexdigest(),
                       "qc": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail", "info")},
                       "data_files": [{"file": f["file"], "md5": f["md5"]} for f in results.get("meta", {}).get("files", [])]})
        proj["plan"]["status"] = "executed"
    store.event(proj, "engine", "run_finished", detail)
    store.save(proj)


def get_run(pid: str, rid: str) -> dict:
    if rid in RUNS:
        return RUNS[rid]
    proj = store.get(pid)
    for r in proj["runs"]:
        if r["id"] == rid:
            log = Path(r["dir"]) / "run_log.txt"
            return {**r, "log": log.read_text().splitlines() if log.exists() else []}
    raise KeyError(rid)


_SCALARS = {"est", "lcl", "ucl", "p", "se", "beta", "n", "p_trend"}


def _normalize(o):
    """R/jsonlite writes empty numerics as []; make those None so the report never sees a list where a number belongs."""
    if isinstance(o, dict):
        return {k: (None if (k in _SCALARS and isinstance(v, list) and not v) else
                    v[0] if (k in _SCALARS and isinstance(v, list) and len(v) == 1) else _normalize(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_normalize(v) for v in o]
    return o


def load_results(pid: str, rid: str) -> dict:
    proj = store.get(pid)
    for r in proj["runs"]:
        if r["id"] == rid:
            f = Path(r["dir"]) / "out" / "results.json"
            if f.exists():
                return _normalize(json.loads(f.read_text()))
    raise KeyError(rid)


def run_probe(pid: str, actor: str = "investigator") -> dict:
    """Blinded feasibility probe (counts only) - allowed before approval."""
    proj = store.get(pid)
    compiled = compile_plan(proj["plan"])
    if compiled["dataset"].get("source") == "synthetic":
        ensure_synthetic()
    probe_id = "probe_" + uuid.uuid4().hex[:8]
    d = store.path(pid) / "probes" / probe_id
    write_compiled(compiled, d / "compiled_plan.json")
    cmd = [settings.rscript, str(settings.engine_script), "--plan", str(d / "compiled_plan.json"), "--out", str(d / "out"), "--probe"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(settings.root), timeout=settings.run_timeout)
    if proc.returncode != 0:
        err = d / "out" / "error.json"
        msg = json.loads(err.read_text())["error"] if err.exists() else (proc.stderr or proc.stdout)[-500:]
        raise RunError(msg)
    probe = json.loads((d / "out" / "probe.json").read_text())
    probe.update({"id": probe_id, "plan_hash": compiled["plan_hash"], "at": _now()})
    proj = store.get(pid)
    proj["plan"]["probe"] = probe
    store.event(proj, actor, "feasibility_probe", {"probe_id": probe_id, "plan_hash": compiled["plan_hash"], "blinded": True,
                                                  "n_analytic": probe.get("n_analytic"), "n_complete_case": probe.get("n_complete_case")})
    store.save(proj)
    return probe
