"""Multi-agent study design: rule-based agents always run; when an approved LLM provider is
configured, LLM agents add interpretation, narrative and critique - but every LLM output is
validated against the ontology / expression whitelist and merged *under* the rules, and
anything the LLM invents (new variables, definitions) is flagged for explicit human approval."""
from __future__ import annotations

import json
import re
from typing import Any

from . import answerability, expressions, normalize, planner, privacy
from .knowledge import Knowledge, get_knowledge
from .language_guard import scan_causal
from .llm import LLMClient, LLMError

SYSTEM_BASE = (
    "You are part of BEDSIDE, a research copilot that designs survey-weighted cross-sectional analyses of NHANES "
    "(or another open dataset) to the standard of JAMA Network Open. You never see participant-level data. "
    "Use associational (non-causal) language. Respond with a single JSON object only."
)


def _catalog(k: Knowledge) -> str:
    concepts = "\n".join(f"- {c['id']}: {c['label']} (e.g. {', '.join(c['synonyms'][:3])})" for c in k.concepts.values())
    pops = "\n".join(f"- {p['id']}: {', '.join(p['patterns'][:3])}" for p in k.populations)
    defs = "\n".join(f"- {d['id']} [{d.get('concept')}]: {d.get('label')}" for d in k.definitions.values())
    blocks = ", ".join(sorted(k.blocks))
    return (f"CONCEPTS:\n{concepts}\n\nPOPULATIONS:\n{pops}\n\nGUIDELINE DEFINITIONS:\n{defs}\n\n"
            f"BUILDING-BLOCK VARIABLES usable in expressions: {blocks}\n"
            f"Expression language: R syntax limited to arithmetic, comparisons, & | !, %in%, c(), ifelse(), coalesce(), "
            f"any_of(), all_of(), cases(cond, \"label\", ...), pmin(), pmax(), log(), sqrt().")


def _investigator_llm(client: LLMClient, question: str, k: Knowledge) -> dict:
    user = (f"{_catalog(k)}\n\nRESEARCH IDEA: \"{question}\"\n\n"
            "Return JSON with keys: study_type ('prevalence' or 'association'), outcome_concept, exposure_concept (or null), "
            "populations (list of population ids), subgroup_concepts (list of concept ids), preferred_definitions (definition ids "
            "explicitly requested or most appropriate), adjust_bmi (bool), refined_question (one sentence, PICO-explicit), "
            "hypothesis (one sentence, associational), clarifying_questions (<=3), unmapped (list of {phrase, role, label, type, "
            "proposed_expression} for important concepts NOT in the catalog; expressions must use building-block names), "
            "terms (list of {text, standard_term, label, note} for every abbreviation, misspelling, lay or regional term in the "
            "idea: text = the exact characters as they appear in the idea, standard_term = the catalog synonym that means the same "
            "thing (e.g. 'sugar diabetes' -> 'diabetes', 'renal stones' -> 'kidney stones'), label = formal clinical name "
            "(e.g. 'Type 2 diabetes mellitus'), note = one short caveat if NHANES measures it differently; never change ages, "
            "years, populations or the direction of the question).")
    return client.complete_json("Investigator", SYSTEM_BASE, user, max_tokens=1500)


