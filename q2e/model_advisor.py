"""AI statistician: lays out the defensible model choices for this study, scores them, and recommends one.

Each option says what it estimates, when it is the right choice, its pros and cons, how often similar NHANES papers in
high-impact journals used it (learned from their abstracts, see evidence.py) and - when the engine can run it - a
one-click fix that changes the plan. Scoring is transparent and rule-based:

  prior fit for the outcome/exposure type
  + data: outcome frequency (odds ratios overstate prevalence ratios when the outcome is common, >=10%),
          complete-case loss, skewed laboratory outcomes
  + literature: share of similar high-impact NHANES papers that used the method (comparability with prior work)

When an approved LLM is configured it re-ranks the same options and writes the rationale; it can only choose among
the listed option ids (anything else is ignored) and it receives plan metadata and method counts, never data.
"""
from __future__ import annotations

import json
from typing import Any

from .knowledge import Knowledge, get_knowledge

SKEWED = ("ferritin", "crp", "c-reactive", "albumin-to-creatinine", "albumin to creatinine", "uacr", "acr", "insulin",
          "triglycer", "cotinine", "lead", "mercury", "cadmium", "homa", "ggt", "gamma-glutamyl", "alanine aminotransferase",
          "aspartate aminotransferase", "vitamin d", "25-hydroxy", "eosinophil count", "liver stiffness", "cap ", "pfas", "phthalate")


def _p0(plan: dict, probe: dict | None, results: dict | None) -> float | None:
    if results:
        for m in results.get("models", []):
            if m.get("events") not in (None, "NA") and m.get("n"):
                try:
                    return float(m["events"]) / float(m["n"])
                except (TypeError, ValueError):
                    pass
    b = (((probe or {}).get("outcome") or {}).get("rate_band"))
    if b and len(b) == 2 and b[1] > 0:
        return (b[0] + b[1]) / 2
    return None


def _cc_loss(results: dict | None) -> float | None:
    for c in (results or {}).get("checks", []):
        if c.get("id") == "missing_covariates":
            import re
            m = re.search(r"(\d+(?:\.\d+)?)%", c.get("message", ""))
            if m:
                return float(m.group(1)) / 100
    return None


def _share(land: dict | None, key: str) -> tuple[float | None, str]:
    if not land or not land.get("papers"):
        return None, ""
    n = land["papers"]
    c = (land.get("counts") or {}).get(key, 0)
    return c / n, f"Used in {c} of {n} similar NHANES papers in high-impact journals"


def _has_sens(plan: dict, typ: str, **kw) -> bool:
    for s in plan.get("sensitivity", []):
        if s.get("type") == typ and s.get("enabled", True) and all(s.get(a) == b for a, b in kw.items()):
            return True
    return False


