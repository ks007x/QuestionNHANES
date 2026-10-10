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
MAX_QUESTIONS = 6

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
age ages sex gender race ethnicity tell telling show something anything interesting interested today tomorrow
yesterday please thanks thank wonder question questions idea ideas thing things stuff
extremely close closer closest similar near nearest change changes changing nhanes instead certain
due lack lacks lacking lacked absence absent noticed notice notices noticing think thought believe believed seem seems seemed
maybe perhaps possibly probably likely unlikely because therefore thus hence people person persons folks someone everyone anyone
kind kinds sort sorts type types way ways part parts reason reasons often sometimes usually always never possible normal
lately recently currently generally mostly mainly especially actually basically involved related regarding concerning toward
towards versus compared aged old young younger older year years""".split())
# Everyday words a typo is most likely meant to be ("pepole" -> "people"); corrected, then ignored like any filler word.
COMMON_WORDS = {w for w in FILLER_WORDS | planner._STOP | planner._RESEARCH_WORDS if len(w) >= 5}
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
    "physical_activity": "Whether the person does any vigorous recreational activity (self-reported, yes/no).",
    "sugar_intake": "How much sugar people eat, from a diet interview.",
    "short_sleep": "Usually sleeping less than 7 hours on weekdays or workdays (self-reported).",
    "smoking": "Smoking status, from the interview.",
    "sodium_intake": "How much salt (sodium) people eat.",
    "alcohol": "Number of alcoholic drinks on days the person drinks.",
    "diabetes": "Diabetes: a doctor's diagnosis, taking diabetes medicine, or a high HbA1c blood test.",
    "hypertension": "High blood pressure at the exam, or taking blood pressure medicine.",
    "protein_intake": "How much protein people eat.",
    "hepatitis_c": "Hepatitis C infection, as reported by the person.",
    "energy_intake": "Total calories eaten in a day.",
    "sedentary": "Time spent sitting on a typical day (self-reported).",
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
    "cvd": "Coronary heart disease, heart attack, stroke or heart failure, as reported by the person.",
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
    # stand-ins for stress/work: offered after any official items that use the word itself
    "stress": ["depression", "short_sleep"], "stressed": ["depression", "short_sleep"], "anxiety": ["depression"],
    "work": ["sedentary", "physical_activity", "short_sleep"], "job": ["sedentary", "physical_activity", "short_sleep"],
    "working": ["sedentary", "physical_activity", "short_sleep"],
    "exercise": ["physical_activity"], "workout": ["physical_activity"], "sitting": ["sedentary"], "drinking": ["alcohol"],
    "cigarettes": ["smoking"], "vaping": ["smoking", "cotinine"], "diet": ["energy_intake", "sugar_intake", "dietary_iron"],
    "food": ["energy_intake", "food_insecurity"], "poor": ["income", "food_insecurity"], "money": ["income"],
    "cholesterol": ["total_cholesterol", "ldl"], "blood": ["hemoglobin", "anemia"],
    # school / study life: NHANES has no questions on it, so the nearest daily behaviours it does measure
    "study": ["short_sleep", "sedentary", "physical_activity"], "studying": ["short_sleep", "sedentary", "physical_activity"],
    "coursework": ["short_sleep", "sedentary", "physical_activity"], "homework": ["short_sleep", "sedentary"],
    "school": ["short_sleep", "sedentary", "physical_activity"], "student": ["short_sleep", "sedentary", "physical_activity"],
    "students": ["short_sleep", "sedentary", "physical_activity"], "college": ["short_sleep", "sedentary", "alcohol"],
    "grades": ["short_sleep", "depression"], "habits": ["short_sleep", "physical_activity", "sedentary", "smoking", "alcohol"],
    "lifestyle": ["physical_activity", "short_sleep", "smoking", "alcohol"], "screen": ["sedentary"], "phone": ["sedentary"],
    "gaming": ["sedentary"], "tv": ["sedentary"],
    "inactivity": ["sedentary", "physical_activity"], "inactive": ["sedentary", "physical_activity"],
    "active": ["physical_activity"], "activity": ["physical_activity", "sedentary"], "lazy": ["sedentary", "physical_activity"],
}
# LAY_TERMS entries above that are stand-ins (not the same thing), so they are never treated as the topic itself
PROXY_WORDS = {"stress", "stressed", "anxiety", "work", "job", "working", "study", "studying", "coursework", "homework",
               "school", "student", "students", "college", "grades", "habits", "lifestyle", "screen", "phone", "gaming", "tv"}
# Behaviours NHANES measures well, offered as close alternatives when a question's exposure is not in NHANES
COMMON_EXPOSURES = ["short_sleep", "physical_activity", "sedentary", "smoking", "alcohol", "obesity"]
# Pairs that measure nearly the same behaviour, so "is one linked to the other?" is not a useful question
SAME_THING = {frozenset(("sedentary", "physical_activity")), frozenset(("obesity", "bmi_concept")),
              frozenset(("obesity", "abdominal_obesity"))}
POP_WORDS = re.compile(r"\b(older adults|young adults|adults|women|men|children|adolescents|teenagers|teens|elderly|seniors)\b", re.I)


def _switch_questions(cids: list[str], outcome: str, pop: str, k: Knowledge, why: str, limit: int = 3) -> list[dict]:
    """'Is <cid> associated with <outcome> in <pop>?' for each candidate topic, kept only if the parser reads it back."""
    res = []
    for cid in cids:
        if cid == outcome or cid not in k.concepts or outcome not in k.concepts:
            continue
        q = f"Is {k.concepts[cid]['synonyms'][0]} associated with {k.concepts[outcome]['synonyms'][0]} in {pop}?"
        p = planner.parse_question(q, k)
        if {p.get("outcome_concept"), p.get("exposure_concept")} == {outcome, cid}:
            w = why.format(label=_label(cid, k).lower())
            res.append({"question": q, "label": _label(cid, k), "why": w[:1].upper() + w[1:]})
        if len(res) >= limit:
            break
    return res


def typed_notes(answers: dict | None, plan: dict, question: str, k: Knowledge | None = None,
                original: str | None = None) -> list[dict]:
    """Account for everything the user TYPED in the follow-up answers, so nothing is silently dropped:
    status 'used' (and as what), 'not_used' (a measurable topic that did not fit) or 'not_in_nhanes'."""
    k = k or get_knowledge()
    out_c = (plan.get("outcome") or {}).get("concept")
    exp_c = (plan.get("exposure") or {}).get("concept")
    first = planner.parse_question(original, k) if original else {}
    # keep the topic the user started with (e.g. 'high blood sugar') when suggesting what to swap in
    anchor = next((c for c in (first.get("outcome_concept"), first.get("exposure_concept")) if c in (out_c, exp_c) and c), out_c)
    pops = POP_WORDS.findall(question)
    pop = {"teenagers": "adolescents", "teens": "adolescents", "elderly": "older adults", "seniors": "older adults"}.get(
        pops[-1].lower(), pops[-1].lower()) if pops else "US adults"
    used_text = " ".join([_label(out_c, k), _label(exp_c, k) if exp_c else ""] +
                         [k.label(c) for c in plan.get("covariates", [])] +
                         [c["label"] for c in plan.get("population", []) if c.get("enabled")]).lower()
    notes, seen = [], set()
    for qid, a in (answers or {}).items():
        text = privacy.scrub(str((a or {}).get("text") or ""))[0].strip()[:120]
        if len(text) < 2 or text.lower() in seen:
            continue
        seen.add(text.lower())
        p = planner.parse_question(text, k)
        found = [c for c in (p.get("outcome_concept"), p.get("exposure_concept")) if c and not c.startswith("dict:")]
        words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in FILLER_WORDS and len(w) > 2]
        if any(c in (out_c, exp_c) for c in found):
            role = "outcome" if out_c in found else "exposure"
            notes.append({"text": text, "status": "used", "note": f"Used as your {role}: {_label(out_c if role == 'outcome' else exp_c, k)}."})
            continue
        if POP_WORDS.search(text) or p.get("populations") or any(a is not None for a in (p.get("age_range") or ())):
            notes.append({"text": text, "status": "used", "note": "Used to choose who is in the study (see 'Who is in the study')."})
            continue
        if words and all(w in used_text for w in words):
            notes.append({"text": text, "status": "used", "note": "Used in the protocol (see the study group and adjustments)."})
            continue
        if found:
            labs = ", ".join(_label(c, k) for c in found)
            notes.append({"text": text, "status": "not_used",
                          "note": f"NHANES measures this ({labs}), but " +
                                  (f"your study already compares {_label(exp_c, k).lower()} with {_label(out_c, k).lower()}. "
                                   if exp_c else f"it was not added to your study of {_label(out_c, k).lower()}. ") +
                                  "Pick a question below to study it.",
                          "alternatives": _switch_questions([c for c in found if c != anchor], anchor, pop, k,
                                                            "Uses what you typed: {label}.") if anchor else []})
            continue
        proxies = [cid for w in words for cid in LAY_TERMS.get(w, []) if cid != anchor]
        proxies = list(dict.fromkeys(proxies))
        proxy_word = next((w for w in words if LAY_TERMS.get(w)), "")
        alts = _switch_questions(proxies, anchor, pop, k, f"Closest NHANES measure to '{proxy_word}': {{label}}.") if anchor and proxies else []
        if anchor and not alts:
            alts = _switch_questions([c for c in COMMON_EXPOSURES if c not in (out_c, exp_c)], anchor, pop, k,
                                     "{label} is measured well in NHANES and often studied with " + _label(anchor, k).lower() + ".")
        notes.append({"text": text, "status": "not_in_nhanes",
                      "note": f"NHANES has no questions on \"{text}\", so it could not be added to the study." +
                              (" These close questions use things NHANES does measure:" if alts else ""),
                      "alternatives": alts})
    return notes


def missing_topics(parsed: dict, k: Knowledge) -> list[str]:
    """Words from the idea that no official NHANES variable mentions at all (e.g. 'cortisol')."""
    return [t for t in unclear_terms(parsed) if not POP_WORDS.search(t) and not term_suggestions(t, k)
            and all(not_measured(w, k) for w in t.split())]


def idea_gaps(original: str, plan: dict, k: Knowledge | None = None) -> list[dict]:
    """Compare the user's ORIGINAL idea with the study that was built, and name every difference:
    topics NHANES does not measure, topics it measures that did not make it into the study, and a
    'does X relate to Y?' idea that became a 'how common is X?' study. Nothing changes silently."""
    k = k or get_knowledge()
    if not original:
        return []
    text, _ = fix_spelling(privacy.scrub(original)[0], k)
    first = planner.parse_question(text, k)
    out_c = (plan.get("outcome") or {}).get("concept")
    exp_c = (plan.get("exposure") or {}).get("concept")
    in_study = {out_c, exp_c} | set(plan.get("covariates") or [])
    current = {out_c, exp_c}
    alts = [a for a in close_questions(text, k, limit=4)
            if {(p := planner.parse_question(a["question"], k)).get("outcome_concept"), p.get("exposure_concept")} != current][:3]
    gaps = []
    for t in missing_topics(first, k):
        gaps.append({"text": t, "status": "not_in_nhanes", "alternatives": alts,
                     "note": f"\"{t}\" is not in this study: none of the {len(k.dictionary):,} official NHANES variables mention it, "
                             "so it cannot be measured. Q2E does not swap in a different measure without asking."})
    for c in (first.get("outcome_concept"), first.get("exposure_concept")):
        if c and c not in in_study and not c.startswith("dict:"):
            gaps.append({"text": _label(c, k), "status": "not_used", "alternatives": [],
                         "note": f"{_label(c, k)} was in your idea but is not in this study (it was changed during set-up). "
                                 "Ask below to put it back."})
    vg = vague_group(text)
    user_ages = any(c.get("source") == "question (age range)" for c in plan.get("population", []))
    if vg and not user_ages:
        word, _, bands = vg
        used = "; ".join(c["label"] for c in plan.get("population", []) if c.get("kind") == "inclusion" and c.get("enabled", True)) or "everyone"
        floor, by = measured_from_age(plan, k)
        gaps.append({"text": word, "status": "assumed",
                     "alternatives": [{"question": o["append"].strip(), "label": o["label"], "why": o["hint"]}
                                      for o in age_band_options(bands, floor, by)],
                     "note": f"You said \"{word}\", which can mean different ages. The study currently uses: {used}. "
                             "You have not confirmed this - pick the ages you mean below."})
    if (first.get("association_cue") or len(missing_topics(first, k)) + len([c for c in (first.get("outcome_concept"), first.get("exposure_concept")) if c]) >= 2) \
            and plan.get("study_type") == "prevalence" and gaps:
        gaps.append({"text": "kind of study", "status": "changed", "alternatives": [],
                     "note": f"Your idea asks whether two things are related, but this study only estimates how common "
                             f"{_label(out_c, k).lower()} is, because the other half of the question is not in NHANES."})
    return gaps


def close_questions(question: str, k: Knowledge | None = None, limit: int = 4) -> list[dict]:
    """Full questions NHANES CAN answer that stay as close as possible to one it cannot: keep the topic that was
    understood and swap the missing one for the nearest thing NHANES measures. Every suggestion is re-read by the
    parser and kept only if it maps to exactly those two topics, so nothing is invented."""
    k = k or get_knowledge()
    parsed = planner.parse_question(question, k)
    out_c, exp_c = parsed.get("outcome_concept"), parsed.get("exposure_concept")
    if out_c and exp_c:
        return []
    anchor = out_c or exp_c
    if not anchor or anchor.startswith("dict:"):
        return []
    pops = POP_WORDS.findall(question)
    pop = pops[-1].lower() if pops else _population_phrase(parsed, k)
    pop = {"teenagers": "adolescents", "teens": "adolescents", "elderly": "older adults", "seniors": "older adults"}.get(pop, pop)
    anchor_words = {w for s in k.concepts[anchor]["synonyms"] + [k.concepts[anchor]["label"]] for w in re.findall(r"[a-z]+", s.lower())}
    words = [w for w in re.findall(r"[a-z]+", question.lower()) if w not in anchor_words]   # "blood sugar" is the topic itself
    words = [w for w in words if w in PROXY_WORDS] + [w for w in words if w not in PROXY_WORDS]
    unclear = ", ".join(t for t in unclear_terms(parsed) if not POP_WORDS.search(t))
    cands: list[tuple[str, str]] = []                       # (concept id, the user's word it stands in for)
    for w in words:
        for cid in LAY_TERMS.get(w, []):
            if cid != anchor and cid in k.concepts and cid not in [c for c, _ in cands]:
                cands.append((cid, w))
    fallback = COMMON_EXPOSURES if out_c else DEFAULT_TOPICS
    for cid in fallback:
        if cid != anchor and cid in k.concepts and cid not in [c for c, _ in cands]:
            cands.append((cid, ""))
    a_lab = _label(anchor, k).lower()
    a_syn = k.concepts[anchor]["synonyms"][0]
    res = []
    for cid, w in cands:
        if frozenset((cid, anchor)) in SAME_THING:
            continue
        syn = k.concepts[cid]["synonyms"][0]
        q = f"Is {syn} associated with {a_syn} in {pop}?" if out_c else f"Is {a_syn} associated with {syn} in {pop}?"
        p = planner.parse_question(q, k)
        if {p.get("outcome_concept"), p.get("exposure_concept")} != {anchor, cid}:
            continue
        lab = _label(cid, k)
        if w and w in PROXY_WORDS:
            why = f"NHANES has no questions on '{w}'; {lab.lower()} is the closest thing it measures."
        elif w:
            why = f"NHANES measures {lab.lower()}, which matches '{w}' in your idea."
        else:
            why = (f"NHANES has no data on '{unclear}'. " if unclear else "") + \
                  f"{lab} is measured well in NHANES and often studied with {a_lab}."
        res.append({"question": q, "label": lab, "why": why})
        if len(res) >= limit:
            break
    return res


def not_measured(word: str, k: Knowledge) -> bool:
    """True only if no official NHANES variable label (CDC variable lists, all cycles) mentions the word."""
    pat = re.compile(r"\b" + re.escape(word.lower()))
    return not any(pat.search(str(r.get("label", "")).lower()) for r in k.dictionary.values())


# NHANES cycle letters used in CDC file names (e.g. OCQ_J = 2017-2018; P_ = 2017-March 2020 pre-pandemic)
CYCLE_YEARS = {"A": (1999, 2000), "B": (2001, 2002), "C": (2003, 2004), "D": (2005, 2006), "E": (2007, 2008),
               "F": (2009, 2010), "G": (2011, 2012), "H": (2013, 2014), "I": (2015, 2016), "J": (2017, 2018),
               "P": (2017, 2020), "L": (2021, 2023)}


def _years(var: str, k: Knowledge) -> str:
    """Survey years an NHANES variable was collected, e.g. '1999-2004' or '2017-2020'."""
    spans = [CYCLE_YEARS[c] for c in k.dictionary.get(var, {}).get("cycles", []) if c in CYCLE_YEARS]
    return f"{min(s[0] for s in spans)}-{max(s[1] for s in spans)}" if spans else ""


_LABEL_WORDS: dict[int, set[str]] = {}


def _label_words(k: Knowledge) -> set[str]:
    """Every word used in the official NHANES variable labels: real English, so not a typo."""
    if id(k) not in _LABEL_WORDS:
        _LABEL_WORDS[id(k)] = {w for r in k.dictionary.values() for w in re.findall(r"[a-z]+", str(r.get("label", "")).lower())}
    return _LABEL_WORDS[id(k)]


def fix_spelling(question: str, k: Knowledge) -> tuple[str, list[dict]]:
    """Correct misspelled health words, but only towards words in Q2E's NHANES vocabulary (never invents terms)."""
    vocab = {w for c in k.concepts.values() for s in c["synonyms"] + [c["label"].lower()]
             for w in re.findall(r"[a-z]+", s.lower()) if len(w) >= 5} | {w for w in LAY_TERMS if len(w) >= 5}
    real = _label_words(k)
    fixes = []

    def sub(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if len(lw) < 5 or lw in vocab or lw in FILLER_WORDS or lw in COMMON_WORDS or lw in real:
            return w      # a real word (used somewhere in NHANES wording) is never "corrected" into another one
        best = difflib.get_close_matches(lw, vocab, n=1, cutoff=0.86) or difflib.get_close_matches(lw, COMMON_WORDS, n=1, cutoff=0.83)
        if not best or best[0] in lw or lw in best[0]:
            return w      # no close word, or a longer/shorter form ("smokers", "inactivity" vs "activity")
        fixes.append({"from": w, "to": best[0]})
        return best[0]

    return re.sub(r"[A-Za-z]+", sub, question), fixes


def unclear_terms(parsed: dict) -> list[str]:
    """Unmapped phrases minus method words ("regression"), goals ("stop") and filler ("learn")."""
    out = []
    for ph in parsed.get("unmapped_terms") or []:
        words = [w for w in re.split(r"[\s\-]+", ph.lower()) if w and w not in FILLER_WORDS and w not in planner._STOP
                 and w not in planner._GENERIC and w not in planner._RESEARCH_WORDS and w not in ("too", "much", "lot")]
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


def term_suggestions(term: str, k: Knowledge, limit: int = 4) -> list[dict]:
    """Closest things NHANES has for an unknown word: official survey items that use the word itself (from the CDC
    variable lists), then everyday meanings and spelling-alike topics, then other text-search matches."""
    syn_to_concept = {s: c["id"] for c in k.concepts.values() for s in c["synonyms"] + [c["label"].lower()]}
    out, seen = [], set()

    def add_concept(cid: str):
        if cid in k.concepts and cid not in seen:
            seen.add(cid)
            syn = k.concepts[cid]["synonyms"][0]
            out.append({"id": f"c_{cid}", "label": _label(cid, k), "hint": _concept_hint(cid, k), "replace": syn})

    def add_var(hit: dict):
        v = hit["variable"]
        if v in seen:
            return
        seen.add(v)
        yrs = _years(v, k)
        lab = _plain_label(hit["label"]) or v
        if lab.lower() in seen:
            return      # the CDC repeats the same wording in several items; showing it twice looks like a bug
        seen.add(lab.lower())
        out.append({"id": f"v_{v}", "label": lab, "replace": lab.lower(),
                    "hint": f"Official NHANES survey item {v}{f', asked in {yrs}' if yrs else ''}: {_plain_label(hit['label'], full=True)}"})

    def latest(h: dict) -> int:
        return max((CYCLE_YEARS[c][1] for c in k.dictionary.get(h["variable"], {}).get("cycles", []) if c in CYCLE_YEARS), default=0)

    # most recent survey years first, so suggestions work with the cycles users usually pick
    hits = sorted((h for h in k.var_index().search(term, top_k=25) if h.get("confidence", 0) >= 0.6),
                  key=lambda h: (latest(h) < 2015, -h.get("confidence", 0), -latest(h)))
    words = [w for w in term.lower().split() if len(w) > 2]
    on_topic = [h for h in hits if any(re.search(r"\b" + re.escape(w), _plain_label(h["label"]).lower()) for w in words)]
    for h in on_topic[:2]:                           # official items whose wording contains the user's word
        add_var(h)
    for w in term.lower().split():
        for cid in LAY_TERMS.get(w, []):
            add_concept(cid)
    for s in difflib.get_close_matches(term.lower(), list(syn_to_concept), n=6, cutoff=0.72):
        add_concept(syn_to_concept[s])
    for h in on_topic[2:]:
        if len(out) < limit:
            add_var(h)
    return out[:limit]


def _plain_label(label: str, full: bool = False) -> str:
    """CDC wording uses placeholders like '{you/SP}' or '{work/works}': keep the first form ('you', 'work')."""
    text = re.sub(r"\{([^/}]*)(?:/[^}]*)?\}", r"\1", label)
    text = re.sub(r"\(SP Interview Version\)\s*|\(Family Interview Version\).*$", "", text).strip()
    if not full:
        parts = [p for p in re.split(r"(?<=[.?!])\s+", text.split("(")[0]) if p.strip()]
        text = next((p for p in reversed(parts) if p.rstrip().endswith("?")), parts[-1] if parts else text)
    return re.sub(r"\s+", " ", text).strip(" ?.")


def _any_hint(cid: str, k: Knowledge) -> str:
    """Explanation for a curated topic or a single NHANES survey item."""
    if cid.startswith("dict:"):
        return f"NHANES survey item {cid[5:]}: {_label(cid, k)}."
    return _concept_hint(cid, k)


def missed_topics(question: str, parsed: dict, k: Knowledge) -> list[str]:
    """Known health topics named in the idea that the parser did not keep (it holds at most two)."""
    kept = [c for c in (parsed.get("outcome_concept"), parsed.get("exposure_concept")) if c]
    kept_text = " ".join(_label(c, k).lower() + " " + " ".join(k.concepts.get(c, {}).get("synonyms", [])) for c in kept)
    unclear = {w for t in unclear_terms(parsed) for w in t.split()}    # these get their own "did you mean" question
    out = []
    for w in re.findall(r"[a-z]+", question.lower()):
        if w in PROXY_WORDS or w not in LAY_TERMS or w in kept_text or w in unclear:
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

    # (no health topic at all is handled by rewrite_help(): the user is sent back to retype the idea)

    # (a1) part of the idea is something NHANES never measured (e.g. cortisol) -> say so first and let the user decide
    gone = missing_topics(parsed, k) if bool(out_c) != bool(exp_c) else []
    if gone:
        names = " or ".join(f"\"{g}\"" for g in gone[:2])
        anchor = out_c or exp_c
        lbl = _label(anchor, k).lower()
        opts = [{"id": f"switch{i}", "label": a["question"], "hint": a["why"], "question": a["question"]}
                for i, a in enumerate(close_questions(question, k, limit=3))]
        opts.append({"id": "only", "label": f"Only study {lbl}, without {names}",
                     "hint": f"The study estimates how common {lbl} is, and the protocol states that {names} was not studied.",
                     "append": " Estimate the prevalence."})
        qs.append(_question("missing", level, {
            "novice": f"NHANES never measured {names}, so it cannot be part of the study. What would you like to do instead?",
            "intermediate": f"{names} is not measured in NHANES. How should the question be reframed?",
            "expert": f"{names}: no NHANES variable. Reframe?"}, {
            "novice": f"None of the {len(k.dictionary):,} official NHANES variables mention {names}. Q2E will not quietly use something "
                      f"else in its place, so you choose: a close question that keeps {lbl} and uses something NHANES does measure, "
                      f"or a study of {lbl} on its own.",
            "intermediate": f"No CDC variable mentions {names}. Choose a measured substitute topic or a descriptive study of {lbl}.",
            "expert": "Construct not measured; substitute or descriptive estimand."},
            opts, {"placeholder": f"Or type another factor to compare with {lbl}", "template": " Is it associated with {text}?"}))

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
            [{"id": f"o_{c}", "label": _label(c, k), "hint": _any_hint(c, k),
              "fixes": [] if c == out_c else [{"op": "set_outcome", "concept": c}]}
             for c in cands[:5]]))

    # (a3) a topic was matched to a single survey item by text search (less certain) -> confirm it
    for role, cid in (("outcome", out_c), ("exposure", exp_c)):
        if missed or not cid or not cid.startswith("dict:"):
            continue
        item = _label(cid, k)
        alts = [s for s in term_suggestions(item, k) if s["id"].startswith("c_")][:3]
        opts = [{"id": "keep", "label": f"Yes: {item}", "hint": _any_hint(cid, k)}]
        opts += [{"id": s["id"], "label": s["label"], "hint": s["hint"],
                  "fixes": [{"op": "set_outcome" if role == "outcome" else "set_exposure", "concept": s["id"][2:]}]}
                 for s in alts]
        qs.append(_question(f"check_{role}", level, {
            "novice": f"We matched part of your idea to this survey question: \"{item}\". Is that what you meant?",
            "intermediate": f"Your {'outcome' if role == 'outcome' else 'exposure'} was matched to the NHANES item \"{item}\". Correct?",
            "expert": f"{role.capitalize()} mapped by text search to {cid[5:]} ({item}). Confirm?"}, {
            "novice": "This match came from searching the survey's wording, so we want to be sure it is right before using it.",
            "intermediate": "Text-search matches are less certain than named health topics.",
            "expert": "Low-specificity mapping; confirm or select a curated concept."},
            opts + [{"id": "edit", "label": "None of these", "hint": "Close this panel with \"Edit my idea\" and describe it in other words."}]))
        qs[-1]["blocking_option"] = "edit"

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
        missing = f"\"{ph}\"" if all(not_measured(w, k) for w in ph.split()) else None
        if missing:
            text = {"novice": f"No NHANES question mentions {missing}. Which of these, which NHANES did measure, is closest to what you mean?",
                    "intermediate": f"No NHANES variable mentions {missing}. Closest measured proxy?",
                    "expert": f"No NHANES variable mentions {missing}. Proxy?"}
            why = {"novice": "Q2E only uses things NHANES actually measured, so it will not pretend these are the same as "
                             f"{missing}. Pick the closest one, or leave it out.",
                   "intermediate": f"These are proxies, not measures of {missing}; results must be read that way.",
                   "expert": "Proxy choice affects construct validity; state it as a limitation."}
        elif any(o["id"].startswith("v_") and ph.split()[0] in o["hint"].lower() for o in sugg):
            text = {"novice": f"NHANES asked people about \"{ph}\" in a few different ways. Which is closest to what you mean?",
                    "intermediate": f"\"{ph}\" matches several official NHANES items. Which one?",
                    "expert": f"\"{ph}\": candidate NHANES items / concepts?"}
            why = {"novice": "These are the survey's own questions (with the years they were asked) or close health topics. "
                             "Pick the one that fits, or leave it out.",
                   "intermediate": "Official CDC variables; check the survey years match the cycles you study.",
                   "expert": "Uncurated catalog items need codebook review before approval."}
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
    if out_c and not exp_c and not has_prev_cue and not goal and i == 0 and not gone:
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

    # (e0) a group word without exact ages ("children", "seniors", "older people") -> ask which ages, never assume
    has_ages = any(a is not None for a in (parsed.get("age_range") or (None, None)))
    vg = None if has_ages else vague_group(question)
    if vg:
        word, kind, bands = vg
        floor, by = measured_from_age(plan, k)
        opts = age_band_options(bands, floor, by)
        if opts and all(o["moved"] for o in opts):
            qs.append(_question("ages", level, {
                "novice": f"NHANES only asked about {by.lower()} from age {floor}, so most \"{word}\" were never asked. "
                          "Which ages should we study?",
                "intermediate": f"{by} is only collected from age {floor}, which excludes most \"{word}\". Which ages?",
                "expert": f"{by}: age >= {floor}; \"{word}\" only partly covered. Bounds?"}, {
                "novice": "Q2E will not pretend the younger ones were measured. You can study the older part of the group, "
                          "or go back and pick a topic NHANES measured at younger ages.",
                "intermediate": "Younger participants have the measure missing by design.",
                "expert": "Missing by design below the component's minimum age."},
                opts, {"placeholder": "Or type the exact ages", "template": " Study people aged {text}."}))
        elif opts:
            qs.append(_question("ages", level, {
                "novice": f"You said \"{word}\". Which ages do you mean exactly?",
                "intermediate": f"\"{word}\" can mean different age ranges. Which one?",
                "expert": f"Age bounds for \"{word}\"?"}, {
                "novice": f"People use \"{word}\" for different age ranges, and the result depends on who is counted, "
                          "so Q2E asks instead of guessing. Pick one or type the exact ages.",
                "intermediate": "Studies define this group differently; the age bounds change the estimate and its comparability.",
                "expert": "Explicit age bounds are required for the analytic domain."},
                opts, {"placeholder": "Or type the exact ages, e.g. 8 to 15, or 70 and older", "template": " Study people aged {text}."}))
        else:
            qs.append(_question("ages", level, {
                "novice": f"NHANES does not measure your topic in \"{word}\". Which group should we study instead?",
                "intermediate": f"The study's measures are not collected in \"{word}\". Alternative group?",
                "expert": f"Measures unavailable for \"{word}\". Alternative domain?"}, {
                "novice": f"In NHANES, {by.lower()} is only collected from age {floor}.",
                "intermediate": f"{by} is only collected from age {floor}.", "expert": f"{by}: age >= {floor}."},
                age_band_options([(floor, None, f"Everyone aged {floor} and older")], floor, by),
                {"placeholder": "Or type the exact ages", "template": " Study people aged {text}."}))

    # (e) who is being studied? (asked at every level when the idea does not say)
    if not vg and not parsed.get("populations") and not has_ages:
        opts, floor, by = population_options(plan, out_c, exp_c, k)
        if len(opts) > 2:
            measured = f"{by} is only collected from age {floor}" if floor else ""
            qs.append(_question("population", level, {
                "novice": "Which group of people do you want to learn about?",
                "intermediate": "Which population should be included?",
                "expert": "Target population / age restriction?"}, {
                "novice": "Results can differ a lot between groups. " + (f"In NHANES, {measured.lower()}, so only groups where it was "
                          "measured are offered." if floor else "These are the groups NHANES measured your topics in."),
                "intermediate": "Sets the inclusion criteria. " + (f"{measured}; younger groups are not offered." if floor else ""),
                "expert": "Analytic domain. " + (f"{measured}." if floor else "")}, opts))

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
    if out_c and not out_c.startswith("dict:") and not parsed.get("hints", {}).get("matched"):
        defs = [d for d in k.concepts.get(out_c, {}).get("definitions", []) if d in k.definitions]
        if len(defs) > 1:
            opts = [{"id": d, "label": k.definitions[d].get("label", d),
                     "hint": str(k.definitions[d].get("short") or k.definitions[d].get("criteria_text") or "")[:160],
                     "fixes": [{"op": "set_definition", "role": "outcome", "value": d, "concept": out_c}]} for d in defs[:4]]
            opts.append({"id": "auto", "label": "Use the default definition" if level != "novice" else "Let Q2E choose",
                         "hint": "Q2E's standard choice for this topic."})
            qs.append(_question("definition", level, {
                "novice": f"Doctors' guidelines draw the line for {_label(out_c, k).lower()} in different places. Which one should we use?",
                "intermediate": f"Several guideline definitions exist for {_label(out_c, k).lower()}. Which one?",
                "expert": f"Case definition for {_label(out_c, k).lower()}?"            }, {
                "novice": "Each guideline uses a different cut-off number, which changes who is counted as having it - and so the result.",
                "intermediate": "Different guidelines use different cut-offs, which changes who counts as a case.",
                "expert": "Affects case ascertainment and comparability with published estimates."}, opts))

    # (h) association: compare people at similar body weight?
    if plan and plan.get("exposure") and not parsed.get("adjust_bmi") and "bmi" not in plan.get("covariates", []) \
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

    # (i) effect measure for a binary outcome (a method choice, not something a beginner's idea leaves unclear)
    if level != "novice" and plan and plan.get("exposure") and plan["outcome"].get("type") == "binary" \
            and not re.search(r"\b(?:prevalence|odds|risk) ratios?\b", q):
        qs.append(_question("estimand", level, {"intermediate": "Report the result as a prevalence ratio or an odds ratio?",
                                                "expert": "Effect measure for the binary outcome?"},
                            {"intermediate": "Both compare groups; prevalence ratios are easier to read when the condition is common.",
                             "expert": "PRs are preferred for common outcomes in cross-sectional data."},
                            [{"id": "pr", "label": "Prevalence ratio", "hint": "Quasi-Poisson, log link (default)."},
                             {"id": "or", "label": "Odds ratio", "hint": "Quasi-binomial, logit link.",
                              "fixes": [{"op": "set", "path": "model.family", "value": "quasibinomial"}]}]))

    # questions that resolve something ambiguous are never cut; optional method questions go first
    must = {"missing", "ages", "focus", "check_outcome", "check_exposure", "population"}
    while len(qs) > MAX_QUESTIONS:
        drop = next((j for j in range(len(qs) - 1, -1, -1) if qs[j]["id"] not in must and not qs[j]["id"].startswith("term")), len(qs) - 1)
        qs.pop(drop)
    return qs


