"""Interviewer agent: adaptive follow-up questions before the study is designed.

The user never tells Q2E how experienced they are. Instead we *infer* it from how the
research idea is written (jargon, NHANES variable codes, thresholds, guideline names vs.
everyday words like "I noticed" or "is it bad for"). Then we look at what the rule-based
parser could NOT work out from the question (no outcome, no population, ambiguous
exposure/outcome direction, unknown words, a "how do I stop it" goal...) and ask about
those gaps only - worded for the detected level:

  novice        plain language and everyday examples
  intermediate  standard research vocabulary
  expert        terse, technical; only the decisions an expert would care about

Nothing is left ambiguous at any level: every question says why it is asked and every
choice has a one-line explanation. When a word is not understood we do not ask the user
to "say it another way"; we suggest the closest terms Q2E knows, each explained.

Safety: answers only ever (a) append text to the question, which the normal parser then
reads, or (b) apply whitelisted plan edits (the same `planner.apply_fix` operations the UI
uses). The server re-creates the questions itself, so a client cannot inject other edits.
"""
from __future__ import annotations

import copy
import difflib
import re
from typing import Any

from . import planner, privacy
from .knowledge import Knowledge, get_knowledge
from .language_guard import scan_causal

LEVELS = ("novice", "intermediate", "expert")
# Only a safety ceiling: questions are asked only for real gaps, so most ideas get fewer (often none).
MAX_QUESTIONS = 5

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
    r"\b(?:learn|know) more\b", r"\bhow (?:can|do|should) i\b",
]
# Words about *how* to analyse, everyday goals, or filler - never worth a "what did you mean?" question.
FILLER_WORDS = set("""adjust adjusted adjusting adjustment regression regressions linear logistic poisson model models modeling
weighted weighting survey surveys ratio ratios odds ci confidence interval intervals report reporting analysis analyses method
methods estimate estimates using bad good healthy unhealthy really very learn learning know knowing more understand find out
want wanting help curious wondering info information stop stopping prevent preventing fix fixing treat treating treatment cure
curing get getting rid reduce reducing improve improving avoid avoiding manage managing beat overcome reverse lower lowering
handle deal better worse can could should would me myself mine
relate relates related relation relationship relationships link links linked connect connected connection affect affects
affected effect effects impact impacts amount amounts level levels high higher low lower everyday daily day days every much
many lot lots have has had does do how what why when which feel feeling give gives make makes cause causes being
age ages sex gender race ethnicity""".split())
# "How can I stop / prevent / treat it?" - a personal goal NHANES cannot test directly.
GOAL_PATTERN = re.compile(r"\b(?:stop|prevent|fix|treat|cure|get rid of|reduce|lower|improve|avoid|manage|reverse|beat|overcome)\b")
# "I have ...", "my ..." - the user is describing themselves, not a population.
PERSONAL_PATTERN = re.compile(r"\b(?:i have|i've got|i got|i am|i'm|i suffer|my (?:doctor|blood|iron|sugar|weight|levels?|labs?))\b")
NHANES_CODE = re.compile(r"\b(?!NHANES\b)(?:[A-Z]{3,5}[A-Z0-9]{2,6}|SEQN|SDMVPSU|SDMVSTRA|WTMEC\w*|WTINT\w*)\b")
CYCLE_MENTION = re.compile(r"\b(?:19|20)\d\d\s*[-–]\s*(?:(?:19|20)?\d\d|march)|\bcycles?\b|\bnhanes\b", re.I)
THRESHOLD = re.compile(r"[<>≤≥]=?\s*\d|\d+(?:\.\d+)?\s*(?:mg/dl|mg/l|ng/ml|mmol|kpa|kg/m|%|cm\b|mmhg|ml/min)", re.I)

