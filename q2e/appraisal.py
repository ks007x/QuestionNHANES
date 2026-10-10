"""Methods summary, detected limitations and a GRADE-informed certainty rating for one cross-sectional study.

GRADE rates a body of evidence, not a single study, so this is explicitly labelled "GRADE-informed, single study".
Observational evidence starts at Low; it is rated down for risk of bias, inconsistency, indirectness and imprecision
and rated up for a large effect or a dose-response gradient. Publication bias cannot be judged from one study.
"""
from __future__ import annotations

import math
from typing import Any

from .knowledge import Knowledge, get_knowledge

LEVELS = ["Very low", "Low", "Moderate", "High"]
SYMBOLS = {"Very low": "⊕◯◯◯", "Low": "⊕⊕◯◯", "Moderate": "⊕⊕⊕◯", "High": "⊕⊕⊕⊕"}


def _cycles_text(plan: dict, k: Knowledge) -> str:
    cyc = plan.get("dataset", {}).get("cycles") or list(k.default_cycles)
    names = [k.cycles.get(c, {}).get("label", c).replace("NHANES ", "") for c in cyc]
    return ", ".join(str(n) for n in names)


def _primary(results: dict | None) -> dict | None:
    if not results:
        return None
    pe = results.get("primary_estimate") or {}
    if pe.get("est") is None or pe.get("lcl") is None or pe.get("ucl") is None:
        return None
    if pe.get("effect") in ("PR", "OR", "RR", "HR") and not (1e-4 < pe["est"] < 1e4):
        return None                               # non-estimable (separation / empty cell) - not interpretable
    return pe


def _ratio(effect: str | None) -> bool:
    return effect in ("PR", "OR", "RR", "HR")


def _null(effect: str | None) -> float:
    return 1.0 if _ratio(effect) else 0.0


def _excludes_null(r: dict, effect: str | None) -> bool:
    n0 = _null(effect)
    return r.get("lcl") is not None and r.get("ucl") is not None and (r["lcl"] > n0 or r["ucl"] < n0)


def _direction(r: dict, effect: str | None) -> int:
    return (r["est"] > _null(effect)) - (r["est"] < _null(effect))


# ------------------------------------------------------------------ methods summary
def methods_summary(plan: dict, results: dict | None = None, k: Knowledge | None = None) -> str:
    return " ".join(b["label"] + ": " + b["text"] + (" (" + "; ".join(b["items"]) + ")" if b.get("items") else "") for b in methods_bullets(plan, results, k))


