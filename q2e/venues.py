"""Where next? - journal match scores, upcoming conference abstract windows, and funding leads for a study.

Three layers, all transparent:
  * Curated knowledge (knowledge/venues.yaml) - works offline.
  * Live evidence when the network allows:
      - PubMed: which journals published NHANES papers on the same outcome/exposure in the last 5 years
        ("precedent"), which drives the journal match score;
      - NIH RePORTER: recently funded NIH projects on the topic (which institutes and mechanisms pay for it);
      - Grants.gov: open or forecasted NIH funding opportunities matching the topic.
  * A Specific Aims seed that turns the study result into preliminary data for an R03/R21/K-award.
"""
from __future__ import annotations

import calendar
import collections
import datetime as dt
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml

from . import literature
from .knowledge import get_knowledge

ROOT = Path(__file__).resolve().parent.parent
REPORTER = "https://api.reporter.nih.gov/v2/projects/search"
GRANTS_GOV = "https://api.grants.gov/v1/api/search2"
DOMAIN_ALIASES = {"iron": ["hematology"], "anthropometry": ["glycemia"], "inflammation": ["cardio"]}


@lru_cache(maxsize=1)
def venues_db() -> dict:
    return yaml.safe_load((ROOT / "knowledge" / "venues.yaml").read_text(encoding="utf-8"))


def _clean(label: str) -> str:
    label = re.sub(r"\(.*?\)", "", label or "")
    label = re.split(r" - |:|;|,", label)[0]
    return re.sub(r"\s+", " ", label).strip()


def plan_profile(plan: dict) -> dict:
    """Domains and plain-language terms that describe the study."""
    k = get_knowledge()
    doms: list[str] = []
    terms: list[str] = []
    for role in ("outcome", "exposure"):
        v = plan.get(role)
        if not v:
            continue
        c = k.concepts.get(v.get("concept", ""), {})
        d = c.get("domain") or v.get("domain") or "default"
        for x in [d] + DOMAIN_ALIASES.get(d, []):
            if x not in doms and x not in ("default", "demographic"):
                doms.append(x)
        t = _clean(v.get("concept_label") or c.get("label") or v.get("label", ""))
        if t and t.lower() not in [x.lower() for x in terms]:
            terms.append(t)
    return {"domains": doms or ["general"], "terms": terms}


def _keyword_hit(item: dict, terms: list[str]) -> bool:
    kws = [w.lower() for w in item.get("keywords", [])]
    return any(kw in t.lower() for t in terms for kw in kws)


def _domain_fit(item: dict, prof: dict) -> float:
    idoms = set(item.get("domains", []))
    if item.get("keywords"):
        return 1.0 if _keyword_hit(item, prof["terms"]) else 0.0
    if idoms & set(prof["domains"]):
        return 1.0
    return 0.6 if "general" in idoms else 0.0


# ---------------------------------------------------------------- journals
DOMAIN_KEYWORDS = {
    "glycemia": ["diabetes", "glycemic", "glucose", "insulin"], "anthropometry": ["obesity", "adiposity", "body weight"],
    "kidney": ["kidney", "renal", "nephro"], "liver": ["liver", "hepat", "fatty liver"], "cardio": ["cardiovascular", "heart", "hypertension", "blood pressure"],
    "hematology": ["anemia", "hematolog", "blood"], "iron": ["iron", "anemia", "ferritin"], "nutrition": ["nutrition", "diet"],
    "behaviour": ["sleep", "physical activity", "behavior"], "mental_health": ["depression", "mental health", "mood"],
    "function": ["aging", "older adults", "disability", "physical function"], "environment": ["environmental", "exposure", "toxic"],
    "respiratory": ["lung", "pulmonary", "asthma", "copd"], "social": ["disparities", "minority health", "social determinants"],
    "inflammation": ["inflammation", "inflammatory"]}


def _synonyms(v: dict, n: int = 4) -> list[str]:
    k = get_knowledge()
    c = k.concepts.get(v.get("concept", ""), {})
    out = []
    for t in [_clean(v.get("concept_label") or ""), _clean(v.get("label") or "")] + list(c.get("synonyms", [])):
        t = t.lower().strip()
        if t and len(t) > 2 and t not in out:
            out.append(t)
    return out[:n]


