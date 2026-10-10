"""Can NHANES answer this question?

Two layers:

1. Static assessment (instant, no data): design fit, concept coverage, co-measurement of all
   required variables in the same survey cycles, subsample restrictions, age eligibility and
   measurement type.
2. Blinded feasibility probe (R, seconds): loads the real files and returns *counts only* -
   participants per cycle meeting the criteria, non-missing outcome/exposure/covariates,
   complete-case n, design df, subgroup sizes, the exposure SD and the outcome rate rounded to a
   5-point band. No association or exact prevalence is revealed before the protocol is approved,
   which avoids results-driven protocol changes. Precision and minimum detectable effects are then
   computed with a design effect assumption.

Verdict: "Answerable" / "Answerable with caveats" / "Not answerable as stated", with concrete
suggestions to make the question answerable.
"""
from __future__ import annotations

import math
import re
from typing import Any

from . import expressions, planner
from .knowledge import Knowledge, get_knowledge

DEFF = 1.8   # typical NHANES design effect for laboratory prevalence estimates (assumption, stated in output)
Z = 1.96
Z_POWER = 2.80   # 1.96 + 0.84 -> 80% power, two-sided alpha .05

# Typical minimum ages for NHANES components (approximate; the probe gives the empirical truth).
MIN_AGE = {"DPQ": 18, "ALQ": 18, "SMQ": 18, "KIQ_U": 20, "MCQ": 20, "BPQ": 16, "SLQ": 16, "OCQ": 16, "DUQ": 18,
           "HEQ": 6, "LUX": 12, "BIOPRO": 12, "GHB": 12, "GLU": 12, "INS": 12, "TRIGLY": 12, "TCHOL": 6, "HDL": 6,
           "ALB_CR": 6, "FETIB": 6, "COT": 3, "BPXO": 8, "BPX": 8, "RHQ": 12, "PAQ": 12}
VAR_MIN_AGE = {"DMDEDUC2": 20}
MULTI_RECORD = {"RXQ_RX", "DR1IFF", "DR2IFF", "DSQIDS", "DS1IDS", "DS2IDS", "PAXMIN", "PAXHR", "AUXAR", "AUXTYM", "AUXWBR"}
SUBSAMPLE_NOTE = {
    "fasting": "Fasting-subsample variables: only the morning fasting subsample (~40-45% of examinees) is eligible; fasting weights are used.",
    "diet": "24-h dietary recall variables: dietary day-one weights are used; recall error and day-to-day variation attenuate associations.",
}


def _chk(dim: str, status: str, title: str, message: str, suggestion: str = "") -> dict:
    return {"dimension": dim, "status": status, "title": title, "message": message, "suggestion": suggestion}


def _min_age(plan: dict) -> float:
    lo = 0.0
    for c in plan.get("population", []):
        if c.get("enabled", True) and c["kind"] == "inclusion":
            for m in re.finditer(r"\bage\s*>=?\s*(\d+)", c["expr"]):
                lo = max(lo, float(m.group(1)))
    return lo


def _raw_for(names: list[str], plan: dict, k: Knowledge) -> dict[str, set[str]]:
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    return {n: planner._raw_dependencies(n, k, custom) for n in names}


