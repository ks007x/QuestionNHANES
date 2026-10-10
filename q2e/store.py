"""File-based project store with a hash-chained provenance ledger.

Every human decision and machine action (draft, edit, fix, approval, run, QC, sign-off,
LLM call) is appended as an event whose hash covers the previous event's hash, making the
trail tamper-evident: `verify_chain()` recomputes it end to end."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from .compiler import plan_hash
from .config import settings

_LOCK = threading.RLock()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class ProjectStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or settings.workspace) / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, pid: str) -> Path:
        if not pid.replace("_", "").isalnum():
            raise ValueError("bad project id")
        return self.root / pid

    def create(self, question: str, plan: dict, actor: str = "investigator") -> dict:
        pid = "prj_" + uuid.uuid4().hex[:10]
        proj = {"id": pid, "created": _now(), "question": question, "plan": plan, "history": [], "events": [],
                "runs": [], "signoff": None}
        self.path(pid).mkdir(parents=True, exist_ok=True)
        self.snapshot(proj, actor, "Initial AI draft")
        self.event(proj, actor, "question_submitted", {"question": question})
        self.event(proj, "agents", "plan_drafted", {"plan_id": plan["plan_id"], "llm": plan.get("llm", {}).get("provider"),
                                                    "llm_calls": plan.get("llm", {}).get("calls", [])})
        self.save(proj)
        return proj

    def snapshot(self, proj: dict, actor: str, note: str) -> None:
        plan = proj["plan"]
        h = plan_hash(plan)
        if proj["history"] and proj["history"][-1]["hash"] == h:
            return
        version = len(proj["history"]) + 1
        plan["version"] = version
        d = self.path(proj["id"]) / "plans"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"plan_v{version}.json").write_text(json.dumps(plan, indent=2, default=str))
        proj["history"].append({"version": version, "hash": h, "at": _now(), "by": actor, "note": note})

    def event(self, proj: dict, actor: str, action: str, detail: dict | None = None) -> dict:
        prev = proj["events"][-1]["hash"] if proj["events"] else "0" * 64
        ev = {"seq": len(proj["events"]) + 1, "at": _now(), "actor": actor, "action": action, "detail": detail or {},
              "plan_hash": plan_hash(proj["plan"]), "prev": prev}
        ev["hash"] = _h({k: v for k, v in ev.items() if k != "hash"})
        proj["events"].append(ev)
        return ev

    @staticmethod
    def verify_chain(proj: dict) -> dict:
        prev = "0" * 64
        for ev in proj["events"]:
            body = {k: v for k, v in ev.items() if k != "hash"}
            if ev["prev"] != prev or _h(body) != ev["hash"]:
                return {"valid": False, "broken_at": ev["seq"]}
            prev = ev["hash"]
        return {"valid": True, "events": len(proj["events"]), "head": prev}

    def save(self, proj: dict) -> None:
        with _LOCK:
            p = self.path(proj["id"])
            p.mkdir(parents=True, exist_ok=True)
            tmp = p / "project.json.tmp"
            tmp.write_text(json.dumps(proj, indent=2, default=str))
            tmp.replace(p / "project.json")

    def get(self, pid: str) -> dict:
        with _LOCK:
            f = self.path(pid) / "project.json"
            if not f.exists():
                raise KeyError(pid)
            return json.loads(f.read_text())

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.root.glob("prj_*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                pr = json.loads(f.read_text())
                out.append({"id": pr["id"], "created": pr["created"], "title": pr["plan"].get("title"), "question": pr["question"],
                            "status": pr["plan"].get("status"), "runs": len(pr.get("runs", [])), "signed": bool(pr.get("signoff"))})
            except Exception:  # noqa: BLE001
                continue
        return out


store = ProjectStore()
