"""JAMA Network Open-style manuscript generator (HTML + Markdown) built from the approved plan,
the engine's results and the provenance trail. Narrative sections come from templates, or
from an approved LLM (aggregate results only) passed through the causal-language guard."""
from __future__ import annotations

import base64
import datetime as _dt
import html
from pathlib import Path
from typing import Any

from .knowledge import get_knowledge
from .language_guard import scan_causal, soften


def _lc(label: str) -> str:
    return " ".join(w if (any(c.isupper() for c in w[1:]) or (len(w) > 1 and w.isupper())) else w.lower() for w in label.split())


# ---------------------------------------------------------------- formatting
def pct(x: float | None, d: int = 1) -> str:
    return "NA" if x is None else f"{100 * x:.{d}f}%"


def ci_pct(est, lcl, ucl, d=1) -> str:
    f = lambda x: "NA" if x is None else f"{100 * x:.{d}f}%"
    return f"{pct(est, d)} (95% CI, {f(lcl)}-{f(ucl)})"


def num(x, d=2) -> str:
    if x is None:
        return "NA"
    return f"{x:,.{d}f}"


def eff(est, lcl, ucl, d=2) -> str:
    if est is None:
        return "NA"
    return f"{num(est, d)} (95% CI, {num(lcl, d)} to {num(ucl, d)})" if (lcl is not None and lcl < 0) else f"{num(est, d)} (95% CI, {num(lcl, d)}-{num(ucl, d)})"


def pfmt(p) -> str:
    if p is None:
        return "P = NA"
    if p < 0.001:
        return "P < .001"
    s = f"{p:.3f}" if p < 0.01 else f"{p:.2f}"
    return "P = " + s.lstrip("0")


def esc(s: Any) -> str:
    if s is None:
        return ""
    return html.escape(str(s)).replace("&gt;=", "≥").replace("&lt;=", "≤")