def options(plan: dict, probe: dict | None = None, results: dict | None = None, land: dict | None = None,
            k: Knowledge | None = None) -> list[dict]:
    k = k or get_knowledge()
    y, x = plan["outcome"], plan.get("exposure")
    fam = plan.get("model", {}).get("family")
    p0 = _p0(plan, probe, results)
    out: list[dict] = []

    def opt(oid, title, estimand, when, pros, cons, score, fix=None, current=False, method_key=None, runnable=True):
        sh, ev = _share(land, method_key) if method_key else (None, "")
        if sh is not None:
            score += round(15 * sh)
        out.append({"id": oid, "title": title, "estimand": estimand, "when": when, "pros": pros, "cons": cons,
                    "score": max(0, min(100, score)), "fix": None if current else fix, "current": current,
                    "runnable": runnable, "literature": ev, "literature_share": sh})

    if plan["study_type"] == "prevalence":
        opt("prev_kg", "Survey-weighted prevalence with Korn-Graubard CIs", "Population prevalence (%)",
            "Descriptive burden questions", ["NCHS-recommended CI for proportions", "Matches how CDC reports NHANES prevalence"],
            ["No adjustment - differences between subgroups are descriptive"], 85, current=True, method_key="survey_weighted")
        opt("prev_adj", "Model-adjusted (predictive margins) prevalence by subgroup", "Age-standardised or adjusted prevalence",
            "Comparing subgroups that differ in age structure", ["Removes confounding by age when comparing groups"],
            ["Not yet automated in the engine - report crude prevalence and age-standardise in a follow-up"], 55, runnable=False)
        return sorted(out, key=lambda o: -o["score"])

    if y["type"] == "binary":
        common = p0 is not None and p0 >= 0.10
        rare = p0 is not None and p0 < 0.10
        ptxt = f" (outcome in about {100 * p0:.0f}% of participants)" if p0 is not None else ""
        opt("pr", "Survey Poisson regression - prevalence ratio", "Adjusted prevalence ratio (PR)",
            "Cross-sectional studies, especially when the outcome is common" + ptxt,
            ["Directly interpretable as 'x times as common'", "Collapsible: unadjusted and adjusted estimates are comparable",
             "Robust (sandwich) variance from the survey design"],
            ["Less familiar to some readers than odds ratios", "Fitted probabilities can exceed 1 (rarely matters for PRs)"],
            72 + (12 if common else 0), fix={"op": "set", "path": "model.family", "value": "quasipoisson"},
            current=fam == "quasipoisson", method_key="poisson_pr")
        opt("or", "Survey logistic regression - odds ratio", "Adjusted odds ratio (OR)",
            "Rare outcomes (<10%), or when matching the published NHANES literature matters most" + ptxt,
            ["Most widely used model in NHANES papers - easy to compare with prior work", "Never predicts probabilities outside 0-1"],
            ["Overstates the prevalence ratio when the outcome is common" + (f" - here roughly {100 * p0:.0f}%" if common else ""),
             "Non-collapsible: ORs shift with adjustment even without confounding"],
            62 + (8 if rare else 0) - (12 if common else 0), fix={"op": "set", "path": "model.family", "value": "quasibinomial"},
            current=fam == "quasibinomial", method_key="logistic")
        if fam == "quasipoisson":
            opt("pr_plus_or", "Prevalence ratio primary, odds ratio as a sensitivity analysis", "PR, with OR reported alongside",
                "You want the better estimand and comparability with the literature",
                ["Reports both numbers reviewers expect", "Shows how much the OR exaggerates the PR"], ["One more table row"],
                70, fix={"op": "add_sensitivity", "item": {"type": "alt_family", "label": "Logistic regression (odds ratio)", "family": "quasibinomial"}},
                current=_has_sens(plan, "alt_family", family="quasibinomial"))
        opt("logbin", "Log-binomial regression - risk ratio", "Adjusted risk (prevalence) ratio",
            "When a reviewer insists on a binomial model", ["Same estimand as Poisson PR with binomial variance"],
            ["Often fails to converge with several covariates", "Not run by the engine - Poisson PR estimates the same quantity"],
            35, runnable=False, method_key="log_binomial")
    else:
        lab = (y.get("label") or "").lower() + " " + (y.get("concept_label") or "").lower()
        skew = any(s in lab for s in SKEWED)
        opt("linear", "Survey linear regression - mean difference", "Adjusted mean difference (beta)",
            "Continuous, roughly symmetric outcomes", ["Effect on the original clinical scale", "Simple to explain"],
            ["Sensitive to skew and outliers" + (" - this outcome is usually right-skewed" if skew else "")],
            80 - (15 if skew else 0), fix={"op": "set", "path": "model.family", "value": "gaussian"},
            current=fam == "gaussian", method_key="linear")
        logname = f"log_{y['variable']}"
        has_log = any(c["name"] == logname for c in plan.get("custom_variables", []))
        opt("loglinear", "Log-transformed outcome - ratio of geometric means", "Percent difference in the outcome",
            "Right-skewed laboratory values (ferritin, CRP, UACR, insulin, toxicants)",
            ["Handles skew; exp(beta) is a ratio, so 1.10 means 10% higher", "Usual choice in biomarker papers"],
            ["Zeros and negative values cannot be logged (set to missing)", "Less intuitive than a mean difference"],
            (78 if skew else 50),
            fix={"op": "batch", "fixes": [
                {"op": "add_custom_variable", "name": logname, "expr": f"ifelse({y['variable']} > 0, log({y['variable']}), NA)",
                 "type": "continuous", "label": f"log {y.get('label', y['variable'])}", "source": "model advisor"},
                {"op": "add_sensitivity", "item": {"type": "alt_outcome", "label": f"Log-transformed outcome: log {y.get('label', '')} (exp(beta) = ratio of geometric means)",
                                                   "outcome": logname, "family": "gaussian"}}]},
            current=has_log)
        opt("threshold", "Clinical threshold - prevalence ratio", "PR for crossing a guideline cut-off",
            "Readers think in categories (e.g. HbA1c >=6.5%)", ["Clinically meaningful", "Comparable with papers that dichotomise"],
            ["Discards information and power"], 55, current=_has_sens(plan, "alt_outcome", family="quasipoisson"), fix=None)
        opt("quantile", "Quantile (median) regression", "Difference in the median",
            "Outcomes with heavy tails where the median matters", ["Robust to outliers"],
            ["Not run by the engine; design-based quantile regression needs replicate weights"], 30, runnable=False, method_key="quantile")

    if x and x.get("type") == "continuous":
        opt("quartiles", "Exposure in weighted quartiles with P for trend", "Q4 vs Q1 contrast and dose-response",
            "Checking for a dose-response or a non-linear shape", ["No linearity assumption", "Supports the dose-response GRADE domain"],
            ["Cut points are sample-specific"], 64, fix={"op": "add_sensitivity", "item": {"type": "exposure_quartiles", "label": "Exposure in weighted quartiles (Q4 vs Q1, P for trend)"}},
            current=_has_sens(plan, "exposure_quartiles"), method_key="spline")
    loss = _cc_loss(results)
    if loss is not None and loss > 0.10:
        opt("mi", "Multiple imputation (chained equations) for missing covariates", "Same estimand, all eligible participants",
            f"Complete-case loss is {100 * loss:.0f}% in this run", ["Less bias if data are missing at random", "Uses everyone eligible"],
            ["Assumes missing at random given the imputation model"], 55 + (15 if loss > 0.2 else 0),
            fix={"op": "add_sensitivity", "item": {"type": "mi", "label": "Multiple imputation of missing covariates (m = 10)", "m": 10}},
            current=_has_sens(plan, "mi"), method_key="multiple_imputation")
    if x and not plan.get("interactions"):
        opt("emod", "Prespecified effect modification by sex and age", "Stratum-specific estimates and interaction P values",
            "When subgroups plausibly differ", ["Answers 'in whom?'", "Prespecified, so not data dredging"],
            ["Multiple testing - label as exploratory"], 50, fix={"op": "set_interactions", "value": ["sex", "agecat"]},
            method_key="interaction")
    return sorted(out, key=lambda o: (-o["score"], not o["current"]))