def precedent_query(plan: dict) -> str:
    parts = []
    for role in ("outcome", "exposure"):
        v = plan.get(role)
        if v:
            parts.append("(" + " OR ".join(f'"{t}"[tiab]' for t in _synonyms(v)) + ")")
    parts.append('(NHANES[tiab] OR "National Health and Nutrition Examination Survey"[tiab])')
    return " AND ".join(parts)


def journal_precedent(plan: dict, years: int = 5, retmax: int = 100) -> dict:
    """Count journals that published NHANES studies on the same topic (PubMed, last `years` years)."""
    term = precedent_query(plan)
    mindate = f"{dt.date.today().year - years}/01/01"
    hits = literature.pubmed_search(term, retmax=retmax, sort="relevance", mindate=mindate)
    counts = collections.Counter(_norm_journal(h["journal"]) for h in hits if h.get("journal"))
    names = {}
    for h in hits:
        names.setdefault(_norm_journal(h["journal"]), h["journal"])
    return {"query": term, "n_papers": len(hits), "counts": dict(counts), "names": names, "examples": hits[:5]}


def _norm_journal(name: str) -> str:
    n = (name or "").lower().replace("&", "and")
    n = re.sub(r"^the ", "", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def journal_matches(plan: dict, precedent: dict | None = None, top: int = 8) -> list[dict]:
    prof = plan_profile(plan)
    counts = (precedent or {}).get("counts", {})
    max_c = max(counts.values()) if counts else 0
    out = []
    seen = set()
    for j in venues_db()["journals"]:
        fit = _domain_fit(j, prof)
        if fit == 0:
            continue
        key = _norm_journal(j["name"])
        seen.add(key)
        c = counts.get(key, 0)
        out.append(_score(j["name"], fit, j.get("design_fit", 0.8), c, max_c, precedent is not None, j))
    # journals that publish this topic but are not in the curated list - still worth showing
    for key, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        if key in seen or c < 2:
            continue
        out.append(_score(precedent["names"].get(key, key), 0.5, 0.8, c, max_c, True,
                          {"note": "Not in the curated list - surfaced because it published similar NHANES studies", "url": None}))
    out.sort(key=lambda r: -r["score"])
    return out[:top]


def _score(name, fit, design, c, max_c, live, meta) -> dict:
    if live:
        prec = (c / max_c) if max_c else 0.0
        score = 100 * (0.45 * prec + 0.35 * fit + 0.20 * design)
        why = f"{c} similar NHANES paper(s) in 5 y" if c else "no similar NHANES papers found in 5 y"
    else:
        prec = None
        score = 100 * (0.6 * fit + 0.4 * design)
        why = "offline: scored on scope and design fit only"
    return {"journal": name, "score": round(score), "similar_papers": c if live else None, "scope_fit": round(fit, 2),
            "design_fit": design, "open_access": meta.get("open_access"), "why": why, "note": meta.get("note", ""),
            "url": meta.get("url")}


# ---------------------------------------------------------------- conferences
def next_deadline(month: int, today: dt.date) -> dt.date:
    year = today.year if month >= today.month else today.year + 1
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def conference_windows(plan: dict, today: dt.date | None = None, top: int = 6) -> list[dict]:
    today = today or dt.date.today()
    prof = plan_profile(plan)
    out = []
    for c in venues_db()["conferences"]:
        fit = _domain_fit(c, prof)
        if fit == 0:
            continue
        d = next_deadline(int(c["deadline_month"]), today)
        days = (d - today).days
        meet_year = d.year if c["meeting_month"] > c["deadline_month"] else d.year + 1
        out.append({"conference": c["name"], "society": c["society"], "fit": fit,
                    "deadline_estimate": f"{calendar.month_name[c['deadline_month']]} {d.year}",
                    "days_until_estimate": days,
                    "meeting": f"{calendar.month_name[c['meeting_month']]} {meet_year}",
                    "urgency": "this month" if days <= 31 else ("soon" if days <= 92 else "plan ahead"),
                    "url": c["url"],
                    "caveat": "Typical abstract window - confirm the exact date on the official page."})
    out.sort(key=lambda r: (-r["fit"], r["days_until_estimate"]))
    best = [r for r in out if r["fit"] == 1.0] + [r for r in out if r["fit"] < 1.0]
    return sorted(best[:top], key=lambda r: r["days_until_estimate"])


# ---------------------------------------------------------------- funding
def reporter_projects(terms: list[str], synonyms: list[str], require_nhanes: bool, years: int = 3, limit: int = 100) -> dict:
    """Recent NIH-funded projects on the topic. RePORTER text search is loose, so results are re-checked locally:
    a project counts only if its title/abstract mentions one of the topic synonyms (and NHANES, when required)."""
    fy = dt.date.today().year + (1 if dt.date.today().month >= 10 else 0)
    words = terms + (["NHANES"] if require_nhanes else [])
    body = {"criteria": {"advanced_text_search": {"operator": "and", "search_field": "projecttitle,terms,abstracttext",
                                                  "search_text": " ".join(words)},
                         "fiscal_years": list(range(fy - years + 1, fy + 1))},
            "include_fields": ["ApplId", "ProjectTitle", "ProjectNum", "AgencyIcAdmin", "ActivityCode", "Organization",
                               "PrincipalInvestigators", "FiscalYear", "AwardAmount", "ProjectDetailUrl", "AbstractText"],
            "offset": 0, "limit": limit, "sort_field": "fiscal_year", "sort_order": "desc"}
    r = httpx.post(REPORTER, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    syn = [x.lower() for x in synonyms if len(x) > 3]

    def relevant(p):
        txt = f"{p.get('project_title') or ''} {p.get('abstract_text') or ''}".lower()
        return any(x in txt for x in syn) and (not require_nhanes or "nhanes" in txt or "national health and nutrition" in txt)

    res = [p for p in (data.get("results") or []) if relevant(p)]
    ics = collections.Counter(((p.get("agency_ic_admin") or {}).get("abbreviation") or "?") for p in res)
    acts = collections.Counter((p.get("activity_code") or "?") for p in res)
    projects = [{"title": p.get("project_title"), "number": p.get("project_num"), "ic": (p.get("agency_ic_admin") or {}).get("abbreviation"),
                 "activity": p.get("activity_code"), "fiscal_year": p.get("fiscal_year"),
                 "organization": (p.get("organization") or {}).get("org_name"),
                 "pi": ", ".join(x.get("full_name", "") for x in (p.get("principal_investigators") or [])[:2]),
                 "award": p.get("award_amount"),
                 "url": p.get("project_detail_url") or (f"https://reporter.nih.gov/project-details/{p.get('appl_id')}" if p.get("appl_id") else None)}
                for p in res[:6]]
    return {"total": len(res), "screened": len(data.get("results") or []), "by_institute": dict(ics.most_common(5)),
            "by_mechanism": dict(acts.most_common(6)), "examples": projects, "search": "https://reporter.nih.gov/"}


def open_opportunities(keywords: list[str], rows: int = 25, keep: int = 8) -> dict:
    """NIH opportunities on Grants.gov whose TITLE mentions one of the topic keywords (Grants.gov keyword search is loose)."""
    seen, opps = set(), []
    for kw in keywords[:3]:
        body = {"keyword": kw, "oppStatuses": "forecasted|posted", "agencies": "HHS-NIH11", "rows": rows}
        r = httpx.post(GRANTS_GOV, json=body, timeout=25)
        r.raise_for_status()
        for h in ((r.json().get("data") or {}).get("oppHits")) or []:
            title = (h.get("title") or "")
            if h.get("id") in seen or not any(k.lower() in title.lower() for k in keywords):
                continue
            seen.add(h.get("id"))
            opps.append({"number": h.get("number"), "title": title, "status": h.get("oppStatus"),
                         "close_date": h.get("closeDate") or "see notice",
                         "url": f"https://www.grants.gov/search-results-detail/{h.get('id')}"})
    return {"keyword": ", ".join(keywords[:3]), "opportunities": opps[:keep],
            "search": "https://www.grants.gov/search-grants"}


def funding_leads(plan: dict, live: bool = True) -> dict:
    prof = plan_profile(plan)
    db = venues_db()
    ics = [i for i in db["nih_institutes"] if set(i["domains"]) & set(prof["domains"])]
    found = [f for f in db["foundations"] if set(f["domains"]) & set(prof["domains"])]
    out: dict[str, Any] = {"institutes": ics, "mechanisms": db["mechanisms"], "foundations": found,
                           "reporter": None, "opportunities": None, "errors": []}
    if live and prof["terms"]:
        try:
            syn = [t for role in ("outcome", "exposure") if plan.get(role) for t in _synonyms(plan[role], 6)]
            rep = reporter_projects(prof["terms"], syn, require_nhanes=True)
            rep["scope"] = f"of the {rep['screened']} most recent search hits use NHANES and match this topic"
            if rep["total"] < 3:
                rep = reporter_projects(prof["terms"], syn, require_nhanes=False)
                rep["scope"] = f"of the {rep['screened']} most recent search hits match this topic (any data source)"
            out["reporter"] = rep
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"NIH RePORTER unavailable: {e}")
        try:
            kws = [t.lower() for t in prof["terms"]] + [w for d in prof["domains"] for w in DOMAIN_KEYWORDS.get(d, [])]
            out["opportunities"] = open_opportunities(list(dict.fromkeys(kws)))
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"Grants.gov unavailable: {e}")
    return out


