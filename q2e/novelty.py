"""Novelty score from PubMed/MEDLINE - shown next to the feasibility score.

Transparent and conservative. It answers "has this NHANES question already been published?", not "is it important".

  exact precedent   NHANES/"National Health and Nutrition Examination Survey" + outcome synonyms (+ exposure synonyms)
                    in title/abstract, PubMed records (MEDLINE plus in-process and publisher-supplied citations, so the newest papers count), last 10 years
  broader topic     the same concepts in any data source (topic saturation)
  recent            exact precedent in the last 3 years (how actively it is being mined)
  levers            what this plan adds that prior NHANES papers probably did not: the newest survey cycle,
                    a 2025+ guideline definition, a prespecified effect-modification analysis

score = 90 * exp(-exact / 8)  (0 papers -> 90, 1 -> 79, 5 -> 48, 13 -> 18)  + levers (max +20), clipped to 5-100.
"""
from __future__ import annotations

import datetime as dt
import math

import httpx

from . import literature
from .knowledge import get_knowledge
from .venues import _synonyms

NHANES = '(NHANES[tiab] OR "National Health and Nutrition Examination Survey"[tiab])'


def _block(v: dict) -> str:
    return "(" + " OR ".join(f'"{t}"[tiab]' for t in _synonyms(v, 5)) + ")"


def queries(plan: dict) -> dict:
    y, x = plan["outcome"], plan.get("exposure")
    topic = [_block(y)] + ([_block(x)] if x else ['(prevalence[tiab] OR prevalent[tiab] OR burden[tiab])'])
    return {"exact": " AND ".join(topic + [NHANES]), "broader": " AND ".join(topic)}


def _count(term: str, mindate: str | None = None) -> int:
    q = {"term": term, "retmax": 0}
    if mindate:
        q.update({"mindate": mindate, "maxdate": "3000", "datetype": "pdat"})
    r = literature.eutils_get("esearch.fcgi", literature._params(q))
    return int(r.json().get("esearchresult", {}).get("count", 0))


def levers(plan: dict) -> list[dict]:
    k = get_knowledge()
    out = []
    cycles = plan.get("dataset", {}).get("cycles") or []
    if "L" in cycles:
        out.append({"lever": "Newest NHANES cycle (August 2021-August 2023)", "points": 10,
                    "why": "Few published analyses use the post-pandemic cycle yet."})
    for role in ("outcome", "exposure"):
        v = plan.get(role) or {}
        d = k.definitions.get(v.get("variable", ""))
        if d and int(d.get("source", {}).get("year", 0) or 0) >= 2025:
            out.append({"lever": f"Current guideline definition ({d.get('short', v['variable'])}, {d['source']['year']})", "points": 10,
                        "why": "Prior NHANES papers used older thresholds."})
            break
    if plan.get("interactions") or plan.get("subgroups"):
        out.append({"lever": "Prespecified effect modification", "points": 5,
                    "why": "Adds who-is-most-affected evidence beyond the overall association."})
    return out


def suggestions(plan: dict, exact: int) -> list[str]:
    if exact < 5:
        return []
    s = []
    if "L" not in (plan.get("dataset", {}).get("cycles") or []):
        s.append("Add the 2021-2023 cycle (L) - most prior work stops at 2017-2020.")
    s.append("Use a current guideline definition (e.g., ASH 2026, KDIGO 2026, Baveno VIII) instead of legacy cut-offs.")
    s.append("Prespecify effect modification by sex, race and ethnicity, or income - report who is most affected.")
    s.append("Change the estimand: dose-response (weighted quartiles, splines) or a clinically defined threshold.")
    s.append("Frame as a replication: low novelty is acceptable when the design fixes known flaws of earlier papers.")
    return s


def novelty(plan: dict, live: bool = True, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    q = queries(plan)
    lv = levers(plan)
    base = {"queries": q, "levers": lv, "source": "PubMed/MEDLINE (NCBI E-utilities)", "checked": today.isoformat(),
            "method": "score = 90*exp(-exact/8) + levers (max +20), clipped 5-100; exact = PubMed NHANES papers on the same "
                      "outcome/exposure in the last 10 years."}
    if not live:
        return {**base, "score": None, "label": "Not checked", "exact": None, "error": "offline"}
    try:
        exact = _count(q["exact"], f"{today.year - 10}/01/01")
        recent = _count(q["exact"], f"{today.year - 3}/01/01")
        broader = _count(q["broader"], f"{today.year - 10}/01/01")
        closest = literature.pubmed_search(q["exact"], retmax=5, sort="relevance", mindate=f"{today.year - 10}/01/01")
    except Exception as e:  # noqa: BLE001
        return {**base, "score": None, "label": "Not checked", "exact": None, "error": f"PubMed unavailable: {e}"}
    bonus = min(20, sum(x["points"] for x in lv))
    score = max(5, min(100, round(90 * math.exp(-exact / 8) + bonus)))
    label = "High" if score >= 70 else ("Moderate" if score >= 40 else "Low")
    return {**base, "score": score, "label": label, "exact": exact, "recent_3y": recent, "broader": broader,
            "closest": closest, "suggestions": suggestions(plan, exact), "error": None,
            "summary": (f"{exact} PubMed NHANES paper(s) on this question in 10 years ({recent} in the last 3); "
                        f"{broader:,} on the topic in any data source.")}
