"""Novelty score from PubMed/MEDLINE - shown next to the feasibility score. Scores the whole PICO, not one pair.

Elements: P (population, when narrower than "adults"), I/E (each exposure; every arm of a multi-arm comparison),
O (outcome). Queries, PubMed records (MEDLINE plus in-process citations), last 10 years:
  full PICO (NHANES)      outcome AND every exposure/arm (AND population) AND NHANES, >=1 element in the title
  each pair (NHANES)      outcome AND one exposure/arm AND NHANES          -> "this link was already mined in NHANES"
  each pair (any data)    outcome AND one exposure/arm, any data source     -> "this link is established elsewhere"
Score:
  effective precedent E = full + 0.5 * sum over pairs of (pair_NHANES - full)+
  score = 90 * exp(-E / 8) + levers (max +20) - 25 per direct precedent (max -40)
          - known-association penalty per pair (any data: >=20 papers -5, >=100 papers -10; max -20), clipped 5-100.
Levers: newest cycle, 2025+ guideline definition, prespecified effect modification, first head-to-head comparison of
the arms (no full-PICO precedent although single pairs exist).
"""
from __future__ import annotations

import datetime as dt
import math

import httpx

from . import literature
from .knowledge import get_knowledge
from .venues import _synonyms

NHANES = '(NHANES[tiab] OR "National Health and Nutrition Examination Survey"[tiab])'


def _block(v: dict, field: str = "tiab") -> str:
    return "(" + " OR ".join(f'"{t}"[{field}]' for t in _synonyms(v, 5)) + ")"


POP_TERMS = {
    "children": ["children", "adolescents", "pediatric", "youth"], "older_adults": ["older adults", "elderly", "aged 65"],
    "women_repro": ["women of reproductive age", "premenopausal women"], "pregnant": ["pregnant", "pregnancy"],
    "women": ["women"], "men": ["men"], "ckd": ["chronic kidney disease", "ckd"], "diabetes": ["diabetes", "diabetic"],
    "heart_failure": ["heart failure"], "htn_pop": ["hypertension", "hypertensive"]}


def _concept_block(cid: str, field: str = "tiab") -> str:
    k = get_knowledge()
    c = k.concepts.get(cid, {})
    v = {"concept": cid, "concept_label": c.get("label", cid), "label": c.get("label", cid)}
    if cid.startswith("dict:"):
        v["label"] = k.dictionary.get(cid[5:], {}).get("label", cid[5:])
        v["concept_label"] = v["label"]
    return _block(v, field)


def elements(plan: dict) -> dict:
    """PICO elements as PubMed blocks: outcome, exposure components (arms), population."""
    y, x = plan["outcome"], plan.get("exposure")
    comps = []
    if x and x.get("arms"):
        for a in x["arms"]["arms"]:
            comps.append({"label": a["label"], "tiab": _concept_block(a["concept"]), "ti": _concept_block(a["concept"], "ti")})
    elif x:
        comps.append({"label": x.get("concept_label") or x["label"], "tiab": _block(x), "ti": _block(x, "ti")})
    pops = [p for p in (plan.get("parsed", {}).get("populations") or []) if p in POP_TERMS]
    pop = None
    if pops:
        terms = [t for p in pops for t in POP_TERMS[p]]
        pop = {"label": ", ".join(pops), "tiab": "(" + " OR ".join(f'"{t}"[tiab]' for t in terms) + ")"}
    return {"outcome": {"label": y.get("concept_label") or y["label"], "tiab": _block(y), "ti": _block(y, "ti")},
            "components": comps, "population": pop}


def queries(plan: dict) -> dict:
    """exact = the full PICO in NHANES; pairs = outcome x each exposure/arm (NHANES and any data)."""
    e = elements(plan)
    o = e["outcome"]
    if e["components"]:
        title = "(" + " OR ".join([o["ti"]] + [c["ti"] for c in e["components"]]) + ")"
        full = [o["tiab"]] + [c["tiab"] for c in e["components"]] + [title]
        pairs = [{"label": f"{c['label']} x {o['label']}",
                  "nhanes": " AND ".join([o["tiab"], c["tiab"], f"({o['ti']} OR {c['ti']})", NHANES]),
                  "any": " AND ".join([o["tiab"], c["tiab"], f"({o['ti']} OR {c['ti']})"])} for c in e["components"]]
    else:
        full = [o["ti"], "(prevalence[tiab] OR prevalent[tiab] OR burden[tiab])"]
        pairs = []
    if e["population"]:
        full.append(e["population"]["tiab"])
    exact = " AND ".join(full + [NHANES])
    return {"exact": exact, "broader": " AND ".join(full), "pairs": pairs,
            "population": e["population"]["label"] if e["population"] else None}


def _count(term: str, mindate: str | None = None) -> int:
    q = {"term": term, "retmax": 0}
    if mindate:
        q.update({"mindate": mindate, "maxdate": "3000", "datetype": "pdat"})
    r = literature.eutils_get("esearch.fcgi", literature._params(q))
    return int(r.json().get("esearchresult", {}).get("count", 0))


PREV_WORDS = ("prevalence", "prevalent", "burden", "trends", "in the us", "in the united states")