def _methods_facts(plan: dict) -> dict:
    """What the plan already specifies, in words, so the AI critiques real gaps instead of asking for things that are
    already done (BP protocol, primary estimator, age standardization, multiplicity)."""
    k = get_knowledge()
    facts: dict = {}
    try:
        from .appraisal import methods_bullets
        facts["methods"] = [b["label"] + ": " + b["text"] + (" (" + "; ".join(b["items"]) + ")" if b.get("items") else "")
                            for b in methods_bullets(plan, None, k)]
    except Exception:  # noqa: BLE001 - context only
        facts["methods"] = [plan.get("model", {}).get("rationale", "")]
    defs = {}
    for role in ("outcome", "exposure"):
        v = plan.get(role) or {}
        d = k.definitions.get(v.get("variable", ""))
        if d:
            defs[role] = {"definition": d.get("label"), "criteria": d.get("criteria_text"),
                          "measurement": d.get("operational_notes"), "source": (d.get("source") or {}).get("citation")}
    facts["case_definitions"] = defs
    est = plan.get("estimand") or {}
    cmp = est.get("comparison") or {}
    if est.get("kind") == "comparison" or cmp:
        facts["primary_analysis"] = (f"Survey-weighted proportion in each group ({cmp.get('label', 'group')}: {cmp.get('level')} vs "
                                     f"{cmp.get('reference')}) with Korn-Graubard 95% CIs; design-based difference in percentage points "
                                     "and prevalence ratio with 95% CIs; Wald test of any difference. Regression is used only for the "
                                     "secondary adjusted comparison.")
        facts["multiplicity"] = "One prespecified primary comparison; subgroup and sensitivity estimates are descriptive and labelled as such."
    aa = plan.get("age_adjust") or {}
    if aa.get("enabled"):
        facts["age_standardization"] = "Direct age standardization to the projected 2000 US population (NCHS age groups), reported with crude estimates."
    return facts


def _statistician_llm(client: LLMClient, plan: dict) -> dict:
    slim = {k2: plan[k2] for k2 in ("refined_question", "study_type", "covariates", "subgroups", "interactions", "model",
                                    "adjustment_sets", "missing_data") if k2 in plan}
    slim["outcome"] = {"label": plan["outcome"]["label"], "type": plan["outcome"]["type"]}
    if plan.get("exposure"):
        slim["exposure"] = {"label": plan["exposure"]["label"], "type": plan["exposure"]["type"], "scale": plan["exposure"].get("scale")}
    slim["sensitivity"] = [s["label"] for s in plan["sensitivity"]]
    slim["already_specified"] = _methods_facts(plan)
    user = ("Draft statistical analysis plan:\n" + json.dumps(slim, indent=1, default=str) +
            "\n\nReturn JSON {rationale: <=120-word justification of estimand, model family, weighting/variance estimation, "
            "missing-data and sensitivity strategy for a JAMA Network Open methods section>, suggestions: [<=3 short concrete "
            "improvements that are NOT already in already_specified; if the plan already covers something, do not suggest it]}.")
    return client.complete_json("Statistician", SYSTEM_BASE, user, max_tokens=900)


def _reviewer_llm(client: LLMClient, plan: dict, rule_issues: list[dict]) -> dict:
    slim = {"refined_question": plan["refined_question"], "hypothesis": plan["hypothesis"], "population": [c["label"] for c in plan["population"] if c.get("enabled")],
            "outcome": plan["outcome"]["label"], "exposure": (plan.get("exposure") or {}).get("label"),
            "covariates": plan["covariates"], "model": plan["model"]["family"], "sensitivity": [s["label"] for s in plan["sensitivity"] if s.get("enabled")],
            "limitations": plan["limitations"], "already_flagged": [i["title"] for i in rule_issues],
            "primary_estimand": (plan.get("estimand") or {}).get("kind"),
            "comparison": {k2: v for k2, v in ((plan.get("estimand") or {}).get("comparison") or {}).items() if k2 in ("label", "level", "reference")},
            "secondary_models": [a["label"] for a in plan.get("adjustment_sets", [])],
            "already_specified": _methods_facts(plan)}
    slim.pop("model", None)       # the regression family is for the secondary model; already_specified gives the primary analysis
    user = ("Act as a critical peer reviewer (\"Reviewer 2\") for JAMA Network Open. Plan:\n" + json.dumps(slim, indent=1, default=str) +
            "\n\nReturn JSON {issues: [{severity: 'major'|'minor', title, detail}]} with at most 4 NEW issues not already flagged "
            "(confounding, selection, measurement, generalizability, reporting). Read already_specified first: do not raise "
            "anything it already handles (estimator, BP or lab measurement protocol, age standardization, multiplicity). "
            "Use 'major' only for problems that would change the conclusion.")
    return client.complete_json("Reviewer", SYSTEM_BASE, user, max_tokens=900)


