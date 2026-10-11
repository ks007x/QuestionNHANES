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
        "trend": bool(TREND_CUES.search(q)) and study_type != "association",
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