# Group words that do not say which ages are meant. Q2E never guesses: it asks, offering the age ranges commonly
# used for that word (each one only if NHANES measures the study's topics at those ages), or exact ages typed in.
VAGUE_GROUPS = [
    (re.compile(r"\b(?:kids?|children|child|youths?|young people|minors|pediatric|paediatric)\b", re.I), "children",
     [(2, 5, "Young children"), (6, 11, "School-age children"), (12, 17, "Teenagers"), (2, 17, "All children and teenagers")]),
    (re.compile(r"\b(?:teens?|teenagers?|adolescents?|adolescence)\b", re.I), "teenagers",
     [(12, 17, "Under 18 only"), (13, 19, "Ages 13 to 19 (the 'teen' years)"), (12, 19, "Ages 12 to 19 (common in NHANES reports)")]),
    (re.compile(r"\byoung adults?\b", re.I), "young adults",
     [(18, 25, "Late teens to mid-twenties"), (18, 29, "Under 30"), (18, 39, "Under 40")]),
    (re.compile(r"\bmiddle[- ]aged?\b", re.I), "middle-aged",
     [(40, 59, "Forties and fifties"), (45, 64, "45 to 64"), (40, 64, "40 to 64")]),
    (re.compile(r"\b(?:older (?:people|adults?|persons?|americans|individuals|men|women|population)|old(?:er)? age|old people|elderly|"
                r"seniors?|senior citizens?|aged people|the aged|retirees|geriatric)\b", re.I), "older people",
     [(60, None, "60 and older"), (65, None, "65 and older (most common in US studies)"), (75, None, "75 and older")]),
]