def methods_bullets(plan: dict, results: dict | None = None, k: Knowledge | None = None) -> list[dict]:
    """The methods as labelled bullets: [{label, text}] (Design, Data, Population, Outcome, Exposure, ...)."""
    k = k or get_knowledge()
    y, x = plan["outcome"], plan.get("exposure")
    pop = [("excluding " + c["label"][0].lower() + c["label"][1:]) if c.get("kind") == "exclusion" else c["label"]
           for c in plan.get("population", []) if c.get("enabled", True)]
    design = (results or {}).get("design") or {}
    n = ((results or {}).get("primary_estimate") or {}).get("n")
    s = [f"Design: cross-sectional analysis of the National Health and Nutrition Examination Survey (NHANES), {_cycles_text(plan, k)}."]
    if pop:
        s.append("Population: " + "; ".join(pop) + (f" (analytic n = {n:,})." if n else "."))
    s.append(f"Outcome: {y.get('label') or k.label(y['variable'])}.")
    if x and plan.get("arms"):
        a = plan["arms"]
        s.append(f"Exposure: mutually exclusive groups ({', '.join(a['levels'])}), reference '{a['reference']}'.")
    elif x:
        s.append(f"Exposure: {x.get('label') or k.label(x['variable'])}.")
    covs = [k.label(c) for c in plan.get("covariates", [])]
    if x and plan.get("arms"):
        a = plan["arms"]
        crit = [c["label"].lower() for c in a.get("control_criteria") or []] if a.get("control_mode") == "healthy" else []
        s.append(f"Comparator: {a['reference']} - negative for every group" + (f" and free of {', '.join(crit)}" if crit else "")
                 + ("; all-negative controls as a sensitivity analysis." if crit else "."))
    elif x and x.get("type") == "continuous":
        s.append("Comparator: per-unit contrast along the exposure (lower vs higher values); quartiles as sensitivity.")
    elif x:
        s.append("Comparator: participants without the exposure, from the same survey population.")
    if covs and plan["study_type"] != "prevalence":
        s.append("Covariates: " + ", ".join(covs) + ".")
    s.append("Descriptive: survey-weighted Table 1" + (" by comparison group" if plan.get("table1_by") == "arms" else f" by {k.label(plan['table1_by']).lower()}" if plan.get("table1_by") else "")
             + "; weighted prevalence with 95% CIs.")
    if plan["study_type"] == "prevalence":
        s.append("Model: survey-weighted prevalence with Korn-Graubard 95% CIs, overall and by subgroup.")
    else:
        fam = plan.get("model", {}).get("family", "quasipoisson")
        what = {"quasipoisson": "prevalence ratios (survey-weighted Poisson regression)", "quasibinomial": "odds ratios (survey-weighted logistic regression)",
                "gaussian": "mean differences (survey-weighted linear regression)"}.get(fam, f"survey-weighted {fam} regression")
        sets = [a["label"] for a in plan.get("adjustment_sets", [])]
        s.append(f"Model: {what}" + (f"; sequential models: {', '.join(sets)}." if sets else "."))
    mods = [k.label(m) for m in plan.get("interactions", [])]
    if mods:
        s.append("Effect modification: interaction tests and stratified estimates by " + ", ".join(m.lower() for m in mods) + ".")
    w = design.get("weight_variable")
    if not w and plan.get("dataset", {}).get("type", "nhanes") == "nhanes":
        try:
            from .compiler import compile_plan
            cp = compile_plan(plan, k)
            ws = sorted({m["weights"].get(cp["weight_level"]) for m in cp["cycles_meta"].values() if m["weights"].get(cp["weight_level"])})
            w = (", ".join(ws) + f" ({cp['weight_level']} weight)") if ws else None
        except Exception:  # noqa: BLE001
            w = None
    s.append(f"Survey design: Taylor linearisation with strata and PSUs{f'; weight {w}' if w else ''}"
             + (f"; design df = {design['analytic_df']}." if design.get("analytic_df") is not None else "."))
    sens = [t["label"] for t in plan.get("sensitivity", []) if t.get("enabled", True)]
    if sens:
        s.append(f"Sensitivity analyses: {len(sens)} prespecified.")
    miss = plan.get("missing_data", {}).get("method", "complete_case")
    s.append("Missing data: " + ("complete-case primary analysis" + ("; multiple imputation as sensitivity." if any(t.get("type") == "mi" for t in plan.get("sensitivity", [])) else ".")
                                 if miss == "complete_case" else f"{miss}."))
    s.append("Reporting: STROBE; plan pre-registered by hash before data access.")
    out = []
    for line in s:
        lab, _, txt = line.partition(": ")
        out.append({"label": lab, "text": txt})
        if lab == "Sensitivity analyses":
            out[-1]["items"] = sens
    return out


