"""Command line interface.

  python -m q2e serve [--port 8000]
  python -m q2e synth                      # generate synthetic NHANES-like demo data
  python -m q2e study "question" [--source synthetic|auto|local|cdc] [--cycles P] [--out dir] [--approver NAME]
  python -m q2e examples                   # run every example question end to end (synthetic)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import settings


def _study(question: str, source: str, cycles: list[str] | None, out: Path, approver: str, provider: str | None) -> int:
    from . import agents, planner, report
    from .bundle import build_bundle
    from .runner import load_results, start_run, get_run
    from .store import store

    settings.ensure_dirs()
    plan = agents.design_study(question, cycles, {"type": "nhanes", "cycles": cycles or ["P"], "source": source}, provider)
    proj = store.create(question, plan, approver)
    print(f"\n== {plan['title']}\n   {plan['refined_question']}\n   feasibility {plan['feasibility']['score']}/100 ({plan['feasibility']['label']})")
    for d in plan["agent_dialogue"]:
        print(f"   [{d['agent']}] {d['message'][:160]}")
    # CLI mode: acknowledge operational assumptions explicitly on behalf of the named approver
    for issue in list(plan["review"]):
        if issue.get("fix", {}) and issue["fix"].get("op") == "acknowledge":
            proj["plan"] = planner.apply_fix(proj["plan"], {**issue["fix"], "by": approver})
            print(f"   [ack by {approver}] {issue['title']}")
    proj["plan"] = agents.refresh_plan(proj["plan"])
    blockers = [i for i in proj["plan"]["review"] if i["severity"] == "blocker"]
    if blockers:
        print("Blockers:", "; ".join(b["title"] for b in blockers))
        return 2
    from .compiler import plan_hash
    import datetime as dt
    proj["plan"]["approvals"].append({"stage": "protocol", "by": approver, "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                      "plan_hash": plan_hash(proj["plan"]), "statement": "CLI approval"})
    store.snapshot(proj, approver, "CLI approval")
    store.event(proj, approver, "protocol_approved", {"via": "cli"})
    store.save(proj)
    run = start_run(proj["id"], approver, wait=True)
    run = get_run(proj["id"], run["id"])
    if run["status"] != "completed":
        print("Run failed:", run.get("error"))
        return 1
    proj = store.get(proj["id"])
    results = load_results(proj["id"], run["id"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "manuscript.html").write_text(report.build_html(proj, run, results))
    (out / "manuscript.md").write_text(report.build_markdown(proj, run, results))
    (out / "bundle.zip").write_bytes(build_bundle(proj, run, None, None, store))
    pe = results.get("primary_estimate") or {}
    print(f"\n   Primary: {pe.get('label')}: {pe.get('est'):.4f} ({pe.get('lcl'):.4f}-{pe.get('ucl'):.4f}) [{pe.get('effect')}]")
    for c in results["checks"]:
        if c["status"] != "pass":
            print(f"   QC {c['status'].upper():5} {c['title']}: {c['message'][:140]}")
    print(f"   Outputs: {out}/manuscript.html, manuscript.md, bundle.zip  (project {proj['id']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="q2e")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    sub.add_parser("synth")
    st = sub.add_parser("study"); st.add_argument("question"); st.add_argument("--source", default="synthetic")
    st.add_argument("--cycles", nargs="*"); st.add_argument("--out", default="outputs"); st.add_argument("--approver", default="CLI investigator")
    st.add_argument("--provider")
    ex = sub.add_parser("examples"); ex.add_argument("--source", default="synthetic"); ex.add_argument("--out", default="outputs/examples")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("q2e.server:app", host=a.host, port=a.port)
        return 0
    if a.cmd == "synth":
        from .runner import ensure_synthetic
        print("Synthetic data in", ensure_synthetic())
        return 0
    if a.cmd == "study":
        return _study(a.question, a.source, a.cycles, Path(a.out), a.approver, a.provider)
    if a.cmd == "examples":
        from .knowledge import get_knowledge
        rc = 0
        for e in get_knowledge().examples:
            rc |= _study(e["question"], a.source, None, Path(a.out) / e["id"], "CLI investigator", None)
        return rc
    return 1


if __name__ == "__main__":
    sys.exit(main())