def static_assessment(plan: dict | None, parsed: dict, k: Knowledge | None = None) -> list[dict]:
    k = k or get_knowledge()
    out: list[dict] = []
    # 1. design fit ---------------------------------------------------------
    for n in parsed.get("not_in_nhanes", []):
        out.append(_chk("Design fit", n["severity"], f"'{n['phrase']}' cannot be studied with NHANES as stated" if n["severity"] == "fail"
                        else f"'{n['phrase']}' needs special handling", n["reason"], n["suggestion"]))
    if not parsed.get("not_in_nhanes"):
        out.append(_chk("Design fit", "ok", "Cross-sectional question",
                        "Prevalence and cross-sectional associations are what NHANES is designed to estimate."))
    # 2. concept coverage ---------------------------------------------------
    for c in parsed.get("component_matches", []):
        desc = "; ".join(f"{t} ({d})" if d else t for t, d in c["descriptions"].items())
        out.append(_chk("Coverage", "caution", f"'{c['phrase']}' is measured in NHANES but has no curated variable",
                        f"{c['note']}. Components: {desc}.",
                        "Build the full catalog (scripts/build_nhanes_catalog.py) or pick the exact variable in the Data map explorer; "
                        "check which cycles and age groups the component covers."))
    for t in parsed.get("unmapped_terms", []):
        out.append(_chk("Coverage", "caution", f"Could not find '{t}' in the NHANES dictionary",
                        "No concept, curated variable or catalog entry matched this phrase.",
                        "Rephrase with the clinical measurement (e.g. 'serum ferritin'), build the full variable catalog, or ignore if it is not a study variable."))
    for m in parsed.get("dictionary_matches", []):
        out.append(_chk("Coverage", "caution", f"'{m['phrase']}' mapped to {m['variable']} by dictionary search",
                        f"{m['label']} ({m['file']}, cycles {', '.join(m['cycles'])}); {'curated' if m['curated'] else 'uncurated catalog'} entry, "
                        f"match confidence {m['confidence']}.", "Confirm coding against the CDC codebook before approval."))
    if parsed.get("association_cue") and (not plan or plan.get("study_type") == "prevalence"):
        out.append(_chk("Coverage", "fail", "Association asked, but fewer than two concepts could be mapped",
                        "The question describes a relationship, but Q2E could not map both sides of it, so the draft defaults to a prevalence study.",
                        "Map the missing concept (see coverage items above) or rephrase."))
    if not plan:
        return out
    # 3. co-measurement across cycles -----------------------------------------
    if plan["dataset"].get("type", "nhanes") == "nhanes":
        roles = [("Outcome", plan["outcome"]["variable"])] + ([("Exposure", plan["exposure"]["variable"])] if plan.get("exposure") else [])
        roles += [("Covariate", c) for c in plan.get("covariates", [])]
        crit_ids = [i for c in plan["population"] if c.get("enabled", True) for i in expressions.identifiers(c["expr"])]
        roles += [("Criterion", i) for i in dict.fromkeys(crit_ids) if i in k.blocks or i in k.definitions]
        raw = _raw_for([n for _, n in roles], plan, k)
        all_cycles = list(k.cycles)
        custom = {c["name"]: c for c in plan.get("custom_variables", [])}

        def cycles_of(n):
            return planner.available_cycles(n, k, custom)
        core = [n for r, n in roles if r in ("Outcome", "Exposure", "Criterion")]
        core_cycles = set(all_cycles)
        for n in core:
            core_cycles &= cycles_of(n)
        selected = set(plan["dataset"].get("cycles", []))
        if not core_cycles:
            out.append(_chk("Co-measurement", "fail", "Outcome, exposure and criteria are never measured in the same cycle",
                            "; ".join(f"{k.label(n)}: {', '.join(sorted(cycles_of(n))) or 'none'}" for n in core),
                            "Choose different measures (e.g. an alternative definition) that share a cycle."))
        elif not selected <= core_cycles:
            out.append(_chk("Co-measurement", "fail", f"Not all core variables exist in cycle(s) {', '.join(sorted(selected - core_cycles))}",
                            f"Core variables are jointly available in: {', '.join(k.cycles[c]['label'] for c in sorted(core_cycles))}.",
                            f"Switch cycles to {', '.join(sorted(core_cycles))} (avoid combining J with P)."))
        else:
            others = sorted(core_cycles - selected - {c for s in selected for c in k.cycles[s].get('overlaps', [])})
            out.append(_chk("Co-measurement", "ok", "All core variables are measured together",
                            f"Jointly available in {', '.join(sorted(core_cycles))}; selected {', '.join(sorted(selected))}.",
                            f"Pooling {', '.join(others)} could increase precision." if others else ""))
        missing_cov = [c for r, c in roles if r == "Covariate" and not selected <= cycles_of(c)]
        if missing_cov:
            out.append(_chk("Co-measurement", "caution", "Some covariates are missing in the selected cycles",
                            ", ".join(k.label(c) for c in missing_cov), "Drop them or change cycles (reviewer offers one-click removal)."))
        # 4. subsamples / weights / file structure ---------------------------
        files = {k.dictionary[r]["file"] for s in raw.values() for r in s if r in k.dictionary}
        levels = {k.dictionary[r]["weight_level"] for s in raw.values() for r in s if r in k.dictionary}
        for lv in ("fasting", "diet"):
            if lv in levels:
                out.append(_chk("Subsample", "caution", f"{lv.capitalize()} subsample", SUBSAMPLE_NOTE[lv]))
        if "LUX" in files:
            out.append(_chk("Subsample", "caution", "Liver elastography", "VCTE was performed in 2017-2020 only, ages >=12, and invalid exams are excluded."))
        multi = files & MULTI_RECORD
        if multi:
            out.append(_chk("Data structure", "fail", "Multi-record files", f"{', '.join(multi)} have several rows per person and need aggregation first.",
                            "Aggregate to one row per participant (e.g. number of medications) before analysis."))
        # 5. age eligibility --------------------------------------------------
        lo = _min_age(plan)
        late = sorted({(f, MIN_AGE[f]) for f in files if f in MIN_AGE and MIN_AGE[f] > lo} |
                      {(v, VAR_MIN_AGE[v]) for s in raw.values() for v in s if v in VAR_MIN_AGE and VAR_MIN_AGE[v] > lo})
        if late:
            out.append(_chk("Eligibility", "caution", "Some measures are collected only at older ages",
                            "; ".join(f"{f}: typically age >={a}" for f, a in late) + f" (population starts at {lo:g} y).",
                            "Raise the minimum age or accept missingness by design (the probe shows the real counts)."))
        # 6. measurement ------------------------------------------------------
        o = plan["outcome"]
        oraw = raw.get(o["variable"], set())
        if oraw and all(k.dictionary.get(r, {}).get("weight_level") == "interview" for r in oraw):
            out.append(_chk("Measurement", "caution", "Outcome comes from the interview (self-report or questionnaire)",
                            "Self-reported diagnoses are subject to under-diagnosis and recall bias; screening instruments (e.g. PHQ-9) are not clinical diagnoses.",
                            "Prefer an examination/laboratory definition where available, or state the limitation."))
        else:
            out.append(_chk("Measurement", "ok", "Outcome is measured objectively",
                            "Examination/laboratory measures from a single visit (no repeat measurement for chronicity)."))
    return out


