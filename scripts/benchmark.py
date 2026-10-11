"""Accuracy benchmark: ask Q2E the questions behind published NHANES estimates and compare the answers.

    python scripts/benchmark.py [--only id1,id2] [--out outputs/benchmark]

Each item in benchmarks/published_estimates.yaml is asked as a plain-language question. Q2E designs the study
itself (definition, population, weights), the protocol is auto-approved exactly as the command-line `study`
does, the R engine runs on CDC data, and the crude weighted prevalence (overall, men, women) is compared with
the published figure. Nothing is tuned per item.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from q2e import agents, planner  # noqa: E402
from q2e.compiler import plan_hash  # noqa: E402
from q2e.runner import get_run, load_results, start_run  # noqa: E402
from q2e.store import store  # noqa: E402

APPROVER = "Benchmark (automatic approval)"
SEX = {"Male": ("Male", "Men", "male"), "Female": ("Female", "Women", "female")}


def _ci(p: dict) -> tuple[float, float, str]:
    if "lcl" in p:
        return p["lcl"], p["ucl"], "published"
    return p["est"] - 1.96 * p["se"], p["est"] + 1.96 * p["se"], "est +/- 1.96 SE"


def _approve(proj: dict) -> dict:
    for issue in list(proj["plan"]["review"]):
        if (issue.get("fix") or {}).get("op") == "acknowledge":
            proj["plan"] = planner.apply_fix(proj["plan"], {**issue["fix"], "by": APPROVER})
    proj["plan"] = agents.refresh_plan(proj["plan"])
    proj["plan"]["approvals"].append({"stage": "protocol", "by": APPROVER, "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                      "plan_hash": plan_hash(proj["plan"]), "statement": "benchmark"})
    store.save(proj)
    return proj


SOURCE = "cdc"


def run_item(item: dict) -> dict:
    t0 = time.time()
    plan = agents.design_study(item["question"], item["cycles"], {"type": "nhanes", "cycles": item["cycles"], "source": SOURCE})
    out = {"id": item["id"], "question": item["question"], "cycles": item["cycles"],
           "q2e_definition": plan["outcome"].get("definition_id") or plan["outcome"].get("variable"),
           "q2e_label": plan["outcome"].get("label"), "q2e_type": plan["outcome"].get("type"),
           "q2e_population": [c["expr"] for c in plan.get("population", [])],
           "expected_definition": item.get("expected_definition"), "comparisons": []}
    out["definition_match"] = bool(item.get("expected_definition")) and out["q2e_definition"] == item["expected_definition"]
    proj = store.create(item["question"], plan, APPROVER)
    proj = _approve(proj)
    blockers = [i["title"] for i in proj["plan"]["review"] if i["severity"] == "blocker"]
    if blockers:
        out.update(status="blocked", note="; ".join(blockers))
        return out
    try:
        run = start_run(proj["id"], APPROVER, wait=True)
        run = get_run(proj["id"], run["id"])
    except Exception as e:  # noqa: BLE001
        out.update(status="run_failed", note=str(e)[:300])
        return out
    if run["status"] != "completed":
        out.update(status="run_failed", note=str(run.get("error"))[:300])
        return out
    res = load_results(proj["id"], run["id"])
    out["weight"] = (res.get("design") or {}).get("weight_variable")
    out["n_analytic"] = (res.get("primary_estimate") or {}).get("n")
    y = proj["plan"]["outcome"].get("variable")
    prev = [p for p in res.get("prevalence", []) if p.get("outcome") == y]
    if out["q2e_type"] != "binary" or not prev:
        pe = res.get("primary_estimate") or {}
        out.update(status="wrong_measure",
                   note=f"Q2E reported {pe.get('effect_label') or pe.get('effect')} of {pe.get('label')} = {pe.get('est')}, not a prevalence")
        return out
    out["status"] = "answered"
    for grp, pub in item["published"].items():
        if grp == "overall":
            q = next((p for p in prev if p.get("group_var") == "Overall"), None)
        else:
            q = next((p for p in prev if p.get("group_var") == "sex" and str(p.get("group")) in SEX[grp]), None)
        lcl, ucl, ci_src = _ci(pub)
        row = {"group": grp, "published": pub["est"], "pub_lcl": round(lcl, 2), "pub_ucl": round(ucl, 2), "pub_ci_source": ci_src}
        if q is None or q.get("est") is None:
            row.update(q2e=None)
        else:
            e, l, u = 100 * q["est"], 100 * q["lcl"], 100 * q["ucl"]
            se_pub = (ucl - lcl) / (2 * 1.96)
            row.update(q2e=round(e, 2), q2e_lcl=round(l, 2), q2e_ucl=round(u, 2), n=q.get("n"),
                       diff_pts=round(e - pub["est"], 2), rel_diff_pct=round(100 * (e - pub["est"]) / pub["est"], 1),
                       within_pub_ci=lcl <= e <= ucl, ci_overlap=l <= ucl and lcl <= u,
                       z=round((e - pub["est"]) / se_pub, 2) if se_pub > 0 else None)
        out["comparisons"].append(row)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def summarize(items: list[dict]) -> dict:
    comps = [c for it in items if it["status"] == "answered" for c in it["comparisons"] if c.get("q2e") is not None]
    matched = [c for it in items if it["status"] == "answered" and it["definition_match"] for c in it["comparisons"] if c.get("q2e") is not None]

    def stats(cs):
        if not cs:
            return {"n": 0}
        ad = [abs(c["diff_pts"]) for c in cs]
        return {"n": len(cs), "within_published_ci": sum(c["within_pub_ci"] for c in cs), "ci_overlap": sum(c["ci_overlap"] for c in cs),
                "mean_abs_diff_pts": round(sum(ad) / len(ad), 2), "median_abs_diff_pts": round(sorted(ad)[len(ad) // 2], 2),
                "max_abs_diff_pts": round(max(ad), 2), "within_1pt": sum(a <= 1 for a in ad), "within_2pt": sum(a <= 2 for a in ad)}
    return {"questions": len(items),
            "answered_as_prevalence": sum(it["status"] == "answered" for it in items),
            "right_definition": sum(it["definition_match"] for it in items),
            "no_matching_definition_in_q2e": sum(not it.get("expected_definition") for it in items),
            "status": {s: sum(it["status"] == s for it in items) for s in sorted({it["status"] for it in items})},
            "all_answered": stats(comps), "right_definition_only": stats(matched)}


def to_markdown(items: list[dict], summ: dict, meta: dict) -> str:
    def pct(a, b):
        return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"
    s, m = summ["all_answered"], summ["right_definition_only"]
    L = ["# Q2E accuracy against published NHANES estimates", "",
         f"Run {meta['date']} on CDC public-use files. {summ['questions']} published prevalence questions from NCHS reports and "
         "JAMA Network Open; each asked once in plain language; Q2E unchanged and auto-approved; crude weighted prevalence "
         "compared with the published crude estimate (overall, men, women).", "",
         "## Summary", "",
         f"* Questions answered as a prevalence: {pct(summ['answered_as_prevalence'], summ['questions'])}",
         f"* Questions where Q2E picked the published case definition: {pct(summ['right_definition'], summ['questions'])}"
         f" ({summ['no_matching_definition_in_q2e']} published definitions are not in Q2E's library)", ""]
    for title, st in (("When Q2E used the published definition", m), ("All estimates Q2E produced", s)):
        if st["n"]:
            L += [f"**{title}** ({st['n']} estimates):", "",
                  f"* Inside the published 95% CI: {pct(st['within_published_ci'], st['n'])}",
                  f"* 95% CIs overlap: {pct(st['ci_overlap'], st['n'])}",
                  f"* Within 1 percentage point: {pct(st['within_1pt'], st['n'])}; within 2 points: {pct(st['within_2pt'], st['n'])}",
                  f"* Mean absolute difference {st['mean_abs_diff_pts']} points (median {st['median_abs_diff_pts']}, max {st['max_abs_diff_pts']})", ""]
    L += ["## Item by item", "", "| Item | Group | Published % (95% CI) | Q2E % (95% CI) | Diff (pts) | In CI | Q2E definition |",
          "|---|---|---|---|---|---|---|"]
    for it in items:
        dn = f"{it['q2e_label']}" + ("" if it["definition_match"] else (" - **differs**" if it.get("expected_definition") else " - **no matching definition**"))
        if it["status"] != "answered":
            L.append(f"| {it['id']} | - | {it['comparisons'][0]['published'] if it['comparisons'] else ''} | **{it['status']}**: {it.get('note', '')} | | | {dn} |")
            continue
        for c in it["comparisons"]:
            got = c.get("q2e") is not None
            q = f"{c['q2e']:.1f} ({c['q2e_lcl']:.1f}-{c['q2e_ucl']:.1f})" if got else "-"
            d = f"{c['diff_pts']:+.1f}" if got else ""
            inci = ("yes" if c["within_pub_ci"] else "no") if got else ""
            L.append(f"| {it['id']} | {c['group']} | {c['published']:.1f} ({c['pub_lcl']:.1f}-{c['pub_ucl']:.1f}) | {q} | {d} | {inci} | "
                     f"{dn if c['group'] == 'overall' else ''} |")
    L += ["", "## Sources", ""] + [f"* {v['citation']} {v['url']}" for v in meta["sources"].values()]
    L += ["", "_CIs from reports that give only standard errors are estimate +/- 1.96 SE. Q2E reports crude (not age-adjusted) prevalence, "
          "so crude published figures are used throughout._"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "benchmark"))
    ap.add_argument("--source", default="cdc", help="cdc (real data) or synthetic (smoke test only)")
    a = ap.parse_args()
    global SOURCE
    SOURCE = a.source
    cfg = yaml.safe_load((ROOT / "benchmarks" / "published_estimates.yaml").read_text(encoding="utf-8"))
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    items = []
    for it in cfg["items"]:
        if only and it["id"] not in only:
            continue
        print(f"== {it['id']}: {it['question']}", flush=True)
        try:
            r = run_item(it)
        except Exception as e:  # noqa: BLE001
            r = {"id": it["id"], "question": it["question"], "status": "error", "note": str(e)[:300], "comparisons": [],
                 "definition_match": False, "expected_definition": it.get("expected_definition"), "q2e_label": "?"}
        for c in r.get("comparisons", []):
            print(f"   {c['group']:8} published {c['published']:5.1f}  Q2E {c.get('q2e')}  diff {c.get('diff_pts')}  in CI {c.get('within_pub_ci')}", flush=True)
        print(f"   status {r['status']}  definition {r.get('q2e_definition')} (expected {r.get('expected_definition')})  {r.get('note', '')}", flush=True)
        items.append(r)
    summ = summarize(items)
    meta = {"date": dt.date.today().isoformat(), "sources": cfg["sources"]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps({"meta": meta, "summary": summ, "items": items}, indent=2, default=str), encoding="utf-8")
    (out / "benchmark.md").write_text(to_markdown(items, summ, meta), encoding="utf-8")
    print(json.dumps(summ, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