def vague_group(question: str) -> tuple[str, str, list] | None:
    """(word the user wrote, kind of group, candidate age bands) for the first group word with no exact ages."""
    for pat, kind, bands in VAGUE_GROUPS:
        m = pat.search(question)
        if m:
            return m.group(0), kind, bands
    return None


def age_band_options(bands: list, floor: int, by: str) -> list[dict]:
    opts = []
    for lo, hi, label in bands:
        lo2 = max(lo, floor)
        if hi is not None and lo2 > hi:
            continue
        span = f"{lo2} to {hi}" if hi is not None else f"{lo2} and older"
        if any(o["append"] == f" Study people aged {span}." for o in opts):
            continue
        hint = label + "." if lo2 == lo else f"The part of '{label.split('(')[0].strip().lower()}' that NHANES measured ({by.lower()} starts at age {floor})."
        opts.append({"id": f"age_{lo2}_{hi or 'up'}", "label": f"Age {span}", "hint": hint,
                     "append": f" Study people aged {span}.", "moved": lo2 != lo})
    return opts


CONDITION_GROUPS = {"diabetes": "diabetes", "ckd": "ckd", "hypertension": "htn_pop"}   # concept -> population id
WOMEN_DOMAINS = {"iron", "hematology"}


def measured_from_age(plan: dict | None, k: Knowledge) -> tuple[int, str]:
    """Youngest age at which every main measure of the study is collected in NHANES, and the measure that sets it."""
    from .answerability import MIN_AGE, VAR_MIN_AGE
    if not plan:
        return 0, ""
    roles = [plan["outcome"]] + ([plan["exposure"]] if plan.get("exposure") else [])
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    floor, by = 0, ""
    for r in roles:
        n = r["variable"]
        for raw in planner._raw_dependencies(n, k, custom):
            a = max(MIN_AGE.get(k.dictionary.get(raw, {}).get("file", ""), 0), VAR_MIN_AGE.get(raw, 0))
            if a > floor:
                lab = r.get("label") or k.label(n)
                floor, by = a, (lab if lab != n else k.dictionary.get(raw, {}).get("label", n))
    return floor, by