def design_study(question: str, cycles: list[str] | None = None, dataset: dict | None = None,
                 provider: str | None = None) -> dict[str, Any]:
    k = get_knowledge()
    clean_q, findings = privacy.scrub(question)
    client = LLMClient(provider)
    dialogue: list[dict] = []
    if findings:
        dialogue.append({"agent": "Privacy Guard", "source": "rules",
                         "message": f"Redacted {len(findings)} potential identifier(s) ({', '.join(sorted({f['type'] for f in findings}))}) before analysis."})
    # Question recognition: rules first (abbreviations, variants, spelling), then the AI Recognizer on Amazon Bedrock
    rule_q, recognized = normalize.normalize(clean_q)
    llm_out: dict = {}
    if client.enabled:
        try:
            llm_out = _investigator_llm(client, rule_q, k)
            rule_q, ai_terms = normalize.apply_ai_terms(rule_q, llm_out.get("terms"))
            recognized += ai_terms
        except LLMError as e:
            dialogue.append({"agent": "Recognizer (AI)", "source": "llm", "message": f"AI unavailable ({e}); recognized terms with rules only."})
    if recognized:
        dialogue.append({"agent": "Recognizer", "source": "llm" if any(r["source"] == "ai" for r in recognized) else "rules",
                         "message": "Recognized " + "; ".join(f"\"{r['from']}\" as {r['label'] or r['to']}" for r in recognized) + "."})
    parsed = planner.parse_question(rule_q, k)
    from . import estimands as _est
    cmp = _est.detect_comparison(rule_q)
    if client.enabled and llm_out:
        try:
            agreed = []
            for key in ("outcome_concept", "exposure_concept"):
                v = llm_out.get(key)
                if v and v in k.concepts and key == "exposure_concept" and (cmp or parsed.get("arms")) \
                        and k.concepts[v].get("domain") in planner.DEMOGRAPHIC_DOMAINS | {"infection"}:
                    continue    # the group comparison (sex, age, race...) or the arms already carry this; not a second exposure
                if v and v in k.concepts:
                    if parsed.get(key) and parsed[key] != v:
                        dialogue.append({"agent": "Investigator (LLM)", "source": "llm",
                                         "message": f"Rules chose {key.split('_')[0]} '{parsed[key]}', LLM suggests '{v}'. Keeping the rule-based choice; use the role/definition pickers to switch."})
                    elif not parsed.get(key):
                        parsed[key] = v
                        agreed.append(v)
            if llm_out.get("study_type") in ("prevalence", "association") and not parsed.get("outcome_concept"):
                parsed["study_type"] = llm_out["study_type"]
            skipped = []
            for pid in llm_out.get("populations", []) or []:
                if not any(p["id"] == pid for p in k.populations) or pid in parsed["populations"]:
                    continue
                why = _population_conflict(pid, parsed["populations"], cmp)
                if why:
                    skipped.append(f"{pid} ({why})")
                    continue
                parsed["populations"].append(pid)
            if skipped:
                dialogue.append({"agent": "Investigator (LLM)", "source": "llm",
                                 "message": "Did not apply AI population filters that would break the question: " + "; ".join(skipped) + "."})
            # the AI's definition picks are offered, not applied: the investigator chooses in the definition picker
            ai_defs = [d for d in llm_out.get("preferred_definitions", []) or []
                       if d in k.definitions and d not in parsed["hints"]["prefer"]]
            if ai_defs:
                dialogue.append({"agent": "Investigator (LLM)", "source": "llm",
                                 "message": "Suggested definitions: " + "; ".join(k.label(d) for d in ai_defs)
                                 + ". Keeping the standard measures; use the definition picker to switch."})
            if llm_out.get("adjust_bmi"):
                parsed["adjust_bmi"] = True
            dialogue.append({"agent": "Investigator (LLM)", "source": "llm",
                             "message": "Interpreted the idea; clarifying questions: " + ("; ".join(llm_out.get("clarifying_questions", [])[:3]) or "none")})
        except (LLMError, AttributeError, TypeError) as e:
            dialogue.append({"agent": "Investigator (LLM)", "source": "llm", "message": f"AI reply unusable ({e}); continuing with rule-based agents."})
    plan = planner.build_plan(rule_q, parsed, cycles, dataset, k)
    plan["recognized_terms"] = recognized
    if rule_q != clean_q:
        plan["question_original"] = clean_q

    # LLM narrative merges (guarded)
    if llm_out:
        for field in ("refined_question", "hypothesis"):
            txt = (llm_out.get(field) or "").strip()
            if txt and not scan_causal(txt) and len(txt) < 600:
                plan[f"{field}_llm"] = txt
        for u in llm_out.get("unmapped", []) or []:
            expr = (u.get("proposed_expression") or "").strip()
            if not expr:
                continue
            try:
                expressions.validate(expr, set(k.blocks) | set(k.definitions))
            except expressions.ExpressionError as e:
                dialogue.append({"agent": "Data Steward", "source": "rules", "message": f"Rejected LLM expression for '{u.get('phrase')}': {e}"})
                continue
            name = "ai_" + "".join(ch if ch.isalnum() else "_" for ch in (u.get("label") or u.get("phrase") or "var").lower())[:30].strip("_")
            plan["custom_variables"].append({"name": name, "expr": expr, "type": u.get("type", "binary") if u.get("type") in ("binary", "continuous") else "binary",
                                             "label": u.get("label") or u.get("phrase"), "source": "ai", "role_hint": u.get("role"), "confidence": 0.6})
            dialogue.append({"agent": "Data Steward", "source": "llm", "message": f"LLM proposed derived variable '{name}' = {expr} for '{u.get('phrase')}' - requires your approval before use."})
    # rule-agent dialogue (always)
    o, x = plan["outcome"], plan.get("exposure")
    dialogue.insert(0, {"agent": "Investigator", "source": "rules", "message":
                        f"I read this as {'an' if plan['study_type'] == 'association' else 'a'} {plan['study_type']} question. Outcome: {o['label']}."
                        + (f" Exposure: {x['label']}" + (f" (per {x['scale']:g} {x.get('units', '')})" if x.get('scale', 1) not in (None, 1) else "") + "." if x else "")
                        + f" Population: {', '.join(c['label'] for c in plan['population'] if c['kind'] == 'inclusion')}."})
    vm = planner.variable_map(plan, k)
    n_direct = sum(1 for r in vm if r["direct"])
    raw = sorted({v for r in vm for v in r["raw_variables"]})
    files = sorted({f for r in vm for fl in r["files"].values() for f in fl})
    dialogue.append({"agent": "Data Steward", "source": "rules", "message":
                     f"Mapped {len(vm)} analysis variables ({n_direct} direct NHANES measures, {len(vm) - n_direct} derived/guideline definitions) "
                     f"onto {len(raw)} raw variables in {len(files)} files: {', '.join(files[:8])}{'...' if len(files) > 8 else ''}."})
    for n in plan["agent_notes"]:
        dialogue.append({"agent": n["agent"], "source": "rules", "message": n["message"]})
    dialogue.append({"agent": "Statistician", "source": "rules", "message": plan["rationale"]["statistician"]})
    issues = planner.review_plan(plan, k)
    if client.enabled:
        # the Statistician and Reviewer read the same draft, so both AI calls run at the same time
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            st_job = pool.submit(_statistician_llm, client, plan)
            rv_job = pool.submit(_reviewer_llm, client, plan, list(issues))
        try:
            st = st_job.result()
            if st.get("rationale"):
                plan["rationale"]["statistician_llm"] = st["rationale"]
            for s in (st.get("suggestions") or [])[:3]:
                dialogue.append({"agent": "Statistician (LLM)", "source": "llm", "message": s})
        except LLMError as e:
            dialogue.append({"agent": "Statistician (LLM)", "source": "llm", "message": f"Unavailable: {e}"})
        try:
            rv = rv_job.result()
            for i, it in enumerate((rv.get("issues") or [])[:4]):
                issues.append({"id": f"llm{i + 1}", "severity": it.get("severity", "minor") if it.get("severity") in ("major", "minor") else "minor",
                               "agent": "Reviewer (LLM)", "title": str(it.get("title", ""))[:140], "detail": str(it.get("detail", ""))[:600], "fix": None})
        except LLMError:
            pass
    sev = {s: sum(1 for i in issues if i["severity"] == s) for s in ("blocker", "major", "minor", "info")}
    dialogue.append({"agent": "Reviewer", "source": "rules", "message":
                     f"Critique: {sev['blocker']} blocker, {sev['major']} major, {sev['minor']} minor issue(s). Resolve blockers and acknowledge operational assumptions before approval."})
    from . import design_audit
    plan["variable_map"] = vm
    plan["design_audit"] = design_audit.audit(plan, None, k, plan.get("novelty"))
    audit_items = design_audit.review_items(plan["design_audit"])
    plan["review"] = issues + audit_items
    a = plan["design_audit"]
    dialogue.append({"agent": "Design auditor", "source": "rules", "message":
                     f"Design audit vs common EHR-network study criticisms: {a['grade']} ({a['counts']['pass']} pass, "
                     f"{a['counts']['caution']} caution, {a['counts']['fail']} fail)."
                     + (" " + "; ".join(i["title"] for i in audit_items) if audit_items else "")})
    plan["feasibility"] = planner.feasibility(plan, k)
    plan["answerability"] = answerability.assess(plan, plan["parsed"])
    _answer_issue(plan)
    av = plan["answerability"]
    dialogue.append({"agent": "Epidemiologist", "source": "rules", "message":
                     f"Can NHANES answer this? {av['verdict']} ({av['n_fail']} blocking, {av['n_caution']} caveat(s)). "
                     "Run the blinded feasibility probe to check real counts and power before approving."})
    plan["agent_dialogue"] = dialogue
    plan["llm"] = {**client.status(), "calls": [c.__dict__ for c in client.calls]}
    plan["privacy"] = {"findings": findings, **privacy.boundary_summary(client.provider.name)}
    from . import expertise
    plan["idea_gaps"] = expertise.idea_gaps(plan.get("question", ""), plan, k)
    _gap_issues(plan)
    return plan


