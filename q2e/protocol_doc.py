"""Study protocol and statistical analysis plan (SAP) as a document - available before any data are touched.

Deliverable 2 of the challenge: "the generated research protocol & analysis plan". Built only from the plan (no
results), so the version that was approved can be shared, registered or attached to an IRB/QI submission.
"""
from __future__ import annotations

import html as _html

from .compiler import plan_hash
from .knowledge import Knowledge, get_knowledge

OVERSIGHT = [
    "Question framing and clinical meaningfulness - the AI proposes, the investigator decides.",
    "Case definitions and every operational assumption - explicit acknowledgement; AI-proposed definitions cannot run until approved.",
    "Confounder selection and causal structure - agents flag mediators and definitional overlap; the investigator decides.",
    "Approval gate - nothing runs until a named human approves this exact plan hash; any edit voids approval.",
    "Statistical sign-off - recorded separately by a statistician/epidemiologist.",
    "QC failures - cannot be silently ignored; each needs a documented override.",
    "Interpretation and publication - narrative drafted from aggregate results only, causal language filtered, human signs off.",
    "Data governance - restricted data only with approved/local models; row-level data never reach an LLM.",
]


def _b(label: str, text: str) -> str:
    return f"- **{label}:** {text}"


def build_markdown(proj: dict, k: Knowledge | None = None) -> str:
    k = k or get_knowledge()
    from . import appraisal, covariates as _cov, power as _pw
    p = proj["plan"]
    pico = p.get("pico") or {}
    cyc = p.get("dataset", {}).get("cycles") or []
    cyc_txt = ", ".join(k.cycles.get(c, {}).get("label", c).replace("NHANES ", "") for c in cyc) or "cycles selected automatically"
    approved = [a for a in p.get("approvals", []) if (a.get("stage") or "protocol") == "protocol"]
    L: list[str] = []
    L.append(f"# Study protocol and statistical analysis plan\n\n## {p['title']}\n")
    L.append(f"_Plan {p['plan_id']} v{p.get('version', 1)} - sha256 `{plan_hash(p)}`"
             + (f" - approved by {approved[-1].get('by')} on {str(approved[-1].get('at', ''))[:10]}" if approved else " - DRAFT (not yet approved)")
             + "_\n")

    L.append("## 1. Research question\n")
    L.append(_b("Clinical observation", f"“{p['question']}”"))
    L.append(_b("Refined question", p["refined_question"]))
    L.append(_b("Primary hypothesis", p.get("hypothesis") or "-"))
    L.append(_b("Study type", f"{p['study_type']} - {pico.get('design', 'cross-sectional complex survey')}"))

    L.append("\n## 2. PICO and eligibility\n")
    for key, lab in (("population", "Population"), ("exposure", "Exposure"), ("comparator", "Comparator"), ("outcome", "Outcome"), ("covariates", "Covariates")):
        if pico.get(key):
            L.append(_b(lab, pico[key]))
    inc = [c["label"] for c in p.get("population", []) if c.get("enabled", True) and c.get("kind", "inclusion") == "inclusion"]
    exc = [c["label"] for c in p.get("population", []) if c.get("enabled", True) and c.get("kind") == "exclusion"]
    L.append(_b("Inclusion criteria", "; ".join(inc) or "-"))
    L.append(_b("Exclusion criteria", "; ".join(exc) or "-"))
    L.append(_b("Data", f"NHANES {cyc_txt} (public-use files, CDC)"))

    L.append("\n## 3. Variables: concepts mapped to NHANES\n")
    L.append("| Role | Concept | NHANES source | Direct or derived | Definition |\n|---|---|---|---|---|")
    for v in p.get("variable_map", []):
        files = "; ".join(f"{c}: {', '.join(fs)}" for c, fs in (v.get("files") or {}).items())
        raw = ", ".join(v.get("raw_variables") or [])
        L.append(f"| {v.get('role', '')} | {v.get('label', v['variable'])} | {raw} ({files}) | "
                 f"{'Direct' if v.get('direct') else 'Derived'} | `{str(v.get('expr', '')).replace('|', '/')[:160]}` |")

    L.append("\n## 4. Statistical analysis plan\n")
    for b in appraisal.methods_bullets(p, None, k):
        if b["label"] not in ("Reporting", "Sensitivity analyses"):
            L.append(_b(b["label"], b["text"]))
    L.append(_b("Why this model", p.get("model", {}).get("rationale") or p.get("rationale", {}).get("statistician", "")))
    if p.get("missing_data", {}).get("rationale"):
        L.append(_b("Missing-data rationale", p["missing_data"]["rationale"]))
    sens = [s for s in p.get("sensitivity", []) if s.get("enabled", True)]
    if sens:
        L.append("- **Prespecified sensitivity analyses:**")
        L += [f"  - {s['label']}" for s in sens]
    if p.get("adjustment_sets"):
        L.append("- **Adjustment sets:**")
        L += [f"  - {a['label']}: {', '.join(k.label(c) for c in a['covariates']) or 'none'}" for a in p["adjustment_sets"]]
    notes = p.get("covariate_notes") or {}
    if notes:
        L.append("- **Covariate decisions:**")
        L += [f"  - {k.label(c)}: {n}" for c, n in notes.items()]
    try:
        cs = [s for s in _cov.suggest(p, k)["suggestions"] if s["available"]]
        if cs:
            L.append("- **Further covariates considered (not in the primary model):**")
            L += [f"  - {s['label']} ({s['role']}): {s['why']}" for s in cs[:8]]
    except Exception:  # noqa: BLE001
        pass
    pw = _pw.assess(p, p.get("probe"), None)
    L.append(_b("Sample size and power", _pw.summary_text(pw)))
    L += [f"  - {a}" for a in pw.get("assumptions", [])]

    L.append("\n## 5. Anticipated limitations\n")
    L += [f"- {x}" for x in p.get("limitations", [])]
    for c in (p.get("design_audit") or {}).get("checks", []):
        if c["status"] in ("caution", "fail") and c["area"] not in ("Rationale", "Oversight", "Prespecification", "Reproducibility"):
            L.append(f"- **{c['area']}:** {c['title']}. {c['detail']}")

    fz = p.get("feasibility") or {}
    nv = p.get("novelty") or {}
    if fz or nv:
        L.append("\n## 6. Feasibility and novelty\n")
        if fz.get("score") is not None:
            L.append(_b("Feasibility in NHANES", f"{fz['score']}/100 ({fz.get('label', '')})"))
        if nv.get("score") is not None:
            L.append(_b("Novelty (PubMed/MEDLINE)", f"{nv['score']}/100 ({nv.get('label', '')}) - {nv.get('summary', '')}"))

    L.append("\n## 7. Quality-control checks run automatically\n")
    L += [f"- {x}" for x in [
        "Analytic sample size and the participant flow at each criterion",
        "Missingness of every variable; complete-case loss with multiple imputation as sensitivity",
        "Raw variable ranges against plausible limits; NHANES non-response codes removed",
        "Correct survey weight for the most restrictive component (interview, MEC, fasting, laboratory subsample); cycle-length rescaling",
        "Design degrees of freedom and NCHS presentation standards for proportions",
        "Model convergence, implausible or non-estimable estimates, single-valued terms, collinearity (VIF)",
        "Agreement across sensitivity analyses and alternative model specifications; unweighted comparison",
        "Benchmark against published estimates where available; E-value for unmeasured confounding"]]

    L.append("\n## 8. Human oversight\n")
    L += [f"- {x}" for x in OVERSIGHT]
    L.append("\n## 9. Reporting\n")
    L.append("- STROBE (cross-sectional); estimates are associations, not causal effects.")
    L.append("- Results, code (R `survey` package) and a hash-chained provenance ledger are exported as a reproducibility bundle.")
    return "\n".join(L) + "\n"


def build_html(proj: dict, k: Knowledge | None = None) -> str:
    md = build_markdown(proj, k)
    try:
        import markdown as _md
        body = _md.markdown(md, extensions=["tables"])
    except Exception:  # noqa: BLE001
        body = f"<pre style='white-space:pre-wrap'>{_html.escape(md)}</pre>"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Protocol and SAP</title><style>"
            "body{font:15px/1.55 Georgia,serif;max-width:900px;margin:32px auto;padding:0 18px;color:#1d1d1d}"
            "h1{font-size:24px}h2{font-size:19px;margin-top:26px;border-bottom:1px solid #ddd;padding-bottom:4px}"
            "table{border-collapse:collapse;font:12.5px/1.4 system-ui,sans-serif;width:100%}td,th{border:1px solid #ddd;padding:4px 6px;vertical-align:top}"
            "th{background:#f3f3f3}code{font-size:11.5px}li{margin:2px 0}</style></head><body>" + body + "</body></html>")