# Factors NHANES measures that are often studied alongside each kind of health topic (by concept domain).
RELATED_FACTORS = {
    "iron": ["dietary_iron", "pregnancy", "ckd", "obesity", "food_insecurity", "inflammation"],
    "glycemia": ["obesity", "abdominal_obesity", "physical_activity", "sugar_intake", "short_sleep", "smoking"],
    "cardio": ["sodium_intake", "obesity", "physical_activity", "smoking", "alcohol", "diabetes"],
    "kidney": ["diabetes", "hypertension", "obesity", "protein_intake", "smoking"],
    "liver": ["alcohol", "obesity", "diabetes", "hepatitis_c"],
    "anthropometry": ["physical_activity", "energy_intake", "sugar_intake", "short_sleep", "sedentary"],
    "mental_health": ["short_sleep", "physical_activity", "food_insecurity", "smoking", "alcohol"],
    "behaviour": ["obesity", "depression", "physical_activity", "smoking"],
    "hematology": ["smoking", "inflammation", "alcohol", "obesity"],
    "respiratory": ["smoking", "cotinine", "obesity", "physical_activity"],
    "_default": ["obesity", "smoking", "physical_activity", "diabetes"],
}
# One-line, plain-language explanations of common factors (shown under each choice).
PLAIN = {
    "dietary_iron": "How much iron people get from food, from a 24-hour diet interview.",
    "pregnancy": "Whether the person is pregnant (pregnancy raises iron needs).",
    "ckd": "Chronic kidney disease, measured with blood and urine tests.",
    "obesity": "Body mass index (BMI) of 30 or more, from measured height and weight.",
    "abdominal_obesity": "Waist size, measured with a tape (belly fat).",
    "food_insecurity": "Not always having enough money for food.",
    "inflammation": "Signs of inflammation in the blood (high CRP).",
    "physical_activity": "How active people say they are each week.",
    "sugar_intake": "How much sugar people eat, from a diet interview.",
    "short_sleep": "Sleeping less than 7 hours a night.",
    "smoking": "Whether the person smokes.",
    "sodium_intake": "How much salt (sodium) people eat.",
    "alcohol": "How much alcohol people drink.",
    "diabetes": "Diabetes, from blood sugar tests or a doctor's diagnosis.",
    "hypertension": "High blood pressure, measured at the exam.",
    "protein_intake": "How much protein people eat.",
    "hepatitis_c": "Hepatitis C infection, as reported by the person.",
    "energy_intake": "Total calories eaten in a day.",
    "sedentary": "Hours spent sitting each day.",
    "depression": "Depression symptoms from a 9-question survey (PHQ-9).",
    "cotinine": "Exposure to tobacco smoke, from a blood test.",
    "anemia": "Low hemoglobin (the oxygen-carrying part of blood), from a blood test.",
    "iron_deficiency": "Low iron stores (low ferritin), from a blood test.",
    "hemoglobin": "The oxygen-carrying protein in red blood cells, from a blood test.",
    "glycemic_control": "Average blood sugar over the past 3 months (HbA1c blood test).",
    "fasting_glucose": "Blood sugar after not eating overnight.",
    "bmi_concept": "Body mass index: weight compared with height.",
    "total_cholesterol": "Total cholesterol in the blood.",
    "ldl": "LDL, the 'bad' cholesterol.",
    "systolic_bp": "The top number of a blood pressure reading.",
    "cvd": "Heart disease or stroke, as reported by the person.",
    "coronary_disease": "Narrowed heart arteries, as reported by the person.",
    "daytime_sleepiness": "Feeling very sleepy during the day.",
    "income": "Household income compared with the poverty line.",
}


# Everyday words -> the health topics (concept ids) people usually mean by them.
LAY_TERMS = {
    "fat": ["obesity", "abdominal_obesity"], "overweight": ["obesity", "bmi_concept"], "heavy": ["obesity", "bmi_concept"],
    "weight": ["bmi_concept", "obesity"], "belly": ["abdominal_obesity"], "chubby": ["obesity"], "big": ["obesity"],
    "sugar": ["glycemic_control", "diabetes", "sugar_intake"], "salt": ["sodium_intake", "hypertension"],
    "pressure": ["hypertension", "systolic_bp"], "heart": ["cvd", "coronary_disease"], "tired": ["daytime_sleepiness", "anemia"],
    "sleepy": ["daytime_sleepiness"], "sad": ["depression"], "kidneys": ["ckd"],
    # NHANES (as loaded in Q2E) has no stress or work/job measure; these are the closest things it does measure
    "stress": ["depression", "short_sleep"], "stressed": ["depression", "short_sleep"], "anxiety": ["depression"],
    "work": ["sedentary", "physical_activity", "short_sleep"], "job": ["sedentary", "physical_activity", "short_sleep"],
    "working": ["sedentary", "physical_activity", "short_sleep"],
    "exercise": ["physical_activity"], "workout": ["physical_activity"], "sitting": ["sedentary"], "drinking": ["alcohol"],
    "cigarettes": ["smoking"], "vaping": ["smoking", "cotinine"], "diet": ["energy_intake", "sugar_intake", "dietary_iron"],
    "food": ["energy_intake", "food_insecurity"], "poor": ["income", "food_insecurity"], "money": ["income"],
    "cholesterol": ["total_cholesterol", "ldl"], "blood": ["hemoglobin", "anemia"],
}
# Words with no direct NHANES measure: said plainly so the suggestions are never passed off as the same thing.
NOT_MEASURED = {"stress": "stress", "stressed": "stress", "anxiety": "anxiety", "work": "work hours or job type",
                "job": "work hours or job type", "working": "work hours or job type"}