# ------------------------------------------------------------------ limitations
def limitations(plan: dict, results: dict | None = None, audit: dict | None = None, power: dict | None = None,
                k: Knowledge | None = None) -> list[dict]:
    k = k or get_knowledge()
    out: list[dict] = []

    def add(area, text, impact="moderate", source="Design"):
        if not any(o["text"] == text for o in out):
            out.append({"area": area, "text": text, "impact": impact, "source": source})

    add("Temporality", "Cross-sectional: exposure and outcome are measured at the same visit, so the direction of association cannot be established.", "major")
    add("Confounding", "Residual and unmeasured confounding cannot be excluded in an observational analysis.", "major")
    y, x = plan["outcome"], plan.get("exposure")
    blob = " ".join(str(v.get("label", "")) + " " + str(v.get("variable", "")) for v in (y, x or {})).lower()
    if "single" in blob or any(w in blob for w in ("egfr", "uacr", "eosinophil", "ferritin", "hba1c", "glucose", "lab")):
        add("Measurement", "Laboratory values come from a single blood or urine sample; transient abnormalities may be misclassified as persistent.")
    if plan.get("arms"):
        a = plan["arms"]
        if a.get("control_mode") == "healthy":
            add("Comparator", "Healthy controls were screened for other diseases while exposure arms were not, which can exaggerate contrasts (healthy-control bias); an all-seronegative control group was run as a sensitivity analysis.", "moderate")
        k_cmp = max(1, len(a.get("levels", [])) - 1)
        if k_cmp > 1:
            add("Multiplicity", f"{k_cmp} comparisons against the reference group; nominal P values are not multiplicity-adjusted unless stated.", "minor")
    for c in (audit or {}).get("checks", []):
        if c["status"] in ("caution", "fail"):
            if c["area"] in ("Rationale", "Oversight", "Reproducibility") and c["status"] == "caution":
                continue                          # process to-dos, not limitations of the evidence
            if c["area"] == "Temporality" and c["status"] == "caution":
                continue                          # already stated as the cross-sectional limitation
            if c["area"] == "Comparator" and plan.get("arms"):
                continue                          # stated above with the healthy-control sensitivity analysis
            add(c["area"], f"{c['title']}: {c['detail']}", "major" if c["status"] == "fail" else "moderate", "Design audit")
    if results:
        for c in results.get("checks", []):
            if c.get("status") in ("warn", "fail") and c.get("id") != "synthetic_data":
                add(c.get("category", "QC"), f"{c['title']}: {c['message']}", "major" if c["status"] == "fail" else "minor", "Quality control")
        if (results.get("meta") or {}).get("synthetic"):
            add("Data", "Synthetic demonstration data were used; estimates are not valid population estimates.", "major", "Quality control")
        design = results.get("design") or {}
        if design.get("analytic_df") is not None and design["analytic_df"] < 8:
            add("Precision", f"Design degrees of freedom = {design['analytic_df']} (< 8); NCHS considers such estimates unreliable.", "major", "Quality control")
        if design.get("weight_level") == "subsample":
            add("Generalisability", "Analyses use a laboratory subsample with its own weights; sample size and precision are lower than for the full MEC sample.", "minor")
    if power and power.get("verdict", "").startswith("Underpowered"):
        add("Precision", f"Sample size: {power['verdict'].lower()} (target PR {power['settings']['target_ratio']}); a null result is not evidence of no association.", "moderate", "Power check")
    pe = _primary(results)
    if pe and _ratio(pe.get("effect")):
        ev = (results or {}).get("evalue") or {}
        if ev.get("point") and ev["point"] < 2 and _excludes_null(pe, pe.get("effect")):
            add("Confounding", f"E-value {ev['point']:.2f}: a modest unmeasured confounder (RR ≈ {ev['point']:.1f} with both exposure and outcome) could explain the association.", "moderate", "E-value")
    order = {"major": 0, "moderate": 1, "minor": 2}
    out.sort(key=lambda o: order[o["impact"]])
    return out