def population_options(plan: dict | None, out_c: str | None, exp_c: str | None, k: Knowledge) -> tuple[list[dict], int, str]:
    """Groups to offer for *this* study: age bands where its measures exist, plus groups that matter for its topic."""
    floor, by = measured_from_age(plan, k)
    note = f" ({by} starts at age {floor})" if floor else ""
    opts: list[dict] = []

    def band(oid: str, label: str, lo: int, hi: int | None, std: str | None = None):
        lo2 = max(lo, floor)
        if hi is not None and lo2 > hi:
            return
        span = f"{lo2} to {hi}" if hi is not None else f"{lo2} and older"
        moved = lo2 != lo
        opts.append({"id": oid, "label": label if not moved else f"{label} ({lo2}+)" if hi is None else f"{label} ({span})",
                     "hint": f"Age {span}." + (note if moved else ""),
                     "append": std if std and not moved else f" Study people aged {span}."})

    band("adults", "Adults", 18, None, " Study adults.")
    band("older", "Older adults", 65, None, " Study older adults.")
    band("teens", "Teenagers", 12, 17)
    band("children", "Children and teens", 1, 17, " Study children.")
    if floor >= 12:
        opts = [o for o in opts if o["id"] != "children"]
    domains = {k.concepts.get(c, {}).get("domain") for c in (out_c, exp_c) if c}
    if domains & WOMEN_DOMAINS and floor <= 18:
        opts.append({"id": "women", "label": "Women of reproductive age", "hint": "Women aged 18 to 49 (iron needs and blood counts differ in this group).",
                     "append": " Study women of reproductive age."})
    related = {c for d in domains if d for c in RELATED_FACTORS.get(d, [])}
    for cid, pid in CONDITION_GROUPS.items():
        if cid in related and cid not in (out_c, exp_c) and cid in k.concepts and len(opts) < 6:
            lab = k.concepts[cid]["label"].lower()
            opts.append({"id": f"with_{cid}", "label": f"Adults with {lab}", "hint": f"Only people who have {lab}, a group often studied for this topic.",
                         "append": f" Study adults with {k.concepts[cid]['synonyms'][0]}."})
    default = "; ".join(c["label"] for c in (plan or {}).get("population", []) if c.get("kind") == "inclusion") or "adults (18 and older)"
    opts.append({"id": "auto", "label": "Let Q2E choose", "hint": f"Q2E would use: {default}."})
    return opts, floor, by


