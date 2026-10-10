"""Interviewer agent: adaptive follow-up questions before the study is designed.

The user never tells Q2E how experienced they are. Instead we *infer* it from how the
research idea is written (jargon, NHANES variable codes, thresholds, guideline names vs.
everyday words like "I noticed" or "is it bad for"). Then we look at what the rule-based
parser could NOT work out from the question (no outcome, no population, ambiguous
exposure/outcome direction, unknown words, several guideline definitions...) and ask
about those gaps only - worded for the detected level:

  novice        plain language, few choices, a short "why we ask" for each question
  intermediate  standard research vocabulary
  expert        terse, technical; only the decisions an expert would care about

Precise questions produce few or no follow-ups; vague ones produce more.

Safety: answers only ever (a) append text to the question, which the normal parser then
reads, or (b) apply whitelisted plan edits (the same `planner.apply_fix` operations the UI
uses). The server re-creates the questions itself, so a client cannot inject other edits.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from . import planner, privacy
from .knowledge import Knowledge, get_knowledge
from .language_guard import scan_causal

LEVELS = ("novice", "intermediate", "expert")
MAX_QUESTIONS = {"novice": 4, "intermediate": 3, "expert": 2}

# Words a researcher / clinician would use; each one found nudges the score up.
TECH_TERMS = [
    "prevalence ratio", "odds ratio", "hazard ratio", "confound", "covariate", "survey-weight", "survey weight",
    "weighted", "stratif", "regression", "cross-sectional", "multivariable", "multivariate", "adjusted", "adjusting for",
    "sensitivity analys", "imputation", "effect modif", "interaction", "estimand", "95% ci", "confidence interval",
    "p-value", "quartile", "tertile", "dose-response", "exposure", "outcome", "cohort", "population-based",
    "hba1c", "egfr", "ferritin", "tsat", "transferrin saturation", "uacr", "hscrp", "fib-4", "kpa", "elastography",
    "phq-9", "bmi", "waist circumference", "glycemic", "glycated", "dyslipidemia", "insulin resistance", "homa-ir",
    "kdigo", "baveno", "ada criteria", "who criteria", "atp iii", "mec weight", "psu", "strata", "quasi-poisson",
    "logistic", "linear model", "glm", "svyglm",
]
# Everyday / informal phrasing; each one found nudges the score down.
NOVICE_PATTERNS = [
    r"\bi (?:have )?(?:noticed|think|feel|wonder|heard|guess)\b", r"\bis it (?:bad|good|true|ok)\b",
    r"\b(?:bad|good) for (?:you|your|people)\b", r"\bmakes? (?:you|people|someone)\b", r"\b(?:stuff|things|kinda|sorta|a lot)\b",
    r"\b(?:fat|skinny|sugar levels?|junk food)\b", r"\bdoes .{0,40}\b(?:cause|make|give)\b", r"\bwhy do\b", r"\bpeople who\b",
]
# Words about *how* to analyse (or plain filler) - never worth a "what did you mean?" question.
METHOD_WORDS = set("""adjust adjusted adjusting adjustment regression regressions linear logistic poisson model models modeling
weighted weighting survey surveys ratio ratios odds ci confidence interval intervals report reporting analysis analyses method
methods estimate estimates using bad good healthy unhealthy really very""".split())
NHANES_CODE = re.compile(r"\b(?!NHANES\b)(?:[A-Z]{3,5}[A-Z0-9]{2,6}|SEQN|SDMVPSU|SDMVSTRA|WTMEC\w*|WTINT\w*)\b")
CYCLE_MENTION = re.compile(r"\b(?:19|20)\d\d\s*[-–]\s*(?:(?:19|20)?\d\d|march)|\bcycles?\b|\bnhanes\b", re.I)
THRESHOLD = re.compile(r"[<>≤≥]=?\s*\d|\d+(?:\.\d+)?\s*(?:mg/dl|mg/l|ng/ml|mmol|kpa|kg/m|%|cm\b|mmhg|ml/min)", re.I)


def unclear_terms(parsed: dict) -> list[str]:
    """Unmapped phrases minus analysis-method words ("adjusting", "regression"...) and filler ("bad")."""
    out = []
    for ph in parsed.get("unmapped_terms") or []:
        words = [w for w in re.split(r"[\s\-]+", ph.lower()) if w and w not in METHOD_WORDS]
        if words:
            out.append(" ".join(words))
    return out


# ---------------------------------------------------------------------------
# 1. Estimate expertise
# ---------------------------------------------------------------------------
def assess_expertise(question: str, parsed: dict | None = None, k: Knowledge | None = None) -> dict[str, Any]:
    """Return {level, score 0-100, signals:[{text, effect}]} from the wording of the question."""
    k = k or get_knowledge()
    parsed = parsed or planner.parse_question(question, k)
    q = question.lower()
    score = 40
    signals: list[dict] = []

    def add(points: int, text: str):
        nonlocal score
        score += points
        signals.append({"text": text, "effect": "+" if points > 0 else "-"})

    tech = sorted({t for t in TECH_TERMS if t in q})
    if tech:
        add(min(6 * len(tech), 36), f"Technical terms: {', '.join(tech[:6])}")
    if NHANES_CODE.search(question):
        add(10, "Uses NHANES variable or design codes")
    if CYCLE_MENTION.search(question):
        add(6, "Names NHANES or a survey cycle")
    if THRESHOLD.search(question):
        add(8, "Gives explicit thresholds or units")
    if parsed.get("age_range") and any(a is not None for a in parsed["age_range"]):
        add(6, "Specifies an age range")
    if parsed.get("populations"):
        add(4, "Defines the study population")
    if parsed.get("hints", {}).get("matched"):
        add(6, "Names a clinical guideline")
    if re.search(r"\bassociat\w* (?:with|between)\b|\brelationship between\b", q):
        add(4, "Frames the idea as an association")

    informal = [p for p in NOVICE_PATTERNS if re.search(p, q)]
    if informal:
        add(-min(8 * len(informal), 32), "Everyday or informal wording")
    if scan_causal(question):
        add(-6, "Causal wording (NHANES can only show associations)")
    unclear = unclear_terms(parsed)
    if unclear:
        add(-min(5 * len(unclear), 15), f"Terms we could not map: {', '.join(unclear[:3])}")
    if len(q.split()) < 8:
        add(-6, "Very short description")

    score = max(0, min(100, score))
    level = "novice" if score < 35 else "expert" if score >= 65 else "intermediate"
    return {"level": level, "score": score, "signals": signals}


# ---------------------------------------------------------------------------
# 2. Build follow-up questions from the gaps in the parsed question
# ---------------------------------------------------------------------------
def _label(cid: str | None, k: Knowledge) -> str:
    if not cid:
        return "?"
    if cid.startswith("dict:"):
        return k.dictionary.get(cid[5:], {}).get("label", cid[5:])
    return k.concepts.get(cid, {}).get("label", cid)


def _question(qid: str, level: str, text: dict, why: str, options: list[dict], free_text: dict | None = None) -> dict:
    """One follow-up question. `text` has a wording per level; `why` is shown to novices only."""
    return {"id": qid, "text": text.get(level) or text["intermediate"], "why": why if level == "novice" else "",
            "options": options, "free_text": free_text}


def _draft_plan(question: str, parsed: dict, cycles: list[str] | None, k: Knowledge) -> dict | None:
    """Try a throw-away rule-based plan so we can see the outcome type, covariates, model..."""
    try:
        return planner.build_plan(question, copy.deepcopy(parsed), cycles, None, k)
    except Exception:  # noqa: BLE001 - no outcome yet, hard stop, etc.
        return None


def build_questions(question: str, level: str, parsed: dict | None = None, cycles: list[str] | None = None,
                    k: Knowledge | None = None) -> list[dict]:
    k = k or get_knowledge()
    parsed = parsed or planner.parse_question(question, k)
    if parsed.get("hard_stop"):
        return []      # the answerability engine explains why; follow-ups would not help
    q = question.lower()
    out_c, exp_c = parsed.get("outcome_concept"), parsed.get("exposure_concept")
    plan = _draft_plan(question, parsed, cycles, k)
    qs: list[dict] = []

    # (a) no health topic found at all -> nothing can run without this
    if not out_c:
        qs.append(_question("topic", level, {
            "novice": "What health condition or body measurement are you most curious about?",
            "intermediate": "Which condition or measurement is the main outcome?",
            "expert": "Primary outcome (condition or biomarker)?"},
            "Every study needs one main thing to measure, like blood sugar, blood pressure or anemia.",
            [], {"placeholder": "e.g. blood sugar, high blood pressure, anemia", "template": " Outcome: {text}."}))

    # (b) words we could not map to NHANES (method words like "regression" are ignored)
    for i, ph in enumerate(unclear_terms(parsed)[:2]):
        qs.append(_question(f"term{i}", level, {
            "novice": f"We didn't understand \"{ph}\". Could you say it another way?",
            "intermediate": f"\"{ph}\" did not map to an NHANES variable. Rephrase or skip?",
            "expert": f"Unmapped term \"{ph}\": synonym or NHANES variable name?"},
            "The tool only knows the words that appear in the NHANES data dictionary.",
            [{"id": "skip", "label": "Skip it, it is not important"}],
            {"placeholder": "e.g. a simpler or more medical word", "template": " ({text})"}))

    # (c) only one topic, no clear aim -> "how common" or "linked to something"?
    has_prev_cue = any(c in q for c in planner.PREVALENCE_CUES)
    if out_c and not exp_c and not has_prev_cue:
        lbl = _label(out_c, k)
        qs.append(_question("aim", level, {
            "novice": f"What would you like to find out about {lbl.lower()}?",
            "intermediate": f"Is this a prevalence question about {lbl.lower()}, or an association with an exposure?",
            "expert": f"Estimand: prevalence of {lbl.lower()}, or association with an exposure?"},
            "Counting how common something is and checking whether two things go together are different kinds of studies.",
            [{"id": "prev", "label": "How common it is" if level == "novice" else "Prevalence (descriptive)", "append": " Estimate the prevalence."},
             {"id": "assoc", "label": "Whether it is linked to something else" if level == "novice" else "Association with an exposure (type it below)"}],
            {"placeholder": "e.g. sleep, smoking, waist size", "template": " Is it associated with {text}?", "requires_option": "assoc"}))

    # (d) who is being studied?
    if not parsed.get("populations") and not any(a is not None for a in (parsed.get("age_range") or (None, None))):
        qs.append(_question("population", level, {
            "novice": "Which group of people do you want to learn about?",
            "intermediate": "Which population should be included?",
            "expert": "Target population / age restriction?"},
            "Results can differ a lot between, for example, children and older adults.",
            [{"id": "adults", "label": "Adults (18+)", "append": " in adults"},
             {"id": "older", "label": "Older adults (65+)", "append": " in older adults"},
             {"id": "children", "label": "Children and teens", "append": " in children"},
             {"id": "women", "label": "Women of reproductive age", "append": " in women of reproductive age"},
             {"id": "auto", "label": "Let Q2E choose a sensible default"}]))

    # (e) the rules guessed which concept is exposure vs outcome -> confirm direction
    x, o = _label(exp_c, k), _label(out_c, k)
    same_thing = x.lower() in o.lower() or o.lower() in x.lower()   # e.g. "waist circumference (BMXWAIST)" matched twice
    if out_c and exp_c and not same_thing and any("treated as exposure" in n for n in parsed.get("notes", [])):
        qs.append(_question("direction", level, {
            "novice": "Which one do you think might affect the other?",
            "intermediate": "Confirm the roles: exposure and outcome?",
            "expert": "Exposure → outcome direction?"},
            "We look at how the outcome changes across levels of the exposure, so the order matters for the analysis.",
            [{"id": "keep", "label": f"{x} → {o}" if level != "novice" else f"{x} might affect {o}"},
             {"id": "swap", "label": f"{o} → {x}" if level != "novice" else f"{o} might affect {x}",
              "fixes": [{"op": "swap_roles"}]}]))

    # (f) the outcome has several guideline definitions and none was named
    if out_c and not out_c.startswith("dict:") and level != "novice" and not parsed.get("hints", {}).get("matched"):
        defs = [d for d in k.concepts.get(out_c, {}).get("definitions", []) if d in k.definitions]
        if len(defs) > 1:
            opts = [{"id": d, "label": k.definitions[d].get("label", d),
                     "fixes": [{"op": "set_definition", "role": "outcome", "value": d, "concept": out_c}]} for d in defs[:4]]
            opts.append({"id": "auto", "label": "Use the default definition"})
            qs.append(_question("definition", level, {
                "intermediate": f"Several guideline definitions exist for {_label(out_c, k).lower()}. Which one?",
                "expert": f"Case definition for {_label(out_c, k).lower()}?"}, "", opts))

    # (g) association: compare people at similar body weight?
    if plan and plan.get("exposure") and not parsed.get("adjust_bmi") and "bmi" not in plan.get("covariates", []) \
            and "bmi" not in (plan["exposure"]["variable"], plan["outcome"]["variable"]):
        qs.append(_question("bmi", level, {
            "novice": "Should we compare people who weigh about the same?",
            "intermediate": "Adjust for BMI?",
            "expert": "Include BMI in the adjustment set (confounder, not mediator)?"},
            "Body weight is linked to many health measures; comparing people at similar weight separates its effect from your topic.",
            [{"id": "yes", "label": "Yes" if level != "novice" else "Yes, compare at similar weight", "append": " independent of BMI"},
             {"id": "no", "label": "No"}]))

    # (h) experts only: effect measure for a binary outcome
    if level == "expert" and plan and plan.get("exposure") and plan["outcome"].get("type") == "binary" \
            and not re.search(r"\b(?:prevalence|odds|risk) ratios?\b", q):
        qs.append(_question("estimand", level, {"expert": "Effect measure for the binary outcome?"}, "",
                            [{"id": "pr", "label": "Prevalence ratio (quasi-Poisson, default)"},
                             {"id": "or", "label": "Odds ratio (quasi-binomial)",
                              "fixes": [{"op": "set", "path": "model.family", "value": "quasibinomial"}]}]))

    return qs[:MAX_QUESTIONS[level]]


def clarify(question: str, cycles: list[str] | None = None, level: str | None = None) -> dict[str, Any]:
    """Main entry point for the API: detect the level (unless overridden) and build questions."""
    k = get_knowledge()
    clean, _ = privacy.scrub(question)
    parsed = planner.parse_question(clean, k)
    ex = assess_expertise(clean, parsed, k)
    used = level if level in LEVELS else ex["level"]
    return {"expertise": ex, "level_used": used, "questions": build_questions(clean, used, parsed, cycles, k)}


# ---------------------------------------------------------------------------
# 3. Turn answers into a refined question + safe plan edits
# ---------------------------------------------------------------------------
def apply_answers(question: str, answers: dict[str, dict], level: str | None = None,
                  cycles: list[str] | None = None) -> dict[str, Any]:
    """answers = {question_id: {"option": option_id, "text": free text}}.

    Returns {question: refined text, fixes: [planner.apply_fix ops], record: what was asked and answered}."""
    info = clarify(question, cycles, level)
    clean, _ = privacy.scrub(question)
    refined, fixes, record = clean.rstrip(), [], []
    for q in info["questions"]:
        a = answers.get(q["id"]) or {}
        opt = next((o for o in q["options"] if o["id"] == a.get("option")), None)
        if opt:
            refined += opt.get("append", "")
            fixes += opt.get("fixes", [])
        text = privacy.scrub(str(a.get("text") or ""))[0].strip()[:120]
        ft = q.get("free_text")
        if text and ft and (not ft.get("requires_option") or ft["requires_option"] == a.get("option")):
            refined += ft["template"].format(text=text)
        if opt or text:
            record.append({"id": q["id"], "question": q["text"], "answer": (opt or {}).get("label", "") + (f" {text}" if text else "")})
    return {"question": refined.strip(), "fixes": fixes, "record": record,
            "expertise": info["expertise"], "level_used": info["level_used"]}


def apply_fixes(plan: dict, fixes: list[dict]) -> dict:
    """Apply answer-driven plan edits. Role swaps go first because they rebuild the plan."""
    k = get_knowledge()
    # a role swap rebuilds the plan from scratch, so keep the agents' conversation and AI/privacy info
    keep = {key: plan[key] for key in ("agent_dialogue", "llm", "privacy") if key in plan}
    for f in sorted(fixes, key=lambda f: f.get("op") != "swap_roles"):
        if f.get("op") == "set_definition" and plan.get("outcome", {}).get("concept") != f.get("concept"):
            continue   # the outcome changed (e.g. after a swap); this definition no longer applies
        plan = planner.apply_fix(plan, {key: v for key, v in f.items() if key != "concept"}, k)
    for key, v in keep.items():
        plan.setdefault(key, v)
    return plan