# ---------------------------------------------------------------- specific aims seed
def aims_seed(plan: dict, results: dict | None = None) -> str:
    y = plan["outcome"]
    x = plan.get("exposure")
    pe = (results or {}).get("primary_estimate") or {}
    n = pe.get("n")
    finding = ""
    if pe.get("est") is not None:
        eff = pe.get("effect_label") or pe.get("effect", "estimate")
        if pe.get("effect") == "prevalence":
            finding = f"{100 * pe['est']:.1f}% (95% CI, {100 * pe['lcl']:.1f}%-{100 * pe['ucl']:.1f}%)"
        else:
            finding = f"{eff} {pe['est']:.2f} (95% CI, {pe['lcl']:.2f}-{pe['ucl']:.2f})"
    ylab = _clean(y.get("concept_label") or y["label"]).lower()
    topic = f"{_clean(x.get('concept_label') or x['label']).lower()} and {ylab}" if x else ylab
    pre = (f"In a prespecified, survey-weighted analysis of {n:,} NHANES participants, we found {finding}. "
           if n and finding else "Our prespecified, survey-weighted NHANES analysis provides national preliminary data. ")
    return (f"SPECIFIC AIMS (seed - edit before use)\n\n"
            f"Gap. Nationally representative evidence on {topic} is limited, and cross-sectional estimates cannot "
            f"establish temporality or mechanism.\n\n"
            f"Preliminary data. {pre}The analysis is fully reproducible (locked protocol, provenance ledger, code bundle).\n\n"
            f"Aim 1. Replicate and extend the finding across additional NHANES cycles and subgroups "
            f"(sex, race and ethnicity, age, income), with prespecified sensitivity analyses.\n"
            f"Aim 2. Test temporality in a longitudinal cohort with repeated measures of {topic}.\n"
            f"Aim 3. Evaluate mechanism or intervention targets suggested by the cross-sectional pattern.\n\n"
            f"Fit. Secondary-data aims suit R03/R21; Aims 2-3 suit a K-award or R01. Confirm institute priorities with a program officer.")