# --------------------------------------------------------------------------- precision from the probe
def _band_mid(band: list | None) -> float | None:
    if not band:
        return None
    return max(min((band[0] + band[1]) / 2, 0.99), 0.01)


def precision_assessment(plan: dict, probe: dict) -> tuple[list[dict], dict]:
    out, metrics = [], {}
    n_cc = probe.get("n_complete_case") or 0
    n_an = probe.get("n_analytic") or 0
    metrics.update({"n_analytic": n_an, "n_complete_case": n_cc, "design_df": probe.get("design", {}).get("analytic_df"), "deff_assumed": DEFF})
    if n_an < 100:
        out.append(_chk("Precision", "fail", f"Only {n_an} eligible participants", "Too few for reliable survey estimates.",
                        "Pool additional cycles or broaden the population."))
    else:
        out.append(_chk("Precision", "ok", f"{n_an:,} eligible participants ({n_cc:,} with complete covariates)",
                        "; ".join(f"{c['cycle']}: {c['n_analytic']:,}" for c in probe.get("per_cycle", []))))
    o = probe.get("outcome", {})
    if o.get("type") == "binary":
        p = _band_mid(o.get("rate_band"))
        if p:
            hw = Z * math.sqrt(DEFF * p * (1 - p) / max(n_an, 1))
            metrics["prevalence_halfwidth_pts"] = round(100 * hw, 1)
            st = "ok" if hw <= 0.03 else "caution" if hw <= 0.06 else "fail"
            out.append(_chk("Precision", st, f"Expected overall 95% CI: ±{100 * hw:.1f} percentage points",
                            f"Outcome rate band {100 * o['rate_band'][0]:.0f}-{100 * o['rate_band'][1]:.0f}% (blinded), design effect {DEFF} assumed."))
            bad = []
            for g in probe.get("subgroups", []):
                n_eff = g["n"] / DEFF
                w = 2 * Z * math.sqrt(DEFF * p * (1 - p) / max(g["n"], 1))
                if n_eff < 30 or w >= 0.30 or (w > 0.05 and w / p > 1.30):
                    bad.append(f"{g['var']}={g['level']} (n={g['n']})")
            if bad:
                out.append(_chk("Reporting", "caution", f"{len(bad)} subgroup estimate(s) likely to fail NCHS standards",
                                ", ".join(bad[:8]), "Collapse categories or pool cycles."))
            if plan.get("exposure"):
                e = probe.get("exposure", {})
                events = n_cc * p
                metrics["expected_events"] = round(events)
                if e.get("type") == "continuous" and e.get("sd"):
                    se = math.sqrt(DEFF / max(events, 1))
                    sc = plan["exposure"].get("scale") or 1
                    mde_sd = math.exp(Z_POWER * se)
                    mde_unit = math.exp(Z_POWER * se / e["sd"])   # probe SD is of the already-scaled exposure
                    metrics.update({"mde_pr_per_sd": round(mde_sd, 3), "mde_pr_per_unit": round(mde_unit, 3)})
                    st = "ok" if mde_unit <= 1.25 else "caution" if mde_unit <= 1.6 else "fail"
                    out.append(_chk("Power", st, f"80% power to detect PR >= {mde_unit:.2f} per {sc:g} {plan['exposure'].get('units', '')}".rstrip(),
                                    f"(= PR {mde_sd:.2f} per SD of exposure; ~{events:.0f} expected events, exposure SD {e['sd']:.3g}). Unadjusted approximation; adjustment for correlated covariates widens this."))
                elif e.get("levels"):
                    lv = sorted(e["levels"], key=lambda x: -x["n"])[:2]
                    if len(lv) == 2:
                        se = math.sqrt(DEFF * ((1 - p) / (lv[0]["n"] * p) + (1 - p) / (lv[1]["n"] * p)))
                        mde = math.exp(Z_POWER * se)
                        metrics["mde_pr_groups"] = round(mde, 3)
                        st = "ok" if mde <= 1.3 else "caution" if mde <= 1.7 else "fail"
                        out.append(_chk("Power", st, f"80% power to detect PR >= {mde:.2f} between the two largest exposure groups",
                                        f"{lv[0]['level']} (n={lv[0]['n']}) vs {lv[1]['level']} (n={lv[1]['n']})."))
                n_par = probe.get("n_parameters") or 1
                epv = events / max(n_par, 1)
                metrics["events_per_parameter"] = round(epv, 1)
                out.append(_chk("Power", "ok" if epv >= 10 else "caution", f"~{epv:.0f} expected events per model parameter",
                                f"{n_par} parameters in the fully adjusted model.", "" if epv >= 10 else "Reduce covariates or collapse categories."))
    elif o.get("type") == "continuous" and plan.get("exposure"):
        e = probe.get("exposure", {})
        sd_y = o.get("sd")
        if sd_y and n_cc:
            se_std = math.sqrt(DEFF / n_cc)
            mde_std = Z_POWER * se_std
            metrics["mde_standardized"] = round(mde_std, 3)
            msg = f"Detectable difference ~{mde_std:.3f} SD of the outcome per SD of exposure"
            if e.get("type") == "continuous" and e.get("sd"):
                sc = plan["exposure"].get("scale") or 1
                mde_unit = mde_std * sd_y / e["sd"]
                metrics["mde_per_unit"] = round(mde_unit, 4)
                msg += f" (= {mde_unit:.3g} outcome units per {sc:g} {plan['exposure'].get('units', '')})".rstrip()
            out.append(_chk("Power", "ok" if mde_std <= 0.1 else "caution", msg, f"Outcome SD {sd_y:.3g}; n={n_cc:,}; DEFF {DEFF}."))
    df = probe.get("design", {}).get("analytic_df")
    n_par = probe.get("n_parameters")
    if df is not None:
        st = "ok" if df >= 8 and (not n_par or n_par <= df) else "caution"
        out.append(_chk("Design", st, f"Design degrees of freedom: {df}",
                        f"{probe['design'].get('analytic_psu')} PSUs in {probe['design'].get('analytic_strata')} strata; model has ~{n_par} parameters.",
                        "" if st == "ok" else "Pool cycles or use a more parsimonious model."))
    miss = [m for m in probe.get("covariate_missing", []) if m["pct"] >= 10]
    if miss:
        out.append(_chk("Missing data", "caution", "Covariates with >=10% missing in the eligible population",
                        ", ".join(f"{m['var']} {m['pct']:.0f}%" for m in miss), "Multiple-imputation sensitivity analysis (already offered)."))
    return out, metrics