AI_SYSTEM = ("You are a senior biostatistician reviewing a survey-weighted NHANES analysis. Choose among the given options "
             "only. Return JSON {\"recommended\": <option id>, \"ranking\": [option ids], \"rationale\": <<=90 words>, "
             "\"per_option\": {<id>: <one sentence>}}.")


def advise(plan: dict, probe: dict | None = None, results: dict | None = None, land: dict | None = None,
           provider: str | None = None, use_llm: bool = True) -> dict[str, Any]:
    opts = options(plan, probe, results, land)
    ids = [o["id"] for o in opts]
    primary = [o for o in opts if o["id"] in ("pr", "or", "linear", "loglinear", "logbin", "prev_kg", "prev_adj", "quantile")]
    rec = next((o for o in primary if o["runnable"]), opts[0] if opts else None)
    rationale = ""
    if rec:
        cur = next((o for o in primary if o["current"]), None)
        rationale = (f"{rec['title']} scores highest ({rec['score']}/100) for this outcome"
                     + (f"; {rec['literature'][0].lower() + rec['literature'][1:]}" if rec.get("literature") and rec.get("literature_share") else "") + ".")
        if cur and cur["id"] != rec["id"]:
            rationale += f" The plan currently uses {cur['title'].lower()}; switching is one click."
        elif cur:
            rationale += " The plan already uses it."
    ai = None
    if use_llm:
        from .llm import LLMClient
        client = LLMClient(provider)
        if client.enabled:
            slim = {"question": plan.get("refined_question"), "outcome": {"label": plan["outcome"]["label"], "type": plan["outcome"]["type"]},
                    "exposure": ({"label": plan["exposure"]["label"], "type": plan["exposure"]["type"]} if plan.get("exposure") else None),
                    "current_family": plan.get("model", {}).get("family"), "literature_methods": (land or {}).get("counts"),
                    "options": [{k2: o[k2] for k2 in ("id", "title", "estimand", "when", "pros", "cons", "score", "runnable")} for o in opts]}
            try:
                data = client.complete_json("Statistician", AI_SYSTEM, json.dumps(slim, default=str), max_tokens=900)
                if data.get("recommended") in ids:
                    rec = next(o for o in opts if o["id"] == data["recommended"])
                    rank = [i for i in data.get("ranking") or [] if i in ids]
                    order = {i: n for n, i in enumerate(rank + [i for i in ids if i not in rank])}
                    opts.sort(key=lambda o: order[o["id"]])
                    for o in opts:
                        note = (data.get("per_option") or {}).get(o["id"])
                        if isinstance(note, str):
                            o["ai_note"] = note[:300]
                    rationale = str(data.get("rationale") or rationale)[:700]
                    ai = {"provider": client.provider.name, "model": client.provider.model}
            except Exception:  # noqa: BLE001
                ai = None
    for o in opts:
        o["recommended"] = rec is not None and o["id"] == rec["id"]
    return {"options": opts, "recommended": rec["id"] if rec else None, "rationale": rationale, "ai": ai,
            "landscape": land, "basis": "rule-based scoring" + (" re-ranked by " + ai["provider"] if ai else "")
            + (" with methods learned from published papers" if land and land.get("papers") else "")}