# populations that pick one group of a baseline characteristic: two from the same family can never both hold, and
# none may be added when the question compares the groups of that characteristic
_POP_FAMILY = {"men": "sex", "women": "sex", "women_repro": "sex", "pregnant": "sex",
               "race_nhwhite": "race_eth", "race_nhblack": "race_eth", "race_nhasian": "race_eth", "race_hispanic": "race_eth",
               "children": "agecat", "adolescents": "agecat", "adults": "agecat", "older_adults": "agecat"}


def _population_conflict(pid: str, current: list[str], cmp: dict | None) -> str:
    fam = _POP_FAMILY.get(pid)
    if not fam:
        return ""
    gv = (cmp or {}).get("group_var", "")
    if cmp and (gv == fam or gv.startswith(fam) or (fam == "agecat" and gv.startswith("agecat"))):
        if not (fam == "agecat" and pid == "adults"):        # "adults" only sets the age floor of an age comparison
            words = {"sex": "sex", "race_eth": "race and ethnicity", "agecat": "age", "age_cmp": "age"}
            return f"the question compares groups by {cmp.get('label') or words.get(gv, words.get(fam, fam))}".lower()
    clash = [c for c in current if _POP_FAMILY.get(c) == fam and fam != "agecat"]
    if clash:
        return f"conflicts with {clash[0]}"
    if fam == "agecat" and any(_POP_FAMILY.get(c) == "agecat" for c in current):
        return "an age group is already set"
    return ""