def where_next(plan: dict, results: dict | None = None, live: bool = True, today: dt.date | None = None) -> dict:
    prec, errors = None, []
    if live:
        try:
            prec = journal_precedent(plan)
        except Exception as e:  # noqa: BLE001
            errors.append(f"PubMed unavailable: {e}")
    funding = funding_leads(plan, live=live)
    errors += funding.pop("errors")
    from . import novelty as _nov
    nv = _nov.novelty(plan, live=live)
    return {"profile": plan_profile(plan), "novelty": nv, "journals": journal_matches(plan, prec),
            "precedent": {k: prec[k] for k in ("query", "n_papers", "examples")} if prec else None,
            "conferences": conference_windows(plan, today), "funding": funding,
            "aims_seed": aims_seed(plan, results), "live": live and not errors, "errors": errors,
            "method": ("Journal match = 45% topical precedent (share of similar NHANES papers in the last 5 years, PubMed) "
                       "+ 35% scope fit + 20% design fit for cross-sectional survey analyses; offline = 60% scope + 40% design. "
                       "Conference windows are typical months - always confirm on the official page.")}


def to_markdown(w: dict) -> str:
    L = ["# Where next? Journals, conferences and funding", "",
         f"Study domains: {', '.join(w['profile']['domains'])}. Topic terms: {', '.join(w['profile']['terms'])}.", ""]
    if w.get("errors"):
        L += ["> Live sources unavailable: " + "; ".join(w["errors"]), ""]
    nv = w.get("novelty") or {}
    if nv.get("score") is not None:
        L += ["## Novelty (PubMed/MEDLINE)", "", f"**{nv['score']}/100 - {nv['label']}.** {nv['summary']}", ""]
        for lv in nv.get("levers", []):
            L.append(f"- +{lv['points']} {lv['lever']}: {lv['why']}")
        if nv.get("closest"):
            L += ["", "Closest prior NHANES work:"] + [f"- [{c['title']}]({c['url']}) - {c['journal']}, {c['pubdate']}" for c in nv["closest"]]
        if nv.get("suggestions"):
            L += ["", "How to differentiate:"] + [f"- {x}" for x in nv["suggestions"]]
        L += ["", f"Query: `{nv['queries']['exact']}`", ""]
    L += ["## Journal match", "", "| Score | Journal | Evidence | Open access |", "|---:|---|---|---|"]
    for j in w["journals"]:
        name = f"[{j['journal']}]({j['url']})" if j.get("url") else j["journal"]
        L.append(f"| {j['score']} | {name} | {j['why']} | {'yes' if j.get('open_access') else ('no' if j.get('open_access') is False else '-')} |")
    if w.get("precedent"):
        L += ["", f"Precedent search ({w['precedent']['n_papers']} papers): `{w['precedent']['query']}`"]
        for e in w["precedent"]["examples"]:
            L.append(f"- [{e['title']}]({e['url']}) - {e['journal']}, {e['pubdate']}")
    L += ["", "## Conference abstract windows (typical - confirm on the official page)", "",
          "| Deadline (est.) | Days | Conference | Meeting |", "|---|---:|---|---|"]
    for c in w["conferences"]:
        L.append(f"| {c['deadline_estimate']} | {c['days_until_estimate']} | [{c['conference']}]({c['url']}) ({c['society']}) | {c['meeting']} |")
    f = w["funding"]
    L += ["", "## Funding leads", ""]
    for i in f["institutes"]:
        L.append(f"- NIH {i['ic']}: [{i['name']}]({i['url']})")
    for m in f["mechanisms"]:
        L.append(f"- {m['code']} ({m['label']}): {m['fit']} - [details]({m['url']})")
    for fo in f["foundations"]:
        L.append(f"- [{fo['name']}]({fo['url']})")
    if f.get("reporter"):
        r = f["reporter"]
        L += ["", f"NIH RePORTER: {r['total']} funded projects {r.get('scope', 'match this topic')}. By institute: "
              + ", ".join(f"{k} {v}" for k, v in r["by_institute"].items()) + ". By mechanism: "
              + ", ".join(f"{k} {v}" for k, v in r["by_mechanism"].items()) + "."]
        for p in r["examples"]:
            L.append(f"- {p['number']} ({p['ic']}, FY{p['fiscal_year']}): {p['title']}" + (f" - [link]({p['url']})" if p.get("url") else ""))
    if f.get("opportunities") and f["opportunities"]["opportunities"]:
        L += ["", f"Open or forecasted NIH opportunities (Grants.gov, keyword '{f['opportunities']['keyword']}'):"]
        for o in f["opportunities"]["opportunities"]:
            L.append(f"- [{o['number']}]({o['url']}): {o['title']} ({o['status']}, closes {o['close_date']})")
    L += ["", "## Specific Aims seed", "", "```", w["aims_seed"], "```", "", f"_Method: {w['method']}_", ""]
    return "\n".join(L)