def fix_spelling(question: str, k: Knowledge) -> tuple[str, list[dict]]:
    """Correct misspelled health words, but only towards words in Q2E's NHANES vocabulary (never invents terms)."""
    vocab = {w for c in k.concepts.values() for s in c["synonyms"] + [c["label"].lower()]
             for w in re.findall(r"[a-z]+", s.lower()) if len(w) >= 5} | {w for w in LAY_TERMS if len(w) >= 5}
    fixes = []

    def sub(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if len(lw) < 5 or lw in vocab or lw in FILLER_WORDS:
            return w
        best = difflib.get_close_matches(lw, vocab, n=1, cutoff=0.86)
        if not best or best[0].startswith(lw) or lw.startswith(best[0]):
            return w      # no close word, or just a plural/other form ("smoker" vs "smokers")
        fixes.append({"from": w, "to": best[0]})
        return best[0]

    return re.sub(r"[A-Za-z]+", sub, question), fixes


def unclear_terms(parsed: dict) -> list[str]:
    """Unmapped phrases minus method words ("regression"), goals ("stop") and filler ("learn")."""
    out = []
    for ph in parsed.get("unmapped_terms") or []:
        words = [w for w in re.split(r"[\s\-]+", ph.lower()) if w and w not in FILLER_WORDS]
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
        add(min(6 * len(tech), 36), f"Uses research or medical terms ({', '.join(tech[:6])})")
    if NHANES_CODE.search(question):
        add(10, "Uses NHANES variable codes")
    if CYCLE_MENTION.search(question):
        add(6, "Names NHANES or specific survey years")
    if THRESHOLD.search(question):
        add(8, "Gives exact cut-off values or units")
    if parsed.get("age_range") and any(a is not None for a in parsed["age_range"]):
        add(6, "Gives an age range")
    if parsed.get("populations"):
        add(4, "Says which group of people to study")
    if parsed.get("hints", {}).get("matched"):
        add(6, "Names a clinical guideline")
    if re.search(r"\bassociat\w* (?:with|between)\b|\brelationship between\b", q):
        add(4, "Asks about a link between two things")

    informal = [p for p in NOVICE_PATTERNS if re.search(p, q)]
    if informal:
        add(-min(8 * len(informal), 32), "Uses everyday wording")
    if scan_causal(question):
        add(-6, "Asks what causes something (NHANES can only show links)")
    unclear = unclear_terms(parsed)
    if unclear:
        add(-min(5 * len(unclear), 15), f"Has words not found in NHANES ({', '.join(unclear[:3])})")
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


def _pick(level: str, texts: dict) -> str:
    return texts.get(level) or texts.get("intermediate") or ""


def _question(qid: str, level: str, text: dict, why: dict, options: list[dict], free_text: dict | None = None) -> dict:
    """One follow-up question. `text` and `why` have a wording per level; every option has a `hint`."""
    return {"id": qid, "text": _pick(level, text), "why": _pick(level, why), "options": options, "free_text": free_text}


def _concept_hint(cid: str, k: Knowledge) -> str:
    """One plain sentence saying what a topic means / how NHANES measures it."""
    if cid in PLAIN:
        return PLAIN[cid]
    c = k.concepts.get(cid, {})
    for d in c.get("definitions", []):
        if k.definitions.get(d, {}).get("label"):
            return f"Defined using: {k.definitions[d]['label']}."
    block = k.blocks.get(c.get("block") or "", {})
    if block:
        units = f" ({block['units']})" if block.get("units") else ""
        return f"Measured in NHANES as {block.get('label', c.get('label', cid)).lower()}{units}."
    return f"A health topic measured in NHANES: {c.get('label', cid).lower()}."


def term_suggestions(term: str, k: Knowledge, limit: int = 3) -> list[dict]:
    """Closest things Q2E knows to an unknown word: everyday meanings, spelling-alike topics, then NHANES variables."""
    syn_to_concept = {s: c["id"] for c in k.concepts.values() for s in c["synonyms"] + [c["label"].lower()]}
    out, seen = [], set()

    def add_concept(cid: str):
        if cid in k.concepts and cid not in seen:
            seen.add(cid)
            syn = k.concepts[cid]["synonyms"][0]
            out.append({"id": f"c_{cid}", "label": _label(cid, k), "hint": _concept_hint(cid, k), "replace": syn})

    for w in term.lower().split():
        for cid in LAY_TERMS.get(w, []):
            add_concept(cid)
    for s in difflib.get_close_matches(term.lower(), list(syn_to_concept), n=6, cutoff=0.72):
        add_concept(syn_to_concept[s])
    for hit in k.var_index().search(term, top_k=4):
        if hit.get("confidence", 0) >= 0.6 and hit["variable"] not in seen and len(out) < limit:
            seen.add(hit["variable"])
            lab = hit["label"].split("(")[0].strip()
            out.append({"id": f"v_{hit['variable']}", "label": lab,
                        "hint": f"Survey question/measurement {hit['variable']}: {hit['label']}.", "replace": lab.lower()})
    return out[:limit]


def missed_topics(question: str, parsed: dict, k: Knowledge) -> list[str]:
    """Known health topics named in the idea that the parser did not keep (it holds at most two)."""
    kept = [c for c in (parsed.get("outcome_concept"), parsed.get("exposure_concept")) if c]
    kept_text = " ".join(_label(c, k).lower() + " " + " ".join(k.concepts.get(c, {}).get("synonyms", [])) for c in kept)
    unclear = {w for t in unclear_terms(parsed) for w in t.split()}    # these get their own "did you mean" question
    out = []
    for w in re.findall(r"[a-z]+", question.lower()):
        if w in NOT_MEASURED or w not in LAY_TERMS or w in kept_text or w in unclear:
            continue
        cid = LAY_TERMS[w][0]
        if cid in k.concepts and cid not in kept and cid not in out \
                and not any(s in kept_text for s in k.concepts[cid]["synonyms"] + [k.concepts[cid]["label"].lower()]):
            out.append(cid)
    return out


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
            "novice": "Which health condition or body measurement are you most curious about?",
            "intermediate": "Which condition or measurement is the main outcome?",
            "expert": "Primary outcome (condition or biomarker)?"}, {
            "novice": "Every study needs one main thing to measure, like blood sugar, blood pressure or anemia.",
            "intermediate": "We could not find a health condition or measurement in your idea.",
            "expert": "No outcome concept was mapped."},
            [{"id": c, "label": _label(c, k), "hint": _concept_hint(c, k), "append": f" Outcome: {k.concepts[c]['synonyms'][0]}."}
             for c in ("diabetes", "hypertension", "obesity", "anemia") if c in k.concepts],
            {"placeholder": "Or type a different condition or measurement", "template": " Outcome: {text}."}))

    # (a2) more health topics than the parser could keep -> which one is the main thing to measure?
    missed = missed_topics(question, parsed, k) if out_c else []
    if missed:
        cands = [c for c in (out_c, exp_c) if c] + missed
        qs.append(_question("focus", level, {
            "novice": "Your idea mentions several health topics. Which one is the main thing you want to measure?",
            "intermediate": "Several topics were mentioned. Which is the primary outcome?",
            "expert": "Multiple candidate outcomes. Primary outcome?"}, {
            "novice": "A study measures one main thing and compares it across the others, so we need to know which one matters most to you.",
            "intermediate": "The other topics can be studied as exposures or covariates.",
            "expert": "Remaining concepts are available as exposure/covariates."},
            [{"id": f"o_{c}", "label": _label(c, k), "hint": "" if c.startswith("dict:") else _concept_hint(c, k),
              "fixes": [] if c == out_c else [{"op": "set_outcome", "concept": c}]}
             for c in cands[:5]]))

    # (b) a personal goal ("how can I stop it?") -> offer factors NHANES can link to the condition
    goal = bool(out_c and not exp_c and GOAL_PATTERN.search(q))
    if goal:
        lbl = _label(out_c, k).lower()
        domain = k.concepts.get(out_c, {}).get("domain") or "_default"
        factors = [c for c in RELATED_FACTORS.get(domain, RELATED_FACTORS["_default"]) if c in k.concepts and c != out_c][:4]
        opts = [{"id": c, "label": _label(c, k), "hint": _concept_hint(c, k),
                 "append": f" Is it more common in people with {k.concepts[c]['synonyms'][0]}?"} for c in factors]
        opts.append({"id": "prev", "label": f"Just show how common {lbl} is", "hint": "Percent of people with it, overall and by age, sex and other groups.",
                     "append": " Estimate the prevalence."})
        qs.append(_question("goal", level, {
            "novice": f"Which of these would you like to check for a link with {lbl}?",
            "intermediate": f"NHANES cannot test treatments. Which factor should we examine alongside {lbl}?",
            "expert": f"Treatment effects are out of scope (cross-sectional). Exposure to examine with {lbl}?"}, {
            "novice": f"Finding out what stops {lbl} needs a clinical trial. NHANES is a one-time snapshot of thousands of "
                      f"people, so it can show which things go together with {lbl} - a useful first step.",
            "intermediate": "NHANES is cross-sectional: it shows associations, not the effect of an intervention.",
            "expert": "Prevention/treatment questions are reframed as cross-sectional associations."},
            opts, {"placeholder": "Or type another factor (e.g. vegetarian diet)", "template": " Is it more common in people with {text}?"}))

    # (c) words we could not map to NHANES -> suggest the closest known terms (no suggestions = nothing to ask)
    i = 0
    for ph in unclear_terms(parsed):
        sugg = term_suggestions(ph, k)
        if not sugg or i == 2:
            continue
        missing = next((NOT_MEASURED[w] for w in ph.split() if w in NOT_MEASURED), None)
        if missing:
            text = {"novice": f"The survey did not measure {missing}. Which of these, which it did measure, is closest to what you mean by \"{ph}\"?",
                    "intermediate": f"NHANES has no {missing} measure. Closest measured proxy for \"{ph}\"?",
                    "expert": f"No {missing} variable in NHANES. Proxy for \"{ph}\"?"}
            why = {"novice": "Q2E only uses things NHANES actually measured, so it will not pretend these are the same as "
                             f"{missing}. Pick the closest one, or leave it out.",
                   "intermediate": f"These are proxies, not measures of {missing}; results must be read that way.",
                   "expert": "Proxy choice affects construct validity; state it as a limitation."}
        else:
            text = {"novice": f"We couldn't find \"{ph}\" in the health survey. Did you mean one of these?",
                    "intermediate": f"\"{ph}\" is not an NHANES term. Closest matches:",
                    "expert": f"Unmapped term \"{ph}\". Candidate mappings:"}
            why = {"novice": "Q2E only understands words that match what NHANES actually measured. Pick the closest one, or leave it out.",
                   "intermediate": "Only terms that map to NHANES variables can be used in the analysis.",
                   "expert": "Pick a mapping or drop the term."}
        qs.append(_question(f"term{i}", level, text, why,
                            sugg + [{"id": "skip", "label": "Leave it out", "hint": "The study is designed without this word."}],
                            {"placeholder": "Or type a different word", "replace": True}))
        qs[-1]["term"] = ph
        i += 1

    # (d) only one topic, no clear aim -> "how common" or "linked to something"?
    has_prev_cue = any(c in q for c in planner.PREVALENCE_CUES)
    if out_c and not exp_c and not has_prev_cue and not goal and i == 0:
        lbl = _label(out_c, k).lower()
        qs.append(_question("aim", level, {
            "novice": f"What would you like to find out about {lbl}?",
            "intermediate": f"Prevalence of {lbl}, or its association with another factor?",
            "expert": f"Estimand: prevalence of {lbl}, or association with an exposure?"}, {
            "novice": "Counting how common something is and checking whether two things go together are different kinds of studies.",
            "intermediate": "This decides between a descriptive and an association analysis.",
            "expert": "Descriptive vs. association design."},
            [{"id": "prev", "label": "How common it is" if level == "novice" else "Prevalence (descriptive)",
              "hint": f"e.g. \"How common is {lbl} among US adults?\"", "append": " Estimate the prevalence."},
             {"id": "assoc", "label": "Whether it is linked to something else" if level == "novice" else "Association with another factor",
              "hint": f"e.g. is {lbl} linked to sleep, diet or another factor? Type that factor in the box below."}],
            {"placeholder": "The other factor (e.g. sleep, smoking, waist size)", "template": " Is it associated with {text}?",
             "requires_option": "assoc"}))

    # (e) who is being studied? Beginners get Q2E's usual group (shown in "What we understood") instead of a question.
    if level != "novice" and not parsed.get("populations") \
            and not any(a is not None for a in (parsed.get("age_range") or (None, None))):
        qs.append(_question("population", level, {
            "novice": "Which group of people do you want to learn about?",
            "intermediate": "Which population should be included?",
            "expert": "Target population / age restriction?"}, {
            "novice": "Results can differ a lot between, for example, children and older adults.",
            "intermediate": "Sets the inclusion criteria for the study.",
            "expert": "Defines the analytic domain (subpopulation)."},
            [{"id": "adults", "label": "Adults", "hint": "Age 18 and older.", "append": " Study adults."},
             {"id": "older", "label": "Older adults", "hint": "Age 65 and older.", "append": " Study older adults."},
             {"id": "children", "label": "Children and teens", "hint": "Age 1 to 17.", "append": " Study children."},
             {"id": "women", "label": "Women of reproductive age", "hint": "Women aged 18 to 49.", "append": " Study women of reproductive age."},
             {"id": "auto", "label": "Let Q2E choose", "hint": "Q2E picks the usual group for this topic (most often adults)."}]))

    # (f) the rules guessed which concept is exposure vs outcome -> confirm direction
    x, o = _label(exp_c, k), _label(out_c, k)
    same_thing = x.lower() in o.lower() or o.lower() in x.lower()   # e.g. "waist circumference (BMXWAIST)" matched twice
    if out_c and exp_c and not same_thing and not missed and any("treated as exposure" in n for n in parsed.get("notes", [])):
        qs.append(_question("direction", level, {
            "novice": "Which one do you think might affect the other?",
            "intermediate": "Confirm the roles: which is the exposure and which is the outcome?",
            "expert": "Exposure → outcome direction?"}, {
            "novice": "We compare the second thing across different levels of the first, so the order changes the analysis.",
            "intermediate": "The exposure is the explanatory variable; the outcome is modelled.",
            "expert": "Determines the regression specification."},
            [{"id": "keep", "label": f"{x} → {o}", "hint": f"Compare {o.lower()} across levels of {x.lower()}."},
             {"id": "swap", "label": f"{o} → {x}", "hint": f"Compare {x.lower()} across levels of {o.lower()}.",
              "fixes": [{"op": "swap_roles"}]}]))

    # (g) the outcome has several guideline definitions and none was named
    if out_c and not out_c.startswith("dict:") and level != "novice" and not parsed.get("hints", {}).get("matched"):
        defs = [d for d in k.concepts.get(out_c, {}).get("definitions", []) if d in k.definitions]
        if len(defs) > 1:
            opts = [{"id": d, "label": k.definitions[d].get("label", d),
                     "hint": str(k.definitions[d].get("short") or k.definitions[d].get("criteria_text") or "")[:160],
                     "fixes": [{"op": "set_definition", "role": "outcome", "value": d, "concept": out_c}]} for d in defs[:4]]
            opts.append({"id": "auto", "label": "Use the default definition", "hint": "Q2E's standard choice for this topic."})
            qs.append(_question("definition", level, {
                "intermediate": f"Several guideline definitions exist for {_label(out_c, k).lower()}. Which one?",
                "expert": f"Case definition for {_label(out_c, k).lower()}?"}, {
                "intermediate": "Different guidelines use different cut-offs, which changes who counts as a case.",
                "expert": "Affects case ascertainment and comparability with published estimates."}, opts))

    # (h) association: compare people at similar body weight? (a modelling choice, so beginners get the standard set)
    if level != "novice" and plan and plan.get("exposure") and not parsed.get("adjust_bmi") and "bmi" not in plan.get("covariates", []) \
            and "bmi" not in (plan["exposure"]["variable"], plan["outcome"]["variable"]):
        qs.append(_question("bmi", level, {
            "novice": "Should we compare people who weigh about the same?",
            "intermediate": "Adjust for BMI?",
            "expert": "Include BMI in the adjustment set (confounder, not mediator)?"}, {
            "novice": "Body weight is linked to many health measures; comparing people at similar weight keeps it from muddying the result.",
            "intermediate": "BMI may confound the association.",
            "expert": "Only appropriate if BMI is not on the causal pathway."},
            [{"id": "yes", "label": "Yes", "hint": "Adjust for body mass index (BMI).", "append": " Compare people independent of BMI."},
             {"id": "no", "label": "No", "hint": "Do not take body weight into account."}]))

    # (i) experts only: effect measure for a binary outcome
    if level == "expert" and plan and plan.get("exposure") and plan["outcome"].get("type") == "binary" \
            and not re.search(r"\b(?:prevalence|odds|risk) ratios?\b", q):
        qs.append(_question("estimand", level, {"expert": "Effect measure for the binary outcome?"},
                            {"expert": "PRs are preferred for common outcomes in cross-sectional data."},
                            [{"id": "pr", "label": "Prevalence ratio", "hint": "Quasi-Poisson, log link (default)."},
                             {"id": "or", "label": "Odds ratio", "hint": "Quasi-binomial, logit link.",
                              "fixes": [{"op": "set", "path": "model.family", "value": "quasibinomial"}]}]))

    return qs[:MAX_QUESTIONS]


