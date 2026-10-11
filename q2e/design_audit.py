"""Design audit - answers the criticisms levelled at EHR-network ("TriNetX-style") observational studies.

Each check maps a published criticism to a concrete test on the plan (and, after a run, on the results):

  Comparator     users-vs-non-users of a treatment (confounding by indication); vague reference groups
  Outcome        code/self-report-only outcomes, treatment-defined outcomes, incidence/mortality claims,
                 outcome that shares items with the exposure
  Temporality    behaviour exposures vs diagnosed conditions (reverse causation / sick-quitter)
  Confounding    minimum adjustment set, mediators kept out, E-value reported
  Rationale      a priori hypothesis and a literature/novelty check before running
  Prespecified   protocol hash-locked before results; every prespecified analysis reported
  Reproducible   executable code + data checksums (no "methods the platform cannot run")
  Meaningful     statistically significant but clinically trivial effects flagged
  Oversight      documented statistical/epidemiological sign-off
"""
from __future__ import annotations

from typing import Any

from .knowledge import Knowledge, get_knowledge

MED_VARS = {"BPQ040A", "BPQ050A", "BPQ150", "DIQ050", "DIQ070", "MCQ053"}
# markers that a participant knows about the outcome condition (diagnosis or treatment) - used for reverse-causation checks
SELF_REPORT_BLOCK = {"DIQ010": "dm_selfreport", "DIQ050": "insulin_use", "DIQ070": "dm_pills", "BPQ020": "htn_selfreport",
                     "BPQ050A": "bp_meds", "BPQ150": "bp_meds", "MCQ160B": "hf", "MCQ160C": "chd", "MCQ160F": "stroke", "MCQ160E": "mi"}
VALIDATED_INSTRUMENT_PREFIX = ("DPQ",)   # PHQ-9 and similar validated questionnaires
BEHAVIOUR_DOMAINS = {"behaviour", "nutrition"}
MIN_ADJUST = {"age", "sex", "race_eth"}
SES = {"pir", "pir_cat", "educ", "insured"}


def _raw(name: str, plan: dict, k: Knowledge) -> set[str]:
    from .planner import _raw_dependencies
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    try:
        return set(_raw_dependencies(name, k, custom))
    except Exception:  # noqa: BLE001
        return set()


def _chk(area, status, title, detail, critique, fix=None, cid=None):
    return {"id": cid or area.lower(), "area": area, "status": status, "title": title, "detail": detail,
            "critique": critique, "fix": fix}