def _gap_issues(plan: dict) -> None:
    """An age group the analyst never confirmed ('seniors' -> 65+?) must be confirmed or accepted before approval."""
    plan["review"] = [i for i in plan.get("review", []) if not i["id"].startswith("ages_")]
    for g in plan.get("idea_gaps", []):
        key = "ages_" + re.sub(r"\W+", "_", g["text"].lower())
        if g["status"] == "assumed" and not plan.get("acknowledgements", {}).get(key):
            plan["review"].append({"id": key, "severity": "major", "agent": "Epidemiologist",
                                   "title": f"Which ages does \"{g['text']}\" mean?", "detail": g["note"] + " Or accept the current choice.",
                                   "fix": {"op": "acknowledge", "key": key}, "alternatives": g["alternatives"]})


def _answer_issue(plan: dict) -> None:
    av = plan.get("answerability") or {}
    if av.get("status") == "fail" and not plan.get("acknowledgements", {}).get("answerability"):
        from . import expertise
        fails = [c["title"] for c in av.get("checks", []) if c["status"] == "fail"]
        alts = expertise.close_questions(plan.get("question", ""))
        plan["review"].append({"id": "answerability", "severity": "major", "agent": "Epidemiologist",
                               "title": "NHANES cannot answer the question exactly as asked",
                               "detail": "; ".join(fails) + ". " + ("Pick one of the close questions below that NHANES can answer, or accept "
                                                                    "to continue with the reframed question shown in the protocol." if alts else
                                                                    "Accept to continue with the reframed cross-sectional question shown in the protocol."),
                               "fix": {"op": "acknowledge", "key": "answerability"}, "alternatives": alts})