def personal_notice(question: str) -> str:
    """Plain note when someone describes their own health ("I have ...")."""
    if PERSONAL_PATTERN.search(question.lower()):
        return ("Q2E looks for patterns across thousands of people in a national US health survey (NHANES). "
                "It cannot give personal medical advice - for your own health, please talk to a doctor. "
                "Below, we turn your idea into a research question about people like you.")
    return ""


def clarify(question: str, cycles: list[str] | None = None, level: str | None = None) -> dict[str, Any]:
    """Main entry point for the API: detect the level (unless overridden) and build questions."""
    k = get_knowledge()
    clean, _ = privacy.scrub(question)
    clean, spelling = fix_spelling(clean, k)
    parsed = planner.parse_question(clean, k)
    ex = assess_expertise(clean, parsed, k)
    used = level if level in LEVELS else ex["level"]
    qs = build_questions(clean, used, parsed, cycles, k)
    return {"expertise": ex, "level_used": used, "notice": personal_notice(clean), "question_used": clean,
            "understood": understood(clean, parsed, spelling, qs, k), "questions": qs}


def understood(question: str, parsed: dict, spelling: list[dict], qs: list[dict], k: Knowledge) -> list[dict]:
    """What Q2E already read from the idea, so it is visible why some things are not asked again.
    Built only from the parser's matches against the NHANES knowledge base."""
    out = []
    for s in spelling:
        out.append({"label": "Spelling", "value": f"read \"{s['from']}\" as \"{s['to']}\""})
    for key, name in (("outcome_concept", "Health topic"), ("exposure_concept", "Factor to compare")):
        cid = parsed.get(key)
        if cid:
            hint = "" if cid.startswith("dict:") else _concept_hint(cid, k)
            out.append({"label": name, "value": _label(cid, k), "hint": hint})
    asked_pop = any(q["id"] == "population" for q in qs)
    if parsed.get("populations") or any(a is not None for a in (parsed.get("age_range") or (None, None))):
        lo, hi = parsed.get("age_range") or (None, None)
        ages = f"ages {lo if lo is not None else '?'}-{hi if hi is not None else '?'}" if (lo is not None or hi is not None) else ""
        names = {p["id"]: p.get("label", p["id"]) for p in k.populations}
        pops = [names.get(p, p).replace("_", " ") for p in parsed.get("populations") or []]
        out.append({"label": "People", "value": ", ".join(x for x in [*pops, ages] if x)})
    elif not asked_pop:
        out.append({"label": "People", "value": "Q2E's usual group for this topic (most often adults), listed on the Protocol page"})
    asked = {q.get("term") for q in qs}
    dropped = [t for t in unclear_terms(parsed) if t not in asked and not term_suggestions(t, k)]
    if dropped:
        out.append({"label": "Not in NHANES (left out)", "value": ", ".join(f"\"{t}\"" for t in dropped)})
    return out