def audit(plan: dict, results: dict | None = None, k: Knowledge | None = None, novelty: dict | None = None) -> dict:
    k = k or get_knowledge()
    y, x = plan["outcome"], plan.get("exposure")
    yr = _raw(y["variable"], plan, k)
    xr = _raw(x["variable"], plan, k) if x else set()
    ydom = k.concepts.get(y.get("concept", ""), {}).get("domain")
    xdom = k.concepts.get(x.get("concept", ""), {}).get("domain") if x else None
    out: list[dict] = []

    # 1. comparator ------------------------------------------------------------------
    if not x:
        out.append(_chk("Comparator", "pass", "Descriptive estimand - no comparison group",
                        "Survey-weighted prevalence in a defined target population; subgroup contrasts are descriptive.",
                        "Inappropriate comparator", cid="comparator"))
    elif plan.get("arms"):
        a = plan["arms"]
        healthy = a.get("control_mode") == "healthy"
        out.append(_chk("Comparator", "caution" if healthy else "pass",
                        f"Multi-arm comparison against '{a['reference']}'",
                        f"Mutually exclusive groups: {', '.join(a['levels'])}. "
                        + ("Healthy controls are screened for other diseases while the arms are not, which inflates contrasts "
                           "(healthy-control bias); the all-seronegative control group runs as a sensitivity analysis."
                           if healthy else "Controls come from the same sample and are negative for every arm."),
                        "Inappropriate comparator", cid="comparator"))
    elif (xr - MED_VARS - {"RIAGENDR", "RIDAGEYR", "RIDEXPRG"}) == set() and (xr & MED_VARS) or any(r.startswith("RXD") for r in xr):
        out.append(_chk("Comparator", "fail", "Treatment users vs non-users (confounding by indication)",
                        "The exposure is a treatment. Non-users include people without the indication, so differences reflect "
                        "why people are treated, not what the treatment does. NHANES has no time zero or new-user design.",
                        "Inappropriate comparator / confounding by indication",
                        {"op": "note", "text": "Restrict to participants with the indication (e.g., among people with hypertension, "
                                               "treated vs untreated), or recast as treatment prevalence among those with the indication."},
                        "comparator"))
    else:
        if x.get("type") == "continuous":
            ref = f"per {x.get('scale', 1)} {x.get('units', '') or 'unit'} higher {x['label'].lower()}; weighted quartiles (Q1 reference) as sensitivity"
        else:
            ref = f"participants in the same eligible population without {x['label'].lower()}"
        out.append(_chk("Comparator", "pass", "Explicit, same-population comparator", f"Contrast: {ref}. Both groups come from "
                        "the same probability sample and eligibility criteria (no convenience controls).",
                        "Inappropriate comparator", cid="comparator"))

    # 2. outcome ---------------------------------------------------------------------
    if plan.get("parsed", {}).get("hard_stop"):
        out.append(_chk("Outcome", "fail", "Outcome needs follow-up NHANES does not have", "Incidence, mortality or "
                        "post-treatment outcomes cannot be measured cross-sectionally.", "Inappropriate outcome", cid="outcome_time"))
    levels = {k.dictionary.get(r, {}).get("weight_level") for r in yr} - {None}
    if yr and all(r.startswith(VALIDATED_INSTRUMENT_PREFIX) or r in ("RIAGENDR", "RIDAGEYR") for r in yr):
        out.append(_chk("Outcome", "pass", "Outcome is a validated screening instrument",
                        "Scored questionnaire with published validity (e.g., PHQ-9), not a diagnosis code; reported as a screen, "
                        "not a clinical diagnosis.", "Code-based / unvalidated outcome", cid="outcome_ascertainment"))
    elif yr and levels <= {"interview"}:
        out.append(_chk("Outcome", "caution", "Outcome is self-reported only",
                        "Self-report (like diagnosis codes in EHR networks) misses undiagnosed disease and differs by access to care. "
                        "Prefer an examination or laboratory definition where one exists.",
                        "Code-based / unvalidated outcome", cid="outcome_ascertainment"))
    else:
        out.append(_chk("Outcome", "pass", "Outcome includes measured (exam or laboratory) data",
                        "Objective measurement captures undiagnosed cases, unlike code-based EHR outcomes.",
                        "Code-based / unvalidated outcome", cid="outcome_ascertainment"))
    if yr & MED_VARS:
        out.append(_chk("Outcome", "caution", "Outcome is partly defined by treatment",
                        "Treated people count as cases. If the exposure affects access to care, outcome misclassification will "
                        "differ by exposure. Report the measured-only definition as a sensitivity analysis.",
                        "Outcome misclassification", cid="outcome_treatment"))
    d = k.definitions.get(y["variable"])
    if d and d.get("status") == "proposed":
        out.append(_chk("Outcome", "caution", "Outcome definition is not yet verified against its source",
                        "Proposed definitions need investigator verification before submission.", "Unvalidated outcome",
                        cid="outcome_definition"))
    if x and (yr & xr) - {"RIAGENDR", "RIDAGEYR", "RIDEXPRG"}:
        out.append(_chk("Outcome", "fail", "Outcome and exposure share source items",
                        f"Shared items: {', '.join(sorted((yr & xr) - {'RIAGENDR', 'RIDAGEYR', 'RIDEXPRG'}))}. The association is partly built in.",
                        "Inappropriate outcome (circularity)", cid="outcome_overlap"))

    # 3. temporality -----------------------------------------------------------------
    if x:
        aware = [SELF_REPORT_BLOCK[r] for r in yr if SELF_REPORT_BLOCK.get(r) and SELF_REPORT_BLOCK[r] in k.blocks]
        if xdom in BEHAVIOUR_DOMAINS and aware:
            aware = sorted(set(aware))
            expr = f"coalesce({aware[0]}, 0) == 1" if len(aware) == 1 else "any_of(" + ", ".join(f"coalesce({a}, 0) == 1" for a in aware) + ")"
            has = any(s.get("enabled") and expr in (s.get("expr") or "") for s in plan.get("sensitivity", []))
            out.append(_chk("Temporality", "pass" if has else "caution",
                            "Reverse causation: diagnosed people may have changed behaviour",
                            "People who know their diagnosis often change diet, activity or smoking (sick-quitter effect), which can "
                            "reverse the apparent association. " + ("Sensitivity analysis excluding diagnosed participants is planned."
                                                                    if has else "Add a sensitivity analysis excluding diagnosed participants."),
                            "Temporality / reverse causation",
                            None if has else {"op": "add_sensitivity", "item": {"type": "exclude", "label": "Exclude participants aware of the diagnosis (reverse causation)", "expr": expr}},
                            "temporality"))
        else:
            out.append(_chk("Temporality", "caution", "Cross-sectional: temporality cannot be established",
                            "Results are reported as associations; causal language is blocked in the manuscript.",
                            "Causal over-interpretation", cid="temporality"))

    # 4. confounding -----------------------------------------------------------------
    if x:
        covs = set(plan.get("covariates", []))
        missing = sorted(MIN_ADJUST - covs)
        ses = bool(covs & SES)
        st = "pass" if not missing and ses else "caution"
        out.append(_chk("Confounding", st, "Prespecified adjustment set",
                        (f"Adjusted for {len(covs)} covariates" + (f"; missing core confounders: {', '.join(missing)}" if missing else "")
                         + ("" if ses else "; no socioeconomic adjustment") + ". Mediators and definitional overlaps are removed "
                         "automatically, and an E-value quantifies how strong unmeasured confounding would need to be."),
                        "Residual confounding (only platform-captured variables)", cid="confounding"))

    # 5. rationale -------------------------------------------------------------------
    nv = novelty or {}
    if nv.get("score") is not None:
        out.append(_chk("Rationale", "pass", "A priori hypothesis with literature check",
                        f"Hypothesis stated before analysis; PubMed/MEDLINE novelty check: {nv['summary']}",
                        "Template exposure-outcome pairs without rationale", cid="rationale"))
    else:
        out.append(_chk("Rationale", "caution", "Run the PubMed/MEDLINE novelty check",
                        "A stated hypothesis exists; checking prior NHANES work documents the a priori rationale and avoids "
                        "re-running a crowded exposure-outcome pair.", "Template exposure-outcome pairs without rationale",
                        cid="rationale"))

    # 6. prespecification ------------------------------------------------------------
    from .compiler import plan_hash
    h = plan_hash(plan)
    locked = any(a.get("plan_hash") == h for a in plan.get("approvals", []))
    n_tests = len(plan.get("subgroups", [])) + len(plan.get("interactions", []))
    out.append(_chk("Prespecification", "pass" if locked else "caution",
                    "Protocol hash-locked before results" if locked else "Approve to hash-lock the protocol before results",
                    f"SHA-256 of the analysis plan is recorded at approval; any later edit voids the approval. "
                    f"All {len(plan.get('sensitivity', []))} prespecified sensitivity analyses are reported regardless of result"
                    + (f"; {n_tests} subgroup/interaction tests are labelled exploratory." if n_tests else "."),
                    "Post-hoc analyses / p-hacking", cid="prespecification"))

    # 7. reproducibility -------------------------------------------------------------
    out.append(_chk("Reproducibility", "pass", "Executable methods with data provenance",
                    "Every result comes with the compiled plan, R code, reproduce.R and MD5 checksums of the exact CDC files - "
                    "the methods section describes what actually ran.", "Methods the platform cannot actually run", cid="reproducibility"))

    # 8. clinical meaningfulness (after a run) ----------------------------------------
    pe = (results or {}).get("primary_estimate") or {}
    if pe.get("est") is not None and pe.get("effect") in ("PR", "OR", "RR"):
        small = abs(pe["est"] - 1) < 0.10
        sig = pe.get("lcl") is not None and (pe["lcl"] > 1 or pe["ucl"] < 1)
        out.append(_chk("Meaningfulness", "caution" if (small and sig) else "pass",
                        "Statistically significant but small effect" if (small and sig) else "Effect size interpretable",
                        f"{pe['effect']} {pe['est']:.2f} ({pe['lcl']:.2f}-{pe['ucl']:.2f}). "
                        + ("With a large sample, a <10% relative difference can be significant yet clinically trivial - discuss absolute differences."
                           if small and sig else "Report absolute prevalence differences alongside the ratio."),
                        "Significance without clinical meaning", cid="meaningfulness"))

    # 9. oversight -------------------------------------------------------------------
    stats_ok = any(a.get("stage") in ("statistics", "statistician") for a in plan.get("approvals", []))
    out.append(_chk("Oversight", "pass" if stats_ok else "caution",
                    "Statistical sign-off documented" if stats_ok else "Add a named statistician or epidemiologist sign-off",
                    "Investigator approval is required to run; journals increasingly expect documented methodological co-authorship "
                    "for large-database studies.", "Data access without methodological expertise", cid="oversight"))

    order = {"fail": 0, "caution": 1, "pass": 2}
    out.sort(key=lambda c: order[c["status"]])
    n = {s: sum(1 for c in out if c["status"] == s) for s in ("pass", "caution", "fail")}
    grade = "Needs redesign" if n["fail"] else ("Defensible with caveats" if n["caution"] else "Robust")
    return {"grade": grade, "counts": n, "checks": out,
            "framework": "Criticisms of EHR-network (TriNetX-style) studies: comparator, outcome, temporality, confounding, "
                         "rationale, prespecification, reproducibility, meaningfulness, oversight."}


def review_items(a: dict) -> list[dict]:
    """Turn failing/cautionary audit checks with an automatic fix into Reviewer issues."""
    items = []
    for c in a["checks"]:
        if c["status"] == "fail" or (c["status"] == "caution" and c.get("fix") and c["fix"].get("op") != "note"):
            items.append({"id": f"audit_{c['id']}", "severity": "major", "agent": "Design auditor",
                          "title": f"{c['area']}: {c['title']}", "detail": c["detail"] + (f" Fix: {c['fix']['text']}" if c.get("fix") and c["fix"].get("op") == "note" else ""),
                          "fix": c["fix"] if c.get("fix") and c["fix"].get("op") != "note" else None})
    return items
