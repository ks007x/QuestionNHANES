"""Which quantity a question asks for, beyond 'prevalence' and 'association':

* age-adjusted (directly age-standardized) prevalence or mean - NCHS's convention for comparing groups or
  survey periods whose age structures differ;
* trends across survey cycles (per-cycle estimates plus a test for linear trend);
* descriptive means, medians and percentiles of a measurement;
* population counts ("how many Americans").

Standard population: 2000 projected U.S. population, NCHS age groups (NHANES tutorials, "Age-Adjusted
Prevalence Rates and Means": 20-39 77,670; 40-59 72,816; 60+ 45,364 thousand). The 18-19 slice (8,000
thousand) reproduces the 18-39 / 40-59 / 60+ proportions NCHS uses for adults 18+ (0.420263, 0.357202, 0.222535).
"""
from __future__ import annotations

import re
from typing import Any

STANDARD_LABEL = "2000 projected U.S. population (NCHS age groups)"
# thousands; contiguous slices that can be combined into the NCHS age groups
_SLICES = [(18, 19, 8000), (20, 39, 77670), (40, 59, 72816), (60, 74, None), (60, None, 45364)]
CYCLE_YEARS = {"A": (1999, 2000), "B": (2001, 2002), "C": (2003, 2004), "D": (2005, 2006), "E": (2007, 2008),
               "F": (2009, 2010), "G": (2011, 2012), "H": (2013, 2014), "I": (2015, 2016), "J": (2017, 2018),
               "P": (2017, 2020), "L": (2021, 2023)}
TREND_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "L"]      # 2-year cycles; P overlaps J

AGE_ADJ_CUES = re.compile(r"age[- ]?(adjusted|standardi[sz]ed|standardi[sz]ation|adjustment)|adjusted for age differences|direct(ly)? standardi[sz]", re.I)
CRUDE_CUES = re.compile(r"\bcrude\b|unadjusted|not age[- ]adjusted", re.I)
TREND_CUES = re.compile(r"\btrends?\b|over time|changed?\b|changing|since (19|20)\d\d|from (19|20)\d\d\s*(to|through|until|-)\s*(19|20)\d\d|"
                        r"between (19|20)\d\d\s*and\s*(19|20)\d\d|across (survey )?cycles|over the (past|last) (\d+|two|three|several) (years|decades)|"
                        r"increas(e|ed|ing) over|decreas(e|ed|ing) over|rise in|decline in", re.I)
MEAN_CUES = re.compile(r"\b(average|mean|median|typical|distribution|percentiles?|quartiles?|reference values?|normal range)\b", re.I)
COUNT_CUES = re.compile(r"how many (people|persons|americans|adults|children|us adults|u\.s\. adults|individuals|men|women)|number of (people|americans|adults|persons)|"
                        r"\bmillions?\b", re.I)


def age_bands(lo: int | None, hi: int | None) -> list[dict] | None:
    """NCHS standard age groups covering [lo, hi]; None when the range cannot be standardized (children, a single
    age group, or a lower age that splits an NCHS group)."""
    lo = 18 if lo is None else lo
    if lo not in (18, 20, 40, 60) or (hi is not None and hi not in (39, 59)):
        return None
    bands = []
    if lo <= 39 and (hi is None or hi >= 39):
        bands.append({"lo": lo, "hi": 39, "label": f"{lo}-39", "population": 77670 + (8000 if lo == 18 else 0)})
    if lo <= 40 and (hi is None or hi >= 59):
        bands.append({"lo": 40, "hi": 59, "label": "40-59", "population": 72816})
    if hi is None:
        bands.append({"lo": 60, "hi": None, "label": "60+", "population": 45364})
    if len(bands) < 2:
        return None
    if lo == 18 and hi is None:        # NCHS's published proportions for adults 18+ (used in hypertension reports)
        for b, pr in zip(bands, (0.420263, 0.357202, 0.222535)):
            b["population"] = round(pr * 203852, 1)
    total = sum(b["population"] for b in bands)
    for b in bands:
        b["proportion"] = round(b["population"] / total, 6)
    return bands


def years_in(q: str) -> tuple[int | None, int | None]:
    ys = [int(y) for y in re.findall(r"\b((?:19|20)\d\d)\b", q)]
    if not ys:
        return None, None
    return min(ys), max(ys) if len(ys) > 1 else None


def trend_cycles(q: str, usable: set[str] | None = None) -> list[str]:
    """Two-year cycles for a trend question, limited to the years named in it."""
    y0, y1 = years_in(q)
    out = []
    for c in TREND_ORDER:
        a, b = CYCLE_YEARS[c]
        if y0 is not None and b < y0:
            continue
        if y1 is not None and a > y1:
            continue
        if usable is not None and c not in usable:
            continue
        out.append(c)
    return out