# ---------------------------------------------------------------------------
# 3. Turn answers into a refined question + safe plan edits
# ---------------------------------------------------------------------------
def _swap_word(text: str, old: str, new: str) -> str:
    """Put `new` where the unknown word `old` was (keeps word order); add it as a note if `old` is not found."""
    pat = re.compile(r"\b" + r"\W+".join(map(re.escape, old.split())) + r"\b", re.I) if old else None
    if pat and pat.search(text):
        return pat.sub(new, text, count=1)
    return f"{text} Meaning: {new}."


def apply_answers(question: str, answers: dict[str, dict], level: str | None = None,
                  cycles: list[str] | None = None) -> dict[str, Any]:
    """answers = {question_id: {"option": option_id, "text": free text}}.

    Returns {question: refined text, fixes: [planner.apply_fix ops], record: what was asked and answered}."""
    info = clarify(question, cycles, level)
    refined, fixes, record = info["question_used"].rstrip(), [], []
    if refined and refined[-1] not in ".?!":
        refined += "."      # so each answer is added as its own sentence
    for q in info["questions"]:
        a = answers.get(q["id"]) or {}
        opt = next((o for o in q["options"] if o["id"] == a.get("option")), None)
        text = privacy.scrub(str(a.get("text") or ""))[0].strip()[:120]
        ft = q.get("free_text") or {}
        if opt:
            refined += opt.get("append", "")
            fixes += opt.get("fixes", [])
            if opt.get("replace"):
                refined = _swap_word(refined, q.get("term", ""), opt["replace"])
        if text and ft.get("replace") and not opt:
            refined = _swap_word(refined, q.get("term", ""), text)
        elif text and ft.get("template") and (not ft.get("requires_option") or ft["requires_option"] == a.get("option")):
            refined += ft["template"].format(text=text)
        if opt or text:
            record.append({"id": q["id"], "question": q["text"], "answer": (opt or {}).get("label", "") + (f" {text}" if text else "")})
    return {"question": refined.strip(), "fixes": fixes, "record": record,
            "expertise": info["expertise"], "level_used": info["level_used"], "understood": info["understood"]}