def refresh_plan(plan: dict, provider: str | None = None) -> dict:
    """Recompute derived views (map, review, feasibility) after a human edit."""
    k = get_knowledge()
    plan = planner.refresh_text(plan, k)
    plan["variable_map"] = planner.variable_map(plan, k)
    llm_issues = [i for i in plan.get("review", []) if i.get("agent") == "Reviewer (LLM)"]
    plan["review"] = planner.review_plan(plan, k) + llm_issues
    from . import design_audit
    plan["design_audit"] = design_audit.audit(plan, None, k, plan.get("novelty"))
    plan["review"] += design_audit.review_items(plan["design_audit"])
    plan["feasibility"] = planner.feasibility(plan, k)
    probe = plan.get("probe")
    if probe:
        from .compiler import plan_hash
        probe["stale"] = probe.get("plan_hash") != plan_hash(plan)
    plan["answerability"] = answerability.assess(plan, plan.get("parsed", {}), probe if probe and not probe.get("stale") else None)
    _answer_issue(plan)
    clar = plan.get("clarification") or {}
    from . import expertise
    if clar.get("answers"):
        clar["typed"] = expertise.typed_notes(clar["answers"], plan, plan.get("question", ""), original=clar.get("original_question"))
    plan["idea_gaps"] = expertise.idea_gaps(clar.get("original_question") or plan.get("question", ""), plan, k)
    _gap_issues(plan)
    return plan