def detect(question: str, study_type: str, outcome_type: str | None) -> dict[str, Any]:
    q = question or ""
    return {
        "age_adjusted_requested": bool(AGE_ADJ_CUES.search(q)),
        "crude_requested": bool(CRUDE_CUES.search(q)),
        "trend": (bool(TREND_CUES.search(q)) or (len(cycles_named(q)) >= 2 and bool(re.search(
            r"differ|chang|compar|between|\bvs\.?\b|versus|increas|decreas|rise|declin", q, re.I)))) and study_type != "association",
        "percentile": (lambda m: float(m.group(1)) / 100 if m else None)(re.search(r"\b(\d{1,2}(?:\.\d)?)(?:st|nd|rd|th)\s+percentile", q, re.I)),
        "mean": bool(MEAN_CUES.search(q)) and outcome_type == "continuous",
        "median": bool(re.search(r"\bmedian\b", q, re.I)),
        "count": bool(COUNT_CUES.search(q)),
    }


def age_adjust_config(criteria: list[dict], study_type: str, requested: bool, trend: bool) -> dict:
    """Age-adjust descriptive adult estimates whenever the population spans NCHS age groups (as NCHS does for
    comparisons between groups and survey periods); the crude estimate stays the primary one unless the question
    asks for age-adjusted figures or a trend."""
    lo = hi = None
    for c in criteria:
        if not c.get("enabled", True) or c.get("kind") == "exclusion":
            continue
        m = re.fullmatch(r"age >= (\d+)(?: & age (<=|<) (\d+))?", c["expr"].replace("  ", " ").strip())
        if m:
            lo = int(m.group(1))
            hi = (int(m.group(3)) - (1 if m.group(2) == "<" else 0)) if m.group(3) else None
    if study_type == "association":
        return {"enabled": False, "reason": "Association models adjust for age as a covariate."}
    bands = age_bands(lo, hi)
    if not bands:
        why = ("children and adolescents are not age-adjusted in NCHS reports" if (lo is not None and lo < 18) else
               "the population covers a single NCHS age group" if lo is not None else "no adult age range")
        return {"enabled": False, "reason": f"Not age-adjusted: {why}.", "requested": requested}
    return {"enabled": True, "standard": STANDARD_LABEL, "bands": bands, "age_var": "age", "not_by": ["agecat", "age"],
            "primary": bool(requested or trend), "requested": requested}


# ---------------------------------------------------------------------------
# Group comparisons ("more common in women than men", "compare ... between Hispanic and non-Hispanic white")
# ---------------------------------------------------------------------------
COMPARE_CUES = re.compile(r"more common (in|among)|less common (in|among)|(higher|lower|greater) (in|among)|more likely|less likely|(higher|lower|greater|smaller) (rates?|prevalence|levels?|risk|proportion|"
                          r"percentage|share|burden)|\bcompar\w+|\bdiffer\w*|disparit\w*|gap between|\bthan\b|\bvs\.?\b|\bversus\b|"
                          r"by (sex|gender|race|ethnicity|race and (hispanic|ethnic)\w*|income|poverty|education)|"
                          r"(sex|gender|racial|ethnic|income|educational|socioeconomic) (difference|gap|disparit)", re.I)
_LEVELS = {
    "sex": [(r"\b(women|woman|females?|girls)\b", "Female"), (r"\b(men|man|males?|boys)\b", "Male"), (r"\b(sex|gender)\b", None)],
    "race_eth": [(r"\bnon-?\s?hispanic white|\bwhite\b", "Non-Hispanic White"), (r"\bnon-?\s?hispanic black|\bblack\b|african american", "Non-Hispanic Black"),
                 (r"\bnon-?\s?hispanic asian|\basian\b", "Non-Hispanic Asian"), (r"(?<!non-)(?<!non )\bhispanic\b|\blatino|\bmexican", "Hispanic"),
                 (r"\brac(e|ial)\b|\bethnic", None)],
    "agecat": [(r"\bolder (adults|people|americans|age groups?)|\belderly\b|\bseniors\b", "60+"), (r"\byounger (adults|people|americans)", "younger"),
               (r"\bby age( group)?\b|\bage groups?\b|\bwith age\b", None)],
    "pir_cat": [(r"\b(low|lower)[- ]income\b|\bpoverty\b|\bpoor\b", "<1.30"), (r"\b(high|higher)[- ]income\b", "3.50+"), (r"\bincome\b", None)],
    "educ": [(r"\bcollege (graduates?|degree)", "College graduate or above"), (r"\b(less than high school|no high school)", "Less than high school"),
             (r"\beducation", None)],
}
GROUP_RAW = {"agecat": {"RIDAGEYR"}, "sex": {"RIAGENDR"}, "race_eth": {"RIDRETH1", "RIDRETH3"}, "pir_cat": {"INDFMPIR"}, "educ": {"DMDEDUC2", "DMDEDUC3"}}