# ------------------------------------------------------------------ certainty
def certainty(plan: dict, results: dict | None = None, audit: dict | None = None, power: dict | None = None) -> dict[str, Any]:
    """GRADE-informed certainty for a single cross-sectional study (start Low, rate down/up)."""
    base = 1  # Low
    domains: list[dict] = []
    pe = _primary(results)
    effect = (pe or {}).get("effect")

    # risk of bias ---------------------------------------------------------------
    rob_reasons = []
    audit_fail = [c for c in (audit or {}).get("checks", []) if c["status"] == "fail"]
    audit_caut = [c for c in (audit or {}).get("checks", []) if c["status"] == "caution" and c["area"] in ("Outcome", "Comparator", "Confounding")]
    if audit_fail:
        rob_reasons.append("design audit failures: " + "; ".join(c["title"] for c in audit_fail))
    if len(audit_caut) >= 2:
        rob_reasons.append("multiple design cautions: " + "; ".join(c["title"] for c in audit_caut))
    if not plan.get("covariates") and plan["study_type"] != "prevalence":
        rob_reasons.append("no adjustment for confounders")
    rob = 2 if (audit_fail and len(rob_reasons) > 1) else (1 if rob_reasons else 0)
    domains.append({"domain": "Risk of bias", "rating": ["Not serious", "Serious", "Very serious"][rob], "change": -rob,
                    "reason": "; ".join(rob_reasons) or "Cross-sectional design already reflected in the Low starting level; adjusted, pre-specified analysis with design audit passed."})

    # inconsistency (across pre-specified sensitivity analyses) ----------------------
    inc = 0
    reason = "Only one study; consistency judged across pre-specified sensitivity analyses."
    if pe and results:
        sens = [s for s in results.get("sensitivity", []) if s.get("est") is not None and s.get("effect") == effect
                and s.get("type") not in ("unweighted",) and not (_ratio(effect) and (s["est"] <= 0 or s["est"] > 1e4))]
        if sens:
            d0 = _direction(pe, effect)
            flips = [s for s in sens if _direction(s, effect) != d0 and _excludes_null(s, effect)]
            lost = [s for s in sens if _excludes_null(pe, effect) and not _excludes_null(s, effect)]
            if flips:
                inc, reason = 1, "Sensitivity analyses point in opposite directions: " + "; ".join(s["label"] for s in flips)
            elif len(lost) > len(sens) / 2:
                inc, reason = 1, f"The association loses significance in {len(lost)} of {len(sens)} sensitivity analyses."
            else:
                reason = f"Direction and inference stable across {len(sens)} sensitivity analyses."
    domains.append({"domain": "Inconsistency", "rating": "Serious" if inc else "Not serious", "change": -inc, "reason": reason})

    # indirectness -----------------------------------------------------------------
    ind_r = []
    for c in (audit or {}).get("checks", []):
        if c["status"] in ("caution", "fail") and c["area"] in ("Outcome", "Meaningfulness") and ("proxy" in c["detail"].lower() or "self-report" in c["title"].lower() or "treatment" in c["title"].lower()):
            ind_r.append(c["title"])
    if (plan.get("exposure") or {}).get("concept", "").startswith(("rx_", "med_")):
        ind_r.append("exposure is a treatment proxy")
    ind = 1 if ind_r else 0
    domains.append({"domain": "Indirectness", "rating": "Serious" if ind else "Not serious", "change": -ind,
                    "reason": "; ".join(ind_r) or "US civilian non-institutionalised population; outcome measured directly."})

    # imprecision --------------------------------------------------------------------
    imp, ir = 0, "Not assessed (no results yet)."
    if pe:
        if _ratio(effect) and pe["lcl"] > 0:
            ratio_w = pe["ucl"] / pe["lcl"]
            crosses = not _excludes_null(pe, effect)
            under = bool(power and power.get("verdict", "").startswith("Underpowered"))
            if crosses and (ratio_w > 3 or under):
                imp, ir = 2, f"95% CI {pe['lcl']:.2f}-{pe['ucl']:.2f} is wide and includes no effect" + (" and the study is underpowered." if under else ".")
            elif crosses or ratio_w > 3 or under:
                imp, ir = 1, f"95% CI {pe['lcl']:.2f}-{pe['ucl']:.2f}" + (" includes no effect" if crosses else " is wide") + (" (underpowered for the target effect)." if under else ".")
            else:
                ir = f"95% CI {pe['lcl']:.2f}-{pe['ucl']:.2f} excludes no effect and is reasonably narrow."
        elif not _ratio(effect):
            crosses = not _excludes_null(pe, effect)
            imp, ir = (1, "95% CI includes no difference.") if crosses else (0, "95% CI excludes no difference.")
        n = pe.get("n")
        if n and n < 400 and imp == 0:
            imp, ir = 1, f"Small analytic sample (n = {n})."
    elif power and power.get("verdict", "").startswith("Underpowered"):
        imp, ir = 1, f"Pre-run power check: {power['verdict'].lower()}."
    domains.append({"domain": "Imprecision", "rating": ["Not serious", "Serious", "Very serious"][imp], "change": -imp, "reason": ir})

    domains.append({"domain": "Publication bias", "rating": "Not assessable", "change": 0,
                    "reason": "Cannot be judged from a single study; pre-registration by plan hash reduces selective reporting."})

    # rating up ------------------------------------------------------------------------
    up = 0
    ups = []
    if pe and _ratio(effect) and _excludes_null(pe, effect) and rob == 0 and imp == 0:   # only a large AND precise effect counts
        r = pe["est"] if pe["est"] >= 1 else 1 / pe["est"]
        lo = pe["lcl"] if pe["est"] >= 1 else 1 / pe["ucl"]
        if r > 5 and lo > 2:
            up, txt = 2, f"Very large effect ({effect} {pe['est']:.2f})"
        elif r > 2 and lo > 1:
            up, txt = 1, f"Large effect ({effect} {pe['est']:.2f})"
        else:
            txt = None
        if txt:
            ups.append({"domain": "Large effect", "change": up, "reason": txt + "."})
    if results and rob == 0:
        for s in results.get("sensitivity", []):
            if s.get("type") == "exposure_quartiles" and "trend" in (s.get("note") or "").lower():
                import re
                m = re.search(r"P for trend\s*([<>=]?\s*[0-9.e-]+)", s["note"])
                try:
                    pv = float(m.group(1).replace("<", "").replace("=", "").strip()) if m else None
                except ValueError:
                    pv = None
                if pv is not None and pv < 0.05:
                    up += 1
                    ups.append({"domain": "Dose-response", "change": 1, "reason": f"Gradient across exposure quartiles (P for trend {m.group(1).strip()})."})
                break
    if not ups:
        ups.append({"domain": "Rating up", "change": 0, "reason": "No large effect or dose-response gradient" + ((" (not considered when risk of bias or imprecision is serious)." if (rob or imp) else "."))})

    down = rob + inc + ind + imp
    level_i = max(0, min(3, base - down + min(up, 2)))
    level = LEVELS[level_i]
    meaning = {"High": "We are very confident the true association lies close to the estimate.",
               "Moderate": "The true association is probably close to the estimate, but may be substantially different.",
               "Low": "The true association may be substantially different from the estimate.",
               "Very low": "The true association is likely to be substantially different from the estimate."}[level]
    symbol = SYMBOLS[level]
    if not pe:
        level, symbol = "Not rated", "-"
        meaning = ("No estimable primary effect (see the quality-control failures), so certainty cannot be rated."
                   if results else "Rated after the analysis has run.")
    return {"framework": "GRADE-informed, single cross-sectional study", "start": "Low (observational)",
            "level": level, "symbol": symbol, "meaning": meaning,
            "domains": domains, "rating_up": ups, "net_down": down, "net_up": min(up, 2),
            "caveat": "GRADE rates bodies of evidence; this single-study rating summarises how much this analysis can contribute "
                      "and should be re-rated in any systematic review.",
            "assessed": bool(pe)}


def appraise(plan: dict, results: dict | None = None, audit: dict | None = None, power: dict | None = None) -> dict:
    mb = methods_bullets(plan, results)
    return {"methods": " ".join(b["label"] + ": " + b["text"] for b in mb), "methods_bullets": mb, "limitations": limitations(plan, results, audit, power),
            "certainty": certainty(plan, results, audit, power)}


def certainty_line(c: dict) -> str:
    downs = [f"{d['domain'].lower()} ({d['rating'].lower()})" for d in c["domains"] if d["change"] < 0]
    ups = [u["domain"].lower() for u in c["rating_up"] if u["change"] > 0]
    s = f"Certainty of evidence (GRADE-informed, single study): {c['level']} {c['symbol']}. Started Low (observational)"
    if downs:
        s += "; rated down for " + ", ".join(downs)
    if ups:
        s += "; rated up for " + ", ".join(ups)
    return s + ". " + c["meaning"]