def esc_code(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _effect_name(effect: str) -> str:
    return {"PR": "prevalence ratio (PR)", "OR": "odds ratio (OR)", "Beta": "mean difference (β)"}.get(effect, effect)


def _short_effect(effect: str) -> str:
    return {"PR": "PR", "OR": "OR", "Beta": "β"}.get(effect, effect)


def _t1_overall(results: dict, var: str, level: str | None = None) -> dict | None:
    t1 = results.get("table1") or {}
    for r in t1.get("rows", []):
        if r["variable"] == var and (level is None or r.get("level") == level):
            return r["values"].get("overall")
    return None


# ---------------------------------------------------------------- narrative
def build_sections(project: dict, results: dict, narrative: dict | None = None) -> dict[str, Any]:
    k = get_knowledge()
    plan = project["plan"]
    pe = results.get("primary_estimate") or {}
    design = results.get("design", {})
    flow = results.get("flow", [])
    n_an = next((f["n"] for f in flow if f["step"] == "outcome"), None)
    n_an = next((f["n"] for f in flow if f["step"] == "exposure"), n_an)
    weighted_m = design.get("sum_weights_millions")
    cycles_txt = " and ".join(k.cycles[c]["label"] for c in plan["dataset"].get("cycles", [])) if plan["dataset"].get("type") == "nhanes" else plan["dataset"].get("name", "the uploaded dataset")
    synthetic = results.get("meta", {}).get("synthetic", False)
    out_lab = plan["outcome"]["label"]
    out_concept = plan["outcome"].get("concept_label", out_lab)
    x = plan.get("exposure")
    # demographics from Table 1
    female = _t1_overall(results, "sex", "Female")
    age65 = _t1_overall(results, "agecat", "65+")
    demo_txt = ""
    if female and female.get("pct") is not None:
        demo_txt = f"; {female['pct']:.1f}% were female (weighted)"
    if age65 and age65.get("pct") is not None:
        demo_txt += f" and {age65['pct']:.1f}% were aged 65 years or older"
    n_txt = f"{n_an:,}" if n_an else "NA"
    pop_txt = f"{n_txt} participants (weighted to represent approximately {weighted_m:,.1f} million US residents{demo_txt})" if weighted_m else f"{n_txt} participants"

    if plan["study_type"] == "prevalence":
        finding = f"the weighted prevalence of {_lc(out_concept)} was {ci_pct(pe.get('est'), pe.get('lcl'), pe.get('ucl'))}"
        if pe.get("pop_millions"):
            finding += f", corresponding to approximately {pe['pop_millions']:.1f} million people"
        subg = [p for p in results.get("prevalence", []) if p["outcome"] == plan["outcome"]["variable"] and p["group_var"] != "Overall" and p.get("nchs") == "meets standard"]
        hi = max(subg, key=lambda p: p["est"]) if subg else None
        lo = min(subg, key=lambda p: p["est"]) if subg else None
        sub_txt = (f"Prevalence ranged from {pct(lo['est'])} ({_lc(lo['group_label'])}: {lo['group']}) to {pct(hi['est'])} "
                   f"({_lc(hi['group_label'])}: {hi['group']})." if hi and lo and hi is not lo else "")
        meaning = (f"{out_concept} affects a substantial share of this population under current guideline-based definitions; "
                   f"case definitions materially change prevalence, so the definition should be reported explicitly.")
        objective = f"To estimate the nationally representative prevalence of {_lc(out_concept)} and its distribution across demographic subgroups."
        exposures_txt = "Demographic and clinical subgroups (" + ", ".join(k.label(s) for s in plan.get("subgroups", [])) + ")."
        importance = (f"{out_concept} is a common, treatable condition whose estimated burden depends on the case definition. "
                      f"Contemporary nationally representative estimates aligned with current guideline thresholds are needed.")
    else:
        eff_lab = _short_effect(pe.get("effect", ""))
        per = ""
        if x and x.get("scale") not in (None, 1):
            per = f" per {x['scale']:g} {x.get('units', '')}".rstrip()
        finding = (f"{_lc(x['label']) if x else 'the exposure'}{per} was associated with {out_lab} ({eff_lab}{'' if eff_lab == 'β' else ''}, "
                   f"{eff(pe.get('est'), pe.get('lcl'), pe.get('ucl'))}) after adjustment for {', '.join(_lc(k.label(c)) for c in plan['covariates'])}")
        sub_txt = ""
        meaning = ("This association is cross-sectional and may reflect residual confounding or reverse causation; "
                   "prospective studies are needed to establish temporality.")
        objective = f"To evaluate whether {_lc(x['label']) if x else 'the exposure'} is associated with {_lc(out_lab)} among {_pop_noun(plan)}."
        exposures_txt = f"{x['label']}{per}." if x else ""
        importance = (f"Whether {_lc(x['label']) if x else 'the exposure'} is associated with {_lc(out_lab)} beyond established risk factors "
                      f"is uncertain in nationally representative data.")
    defn = k.definitions.get(plan["outcome"]["variable"])
    outcome_measure = (f"{out_lab}: {defn['criteria_text']} ({defn['source'].get('citation', '')})" if defn else out_lab)
    robust = next((c for c in results.get("checks", []) if c["id"] == "robustness"), None)
    bms = results.get("benchmarks", [])
    bm_txt = " ".join(
        f"The estimate {'was consistent with' if b['overlap'] else 'differed from'} the published estimate of {pct(b['published'], 0)} "
        f"({b['label']})." for b in bms[:1])
    results_par = (f"The analytic sample included {pop_txt}. Overall, {finding}. {sub_txt} "
                   + (robust["message"] + " " if robust else "") + bm_txt).strip()
    conclusion = (f"In this cross-sectional study of {_pop_noun(plan)}, {finding}. " + meaning)
    if synthetic:
        conclusion = "[ILLUSTRATIVE - SYNTHETIC DATA] " + conclusion

    intro = narrative.get("introduction") if narrative else None
    discussion = narrative.get("discussion") if narrative else None
    if not intro:
        intro = (f"{importance} National Health and Nutrition Examination Survey (NHANES) data permit design-based estimation that "
                 f"generalizes to the noninstitutionalized US population. {objective.replace('To ', 'We aimed to ', 1)}")
    if not discussion:
        lim = plan.get("limitations", [])
        discussion = (f"In this nationally representative cross-sectional analysis, {finding}. "
                      + (bm_txt + " " if bm_txt else "")
                      + "Strengths include a prespecified, investigator-approved protocol; guideline-versioned, citable case definitions; "
                        "design-based variance estimation with appropriate examination weights; NCHS reliability standards; multiple "
                        "prespecified sensitivity analyses; and a fully reproducible, provenance-tracked pipeline. "
                      + "Limitations: " + " ".join(lim[:6]))
    intro, discussion = soften(intro), soften(discussion)
    return {
        "title": plan["title"], "synthetic": synthetic,
        "key_points": {"question": plan["refined_question"], "findings": f"In this cross-sectional study of {pop_txt}, {finding}.",
                       "meaning": meaning},
        "abstract": {"Importance": importance, "Objective": objective,
                     "Design, Setting, and Participants": (f"This cross-sectional study used {cycles_txt} data. "
                                                           f"Eligible participants: {'; '.join(c['label'] for c in plan['population'] if c.get('enabled') and c['kind'] == 'inclusion')}"
                                                           + ("; excluded: " + "; ".join(_lc(c['label']) for c in plan['population'] if c.get('enabled') and c['kind'] == 'exclusion') if any(c.get('enabled') and c['kind'] == 'exclusion' for c in plan['population']) else "")
                                                           + f". Data were analyzed on {_dt.date.today():%B %d, %Y}."),
                     "Exposures": exposures_txt, "Main Outcomes and Measures": outcome_measure,
                     "Results": results_par,
                     "Conclusions and Relevance": (narrative or {}).get("conclusion") or conclusion},
        "introduction": intro, "discussion": discussion,
        "plain_language": _plain_language(plan, pe, n_an, synthetic),
        "n_analytic": n_an,
    }


def _pop_noun(plan: dict) -> str:
    t = plan.get("title", "")
    if " Among " in t:
        return _lc(t.split(" Among ")[1].split(":")[0]).replace("us ", "US ")
    return "US adults"


def _plain_language(plan, pe, n, synthetic) -> str:
    x = plan.get("exposure")
    if plan["study_type"] == "prevalence":
        s = (f"We looked at {n:,} people in a national health survey. About {100 * pe.get('est', 0):.0f} in every 100 adults "
             f"met the definition of {_lc(plan['outcome'].get('concept_label', plan['outcome']['label']))}. ") if n else ""
    else:
        s = (f"We looked at {n:,} people in a national health survey. People with higher {_lc(x['label'])} tended to have "
             f"{'higher' if (pe.get('est', 0) > (1 if pe.get('effect') in ('PR', 'OR') else 0)) else 'lower'} "
             f"{_lc(plan['outcome']['label'])}, even after accounting for {len(plan['covariates'])} other factors. "
             f"Because everyone was measured once, this shows a link, not cause and effect. ") if n and x else ""
    if synthetic:
        s += "These numbers come from synthetic demonstration data, not the real survey."
    return s


# ---------------------------------------------------------------- tables
def _table1_html(results) -> str:
    t1 = results.get("table1")
    if not t1:
        return ""
    cols = t1["columns"]
    def _hd(c):
        share = "" if c["key"] == "overall" else f" ({c['weighted_pct']:.1f}%)"
        return f"<th>{esc(c['label'])}<br><span class='sub'>n = {c['n']:,}{share}</span></th>"
    head = "".join(_hd(c) for c in cols)
    rows = []
    for r in t1["rows"]:
        if r.get("header") and r["type"] == "categorical":
            rows.append(f"<tr class='grp'><td>{esc(r['label'])}</td>" + "".join("<td></td>" for _ in cols) + f"<td>{esc(r.get('p_text', ''))}</td></tr>")
            continue
        cls = "lvl" if not r.get("header") else ""
        vals = "".join(f"<td>{esc(r['values'].get(c['key'], {}).get('text', ''))}</td>" for c in cols)
        rows.append(f"<tr class='{cls}'><td>{esc(r['label'])}</td>{vals}<td>{esc(r.get('p_text', ''))}</td></tr>")
    by = esc(t1.get("by_label") or "")
    return (f"<table class='tbl'><caption><b>Table 1.</b> Characteristics of the analytic sample{(' by ' + _lc(by)) if by else ''}</caption>"
            f"<thead><tr><th>Characteristic</th>{head}<th>P value</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
            f"<p class='note'>{esc(t1.get('note', ''))}</p>")


def _pci(p) -> str:
    f = lambda x: "NA" if x is None else f"{100 * x:.1f}"
    return f"{f(p.get('est'))} ({f(p.get('lcl'))}-{f(p.get('ucl'))})"


def _popm(p) -> str:
    v = p.get("pop_millions")
    return "" if v is None else f"{v:.1f}"


def _prev_html(results, plan) -> str:
    rows = [p for p in results.get("prevalence", [])]
    if not rows:
        return ""
    outs = []
    for p in rows:
        lvl = f" - {p['outcome_level']}" if p.get("outcome_level") else ""
        flag = "" if p["nchs"] == "meets standard" else f" <span class='flag'>{esc(p['nchs'])}</span>"
        outs.append(f"<tr><td>{esc(p['outcome_label'])}{esc(lvl)}</td><td>{esc(p['group_label'] if p['group_var'] != 'Overall' else '')}</td>"
                    f"<td>{esc(p['group'])}</td><td>{p['n']:,}</td><td>{p['events']:,}</td>"
                    f"<td>{_pci(p)}{flag}</td>"
                    f"<td>{_popm(p)}</td></tr>")
    return ("<table class='tbl'><caption><b>Table 2.</b> Survey-weighted prevalence, overall and by subgroup</caption>"
            "<thead><tr><th>Outcome</th><th>Subgroup</th><th>Level</th><th>No.</th><th>Cases</th><th>Weighted % (95% CI)</th><th>Population, millions</th></tr></thead>"
            f"<tbody>{''.join(outs)}</tbody></table><p class='note'>Korn-Graubard 95% CIs. Estimates not meeting NCHS Data Presentation Standards for Proportions are flagged.</p>")


def _models_html(results, plan) -> str:
    models = results.get("models", [])
    if not models:
        return ""
    x = (results.get("primary_estimate") or {}).get("term")
    rows = []
    for m in models:
        terms = [t for t in m["terms"] if t["term"] != "(Intercept)"]
        if plan["study_type"] == "association":
            terms = [t for t in terms if t["variable"] == x or t["term"].startswith(str(x))]
        for t in terms:
            rows.append(f"<tr><td>{esc(m['label'])}</td><td>{esc(t['label'])}</td><td>{m['n']:,}</td>"
                        f"<td>{eff(t['est'], t['lcl'], t['ucl'])}</td><td>{pfmt(t['p'])}</td></tr>")
    eff_label = models[0].get("effect_label", "")
    cap = "Association of the exposure with the outcome across adjustment sets" if plan["study_type"] == "association" else "Mutually adjusted correlates of the outcome"
    return (f"<table class='tbl'><caption><b>Table 3.</b> {cap} ({esc(eff_label)}, survey-weighted {esc(models[0]['family'])} regression)</caption>"
            f"<thead><tr><th>Model</th><th>Term</th><th>No.</th><th>{esc(_short_effect(models[0]['effect']))} (95% CI)</th><th>P value</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _sens_html(results) -> str:
    s = results.get("sensitivity", [])
    if not s:
        return ""
    rows = []
    for x in s:
        if x.get("error"):
            rows.append(f"<tr><td>{esc(x['label'])}</td><td colspan=3 class='flag'>{esc(x['error'])}</td></tr>")
            continue
        est = (ci_pct(x["est"], x["lcl"], x["ucl"]) if x.get("effect") == "prevalence" else f"{_short_effect(x.get('effect', ''))} {eff(x.get('est'), x.get('lcl'), x.get('ucl'))}") if x.get("est") is not None else "NA"
        n_txt = "" if x.get("n") is None else f"{x['n']:,}"
        rows.append(f"<tr><td>{esc(x['label'])}</td><td>{n_txt}</td><td>{esc(est)}</td><td>{esc(x.get('note') or '')}</td></tr>")
    return ("<table class='tbl'><caption><b>eTable 1.</b> Prespecified sensitivity analyses</caption>"
            "<thead><tr><th>Analysis</th><th>No.</th><th>Estimate</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _checks_html(results) -> str:
    rows = "".join(f"<tr><td class='st {c['status']}'>{c['status'].upper()}</td><td>{esc(c['category'])}</td><td>{esc(c['title'])}</td><td>{esc(c['message'])}</td></tr>"
                   for c in results.get("checks", []))
    return ("<table class='tbl'><caption><b>eTable 2.</b> Automated validation and quality-control checks</caption>"
            f"<thead><tr><th>Status</th><th>Area</th><th>Check</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table>")


def _flow_html(results) -> str:
    def _li(f):
        exc = f" <span class='sub'>(excluded {f['excluded']:,})</span>" if f.get("excluded") else ""
        return f"<li><b>{f['n']:,}</b> {esc(f['label'])}{exc}</li>"
    items = "".join(_li(f) for f in results.get("flow", []))
    return f"<ol class='flow'>{items}</ol>"


def _img(run_dir: Path, f: str) -> str:
    p = run_dir / "out" / f
    if not p.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


CSS = """
body{font-family:Georgia,'Times New Roman',serif;max-width:860px;margin:32px auto;padding:0 20px;color:#1d1d1f;line-height:1.55;background:#fff}
h1{font-size:26px;line-height:1.25;margin:8px 0 6px} h2{font-size:17px;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid #ccc;padding-bottom:3px;margin-top:30px}
h3{font-size:15px;margin:18px 0 4px}.kp{border-left:4px solid #1F5A85;background:#f4f7fa;padding:10px 16px;margin:16px 0}
.abs p{margin:4px 0}.abs b{font-variant:small-caps}.tbl{border-collapse:collapse;width:100%;font:12.5px/1.35 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:14px 0}
.tbl caption{text-align:left;padding:4px 0 6px;font-size:13px}.tbl th{background:#eef2f6;text-align:left;padding:5px 6px;border-bottom:1px solid #9aa}.tbl td{padding:4px 6px;border-bottom:1px solid #e3e6ea;vertical-align:top}
.tbl tr.grp td{font-weight:600}.tbl tr.lvl td:first-child{padding-left:18px}.note,.sub{color:#666;font-size:12px}.flag{color:#a0522d;font-size:11px}
.st{font-weight:700;font-size:11px}.st.pass{color:#2e7d32}.st.warn{color:#b26a00}.st.fail{color:#b00020}.st.info{color:#555}
figure{margin:18px 0}figure img{width:100%;border:1px solid #eee}figcaption{font-size:13px;color:#333}
.banner{background:#fff3e0;border:1px solid #f0b46a;padding:8px 12px;font:600 13px Helvetica,Arial,sans-serif;color:#7a4a00}
.meta{font:12px Helvetica,Arial,sans-serif;color:#555}.flow{font:13px Helvetica,Arial,sans-serif}code{font-size:12px;background:#f5f5f5;padding:1px 4px}
"""


def build_html(project: dict, run: dict, results: dict, narrative: dict | None = None) -> str:
    k = get_knowledge()
    plan = project["plan"]
    sec = build_sections(project, results, narrative)
    run_dir = Path(run["dir"])
    design = results.get("design", {})
    meta = results.get("meta", {})
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(plan['title'])}</title><style>{CSS}</style></head><body>"]
    if sec["synthetic"]:
        parts.append("<div class='banner'>SYNTHETIC DEMONSTRATION DATA - estimates are illustrative and are not valid NHANES population estimates.</div>")
    parts.append(f"<p class='meta'>Original Investigation · Cross-sectional study · Generated by Q2E v{esc(meta.get('engine_version', ''))} · "
                 f"Plan {esc(plan['plan_id'])} v{plan.get('version')} (sha256 {esc(run['plan_hash'][:12])})</p>")
    parts.append(f"<h1>{esc(sec['title'])}</h1>")
    so = project.get("signoff")
    parts.append(f"<p class='meta'>{'Signed off by ' + esc(so['by']) + ' on ' + esc(so['at']) if so else 'DRAFT - awaiting investigator sign-off'}</p>")
    kp = sec["key_points"]
    parts.append(f"<div class='kp'><b>Key Points</b><p><b>Question</b> {esc(kp['question'])}</p><p><b>Findings</b> {esc(kp['findings'])}</p><p><b>Meaning</b> {esc(kp['meaning'])}</p></div>")
    parts.append("<h2>Abstract</h2><div class='abs'>" + "".join(f"<p><b>{esc(h)}:</b> {esc(t)}</p>" for h, t in sec["abstract"].items()) + "</div>")
    parts.append(f"<h2>Introduction</h2><p>{esc(sec['introduction'])}</p>")
    # methods
    parts.append("<h2>Methods</h2>")
    if plan["dataset"].get("type") == "nhanes":
        parts.append("<h3>Data Source</h3><p>NHANES is a continuous, nationally representative survey of the US civilian noninstitutionalized population "
                     "using a stratified, multistage probability design, with household interviews and standardized physical examinations and laboratory "
                     f"testing in mobile examination centers (MECs). We used {esc(', '.join(k.cycles[c]['label'] for c in plan['dataset']['cycles']))}. "
                     "NHANES protocols were approved by the National Center for Health Statistics Research Ethics Review Board and participants provided "
                     "written informed consent; this analysis of deidentified public-use data did not require additional institutional review board review. "
                     "We followed the Strengthening the Reporting of Observational Studies in Epidemiology (STROBE) reporting guideline.</p>")
    parts.append("<h3>Study Population</h3>" + _flow_html(results))
    parts.append("<h3>Definitions</h3><ul>")
    used = [plan["outcome"]["variable"]] + ([plan["exposure"]["variable"]] if plan.get("exposure") else []) + plan.get("prevalence_outcomes", [])
    seen = set()
    for v in used:
        if v in seen:
            continue
        seen.add(v)
        d = k.definitions.get(v)
        if d:
            notes = " ".join(d.get("operational_notes", []))
            parts.append(f"<li><b>{esc(d['label'])}.</b> {esc(d['criteria_text'])} <i>Source:</i> {esc(d['source'].get('citation', ''))} "
                         f"[{esc(d.get('status'))}]{(' <i>Operationalization:</i> ' + esc(notes)) if notes else ''} <code>{esc_code(d['expr'])}</code></li>")
        elif v in k.blocks:
            b = k.blocks[v]
            parts.append(f"<li><b>{esc(b['label'])}</b>{' (' + esc(b.get('units')) + ')' if b.get('units') else ''}: <code>{esc_code(b.get('nhanes') or b.get('expr'))}</code></li>")
    parts.append("</ul>")
    parts.append("<h3>Covariates</h3><p>" + esc("; ".join(f"{k.label(c)}" + (f" ({plan['covariate_notes'][c]})" if c in plan.get("covariate_notes", {}) else "") for c in plan["covariates"])) + ".</p>")
    sens_list = "; ".join(s["label"] for s in plan["sensitivity"] if s.get("enabled"))
    pkgs = meta.get("packages", {})
    parts.append("<h3>Statistical Analysis</h3><p>" + esc(plan["rationale"].get("statistician_llm") or plan["rationale"]["statistician"]) + " "
                 + esc(f"All analyses incorporated the {design.get('weight_variable')} sample weight ({design.get('weight_level')} component), "
                       f"masked variance pseudo-strata and pseudo-PSUs (Taylor series linearization; {design.get('n_strata')} strata, "
                       f"{design.get('n_psu')} PSUs, design df = {design.get('design_df')}); subpopulations were analyzed with domain (subset) "
                       f"estimation to preserve the full design. Proportions use Korn-Graubard 95% CIs and were evaluated against the NCHS Data "
                       f"Presentation Standards for Proportions. Regression inference used t distributions with design degrees of freedom. ")
                 + esc(plan["rationale"]["epidemiologist"]) + " "
                 + esc(f"Effect modification was assessed with Wald F tests of product terms ({', '.join(k.label(i) for i in plan.get('interactions', []))}). " if plan.get("interactions") else "")
                 + esc(plan["missing_data"]["rationale"] + " ")
                 + esc(f"Prespecified sensitivity analyses: {sens_list}. ")
                 + esc("E-values quantified the minimum strength of unmeasured confounding needed to explain away the primary association. " if plan["study_type"] == "association" else "")
                 + esc(f"Two-sided P < .05 denoted significance. Analyses used {meta.get('r_version', 'R')} with survey {pkgs.get('survey', '')}, "
                       f"mice {pkgs.get('mice', '')} and ggplot2 {pkgs.get('ggplot2', '')}, orchestrated by Q2E.") + "</p>")
    parts.append("<h3>Human Oversight and Use of AI</h3><p>" + esc(
        f"The protocol was drafted by Q2E research agents ({plan.get('llm', {}).get('provider', 'offline')} mode: "
        f"{'rule-based agents only' if plan.get('llm', {}).get('provider', 'offline') == 'offline' else 'rule-based agents with LLM assistance; LLMs received only metadata' + (' and aggregate results' if narrative else '')}), "
        f"then reviewed, edited and approved by the investigator before execution. No participant-level data were sent to any language model. "
        f"Statistical code was not generated free-form: analyses ran in a versioned R engine whose derived-variable expressions pass a "
        f"whitelisted parser. All outputs were checked by {len(results.get('checks', []))} automated validation rules and signed off by the investigator.") + "</p>")
    # results
    parts.append("<h2>Results</h2><p>" + esc(sec["abstract"]["Results"]) + "</p>")
    ev = results.get("evalue")
    if ev:
        parts.append(f"<p>The E-value for the primary estimate was {num(ev['point'])} (CI limit {num(ev['ci'])}); {esc(ev['note'])}.</p>")
    for it in results.get("interactions", []):
        strata = "; ".join(f"{s['level']}: {num(s['est'])} ({num(s['lcl'])}-{num(s['ucl'])})" for s in it["strata"])
        parts.append(f"<p>Effect modification by {esc(_lc(it['label']))}: {pfmt(it['p_interaction'])} for interaction ({esc(strata)}).</p>")
    parts.append(_table1_html(results))
    parts.append(_prev_html(results, plan))
    parts.append(_models_html(results, plan))
    for i, f in enumerate(results.get("figures", []), 1):
        src = _img(run_dir, f["file"])
        if src:
            parts.append(f"<figure><img src='{src}' alt='{esc(f['title'])}'><figcaption><b>Figure {i}.</b> {esc(f['title'])}. "
                         f"Survey-weighted estimates with 95% CIs.</figcaption></figure>")
    parts.append(f"<h2>Discussion</h2><p>{esc(sec['discussion'])}</p>")
    parts.append("<h3>Limitations</h3><ul>" + "".join(f"<li>{esc(l)}</li>" for l in plan.get("limitations", [])) + "</ul>")
    parts.append(f"<h2>Conclusions</h2><p>{esc(sec['abstract']['Conclusions and Relevance'])}</p>")
    # supplement
    parts.append("<h2>Supplement</h2>")
    parts.append(_sens_html(results))
    parts.append(_checks_html(results))
    parts.append("<h3>eMethods. Derivation trace and provenance</h3><pre style='white-space:pre-wrap;font-size:11.5px;background:#f7f7f7;padding:10px'>"
                 + esc_code("\n".join(results.get("trace", []))) + "</pre>")
    files = "".join(f"<li>{esc(f['file'])} ({esc(f['origin'])}) md5 <code>{esc(f['md5'])}</code> n={f['nrow']:,}</li>" for f in meta.get("files", []))
    parts.append(f"<ul class='meta'><li>Plan hash: <code>{esc(run['plan_hash'])}</code></li><li>Run: {esc(run['id'])} · {esc(meta.get('started'))} → {esc(meta.get('finished'))} ({meta.get('seconds')} s)</li>"
                 f"<li>{esc(meta.get('r_version'))} on {esc(meta.get('platform'))}; seed {meta.get('seed')}</li>{files}</ul>")
    parts.append("</body></html>")
    out = "\n".join(parts)
    return out


def build_markdown(project: dict, run: dict, results: dict, narrative: dict | None = None) -> str:
    sec = build_sections(project, results, narrative)
    plan = project["plan"]
    lines = []
    if sec["synthetic"]:
        lines.append("> **SYNTHETIC DEMONSTRATION DATA - estimates are illustrative only.**\n")
    lines.append(f"# {sec['title']}\n")
    kp = sec["key_points"]
    lines.append(f"**Key Points**\n\n- **Question:** {kp['question']}\n- **Findings:** {kp['findings']}\n- **Meaning:** {kp['meaning']}\n")
    lines.append("## Abstract\n")
    for h, t in sec["abstract"].items():
        lines.append(f"**{h}:** {t}\n")
    lines.append(f"## Introduction\n\n{sec['introduction']}\n")
    lines.append("## Study population\n")
    for f in results.get("flow", []):
        lines.append(f"- {f['n']:,} - {f['label']}")
    lines.append("\n## Results\n")
    pe = results.get("primary_estimate") or {}
    lines.append(sec["abstract"]["Results"] + "\n")
    lines.append("| Outcome | Subgroup | Level | n | Weighted % (95% CI) | NCHS |\n|---|---|---|---|---|---|")
    for p in results.get("prevalence", []):
        lines.append(f"| {p['outcome_label']}{(' - ' + str(p['outcome_level'])) if p.get('outcome_level') else ''} | {p['group_label'] if p['group_var'] != 'Overall' else ''} | {p['group']} | {p['n']:,} | {_pci(p)} | {p['nchs']} |")
    if results.get("models"):
        lines.append("\n| Model | Term | n | Estimate (95% CI) | P |\n|---|---|---|---|---|")
        for m in results["models"]:
            for t in m["terms"]:
                if t["term"] == "(Intercept)":
                    continue
                if plan["study_type"] == "association" and t["term"] != pe.get("term") and not t["term"].startswith(str(pe.get("term"))):
                    continue
                lines.append(f"| {m['label']} | {t['label']} | {m['n']:,} | {eff(t['est'], t['lcl'], t['ucl'])} | {pfmt(t['p'])} |")
    lines.append("\n## Sensitivity analyses\n")
    for s in results.get("sensitivity", []):
        lines.append(f"- {s['label']}: " + (s.get("error") or (f"{s.get('est'):.3f} ({s.get('lcl'):.3f}-{s.get('ucl'):.3f})" if s.get("est") is not None else "NA")))
    lines.append(f"\n## Discussion\n\n{sec['discussion']}\n")
    lines.append("## Limitations\n")
    lines += [f"- {l}" for l in plan.get("limitations", [])]
    lines.append("\n## Validation checks\n")
    lines += [f"- **{c['status'].upper()}** {c['title']}: {c['message']}" for c in results.get("checks", [])]
    lines.append(f"\n---\nPlan hash `{run['plan_hash']}` · run `{run['id']}` · {results.get('meta', {}).get('r_version', '')}")
    md = "\n".join(lines)
    return md