def narrative(plan: dict, results: dict, provider: str | None = None) -> dict | None:
    """Optional LLM-written Introduction/Discussion from aggregate, NCHS-reliable results."""
    client = LLMClient(provider)
    if not client.enabled or not privacy.aggregates_allowed():
        return None
    agg = {"title": plan["title"], "question": plan["refined_question"], "primary": results.get("primary_estimate"),
           "benchmarks": [{"label": b["label"], "published": b["published"], "replicated": b["replicated"]} for b in results.get("benchmarks", [])],
           "sensitivity": [{"label": s.get("label"), "est": s.get("est")} for s in results.get("sensitivity", [])],
           "subgroups": [{"group": f"{p['group_label']}: {p['group']}", "est": p["est"]} for p in results.get("prevalence", [])
                         if p.get("nchs") == "meets standard" and p["outcome"] == plan["outcome"]["variable"]][:12],
           "synthetic_data": results.get("meta", {}).get("synthetic"),
           "methods": {"design": "cross-sectional, survey-weighted NHANES", "model": plan.get("model", {}).get("family"),
                       "covariates": plan.get("covariates", []), "sensitivity": [s.get("label") for s in plan.get("sensitivity", []) if s.get("enabled")]},
           "limitations_from_plan": plan.get("limitations", [])[:8]}
    user = ("Aggregate results (no individual data):\n" + json.dumps(agg, default=str, indent=1) +
            "\n\nReturn JSON {introduction: 2 short paragraphs (context, gap, objective), discussion: 3 short paragraphs "
            "(principal findings in context, implications, strengths), limitations: 1 paragraph prioritising the most important "
            "limitations_from_plan and what they mean for interpretation, methods_summary: 2-3 plain sentences on how the study "
            "was done, plain_summary: 3 sentences a patient could read, conclusion: 1-2 sentences}. Do not invent citations or numbers "
            "beyond those provided; use associational language; if synthetic_data is true say results are illustrative only.")
    try:
        out = client.complete_json("Writer", SYSTEM_BASE, user, max_tokens=1500)
        out["llm"] = {**client.status(), "calls": [c.__dict__ for c in client.calls]}
        return out
    except LLMError:
        return None


def import_guideline(text: str, provider: str | None = None) -> dict:
    """Draft a computable definition from pasted guideline text (requires LLM); status = proposed."""
    k = get_knowledge()
    client = LLMClient(provider)
    if not client.enabled:
        raise LLMError("Guideline import needs an approved LLM provider (set Q2E_LLM_PROVIDER).")
    clean, _ = privacy.scrub(text[:12000])
    user = (f"{_catalog(k)}\n\nGUIDELINE TEXT:\n\"\"\"{clean}\"\"\"\n\nExtract ONE computable case definition. Return JSON "
            "{id (snake_case), concept (existing concept id or new snake_case id), label, short, type ('binary'|'categorical'), "
            "expr (expression over building-block names), criteria_text (verbatim thresholds), operational_notes (list of "
            "assumptions needed to compute it in NHANES), source: {citation, year, url, doi}}. Do not invent thresholds not in the text.")
    d = client.complete_json("Guideline curator", SYSTEM_BASE, user, max_tokens=1200)
    expressions.validate(d.get("expr", ""), set(k.blocks) | set(k.definitions))
    d["status"] = "proposed"
    return d


_CAUSAL_EXTRA = re.compile(r"\b(?:caus(?:es|ed|ing)|leads? to|led to|results? in|prevents?|protects? against|protective|"
                          r"(?:reduc|increas|rais|lower)\w*\s+(?:the\s+|their\s+|your\s+)?(?:\w+\s+){0,2}risk)\b", re.I)