def detect_comparison(question: str) -> dict | None:
    q = " " + question.lower() + " "
    if not COMPARE_CUES.search(q):
        return None
    best = None
    for var, pats in _LEVELS.items():
        found, used = [], []
        for pat, lvl in pats:
            for m in re.finditer(pat, q):
                if any(a <= m.start() < b for a, b in used):
                    continue
                used.append((m.start(), m.end()))
                found.append((m.start(), lvl))
        if found:
            levels = [l for _, l in sorted(found) if l]
            levels = list(dict.fromkeys(levels))
            cand = {"group_var": var, "levels": levels, "hits": len(found)}
            if best is None or cand["hits"] > best["hits"]:
                best = cand
    if not best:
        return None
    lv = best["levels"]
    ref = None
    if best["group_var"] == "race_eth" and "Non-Hispanic White" in lv:
        ref = "Non-Hispanic White"
    elif len(lv) >= 2:
        ref = lv[1]
    level = next((l for l in lv if l != ref), None)
    return {"enabled": True, "group_var": best["group_var"], "levels": lv, "level": level, "reference": ref}


_AGE_SPANS = [
    (r"\b(\d{1,2})\s*(?:-|–|to|through)\s*(\d{1,2})\b(?!\s*(?:mg|g/|mmol|%|kg|cm))", "range"),
    (r"\b(\d{1,2})\s*(?:years?\s*(?:of age\s*|old\s*)?)?(?:and|or)\s*(?:older|over|above)\b", "min"),
    (r"\b(\d{1,2})\s*\+", "min"),
    (r"\b(?:over|older than|above|at least)\s+(?:age\s+)?(\d{1,2})\b", "min"),
    (r"\b(\d{1,2})\s*(?:years?\s*)?(?:and|or)\s*(?:under|younger|below)\b", "max_incl"),
    (r"\b(?:under|younger than|below)\s+(?:age\s+)?(\d{1,2})\b", "max"),
]


def age_groups(question: str) -> list[dict]:
    """Every age group a question names, in order: 'adults 60 and older than adults 20-39' -> [60+, 20-39]."""
    q = " " + question.lower() + " "
    found, used = [], []
    for pat, kind in _AGE_SPANS:
        for m in re.finditer(pat, q):
            if any(a < m.end() and m.start() < b for a, b in used):
                continue
            if kind == "range":
                lo, hi = int(m.group(1)), int(m.group(2))
                if hi <= lo:
                    continue
                g = {"lo": lo, "hi": hi, "label": f"{lo}-{hi}"}
            elif kind == "min":
                lo = int(m.group(1)); g = {"lo": lo, "hi": None, "label": f"{lo}+"}
            else:
                hi = int(m.group(1)) - (0 if kind == "max_incl" else 1); g = {"lo": None, "hi": hi, "label": f"<{hi + 1}"}
            used.append((m.start(), m.end()))
            found.append((m.start(), g))
    return [g for _, g in sorted(found, key=lambda t: t[0])]


def age_comparison(question: str) -> dict | None:
    """Two or more named age groups plus a comparison cue -> a comparison on a custom age-group variable."""
    if not COMPARE_CUES.search(" " + question.lower() + " "):
        return None
    groups = age_groups(question)
    labels = list(dict.fromkeys(g["label"] for g in groups))
    if len(labels) < 2:
        return None
    groups = [next(g for g in groups if g["label"] == l) for l in labels]
    parts = []
    for g in groups:
        cond = " & ".join(c for c in ((f"age >= {g['lo']}" if g["lo"] is not None else ""), (f"age <= {g['hi']}" if g["hi"] is not None else "")) if c)
        parts += [cond, f'"{g["label"]}"']
    lo = min((g["lo"] for g in groups if g["lo"] is not None), default=None)
    his = [g["hi"] for g in groups]
    hi = None if any(h is None for h in his) else max(his)
    return {"enabled": True, "group_var": "age_cmp", "levels": labels, "level": labels[0], "reference": labels[1],
            "label": "Age group", "age_range": (lo, hi),
            "custom": {"name": "age_cmp", "expr": "cases(" + ", ".join(parts) + ")", "type": "categorical",
                       "label": "Age group (" + " vs ".join(labels) + ")", "source": "rules"}}


def cycles_named(question: str) -> list[str]:
    """Survey cycles a question names explicitly ('in 2021-2023', 'NHANES 2017-2018', '2015 to 2018')."""
    out = []
    for a, b in re.findall(r"\b((?:19|20)\d\d)\s*(?:-|–|to|through)\s*((?:19|20)?\d\d)\b", question):
        a = int(a)
        b = int(b) if len(b) == 4 else int(str(a)[:2] + b)
        if b < a:
            continue
        hits = [c for c in TREND_ORDER if CYCLE_YEARS[c][0] >= a and CYCLE_YEARS[c][1] <= b + (1 if b == 2020 else 0)]
        if a == 2017 and b in (2020,):
            hits = ["P"]
        out += [c for c in hits if c not in out]
    return out