def _set_outcome(plan: dict, cid: str | None, k: Knowledge) -> dict:
    """Make another topic from the idea the outcome; the remaining one stays as the exposure."""
    parsed = dict(plan.get("parsed") or {})
    if not cid or not (cid in k.concepts or cid.startswith("dict:")) or not parsed:
        return plan
    old_out, old_exp = parsed.get("outcome_concept"), parsed.get("exposure_concept")
    if cid == old_out:
        return plan
    parsed["outcome_concept"] = cid
    parsed["exposure_concept"] = old_exp if old_exp and old_exp != cid else old_out
    parsed["hints"] = parsed.get("hints") or {"prefer": [], "upgrade": {}}
    rebuilt = planner.build_plan(plan["question"], parsed, plan["dataset"].get("cycles"), plan["dataset"], k)
    rebuilt["plan_id"] = plan.get("plan_id", rebuilt.get("plan_id"))
    rebuilt["version"] = plan.get("version", 1)
    return rebuilt


def apply_fixes(plan: dict, fixes: list[dict]) -> dict:
    """Apply answer-driven plan edits. Role swaps go first because they rebuild the plan."""
    k = get_knowledge()
    # a role swap rebuilds the plan from scratch, so keep the agents' conversation and AI/privacy info
    keep = {key: plan[key] for key in ("agent_dialogue", "llm", "privacy") if key in plan}
    order = {"set_outcome": 0, "swap_roles": 1}
    for f in sorted(fixes, key=lambda f: order.get(f.get("op"), 2)):
        if f.get("op") == "set_outcome":
            plan = _set_outcome(plan, f.get("concept"), k)
            continue
        if f.get("op") == "set_definition" and plan.get("outcome", {}).get("concept") != f.get("concept"):
            continue   # the outcome changed (e.g. after a swap); this definition no longer applies
        plan = planner.apply_fix(plan, {key: v for key, v in f.items() if key != "concept"}, k)
    for key, v in keep.items():
        plan.setdefault(key, v)
    return plan