def personal_notice(question: str) -> str:
    """Plain note when someone describes their own health ("I have ...")."""
    if PERSONAL_PATTERN.search(question.lower()):
        return ("Q2E looks for patterns across thousands of people in a national US health survey (NHANES). "
                "It cannot give personal medical advice - for your own health, please talk to a doctor. "
                "Below, we turn your idea into a research question about people like you.")
    return ""


def ai_questions(question: str, cycles: list[str] | None = None, level: str | None = None,
                 provider: str | None = None) -> dict[str, Any]:
    """Only the AI interviewer's extra questions (the page shows the rule-based ones first, then adds these)."""
    from . import ai_interview
    info = clarify(question, cycles, level, provider, use_ai=False)
    if info["needs_rewrite"]:
        return {"questions": [], "note": None}
    qs, note = ai_interview.suggest(info["question_used"], info["understood"], info["questions"], get_knowledge(), provider)
    return {"questions": qs, "note": note}


def clarify(question: str, cycles: list[str] | None = None, level: str | None = None,
            provider: str | None = None, use_ai: bool = True) -> dict[str, Any]:
    """Main entry point for the API: detect the level (unless overridden) and build questions.
    Rule-based questions come first; the AI interviewer (when an LLM is configured) may add checked ones after them."""
    from . import ai_interview
    from .llm import LLMClient
    k = get_knowledge()
    clean, _ = privacy.scrub(question)
    clean, spelling = fix_spelling(clean, k)
    parsed = planner.parse_question(clean, k)
    ex = assess_expertise(clean, parsed, k)
    used = level if level in LEVELS else ex["level"]
    qs = build_questions(clean, used, parsed, cycles, k)
    rewrite = None
    no_match = [t for t in unclear_terms(parsed) if not term_suggestions(t, k)]
    if not parsed.get("outcome_concept") and not parsed.get("hard_stop") \
            and (no_match or not any(q["id"].startswith("term") for q in qs)):
        rewrite, qs = rewrite_help(clean, parsed, k), []
    read = understood(clean, parsed, spelling, qs, k)
    ai_note = None
    if use_ai and not rewrite and not parsed.get("hard_stop"):
        extra, ai_note = ai_interview.suggest(clean, read, qs, k, provider)
        qs = qs + extra
    st = LLMClient(provider).status()
    return {"expertise": ex, "level_used": used, "notice": personal_notice(clean), "question_used": clean,
            "understood": read, "questions": qs, "needs_rewrite": rewrite,
            "ai": {"enabled": st["enabled"], "provider": st["provider"], "model": st["model"], "note": ai_note}}


