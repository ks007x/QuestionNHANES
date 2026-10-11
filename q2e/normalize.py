"""Question recognition: turn the way clinicians actually type into the terms the planner knows.

Two layers, both auditable:
  1. Rules (always on, offline): clinical abbreviations and variants ("type ii diabetes", "T2DM", "DM2", "HTN",
     "high BP", "w/o"), and conservative spelling correction ("diabetis" -> "diabetes") against the medical
     vocabulary in the knowledge base.
  2. Amazon Bedrock (when an AI provider is on): the Recognizer agent returns exact phrases from the question
     with their standard clinical names. Only phrases that occur verbatim in the question are applied, and only
     short plain-text names are accepted, so the model can relabel a phrase but cannot rewrite the question.

Every change is returned as {from, to, label, source, note} and shown to the investigator before approval.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

# (pattern, replacement understood by the planner, formal clinical name, note). Order matters: specific first.
_T2 = "Type 2 diabetes mellitus"
_NOTE_DM = ("NHANES does not separate diabetes types; NCHS estimates total diabetes, of which about 90-95% is type 2 "
            "(CDC National Diabetes Statistics Report).")
_RULES: list[tuple[str, str, str, str, int]] = [
    # diabetes
    (r"\b(?:type\s*-?\s*(?:ii|2|two)|t2)\s*(?:diabetes\s*mellitus|diabetes|dm)\b", "type 2 diabetes", _T2, _NOTE_DM, re.I),
    (r"\b(?:dm\s*-?\s*(?:type\s*)?(?:ii|2)|t2dm?|niddm)\b", "type 2 diabetes", _T2, _NOTE_DM, re.I),
    (r"\b(?:type\s*-?\s*(?:i|1|one)|t1)\s*(?:diabetes\s*mellitus|diabetes|dm)\b|\b(?:t1dm?|iddm|dm\s*-?\s*(?:type\s*)?(?:i|1))\b",
     "type 1 diabetes", "Type 1 diabetes mellitus",
     "NHANES cannot reliably identify type 1 diabetes; the plan will estimate total diabetes - review before approval.", re.I),
    (r"\bdiabetes\s+mellitus\b", "diabetes", "Diabetes mellitus", "", re.I),
    (r"\bpre-?\s*dm\b", "prediabetes", "Prediabetes", "", re.I),
    (r"\bDM\b", "diabetes", "Diabetes mellitus", "", 0),
    # blood pressure
    (r"\bHTN\b", "hypertension", "Hypertension", "", re.I),
    (r"\b(?:high|elevated|raised)\s+(?:bp|blood\s+pressures?)\b", "high blood pressure", "Hypertension", "", re.I),
    (r"\bSBP\b", "systolic blood pressure", "Systolic blood pressure", "", 0),
    (r"\bDBP\b", "diastolic blood pressure", "Diastolic blood pressure", "", 0),
    # lipids, heart, liver, kidney
    (r"\b(?:HLD|HLP)\b", "hyperlipidemia", "Hyperlipidemia", "", re.I),
    (r"\b(?:high|elevated)\s+(?:chol|cholesterol)\b", "high cholesterol", "High total cholesterol", "", re.I),
    (r"\b(?:CAD|CHD|ASCVD)\b", "coronary heart disease", "Coronary heart disease", "", 0),
    (r"\b(?:MI|AMI|STEMI|NSTEMI)\b", "heart attack", "Myocardial infarction", "", 0),
    (r"\b(?:CHF|HFrEF|HFpEF)\b", "heart failure", "Heart failure", "", 0),
    (r"\bCVA\b", "stroke", "Stroke", "", 0),
    (r"\b(?:MASLD|MAFLD|NAFLD|NASH|MASH)\b", "fatty liver", "Steatotic liver disease", "", re.I),
    (r"\bhep\.?\s*c\b", "hepatitis c", "Hepatitis C", "", re.I),
    (r"\b(?:ESRD|ESKD)\b", "chronic kidney disease", "Chronic kidney disease (kidney failure)",
     "NHANES excludes dialysis; end-stage disease is studied as CKD.", 0),
    (r"\bUACR\b", "urine albumin-to-creatinine ratio", "Urine albumin-to-creatinine ratio", "", 0),
    # blood counts and labs
    (r"\b(?:hgb|hb)\b", "hemoglobin", "Hemoglobin", "", re.I),
    (r"\b(?:plts?)\b", "platelets", "Platelet count", "", re.I),
    (r"\blow\s+platelets?\b", "thrombocytopenia", "Thrombocytopenia", "", re.I),
    (r"\b(?:ANC)\b", "neutrophil count", "Absolute neutrophil count", "", 0),
    (r"\b(?:vit\.?\s*d|25-?oh-?d)\b", "vitamin d", "Vitamin D (25-hydroxyvitamin D)", "", re.I),
    (r"\b(?:IDA)\b", "iron deficiency anemia", "Iron-deficiency anemia", "", 0),
    (r"\b(?:a1c)\b", "hba1c", "Hemoglobin A1c", "", re.I),
    # lung, sleep, mood
    (r"\bOSA\b", "obstructive sleep apnea", "Obstructive sleep apnea", "", 0),
    (r"\b(?:MDD)\b", "depression", "Depression", "", 0),
    # shorthand
    (r"\bw/o\b", "without", "", "", re.I),
    (r"\bw/(?=\s|\w)", "with ", "", "", re.I),
    (r"\b(?:h/o|hx\s+of)\b", "history of", "", "", re.I),
    (r"\b(?:y/?o|yrs?\s+old)\b", "years old", "", "", re.I),
    (r"\bpts\b", "patients", "", "", re.I),
]
_COMPILED = [(re.compile(p, f), rep, label, note) for p, rep, label, note, f in _RULES]

# words a question is made of besides medical terms - never "corrected"
_QUESTION_WORDS = """prevalence prevalent incidence common commonly associated association associations linked link related
relationship relation correlated correlation between among amongst adults adult children child adolescents adolescent
teenagers women woman men man male female males females older younger elderly seniors people persons participants
patients population united states american americans national nhanes survey surveys compared compare comparison versus
higher lower increase increased decrease decreased trend trends change changed changes over time years year aged ages
without with history having those whose which what does there more less than likely risk odds ratio mean average median
level levels concentration concentrations proportion percentage percent estimate estimates cycle cycles pandemic
before after during since until black white hispanic mexican asian race ethnicity income poverty education insurance
pregnant pregnancy weight obesity obese overweight""".split()


@lru_cache(maxsize=1)
def _vocab() -> tuple[frozenset, tuple]:
    """(all known words, medical words a typo may be corrected to)."""
    from .knowledge import get_knowledge
    k = get_knowledge()
    med: set[str] = set()
    for c in k.concepts.values():
        for s in [c.get("label", "")] + list(c.get("synonyms", [])):
            med.update(w for w in re.findall(r"[a-z]+", s.lower()) if len(w) >= 5)
    for p in k.populations:
        for s in p.get("patterns", []):
            med.update(w for w in re.findall(r"[a-z]+", s.lower()) if len(w) >= 5)
    for d in k.definitions.values():
        med.update(w for w in re.findall(r"[a-z]+", str(d.get("label", "")).lower()) if len(w) >= 5)
    known = set(med) | set(_QUESTION_WORDS)
    for row in k.dictionary.values():
        known.update(re.findall(r"[a-z]+", str(row.get("label", "")).lower()))
    return frozenset(known), tuple(sorted(med | {w for w in _QUESTION_WORDS if len(w) >= 6}))


def _one_edit(a: str, b: str) -> bool:
    """True when b is one insertion, deletion, substitution or adjacent swap away from a."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _spell(text: str, changes: list[dict]) -> str:
    known, targets = _vocab()

    def fix(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if len(lw) < 5 or not lw.isalpha() or lw in known:
            return w
        if any(lw.endswith(suf) and lw[: -len(suf)] in known for suf in ("s", "es", "ed", "d", "ing", "ly", "er", "ers", "al")):
            return w   # an inflection of a known word ("weighted", "adjusting"), not a typo
        cands = [t for t in targets if _one_edit(lw, t)]
        if not cands and len(lw) >= 7:
            cands = difflib.get_close_matches(lw, targets, n=4, cutoff=0.84)
        # typos keep the first letter and are not just a longer/shorter form of the same word
        cands = [c for c in cands if c[0] == lw[0] and not (lw.startswith(c) or c.startswith(lw))]
        if not cands:
            return w
        # a typo usually keeps the word's length ("diabetis" -> "diabetes", not "diabetics")
        score = lambda c: (abs(len(c) - len(lw)), -difflib.SequenceMatcher(None, lw, c).ratio(), c)
        cands.sort(key=score)
        a, b = cands[0], (cands[1] if len(cands) > 1 else None)
        if b and score(a)[:1] == score(b)[:1] and abs(score(a)[1] - score(b)[1]) < 0.02 and a[:6] != b[:6]:
            return w   # two equally close, unrelated words: do not guess
        changes.append({"from": w, "to": a, "label": a, "source": "rules", "note": "spelling"})
        return a

    return re.sub(r"[A-Za-z]+", fix, text)


def normalize(question: str) -> tuple[str, list[dict]]:
    """Rule layer. Returns (question the planner reads, list of changes)."""
    changes: list[dict] = []
    text = question
    for rx, rep, label, note in _COMPILED:
        def sub(m: re.Match, rep=rep, label=label, note=note) -> str:
            src = m.group(0)
            if src.strip().lower() == rep.strip().lower():
                return src
            if label:
                changes.append({"from": src.strip(), "to": rep.strip(), "label": label, "source": "rules", "note": note})
            return rep
        text = rx.sub(sub, text)
    text = _spell(text, changes)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # one entry per (from, to)
    seen, out = set(), []
    for c in changes:
        key = (c["from"].lower(), c["to"].lower())
        if key not in seen:
            seen.add(key)
            out.append(c)
    return text, out


_SAFE_TERM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,'()/+\-.]{0,59}$")


def apply_ai_terms(question: str, terms: list[dict] | None) -> tuple[str, list[dict]]:
    """Apply the Recognizer's {text, standard_term} pairs. A pair is used only when `text` occurs verbatim in the
    question and `standard_term` is a short plain clinical name - the model can relabel, never rewrite."""
    applied: list[dict] = []
    text = question
    for t in (terms if isinstance(terms, list) else [])[:8]:
        if not isinstance(t, dict):
            continue
        src = str(t.get("text") or "").strip()
        dst = str(t.get("standard_term") or "").strip()
        if not src or not dst or src.lower() == dst.lower() or not _SAFE_TERM.match(dst) or len(src) > 60:
            continue
        rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(src) + r"(?![A-Za-z0-9])", re.I)
        if not rx.search(text):
            continue
        text = rx.sub(dst.lower(), text, count=1)
        applied.append({"from": src, "to": dst.lower(), "label": str(t.get("label") or dst)[:80], "source": "ai",
                        "note": str(t.get("note") or "")[:200]})
    return text, applied
