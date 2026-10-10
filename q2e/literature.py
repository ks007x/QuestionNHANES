"""PubMed (NCBI E-utilities) search for prior literature and guideline-update watching."""
from __future__ import annotations

import datetime as _dt

import httpx

from .config import settings
from .knowledge import get_knowledge

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _params(extra: dict) -> dict:
    p = {"db": "pubmed", "retmode": "json", "tool": "q2e"}
    if settings.ncbi_email:
        p["email"] = settings.ncbi_email
    if settings.ncbi_api_key:
        p["api_key"] = settings.ncbi_api_key
    p.update(extra)
    return p


def pubmed_search(term: str, retmax: int = 8, sort: str = "relevance", mindate: str | None = None) -> list[dict]:
    q = {"term": term, "retmax": retmax, "sort": sort}
    if mindate:
        q.update({"mindate": mindate, "maxdate": "3000", "datetype": "pdat"})
    r = httpx.get(f"{EUTILS}/esearch.fcgi", params=_params(q), timeout=20)
    r.raise_for_status()
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    s = httpx.get(f"{EUTILS}/esummary.fcgi", params=_params({"id": ",".join(ids)}), timeout=20)
    s.raise_for_status()
    res = s.json().get("result", {})
    out = []
    for pmid in ids:
        it = res.get(pmid, {})
        authors = it.get("authors", [])
        out.append({"pmid": pmid, "title": it.get("title", ""), "journal": it.get("fulljournalname") or it.get("source", ""),
                    "pubdate": it.get("pubdate", ""), "first_author": authors[0]["name"] if authors else "",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    return out


def query_for_plan(plan: dict) -> str:
    terms = []
    for v in (plan.get("outcome"), plan.get("exposure")):
        if v:
            lab = v.get("concept_label") or v.get("label")
            terms.append(f'("{lab.lower()}"[tiab])')
    ds = "NHANES[tiab] OR \"National Health and Nutrition Examination Survey\"[tiab]"
    return " AND ".join(terms + [f"({ds})"])


def prior_literature(plan: dict, retmax: int = 8) -> dict:
    term = query_for_plan(plan)
    try:
        return {"query": term, "results": pubmed_search(term, retmax), "error": None}
    except Exception as e:  # noqa: BLE001
        return {"query": term, "results": [], "error": f"PubMed unavailable: {e}"}


def guideline_watch() -> list[dict]:
    """For each definition with a watch query, list PubMed records published after the library version year."""
    k = get_knowledge()
    out = []
    for d in k.definitions.values():
        q = d.get("watch_query")
        if not q:
            continue
        year = int(d.get("source", {}).get("year", 2000))
        try:
            hits = pubmed_search(q, retmax=5, sort="pub_date", mindate=f"{year}/01/01")
            err = None
        except Exception as e:  # noqa: BLE001
            hits, err = [], str(e)
        out.append({"definition": d["id"], "label": d.get("label"), "library_year": year, "status": d.get("status"),
                    "checked": _dt.date.today().isoformat(), "candidates": hits, "error": err,
                    "action": "Review candidates; if a newer guideline exists, import it (Guideline import) and approve the new version."})
    return out
