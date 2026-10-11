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


def _compare(grp: str, pub: dict, q: dict | None, key: str = "") -> dict:
    lcl, ucl, ci_src = _ci(pub)
    row = {"group": grp, "published": pub["est"], "pub_lcl": round(lcl, 2), "pub_ucl": round(ucl, 2), "pub_ci_source": ci_src}
    if q is None or q.get(key + "est") is None:
        row.update(q2e=None)
        return row
    e, l, u = 100 * q[key + "est"], 100 * q[key + "lcl"], 100 * q[key + "ucl"]
    se_pub = (ucl - lcl) / (2 * 1.96)
    row.update(q2e=round(e, 2), q2e_lcl=round(l, 2), q2e_ucl=round(u, 2), n=q.get("n"),
               diff_pts=round(e - pub["est"], 2), rel_diff_pct=round(100 * (e - pub["est"]) / pub["est"], 1) if pub["est"] else None,
               within_pub_ci=lcl <= e <= ucl, ci_overlap=l <= ucl and lcl <= u, z=round((e - pub["est"]) / se_pub, 2) if se_pub > 0 else None)
    return row


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
    out["data_limits"] = [f"{d['severity']}: {d['title']}" for d in plan.get("data_limits") or []]
    proj = store.create(item["question"], plan, APPROVER)
    proj = _approve(proj)
    blockers = [i["title"] for i in proj["plan"]["review"] if i["severity"] == "blocker"]
    if item.get("expect_limit"):
        # the published figure uses restricted (RDC) data: the right answer is to flag or decline, not to match it
        out.update(status="flagged_limit" if out["data_limits"] else "missed_limit",
                   note="; ".join(out["data_limits"]) or "did not flag that the public files cannot reproduce this population")
        if blockers or not out["data_limits"]:
            return out
    elif blockers:
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
    if out.get("status") not in ("flagged_limit", "missed_limit"):
        out["status"] = "answered"
    measure = item.get("measure", "crude")
    out["measure"] = measure
    if measure == "mean":
        means = res.get("means") or []
        if not means:
            pe = res.get("primary_estimate") or {}
            out.update(status="wrong_measure", note=f"Q2E reported {pe.get('effect_label')} = {pe.get('est')}, not a mean")
            return out
        for grp, pub in item["published"].items():
            m = next((x for x in means if (x["group_var"] == "Overall" and grp == "overall") or str(x["group"]) in SEX.get(grp, (grp,))), None)
            lcl, ucl, ci_src = _ci(pub)
            row = {"group": grp, "published": pub["est"], "pub_lcl": round(lcl, 3), "pub_ucl": round(ucl, 3), "pub_ci_source": ci_src, "units": True}
            if m:
                row.update(q2e=round(m["mean"], 3), q2e_lcl=round(m["mean_lcl"], 3), q2e_ucl=round(m["mean_ucl"], 3), n=m.get("n"),
                           diff_pts=round(m["mean"] - pub["est"], 3), within_pub_ci=lcl <= m["mean"] <= ucl,
                           ci_overlap=m["mean_lcl"] <= ucl and lcl <= m["mean_ucl"])
                if pub.get("quantiles"):
                    qs = {round(q["p"], 2): q["est"] for q in m.get("quantiles", [])}
                    row["quantiles"] = {str(k): {"published": v, "q2e": qs.get(round(float(k), 2))} for k, v in pub["quantiles"].items()}
            out["comparisons"].append(row)
        out["seconds"] = round(time.time() - t0, 1)
        return out
    if measure == "anchor":
        # regression anchors: Q2E's own earlier real-data results, which must not drift without an explanation
        pe = res.get("primary_estimate") or {}
        a = item["anchor"]
        ok = pe.get("est") is not None and abs(pe["est"] - a["est"]) <= a.get("tol", 1e-3)
        out["comparisons"].append({"group": "primary", "published": a["est"], "pub_lcl": a["est"], "pub_ucl": a["est"], "units": True,
                                   "q2e": pe.get("est"), "q2e_lcl": pe.get("lcl"), "q2e_ucl": pe.get("ucl"), "n": pe.get("n"),
                                   "diff_pts": None if pe.get("est") is None else round(pe["est"] - a["est"], 6), "within_pub_ci": ok, "ci_overlap": ok,
                                   "anchor": True, "anchor_n": a.get("n")})
        out["seconds"] = round(time.time() - t0, 1)
        return out
    if measure == "comparison":
        cmp = res.get("comparison") or {}
        cs = cmp.get("contrasts") or []
        if not cs:
            out.update(status="wrong_measure", note="Q2E did not produce a group comparison")
            return out
        vals = {}
        for c in cs:
            vals[(c["basis"], c["level"])] = c["est_level"]
            vals[(c["basis"], c["reference"])] = c["est_ref"]
        for basis, key in (("crude", "published"), ("age-adjusted", "published_aa")):
            for grp, pub in (item.get(key) or {}).items():
                v = vals.get((basis, grp))
                out["comparisons"].append(_compare(f"{grp} ({basis})", pub, {"est": v, "lcl": v, "ucl": v} if v is not None else None))
        if "published_significant" in item:
            ps = [c["p"] for c in cs if c["basis"] == "crude"]
            q2e_sig = bool(ps) and min(ps) < 0.05
            out["significance"] = {"published": item["published_significant"], "q2e": q2e_sig, "p": min(ps) if ps else None,
                                   "agrees": q2e_sig == item["published_significant"]}
        out["seconds"] = round(time.time() - t0, 1)
        return out
    if item.get("trend"):
        tr = res.get("trend") or {}
        if not tr.get("rows"):
            out.update(status="wrong_measure", note="Q2E did not produce per-cycle estimates")
            return out
        out["trend_tests"] = tr.get("tests")
        key = "adj_" if measure == "age_adjusted" else ""
        for cy, groups in item["by_cycle"].items():
            for grp, pub in groups.items():
                r = next((x for x in tr["rows"] if x["cycle"] == cy and ((grp == "overall" and x["group_var"] == "Overall")
                                                                           or str(x["group"]) in SEX.get(grp, (grp,)))), None)
                out["comparisons"].append(_compare(f"{cy} {grp}", pub, r, key))
        out["seconds"] = round(time.time() - t0, 1)
        return out
    prev = [p for p in res.get("prevalence", []) if p.get("outcome") == y]
    if out["q2e_type"] != "binary" or not prev:
        pe = res.get("primary_estimate") or {}
        out.update(status="wrong_measure",
                   note=f"Q2E reported {pe.get('effect_label') or pe.get('effect')} of {pe.get('label')} = {pe.get('est')}, not a prevalence")
        return out
    key = "adj_" if measure == "age_adjusted" else ""
    for grp, pub in item["published"].items():
        if grp == "overall":
            q = next((p for p in prev if p.get("group_var") == "Overall"), None)
        elif grp in SEX:
            q = next((p for p in prev if p.get("group_var") == "sex" and str(p.get("group")) in SEX[grp]), None)
        else:   # age groups and other published subgroups, matched by label
            q = next((p for p in prev if p.get("group_var") not in ("Overall", "sex") and str(p.get("group")) == grp), None)
        out["comparisons"].append(_compare(grp, pub, q, key))
    out["seconds"] = round(time.time() - t0, 1)
    return out