DOMAIN_NAMES = {
    "anthropometry": "Body size", "behaviour": "Habits (smoking, alcohol, sleep, activity)", "cardio": "Heart, blood pressure & cholesterol",
    "demographic": "Age, income & background", "environment": "Environment", "function": "Daily functioning",
    "glycemia": "Blood sugar & diabetes", "hematology": "Blood counts", "inflammation": "Inflammation", "iron": "Iron",
    "kidney": "Kidneys", "liver": "Liver", "mental_health": "Mood & mental health", "nutrition": "Diet & nutrition",
    "respiratory": "Lungs & breathing", "social": "Social factors", "default": "Other",
}
DEFAULT_TOPICS = ["hypertension", "diabetes", "total_cholesterol", "short_sleep", "depression", "obesity"]


def _population_phrase(parsed: dict, k: Knowledge) -> str:
    """The group of people the user named, worded so the parser reads it back the same way."""
    lo, hi = parsed.get("age_range") or (None, None)
    if lo is not None and hi is not None:
        return f"people aged {lo} to {hi}"
    if lo is not None:
        return f"people aged {lo} and older"
    if hi is not None:
        return f"people aged {hi} and under"
    pops = {p["id"]: p for p in k.populations}
    for pid in parsed.get("populations") or []:
        if pid in pops and pops[pid].get("patterns"):
            p = pops[pid]["patterns"][0]
            return f"people {p}" if p.startswith("with ") else p
    return "US adults"