def direct_precedents(plan: dict, closest: list[dict]) -> list[dict]:
    """Prior papers whose TITLE names every element of this question (outcome + every exposure/arm, or outcome + prevalence)."""
    k = get_knowledge()
    y, x = plan["outcome"], plan.get("exposure")
    ys = _synonyms(y, 6)
    if x and x.get("arms"):
        groups = [_synonyms({"concept": a["concept"], "concept_label": a["label"], "label": a["label"]}, 6) for a in x["arms"]["arms"]]
    elif x:
        groups = [_synonyms(x, 6)]
    else:
        groups = None
    out = []
    for c in closest or []:
        t = (c.get("title") or "").lower()
        hit_y = any(w in t for w in ys)
        hit_x = all(any(w in t for w in g) for g in groups) if groups is not None else any(w in t for w in PREV_WORDS)
        if hit_y and hit_x:
            out.append({"title": c.get("title"), "journal": c.get("journal"), "url": c.get("url")})
    return out


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


_CACHE: dict[str, tuple[float, dict]] = {}


def novelty(plan: dict, live: bool = True, today: dt.date | None = None, quick: bool = False) -> dict:
    """quick=True skips the 3-year and any-data topic counts (used to score many chat options at once)."""
    import json as _json
    import time as _time
    today = today or dt.date.today()
    q = queries(plan)
    key = _json.dumps([q["exact"], [p["nhanes"] for p in q["pairs"]], plan.get("dataset", {}).get("cycles"), quick], sort_keys=True)
    hit = _CACHE.get(key)
    if live and hit and _time.time() - hit[0] < 86400:
        return hit[1]
    res = _novelty(plan, q, live, today, quick)
    if live and res.get("score") is not None:
        _CACHE[key] = (_time.time(), res)
    return res


def _novelty(plan: dict, q: dict, live: bool, today: dt.date, quick: bool) -> dict:
    lv = levers(plan)
    base = {"queries": q, "levers": lv, "source": "PubMed/MEDLINE (NCBI E-utilities)", "checked": today.isoformat(),
            "method": "Full PICO and every outcome x exposure/arm pair are searched. score = 90*exp(-E/8) + levers (max +20) "
                      "- 25 per direct precedent (max -40) - known-association penalty (max -20), clipped 5-100; "
                      "E = full-PICO NHANES papers + half of each pair's additional NHANES papers (last 10 years)."}
    if not live:
        return {**base, "score": None, "label": "Not checked", "exact": None, "error": "offline"}
    since10, since3 = f"{today.year - 10}/01/01", f"{today.year - 3}/01/01"
    try:
        exact = _count(q["exact"], since10)
        recent = _count(q["exact"], since3) if not quick else None
        broader = _count(q["broader"], since10) if not quick else None
        pairs = []
        for pr in q["pairs"]:
            pairs.append({"label": pr["label"], "nhanes": _count(pr["nhanes"], since10), "any": _count(pr["any"], since10)})
        if quick:
            closest = literature.pubmed_search(q["exact"], retmax=3, sort="relevance", mindate=since10) if exact else []
        else:
            closest = literature.pubmed_search(q["exact"], retmax=5, sort="relevance", mindate=since10)
        if not closest and pairs and not quick:
            top = max(range(len(pairs)), key=lambda i: pairs[i]["nhanes"])
            closest = literature.pubmed_search(q["pairs"][top]["nhanes"], retmax=5, sort="relevance", mindate=since10)
    except Exception as e:  # noqa: BLE001
        return {**base, "score": None, "label": "Not checked", "exact": None, "error": f"PubMed unavailable: {e}"}
    e_eff = exact + 0.5 * sum(max(0, p["nhanes"] - exact) for p in pairs)
    known = sum(10 if p["any"] >= 100 else 5 if p["any"] >= 20 else 0 for p in pairs)
    known = min(20, known)
    if len(pairs) > 1 and exact == 0 and any(p["nhanes"] or p["any"] for p in pairs):
        lv = lv + [{"lever": "First head-to-head comparison of these groups", "points": 5,
                    "why": "Single links have been studied, but not all groups against the same outcome in one analysis."}]
    direct = direct_precedents(plan, closest)
    bonus = min(20, sum(x["points"] for x in lv))
    penalty = min(40, 25 * len(direct))
    score = max(5, min(100, round(90 * math.exp(-e_eff / 8) + bonus - penalty - known)))
    label = "High" if score >= 70 else ("Moderate" if score >= 40 else "Low")
    pair_txt = "; ".join(f"{p['label']}: {p['nhanes']} NHANES / {p['any']:,} any data" for p in pairs)
    established = [p["label"] for p in pairs if p["any"] >= 20]
    sugg = [f"Direct precedent: '{d['title']}' ({d['journal']}) - frame as an update or replication, or add a new angle." for d in direct]
    if established:
        sugg.append("Already established in other data: " + ", ".join(established) + " - emphasise what NHANES adds "
                    "(national prevalence-weighted estimates, subgroups, a head-to-head comparison or a newer definition).")
    sugg += suggestions(plan, max(round(e_eff), 5 if direct else 0))
    return {**base, "levers": lv, "score": score, "label": label, "exact": exact, "recent_3y": recent, "broader": broader,
            "pairs": pairs, "effective_precedent": round(e_eff, 1), "known_penalty": known,
            "closest": closest, "direct_precedents": direct, "penalty": penalty, "suggestions": sugg, "error": None,
            "summary": (f"{exact} PubMed NHANES paper(s) on the full question in 10 years" + (f" ({recent} in the last 3)" if recent is not None else "")
                        + (f", {len(direct)} with a title naming the whole question" if direct else "")
                        + (f". By element - {pair_txt}" if pairs else (f"; {broader:,} on the topic in any data source" if broader is not None else "")) + ".")}