def summarize(items: list[dict]) -> dict:
    comps = [c for it in items if it["status"] == "answered" for c in it["comparisons"] if c.get("q2e") is not None and not c.get("units")]
    matched = [c for it in items if it["status"] == "answered" and it["definition_match"] for c in it["comparisons"]
               if c.get("q2e") is not None and not c.get("units")]

    def stats(cs):
        if not cs:
            return {"n": 0}
        ad = [abs(c["diff_pts"]) for c in cs]
        return {"n": len(cs), "within_published_ci": sum(c["within_pub_ci"] for c in cs), "ci_overlap": sum(c["ci_overlap"] for c in cs),
                "mean_abs_diff_pts": round(sum(ad) / len(ad), 2), "median_abs_diff_pts": round(sorted(ad)[len(ad) // 2], 2),
                "max_abs_diff_pts": round(max(ad), 2), "within_1pt": sum(a <= 1 for a in ad), "within_2pt": sum(a <= 2 for a in ad)}
    return {"questions": len(items),
            "answered_as_prevalence": sum(it["status"] == "answered" for it in items),
            "right_definition": sum(it["definition_match"] for it in items if it["status"] not in ("flagged_limit", "missed_limit")),
            "no_matching_definition_in_q2e": sum(not it.get("expected_definition") and it.get("measure") not in ("anchor", "mean") for it in items),
            "status": {s: sum(it["status"] == s for it in items) for s in sorted({it["status"] for it in items})},
            "public_data_limits": {"expected": sum(1 for it in items if it["status"] in ("flagged_limit", "missed_limit")),
                                   "flagged": sum(1 for it in items if it["status"] == "flagged_limit")},
            "all_answered": stats(comps), "right_definition_only": stats(matched),
            "by_estimand": {k: stats([c for it in items if it["status"] == "answered" and _kind(it) == k for c in it["comparisons"]
                                      if c.get("q2e") is not None and not c.get("units")])
                            for k in sorted({_kind(it) for it in items}) if k not in ("mean", "anchor")},
            "anchors": [{"id": it["id"], **c} for it in items if _kind(it) == "anchor" for c in it["comparisons"]],
            "means": [{"id": it["id"], **c} for it in items if _kind(it) == "mean" for c in it["comparisons"]],
            "significance": {"checked": sum(1 for it in items if it.get("significance")),
                             "agree": sum(1 for it in items if (it.get("significance") or {}).get("agrees"))}}


def _kind(it: dict) -> str:
    m = it.get("measure", "crude")
    if it.get("trend"):
        return f"trend ({m.replace('_', '-')})"
    if m == "mean":
        return "mean"
    if m == "anchor":
        return "anchor"
    if m == "comparison":
        return "group comparison"
    subgroup = any(c["group"] not in ("overall", "Male", "Female") for c in it.get("comparisons", []))
    return m.replace("_", "-") + (" incl. age groups" if subgroup and m == "crude" else "")


def _pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def _estimand_lines(summ: dict) -> list[str]:
    L = ["| Estimand | Estimates | Inside published 95% CI | Within 1 point | Mean abs. difference (pts) |", "|---|---|---|---|---|"]
    for k, st in (summ.get("by_estimand") or {}).items():
        if st.get("n"):
            L.append(f"| {k} | {st['n']} | {_pct(st['within_published_ci'], st['n'])} | {_pct(st['within_1pt'], st['n'])} | {st['mean_abs_diff_pts']} |")
    for m in summ.get("means") or []:
        if m.get("q2e") is not None:
            L.append(f"| mean ({m['id']}, {m['group']}) | 1 | {'yes' if m['within_pub_ci'] else 'no'} | published {m['published']} vs Q2E {m['q2e']} | {abs(m['diff_pts'])} (units) |")
    for a in summ.get("anchors") or []:
        L.append(f"| regression anchor ({a['id']}) | 1 | {'unchanged' if a['within_pub_ci'] else '**CHANGED**'} | earlier {a['published']} vs now {a['q2e']} | n {a.get('anchor_n')} vs {a.get('n')} |")
    sig = summ.get("significance") or {}
    if sig.get("checked"):
        L += ["", f"Published significance conclusions reproduced: {_pct(sig['agree'], sig['checked'])}"]
    return L + [""]


def _summary_lines(summ: dict) -> list[str]:
    s, m = summ["all_answered"], summ["right_definition_only"]
    lim = summ.get("public_data_limits") or {}
    L = [f"* Questions answered with the requested estimand: {_pct(summ['answered_as_prevalence'], summ['questions'] - lim.get('expected', 0))}"
         + (f"; questions the public files cannot answer as published, correctly flagged or declined: {_pct(lim['flagged'], lim['expected'])}"
            if lim.get("expected") else ""),
         f"* Questions where Q2E picked the published case definition: {_pct(summ['right_definition'], summ['questions'] - lim.get('expected', 0))}"
         f" ({summ['no_matching_definition_in_q2e']} published definitions are not in Q2E's library)", ""]
    for title, st in (("When Q2E used the published definition", m), ("All estimates Q2E produced", s)):
        if st["n"]:
            L += [f"**{title}** ({st['n']} estimates):", "",
                  f"* Inside the published 95% CI: {_pct(st['within_published_ci'], st['n'])}",
                  f"* 95% CIs overlap: {_pct(st['ci_overlap'], st['n'])}",
                  f"* Within 1 percentage point: {_pct(st['within_1pt'], st['n'])}; within 2 points: {_pct(st['within_2pt'], st['n'])}",
                  f"* Mean absolute difference {st['mean_abs_diff_pts']} points (median {st['median_abs_diff_pts']}, max {st['max_abs_diff_pts']})", ""]
    return L


def to_markdown(items: list[dict], summ: dict, meta: dict) -> str:
    L = ["# Q2E accuracy against published NHANES estimates", "",
         f"Run {meta['date']} on CDC public-use files. Published crude prevalence estimates from NCHS reports and JAMA Network "
         "Open; each question asked once in plain language; Q2E auto-approved with no per-item tuning; crude weighted "
         "prevalence compared with the published figure (overall, men, women).", ""]
    for key, title in (("core", "Original questions"),
                       ("holdout", "Hold-out set 1 (added after the first fixes; its three failures were then fixed, so no longer unseen)"),
                       ("holdout2", "Hold-out set 2 (added last; never used to tune Q2E)"),
                       ("estimands", "New estimands: age-adjusted prevalence, trends, age groups, means (first run)"), ("all", "All questions")):
        if key in summ and summ[key]["questions"]:
            L += [f"## {title}", ""] + _summary_lines(summ[key]) + (["**By estimand:**", ""] + _estimand_lines(summ[key]) if key == "all" else [])
    L += ["## Item by item", "", "| Item | Group | Published % (95% CI) | Q2E % (95% CI) | Diff (pts) | In CI | Q2E definition |",
          "|---|---|---|---|---|---|---|"]
    for it in items:
        tag = {"holdout": " (hold-out 1)", "holdout2": " (hold-out 2)", "estimands": " (new estimand)"}.get(it.get("set"), "")
        dn = f"{it['q2e_label']}" + ("" if it["definition_match"] else (" - **differs**" if it.get("expected_definition") else " - **no matching definition**"))
        if it["status"] != "answered":
            L.append(f"| {it['id']}{tag} | - | {it.get('published_overall', '')} | **{it['status']}**: {it.get('note', '')} | | | {dn} |")
            continue
        for c in it["comparisons"]:
            got = c.get("q2e") is not None
            q = f"{c['q2e']:.1f} ({c['q2e_lcl']:.1f}-{c['q2e_ucl']:.1f})" if got else "-"
            d = f"{c['diff_pts']:+.1f}" if got else ""
            inci = ("yes" if c["within_pub_ci"] else "no") if got else ""
            L.append(f"| {it['id']}{tag} | {c['group']} | {c['published']:.1f} ({c['pub_lcl']:.1f}-{c['pub_ucl']:.1f}) | {q} | {d} | {inci} | "
                     f"{dn if c['group'] == 'overall' else ''} |")
    L += ["", "## Sources", ""] + [f"* {v['citation']} {v['url']}" for v in meta["sources"].values()]
    L += ["", "_CIs from reports that give only standard errors are estimate +/- 1.96 SE. Crude items are compared with crude published "
          "figures, age-adjusted items with age-adjusted figures (direct standardization to the 2000 U.S. standard population)._"]
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
        r["set"] = it.get("set", "core")
        r["published_overall"] = ((it.get("published") or {}).get("overall") or {}).get("est")
        r["measure"] = it.get("measure", "crude")
        r["trend"] = bool(it.get("trend"))
        items.append(r)
    summ = {"core": summarize([i for i in items if i.get("set", "core") == "core"]),
            "holdout": summarize([i for i in items if i.get("set") == "holdout"]),
            "holdout2": summarize([i for i in items if i.get("set") == "holdout2"]),
            "estimands": summarize([i for i in items if i.get("set") == "estimands"]), "all": summarize(items)}
    meta = {"date": dt.date.today().isoformat(), "sources": cfg["sources"]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps({"meta": meta, "summary": summ, "items": items}, indent=2, default=str), encoding="utf-8")
    (out / "benchmark.md").write_text(to_markdown(items, summ, meta), encoding="utf-8")
    print(json.dumps(summ, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