_NUM = re.compile(r"(?<![\w.])[-+−]?\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace("−", "-").lstrip("+") for n in _NUM.findall(text or "")}


def explain(plan: dict, results: dict, sections: dict, provider: str | None = None) -> dict:
    """Amazon Bedrock rewrites the plain-language summary and key point for a clinician audience. It receives only
    the rule-written sentences (aggregate numbers from R) and may not introduce any number: every number in its text
    must already appear in those sentences, otherwise the rule-written text is kept."""
    client = LLMClient(provider)
    if not client.enabled:
        return {"available": False, "reason": "AI is off - connect Amazon Bedrock to rewrite this summary."}
    src_plain = sections.get("plain_language", "")
    src_key = (sections.get("key_points") or {}).get("findings", "")
    pe = results.get("primary_estimate") or {}
    facts = {"question": plan.get("refined_question"), "plain_summary": src_plain, "key_point": src_key,
             "effect": pe.get("effect"), "statistically_significant": bool(pe.get("lcl") is not None and pe.get("ucl") is not None
                                                                         and (pe["lcl"] > (1 if pe.get("effect") in ("PR", "OR") else 0)
                                                                              or pe["ucl"] < (1 if pe.get("effect") in ("PR", "OR") else 0))),
             "synthetic_data": results.get("meta", {}).get("synthetic", False)}
    user = ("Rewrite these two texts from a survey-weighted NHANES analysis.\n" + json.dumps(facts, default=str, indent=1) +
            "\n\nReturn JSON {plain: 2-3 short sentences a patient or busy clinician understands at once, key_point: one "
            "precise sentence for a clinician}. Rules: use ONLY numbers that appear in plain_summary or key_point, copied "
            "exactly (you may drop numbers, never add or change them); differences between two percentages are 'percentage "
            "points'; say plainly when a difference is not statistically significant; cross-sectional, so associational "
            "language only (no 'causes', 'leads to', 'reduces risk'); if synthetic_data is true say the numbers are illustrative.")
    try:
        out = client.complete_json("Explainer", SYSTEM_BASE, user, max_tokens=600)
    except LLMError as e:
        return {"available": False, "reason": f"AI unavailable: {str(e)[:160]}"}
    allowed = _numbers(src_plain) | _numbers(src_key) | {"100"}
    res: dict = {"available": True, "ai": {"provider": client.provider.name, "model": client.provider.model}, "rejected": []}
    for key, fallback in (("plain", src_plain), ("key_point", src_key)):
        txt = str(out.get(key) or "").strip()
        extra = _numbers(txt) - allowed
        if not txt or len(txt) > 700:
            res[key] = fallback
            res["rejected"].append(f"{key}: empty or too long")
        elif extra:
            res[key] = fallback
            res["rejected"].append(f"{key}: introduced numbers not in the results ({', '.join(sorted(extra))})")
        elif scan_causal(re.sub(r"due to (?:chance|random variation|sampling)", "", txt, flags=re.I)) or _CAUSAL_EXTRA.search(txt):
            res[key] = fallback
            res["rejected"].append(f"{key}: causal wording")
        elif _wrong_direction(txt, pe, plan):
            res[key] = fallback
            res["rejected"].append(f"{key}: stated the difference in the wrong direction")
        else:
            res[key] = txt
    res["checked"] = "Every number was checked against the R results; anything that did not match was replaced by the standard wording."
    return res


def _wrong_direction(text: str, pe: dict, plan: dict) -> bool:
    """For a two-group comparison, catch 'more common in men' when men were lower (or the reverse)."""
    if pe.get("effect") != "difference" or pe.get("est") in (None, 0):
        return False
    from .report import group_words
    a, b = group_words(pe.get("level"), plan).lower(), group_words(pe.get("reference"), plan).lower()
    if not a or not b:
        return False
    t = " " + text.lower() + " "
    up = r"(?:more common|more prevalent|more frequent|higher|greater|more likely)"
    down = r"(?:less common|less prevalent|less frequent|lower|smaller|less likely)"
    grp = re.compile(rf"\b(?:in|among|for)\s+(?:the\s+)?({re.escape(a)}|{re.escape(b)})\b")
    a_higher = a_lower = False
    for word, sign in ((up, 1), (down, -1)):
        for m in re.finditer(word, t):
            g = grp.search(t, m.end(), m.end() + 30)            # the group this word is about: the first one named after it
            if not g:
                g2 = re.search(rf"\b({re.escape(a)}|{re.escape(b)})\b[^.;]{{0,25}}$", t[max(0, m.start() - 40):m.start()])
                who = g2.group(1) if g2 else None               # "men had higher ..."
            else:
                who = g.group(1)
            if who is None:
                continue
            if (who == a) == (sign == 1):
                a_higher = True
            else:
                a_lower = True
    return (pe["est"] < 0 and a_higher and not a_lower) or (pe["est"] > 0 and a_lower and not a_higher)