def rewrite_help(question: str, parsed: dict, k: Knowledge) -> dict:
    """No health topic NHANES measures was found: explain why and offer rewrites that are checked to work."""
    missing = [t for t in unclear_terms(parsed) if not term_suggestions(t, k)]
    words = re.findall(r"[a-z]+", question.lower())
    related: list[str] = []
    # closest measured topic for each word in the idea first (work -> sitting, stress -> depression), then the rest
    for rank in range(3):
        for w in words:
            cands = [c for c in LAY_TERMS.get(w, []) if c in k.concepts]
            if rank < len(cands) and cands[rank] not in related:
                related.append(cands[rank])
    for cid in DEFAULT_TOPICS:
        if len(related) >= 6:
            break
        if cid in k.concepts and cid not in related:
            related.append(cid)
    syn = {c: k.concepts[c]["synonyms"][0] for c in related}
    group = {}                      # concept -> the word in the idea it came from (two stand-ins for one word are not a pair)
    for w in words:
        for c in LAY_TERMS.get(w, []):
            group.setdefault(c, w)
    pop = _population_phrase(parsed, k)
    hi = (parsed.get("age_range") or (None, None))[1]

    # example rewrites built from this idea's own words and group of people; each is kept only if Q2E's parser
    # reads it and NHANES measures both topics at the ages asked about
    candidates = []
    own = [c for c in related if c in group]
    others = [c for c in related if c not in own]
    for a in own or related[:1]:
        for b in [c for c in related if c != a and (group.get(c) is None or group.get(c) != group.get(a))] + others:
            candidates.append(f"Is {syn[a]} linked to {syn[b]} in {pop}?")
    candidates += [f"How common is {syn[c]} among {pop}?" for c in own + others]
    examples = []
    for text in dict.fromkeys(candidates):
        p = planner.parse_question(text, k)
        if not p.get("outcome_concept") or p.get("hard_stop"):
            continue
        if hi is not None and measured_from_age(_draft_plan(text, p, None, k), k)[0] > hi:
            continue
        examples.append(text)
        if len(examples) == 3:
            break

    by_domain: dict[str, list[dict]] = {}
    for c in sorted(k.concepts.values(), key=lambda c: c["label"].lower()):
        by_domain.setdefault(DOMAIN_NAMES.get(c.get("domain") or "default", "Other"), []).append(
            {"label": c["label"], "use": c["synonyms"][0], "hint": _concept_hint(c["id"], k)})

    shown = ", ".join(f"\"{t}\"" for t in missing[:3])
    return {
        "missing": missing[:3],
        "what_happened": (f"You asked about {shown}, but none of the {len(k.dictionary):,} official variables in the national "
                          f"survey Q2E uses (NHANES) mention {'it' if len(missing) == 1 else 'them'}, so there is nothing to "
                          f"study yet. (If NHANES uses a different name for it, try that name.)") if missing else
                         "We could not find a health condition or measurement in your idea, so there is nothing to study yet.",
        "what_to_do": "Rewrite your idea around something NHANES did measure. Click an example below to use it, "
                      "or swap in one of the closest topics.",
        "examples": examples,
        "related": [{"label": _label(c, k), "use": syn[c], "hint": _concept_hint(c, k)} for c in related],
        "all_topics": [{"group": g, "topics": t} for g, t in sorted(by_domain.items())],
    }


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
                  cycles: list[str] | None = None, provider: str | None = None, use_ai: bool = True) -> dict[str, Any]:
    """answers = {question_id: {"option": option_id, "text": free text}}.

    Returns {question: refined text, fixes: [planner.apply_fix ops], record: what was asked and answered}."""
    info = clarify(question, cycles, level, provider, use_ai=use_ai)
    refined, fixes, record = info["question_used"].rstrip(), [], []
    if refined and refined[-1] not in ".?!":
        refined += "."      # so each answer is added as its own sentence
    for q in info["questions"]:
        a = answers.get(q["id"]) or {}
        opt = next((o for o in q["options"] if o["id"] == a.get("option")), None)
        text = privacy.scrub(str(a.get("text") or ""))[0].strip()[:120]
        ft = q.get("free_text") or {}
        if opt and opt.get("question"):
            refined = opt["question"]       # the user picked a close question NHANES can answer instead
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
            record.append({"id": q["id"], "question": q["text"], "answer": (opt or {}).get("label", "") + (f" {text}" if text else ""),
                           "source": q.get("source", "rules")})
    return {"question": refined.strip(), "fixes": fixes, "record": record,
            "expertise": info["expertise"], "level_used": info["level_used"], "understood": info["understood"]}