def verdict(checks: list[dict]) -> dict:
    fails = [c for c in checks if c["status"] == "fail"]
    cautions = [c for c in checks if c["status"] == "caution"]
    if fails:
        v, cls = "Not answerable as stated", "fail"
    elif cautions:
        v, cls = "Answerable with caveats", "caution"
    else:
        v, cls = "Answerable", "ok"
    return {"verdict": v, "status": cls, "n_fail": len(fails), "n_caution": len(cautions),
            "suggestions": [c["suggestion"] for c in fails + cautions if c.get("suggestion")][:6]}


def assess(plan: dict | None, parsed: dict, probe: dict | None = None) -> dict:
    k = get_knowledge()
    checks = static_assessment(plan, parsed, k)
    metrics = {}
    if probe and plan:
        pc, metrics = precision_assessment(plan, probe)
        checks += pc
    res = {**verdict(checks), "checks": checks, "metrics": metrics, "probed": bool(probe),
           "probe_note": None if probe else "Run the blinded feasibility probe to check real counts and precision."}
    return res


def assess_question(question: str, cycles: list[str] | None = None) -> dict:
    """Pre-check from the question alone (used before/without a full plan)."""
    k = get_knowledge()
    parsed = planner.parse_question(question, k)
    plan = None
    try:
        if not parsed.get("hard_stop"):
            plan = planner.build_plan(question, parsed, cycles, None, k)
    except (ValueError, KeyError):
        pass
    res = assess(plan, parsed)
    if parsed.get("hard_stop"):
        res.update({"verdict": "Not answerable with NHANES - hard stop", "status": "fail", "hard_stop": True})
        res["checks"].insert(0, _chk("Design fit", "fail", "Hard stop: no study will be drafted",
                                     "NHANES is a cross-sectional survey of community-dwelling people; it cannot observe " +
                                     ", ".join(f"'{h['phrase']}'" for h in parsed["hard_stop"]) + ".",
                                     parsed["hard_stop"][0]["suggestion"]))
    elif not plan:
        res["checks"].insert(0, _chk("Coverage", "fail", "No analysable outcome identified",
                                     "None of the clinical terms could be mapped to an NHANES variable or definition.",
                                     "Name the condition or measurement explicitly (e.g. 'serum ferritin <30', 'HbA1c', 'liver stiffness')."))
        res.update(verdict(res["checks"]))
    res["parsed"] = {k2: parsed[k2] for k2 in ("study_type", "outcome_concept", "exposure_concept", "populations", "matched_phrases",
                                               "not_in_nhanes", "component_matches", "dictionary_matches", "unmapped_terms")}
    return res
