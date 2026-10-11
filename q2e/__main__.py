"""Command line interface.

  python -m q2e serve [--port 8000]
  python -m q2e synth                      # generate synthetic NHANES-like demo data
  python -m q2e study "question" [--source synthetic|auto|local|cdc] [--cycles P] [--out dir] [--approver NAME]
  python -m q2e examples                   # run every example question end to end (synthetic)
  python -m q2e mcp                        # MCP server (stdio) for AI assistants
  python -m q2e integrations --base-url URL  # tool manifests for Azure OpenAI, AWS Bedrock, ElevenLabs, MCP
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
    from .llm import LLMClient
    st = LLMClient(provider).status()
    print(f"AI agents: {st['provider']} ({st['model']})" if st["enabled"] else
          "AI agents: off - rule-based agents only" + (f" ({st['provider']}: {st['why'] or st['policy_message']})" if st["provider"] != "offline" else ""))
    plan = agents.design_study(question, cycles, {"type": "nhanes", "cycles": cycles or ["P"], "source": source}, provider)
    proj = store.create(question, plan, approver)
    print(f"\n== {plan['title']}\n   {plan['refined_question']}\n   feasibility {plan['feasibility']['score']}/100 ({plan['feasibility']['label']})")
    if settings.allow_download and source != "synthetic":
        from . import novelty as _nov
        nv = _nov.novelty(plan)
        print(f"   novelty {nv['score']}/100 ({nv['label']}) - {nv.get('summary') or nv.get('error')}" if nv.get("score") is not None
              else f"   novelty not checked ({nv.get('error')})")
        if nv.get("score") is not None:
            proj["plan"]["novelty"] = {"score": nv["score"], "label": nv["label"], "summary": nv["summary"], "checked": nv["checked"]}
            proj["plan"] = agents.refresh_plan(proj["plan"])
            store.save(proj)
    for d in plan["agent_dialogue"]:
        print(f"   [{d['agent']}] {d['message'][:160]}")
    # CLI mode: acknowledge operational assumptions explicitly on behalf of the named approver
    for issue in list(plan["review"]):
        if issue.get("agent") == "Design auditor" and (issue.get("fix") or {}).get("op") == "add_sensitivity":
            proj["plan"] = planner.apply_fix(proj["plan"], issue["fix"])
            print(f"   [design auditor fix applied] {issue['title']}")
    for issue in list(proj["plan"]["review"]):
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
    from . import protocol_doc
    (out / "protocol_and_sap.md").write_text(protocol_doc.build_markdown(proj), encoding="utf-8")
    (out / "protocol_and_sap.html").write_text(protocol_doc.build_html(proj), encoding="utf-8")
    (out / "manuscript.html").write_text(report.build_html(proj, run, results), encoding="utf-8")
    (out / "manuscript.md").write_text(report.build_markdown(proj, run, results), encoding="utf-8")
    (out / "bundle.zip").write_bytes(build_bundle(proj, run, None, None, store))
    from . import r_script
    (out / "analysis.R").write_text(r_script.build(json.loads((Path(run["dir"]) / "compiled_plan.json").read_text(encoding="utf-8")),
                                                   proj, results), encoding="utf-8")
    try:
        from . import venues
        (out / "where_next.md").write_text(venues.to_markdown(venues.where_next(proj["plan"], results, live=settings.allow_download)), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print("   (where-next suggestions skipped:", e, ")")
    try:
        from . import appraisal, design_audit, power
        pw = power.assess(proj["plan"], proj["plan"].get("probe"), results)
        ap = appraisal.appraise(proj["plan"], results, design_audit.audit(proj["plan"], results, novelty=proj["plan"].get("novelty")), pw)
        print("   " + power.summary_text(pw))
        print("   " + appraisal.certainty_line(ap["certainty"]))
        (out / "appraisal.json").write_text(json.dumps({**ap, "power": pw}, indent=2, default=str), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print("   (appraisal skipped:", e, ")")
    try:
        from . import evidence, model_advisor
        ev = evidence.check(proj["plan"], results, live=settings.allow_download, provider=provider)
        proj["evidence"] = ev
        store.save(proj)
        (out / "evidence_check.md").write_text(evidence.to_markdown(ev))
        s = ev["summary"]
        print(f"   Published evidence: {s['label']} ({s['papers']} papers, {s['comparable']} comparable, {s['same_direction']} same direction)"
              + (f" - {ev['error']}" if ev.get("error") else ""))
        adv = model_advisor.advise(proj["plan"], proj["plan"].get("probe"), results, ev.get("landscape"), provider=provider)
        (out / "model_options.json").write_text(json.dumps(adv, indent=2, default=str))
        print(f"   Model advisor: {adv['rationale']}" + (f" [AI: {adv['ai']['provider']} {adv['ai']['model']}]" if adv.get("ai") else " [rule-based]"))
        if ev.get("llm"):
            print(f"   Abstracts also read by AI: {ev['llm']['provider']} {ev['llm']['model']} (numbers kept only if found in the abstract text)")
    except Exception as e:  # noqa: BLE001
        print("   (literature check skipped:", e, ")")
    pe = results.get("primary_estimate") or {}
    if pe.get("est") is not None:
        print(f"\n   Primary: {pe.get('label')}: {pe.get('est'):.4f} ({pe.get('lcl'):.4f}-{pe.get('ucl'):.4f}) [{pe.get('effect')}]")
    else:
        print("\n   Primary: not estimable - see the QC checks and model warnings")
    for c in results["checks"]:
        if c["status"] != "pass":
            print(f"   QC {c['status'].upper():5} {c['title']}: {c['message'][:140]}")
    print(f"   Outputs: {out}/manuscript.html, manuscript.md, analysis.R, bundle.zip  (project {proj['id']})")
    return 0


AI_TEST_QUESTIONS = ["Is HTN more common in men than women among US adults?",
                     "Is sugar diabetes linked to renal stones?",
                     "Toxocara vs Toxoplasma vs healthy for eos",
                     "Does obesity prevalence differ by race and ethnicity?"]


def _ai_test(questions: list[str]) -> int:
    """Run the AI agents live and print what each one did. Writes ai_test.md (no data is analysed, nothing is run)."""
    import time
    from . import agents, covariates
    from .llm import LLMClient
    client = LLMClient("bedrock")
    st = client.status()
    print(f"Amazon Bedrock: {st['model'] or '(no model id)'} - " + ("ready" if st["enabled"] else f"NOT ready: {st['why'] or st['policy_message']}"))
    if not st["enabled"]:
        print("Connect first: python3 -m q2e bedrock-connect")
        return 1
    lines = ["# BEDSIDE live AI test", "", f"Model: `{st['model']}` on Amazon Bedrock", ""]
    ok = True
    for q in questions or AI_TEST_QUESTIONS:
        t0 = time.time()
        plan = agents.design_study(q, None, None, provider="bedrock")
        secs = time.time() - t0
        calls = plan.get("llm", {}).get("calls", [])
        good = sum(1 for c in calls if c.get("ok"))
        cmp = (plan.get("estimand") or {}).get("comparison") or {}
        x = plan.get("exposure") or {}
        block = [f"## {q}", "",
                 f"- AI calls: {good}/{len(calls)} succeeded in {secs:.0f} s",
                 f"- Understood as: **{plan['study_type']}** - outcome *{plan['outcome']['label']}*"
                 + (f"; exposure *{x.get('label')}*" if x else "")
                 + (f"; comparison by {cmp.get('label', cmp.get('group_var'))} ("
                    + (f"{cmp['level']} vs {cmp['reference']}" if cmp.get("level") and cmp.get("reference") else "every group vs the reference")
                    + ")" if cmp else "")]
        for t in plan.get("recognized_terms", []):
            block.append(f"- Recognized ({'AI' if t['source'] == 'ai' else 'rules'}): \"{t['from']}\" -> {t['label'] or t['to']}")
        for d in plan.get("agent_dialogue", []):
            if d.get("source") == "llm":
                block.append(f"- {d['agent']}: {d['message']}")
        if plan.get("refined_question_llm"):
            block.append(f"- AI phrasing of the question: {plan['refined_question_llm']}")
        for i in plan.get("review", []):
            if i.get("agent") == "Reviewer (LLM)":
                block.append(f"- AI reviewer ({i['severity']}): {i['title']}")
        if x and not x.get("arms"):
            cv = covariates.suggest(plan, provider="bedrock")
            for s in cv.get("suggestions", []):
                if s.get("ai"):
                    block.append(f"- AI on covariate {s['label']}: {s['ai']['role']} - {s['ai']['why']}")
        failed = [c for c in calls if not c.get("ok")]
        for c in failed[:3]:
            block.append(f"- FAILED call ({c.get('agent')}): {str(c.get('error'))[:200]}")
        ok = ok and good > 0
        print("\n".join(block) + "\n", flush=True)
        lines += block + [""]
    from pathlib import Path
    Path("ai_test.md").write_text("\n".join(lines), encoding="utf-8")
    print("Saved: ai_test.md" + ("" if ok else "  (some questions had no successful AI call - see FAILED lines)"))
    return 0 if ok else 1


def _bedrock_connect(region: str, model: str) -> int:
    """Ask for the Bedrock API key without echoing it, test it, and save it to .env (which git ignores)."""
    import getpass
    import os
    from .llm import LLMError, bedrock_connect
    print("Connect BEDSIDE to Amazon Bedrock.\nCreate a key in the AWS console: Amazon Bedrock > API keys > Generate. "
          "The key is saved only in this folder's .env file, which is never uploaded to GitHub.")
    key = getpass.getpass("Bedrock API key (hidden): ").strip()
    region = region or input(f"AWS region [{os.environ.get('AWS_REGION', 'us-east-1')}]: ").strip()
    model = model or input("Model id (Enter = pick a Claude model automatically): ").strip()
    print("Testing the key with one short request...")
    try:
        out = bedrock_connect(key, region, model, remember=True)
    except LLMError as e:
        print(f"Not connected: {e}")
        return 1
    print(f"Connected: {out['model']} in {out['region']} (key {out['key']}). Saved to .env. "
          "Start the app with: python -m q2e serve")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="q2e")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    sub.add_parser("synth")
    sub.add_parser("bedrock-check", help="test the AWS Bedrock login and list the models it can use")
    at = sub.add_parser("ai-test", help="live test of the AI agents on Amazon Bedrock: shows what the AI did for a few questions")
    at.add_argument("questions", nargs="*")
    rd = sub.add_parser("refresh-data", help="re-download cached CDC files and replace any that CDC has updated")
    rd.add_argument("--check", action="store_true", help="only report which files changed")
    sub.add_parser("setup-code", help="show the code the browser asks for when connecting Bedrock from a Codespace or another computer")
    bc = sub.add_parser("bedrock-connect", help="enter a Bedrock API key (hidden), test it and save it to the local .env")
    bc.add_argument("--region", default=""); bc.add_argument("--model", default="")
    sub.add_parser("mcp", help="run the MCP (Model Context Protocol) server on stdio")
    ig = sub.add_parser("integrations", help="write tool manifests for Azure/AWS/ElevenLabs/MCP")
    ig.add_argument("--base-url", default=settings.public_url); ig.add_argument("--out", default="integrations/generated")
    st = sub.add_parser("study"); st.add_argument("question"); st.add_argument("--source", default="synthetic")
    st.add_argument("--cycles", nargs="*"); st.add_argument("--out", default="outputs"); st.add_argument("--approver", default="CLI investigator")
    st.add_argument("--provider")
    ex = sub.add_parser("examples"); ex.add_argument("--source", default="synthetic"); ex.add_argument("--out", default="outputs/examples")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("q2e.server:app", host=a.host, port=a.port)
        return 0
    if a.cmd == "bedrock-check":
        from .llm import bedrock_check
        return bedrock_check()
    if a.cmd == "ai-test":
        return _ai_test(a.questions)
    if a.cmd == "refresh-data":
        from .data_refresh import refresh
        out = refresh(check_only=a.check)
        return 1 if out["failed"] and not out["checked"] else 0
    if a.cmd == "setup-code":
        from .access import setup_code
        print(f"BEDSIDE setup code: {setup_code()}")
        return 0
    if a.cmd == "bedrock-connect":
        return _bedrock_connect(a.region, a.model)
    if a.cmd == "mcp":
        from .mcp_server import serve_stdio
        serve_stdio()
        return 0
    if a.cmd == "integrations":
        from .integrations import write_all
        for p in write_all(a.base_url, Path(a.out)):
            print("wrote", p)
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