def _set_role(plan: dict, role: str, cid: str | None, k: Knowledge) -> dict:
    """Put another topic in the outcome or exposure role and rebuild the plan (like the planner's swap_roles)."""
    parsed = dict(plan.get("parsed") or {})
    if not cid or not (cid in k.concepts or cid.startswith("dict:")) or not parsed:
        return plan
    old_out, old_exp = parsed.get("outcome_concept"), parsed.get("exposure_concept")
    if role == "outcome":
        if cid == old_out:
            return plan
        parsed["outcome_concept"] = cid
        parsed["exposure_concept"] = old_exp if old_exp and old_exp != cid else old_out   # the other topic stays in
    else:
        if cid == old_exp or cid == old_out:
            return plan
        parsed["exposure_concept"] = cid
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
    order = {"set_outcome": 0, "set_exposure": 0, "swap_roles": 1}
    for f in sorted(fixes, key=lambda f: order.get(f.get("op"), 2)):
        if f.get("op") in ("set_outcome", "set_exposure"):
            plan = _set_role(plan, f["op"][4:], f.get("concept"), k)
            continue
        if f.get("op") == "set_definition" and plan.get("outcome", {}).get("concept") != f.get("concept"):
            continue   # the outcome changed (e.g. after a swap); this definition no longer applies
        plan = planner.apply_fix(plan, {key: v for key, v in f.items() if key != "concept"}, k)
    for key, v in keep.items():
        plan.setdefault(key, v)
    return plan
