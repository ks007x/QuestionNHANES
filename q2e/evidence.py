"""Learn from, and check results against, NHANES studies in high-impact journals.

1. Search PubMed for NHANES papers on the same outcome and exposure (or arms) in the journals of
   knowledge/high_impact_journals.yaml (JAMA Network, Lancet group, NEJM, BMJ, Annals, and society journals such as
   JACC, Stroke, Blood, Am J Gastroenterol, J Hepatol). Falls back to any journal when fewer than 3 are found.
2. Read each abstract (efetch) and extract
   - reported effect estimates with 95% CIs (OR / PR / RR / HR / beta / mean difference / prevalence %),
   - the analytic methods used (logistic, Poisson, linear, Cox, splines, multiple imputation ...),
   - NHANES years and sample size.
   Extraction is rule-based; when an approved LLM is configured it extracts as well, and every number it returns must
   appear verbatim in the abstract or it is discarded (a hallucination guard). Only public abstracts and Q2E's
   aggregate estimate are ever sent to the LLM.
3. Compare: our primary estimate against each comparable published estimate - same direction? overlapping 95% CIs
   when the measure is the same? - and summarise the concordance.
4. "Methods landscape": how often each method appears in the similar papers - used by the model advisor.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import literature
from .novelty import NHANES, elements

ROOT = Path(__file__).resolve().parent.parent
RATIO = {"OR", "PR", "RR", "HR", "IRR"}
_CACHE: dict[str, tuple[float, Any]] = {}


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((ROOT / "knowledge" / "high_impact_journals.yaml").read_text())


def journals() -> list[dict]:
    seen, out = set(), []
    for j in config()["journals"]:
        if j["jour"] not in seen:
            seen.add(j["jour"])
            out.append(j)
    return out


def journal_group(name: str) -> str | None:
    n = (name or "").lower().replace(".", "").strip()
    full = {"jama network open": "JAMA Netw Open", "jama internal medicine": "JAMA Intern Med", "the lancet": "Lancet",
            "new england journal of medicine": "N Engl J Med", "the new england journal of medicine": "N Engl J Med",
            "annals of internal medicine": "Ann Intern Med", "journal of the american college of cardiology": "J Am Coll Cardiol",
            "american journal of gastroenterology": "Am J Gastroenterol", "the american journal of gastroenterology": "Am J Gastroenterol",
            "journal of hepatology": "J Hepatol", "blood advances": "Blood Adv", "diabetes care": "Diabetes Care",
            "journal of the american heart association": "J Am Heart Assoc", "american journal of epidemiology": "Am J Epidemiol",
            "the american journal of clinical nutrition": "Am J Clin Nutr", "american journal of clinical nutrition": "Am J Clin Nutr",
            "the journal of clinical endocrinology and metabolism": "J Clin Endocrinol Metab"}
    target = full.get(n, name)
    for j in journals():
        if j["jour"].lower().replace(".", "") in (n, target.lower().replace(".", "")):
            return j["group"]
    return None


def journal_filter() -> str:
    return "(" + " OR ".join(f'"{j["jour"]}"[jour]' for j in journals()) + ")"


# ------------------------------------------------------------------ search + fetch
def queries(plan: dict) -> dict:
    e = elements(plan)
    o = e["outcome"]
    comps = e["components"]
    if comps:
        exp = "(" + " OR ".join(c["tiab"] for c in comps) + ")"
        topic = f"{o['tiab']} AND {exp}"
    else:
        topic = f"{o['tiab']} AND (prevalence[tiab] OR prevalent[tiab] OR burden[tiab])"
    return {"high_impact": f"{topic} AND {NHANES} AND {journal_filter()}", "any_journal": f"{topic} AND {NHANES}",
            "outcome_only": f"{o['tiab']} AND {NHANES} AND {journal_filter()}",
            "terms": {"outcome": o["label"], "exposures": [c["label"] for c in comps]}}


def _text(el) -> str:
    return "".join(el.itertext()) if el is not None else ""


def fetch_abstracts(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    p = literature._params({"id": ",".join(pmids), "rettype": "abstract"})
    p["retmode"] = "xml"
    r = literature.eutils_get("efetch.fcgi", p, timeout=30)
    root = ET.fromstring(r.text)
    out = []
    for art in root.iter("PubmedArticle"):
        pmid = _text(art.find(".//PMID"))
        title = _text(art.find(".//ArticleTitle"))
        journal = _text(art.find(".//Journal/Title")) or _text(art.find(".//MedlineTA"))
        ta = _text(art.find(".//MedlineJournalInfo/MedlineTA"))
        year = _text(art.find(".//JournalIssue/PubDate/Year")) or _text(art.find(".//ArticleDate/Year")) or \
            (_text(art.find(".//JournalIssue/PubDate/MedlineDate"))[:4])
        parts = []
        for a in art.findall(".//Abstract/AbstractText"):
            lab = a.get("Label")
            parts.append((f"{lab}: " if lab else "") + _text(a))
        out.append({"pmid": pmid, "title": title, "journal": journal, "journal_abbrev": ta, "year": year,
                    "abstract": " ".join(parts), "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    return out


# ------------------------------------------------------------------ extraction (rules)
NUM = r"-?\d+(?:\.\d+)?"
_MEAS = (r"(?P<m>(?i:adjusted odds ratios?|odds ratios?|adjusted hazard ratios?|hazard ratios?|adjusted prevalence ratios?|"
         r"prevalence ratios?|relative risks?|risk ratios?|incidence rate ratios?|mean differences?|"
         r"regression coefficients?|percent(?:age)? change|beta)|aORs?|ORs?|aHRs?|HRs?|aPRs?|PRs?|aRRs?|RRs?|IRRs?|β|B|MD)")
EST_RE = re.compile(_MEAS + r"(?![A-Za-z])[^0-9\-]{0,28}?(?P<v>" + NUM + r")\s*%?\s*[,;]?\s*\(?\[?\s*"
                    r"(?:95\s*%\s*(?:CI|confidence interval)s?\s*[:,=]?\s*)?(?P<l>" + NUM + r")\s*%?\s*(?:-|to|,)\s*(?P<u>" + NUM + r")")
PREV_RE = re.compile(r"(?P<v>\d+(?:\.\d+)?)\s*%\s*[,;]?\s*\(?\[?\s*95\s*%\s*(?:CI|confidence interval)\s*[:,=]?\s*"
                     r"(?P<l>\d+(?:\.\d+)?)\s*%?\s*(?:-|to|,)\s*(?P<u>\d+(?:\.\d+)?)\s*%?")
N_RE = re.compile(r"(?P<n>\d{1,3}(?:[, ]\d{3})+|\d{3,6})\s+(?:US\s+|U\.S\.\s+)?(?:adult\s+)?(?:participants|adults|individuals|persons|people|respondents|children|adolescents|women|men|patients)")
YEARS_RE = re.compile(r"(?:19|20)\d{2}\s*(?:-|to|through|and)\s*(?:19|20)?\d{2}")


def _norm(t: str) -> str:
    return (t.replace("−", "-").replace("–", "-").replace("—", "-").replace("·", ".")
            .replace(" ", " ").replace(" ", " "))


def _measure(m: str) -> str:
    s = m.lower().rstrip("s")
    if "odds" in s or s in ("or", "aor"):
        return "OR"
    if "hazard" in s or s in ("hr", "ahr"):
        return "HR"
    if "prevalence ratio" in s or s in ("pr", "apr"):
        return "PR"
    if "incidence rate" in s or s == "irr":
        return "IRR"
    if "relative risk" in s or "risk ratio" in s or s in ("rr", "arr"):
        return "RR"
    if "percent" in s:
        return "% change"
    return "Beta"


def extract_rules(abstract: str) -> dict:
    t = _norm(abstract)
    ests = []
    for m in EST_RE.finditer(t):
        try:
            v, lo, hi = float(m.group("v")), float(m.group("l")), float(m.group("u"))
        except ValueError:
            continue
        meas = _measure(m.group("m"))
        if not (lo <= v <= hi) or (meas in RATIO and (v <= 0 or lo <= 0 or hi > 1000)):
            continue
        s0 = t.rfind(".", 0, m.start()) + 1
        ctx = t[s0:min(len(t), m.end() + 60)].strip()
        ests.append({"measure": meas, "value": v, "lcl": lo, "ucl": hi, "context": ctx[:260], "source": "rules"})
    prev = []
    for m in PREV_RE.finditer(t):
        v, lo, hi = float(m.group("v")), float(m.group("l")), float(m.group("u"))
        if lo <= v <= hi <= 100:
            s0 = t.rfind(".", 0, m.start()) + 1
            prev.append({"measure": "Prevalence %", "value": v, "lcl": lo, "ucl": hi, "context": t[s0:m.end() + 40].strip()[:260], "source": "rules"})
    meths = [k for k, rx in config()["methods"].items() if re.search(rx, t, re.I)]
    n = None
    mn = N_RE.search(t)
    if mn:
        n = int(mn.group("n").replace(",", "").replace(" ", ""))
    years = sorted(set(YEARS_RE.findall(t)))[:3]
    return {"estimates": ests[:12], "prevalence": prev[:8], "methods": meths, "n": n, "years": years}


# ------------------------------------------------------------------ extraction (LLM, verified)
LLM_SYSTEM = ("You extract numbers from medical abstracts. Return JSON only: {\"estimates\": [{\"measure\": \"OR|PR|RR|HR|Beta|"
              "Prevalence %\", \"value\": number, \"lcl\": number, \"ucl\": number, \"exposure\": str, \"outcome\": str, "
              "\"contrast\": str}], \"methods\": [str], \"population\": str, \"nhanes_years\": str}. Copy numbers exactly "
              "as written. Do not compute or infer any number that is not printed in the abstract.")


def _appears(x: float, text: str) -> bool:
    cands = {f"{x:g}", f"{x:.1f}", f"{x:.2f}", f"{x:.3f}"}
    return any(re.search(r"(?<![\d.])" + re.escape(c) + r"(?![\d])", text) for c in cands)


def extract_llm(client, paper: dict) -> dict | None:
    try:
        data = client.complete_json("Librarian", LLM_SYSTEM, f"Title: {paper['title']}\nAbstract: {paper['abstract'][:6000]}", max_tokens=1200)
    except Exception:  # noqa: BLE001
        return None
    text = _norm(paper["abstract"])
    kept, rejected = [], 0
    for e in data.get("estimates") or []:
        try:
            v, lo, hi = float(e["value"]), float(e["lcl"]), float(e["ucl"])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        if all(_appears(z, text) for z in (v, lo, hi)) and lo <= v <= hi:
            kept.append({"measure": _measure(str(e.get("measure", "Beta"))) if "prev" not in str(e.get("measure", "")).lower() else "Prevalence %",
                         "value": v, "lcl": lo, "ucl": hi, "context": f"{e.get('exposure', '')} -> {e.get('outcome', '')} ({e.get('contrast', '')})"[:260],
                         "source": "llm (verified against abstract text)"})
        else:
            rejected += 1
    return {"estimates": kept, "methods": [str(m) for m in data.get("methods") or []][:10], "population": data.get("population"),
            "years": data.get("nhanes_years"), "rejected": rejected}


# ------------------------------------------------------------------ comparison
def _ours(results: dict | None, plan: dict) -> dict | None:
    pe = (results or {}).get("primary_estimate") or {}
    if pe.get("est") is None or pe.get("lcl") is None:
        return None
    eff = pe.get("effect")
    if eff == "prevalence":
        return {"measure": "Prevalence %", "value": 100 * pe["est"], "lcl": 100 * pe["lcl"], "ucl": 100 * pe["ucl"], "label": pe.get("label")}
    return {"measure": eff if eff in RATIO else "Beta", "value": pe["est"], "lcl": pe["lcl"], "ucl": pe["ucl"], "label": pe.get("label")}


def _dir(measure: str, v: float) -> int:
    null = 1.0 if measure in RATIO else 0.0
    return (v > null) - (v < null)


def _relevant(est: dict, terms: list[str]) -> bool:
    c = est.get("context", "").lower()
    return any(t and t.lower()[:6] in c for t in terms)


def compare(ours: dict | None, paper: dict, terms: list[str]) -> dict:
    if not ours:
        return {"verdict": "Not compared", "why": "No estimate from this study yet - run the analysis first."}
    pool = paper["prevalence"] if ours["measure"] == "Prevalence %" else paper["estimates"]
    if not pool:
        return {"verdict": "No numbers in abstract", "why": "The abstract reports no estimate with a 95% CI that could be read."}
    rel = [e for e in pool if _relevant(e, terms)] or pool
    e = rel[0]
    same = e["measure"] == ours["measure"] or (ours["measure"] in RATIO and e["measure"] in RATIO)
    if not same and not (ours["measure"] == "Beta" and e["measure"] == "Beta"):
        return {"verdict": "Different measure", "published": e,
                "why": f"Published {e['measure']} vs our {ours['measure']}; direction only."
                       + (" Same direction." if _dir(e["measure"], e["value"]) == _dir(ours["measure"], ours["value"]) != 0 else "")}
    d_pub, d_our = _dir(e["measure"], e["value"]), _dir(ours["measure"], ours["value"])
    overlap = not (ours["ucl"] < e["lcl"] or e["ucl"] < ours["lcl"])
    note = ""
    if e["measure"] != ours["measure"]:
        note = f" ({e['measure']} vs {ours['measure']}: odds ratios exceed prevalence ratios when the outcome is common.)"
    if ours["measure"] == "Beta":
        note += " Units and exposure scaling may differ; compare direction first."
    if d_pub == d_our and overlap:
        return {"verdict": "Consistent", "published": e, "why": "Same direction and overlapping 95% CIs." + note}
    if d_pub == d_our:
        return {"verdict": "Same direction, different size", "published": e, "why": "Same direction; 95% CIs do not overlap." + note}
    if d_pub == 0 or d_our == 0:
        return {"verdict": "One estimate is null", "published": e, "why": "One of the two estimates sits on the null value." + note}
    return {"verdict": "Opposite direction", "published": e, "why": "The published estimate points the other way - check definitions, population and adjustment." + note}


def _summary(rows: list[dict]) -> dict:
    comp = [r for r in rows if r["comparison"]["verdict"] in ("Consistent", "Same direction, different size", "Opposite direction", "One estimate is null")]
    agree = [r for r in comp if r["comparison"]["verdict"] in ("Consistent", "Same direction, different size")]
    cons = [r for r in comp if r["comparison"]["verdict"] == "Consistent"]
    if not rows:
        label = "No comparable NHANES publications found"
    elif not comp:
        label = "Published studies found, but none report a comparable estimate in the abstract"
    elif len(agree) == len(comp):
        label = "Agrees with the published NHANES evidence" if cons else "Same direction as published studies, different size"
    elif not agree:
        label = "Disagrees with the published NHANES evidence"
    else:
        label = "Mixed agreement with published studies"
    return {"papers": len(rows), "comparable": len(comp), "same_direction": len(agree), "consistent": len(cons), "label": label,
            "score": round(100 * len(agree) / len(comp)) if comp else None}


def _memory_path() -> Path:
    from .config import settings
    return Path(settings.workspace) / "learned_evidence.json"


def topic_key(plan: dict) -> str:
    x = plan.get("exposure") or {}
    xs = "+".join(a["concept"] for a in x["arms"]["arms"]) if x.get("arms") else (x.get("concept") or "")
    return f"{plan['outcome'].get('concept') or plan['outcome']['variable']}|{xs}"


def remember(plan: dict, ev: dict) -> None:
    """Keep what was learned (methods used, published estimates) per topic, so later studies on the same topic use it
    even when PubMed is unreachable."""
    import json
    if not ev.get("papers"):
        return
    f = _memory_path()
    try:
        mem = json.loads(f.read_text()) if f.exists() else {}
    except Exception:  # noqa: BLE001
        mem = {}
    mem[topic_key(plan)] = {"checked": ev["checked"], "landscape": ev["landscape"], "summary": ev["summary"],
                            "published": [{"pmid": r["pmid"], "journal": r["journal"], "year": r["year"],
                                           "estimate": r["comparison"].get("published")} for r in ev["papers"][:12]]}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(mem, indent=1, default=str))


def recall(plan: dict) -> dict | None:
    import json
    f = _memory_path()
    try:
        return (json.loads(f.read_text()) if f.exists() else {}).get(topic_key(plan))
    except Exception:  # noqa: BLE001
        return None


def landscape(papers: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for p in papers:
        for m in set(p.get("methods") or []):
            counts[m] = counts.get(m, 0) + 1
    return {"papers": len(papers), "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1]))}


# ------------------------------------------------------------------ main entry
def check(plan: dict, results: dict | None = None, live: bool = True, retmax: int = 12, use_llm: bool = True,
          provider: str | None = None) -> dict:
    q = queries(plan)
    base = {"queries": q, "checked": dt.date.today().isoformat(), "source": "PubMed/MEDLINE (NCBI E-utilities)",
            "journals": sorted({j["group"] for j in journals()}),
            "method": "Rule-based extraction of estimates with 95% CIs from abstracts" + (", plus LLM extraction verified against the abstract text" if use_llm else "")
                      + "; our primary estimate is compared for direction and CI overlap.",
            "caveat": "Abstract-level comparison. Cycles, case definitions, covariates and exposure scaling differ between "
                      "studies, so read the paper before citing agreement or disagreement."}
    if not live:
        return {**base, "papers": [], "summary": _summary([]), "landscape": landscape([]), "error": "Live PubMed search disabled"}
    key = q["high_impact"] + "|" + str(retmax)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 86400:
        papers, scope = hit[1]
    else:
        try:
            ids = [p["pmid"] for p in literature.pubmed_search(q["high_impact"], retmax=retmax)]
            scope = "high-impact journals"
            if len(ids) < 3:
                more = [p["pmid"] for p in literature.pubmed_search(q["any_journal"], retmax=retmax)]
                ids = list(dict.fromkeys(ids + more))[:retmax]
                scope = "high-impact journals, topped up from any journal" if more else scope
            papers = fetch_abstracts(ids)
        except Exception as e:  # noqa: BLE001
            return {**base, "papers": [], "summary": _summary([]), "landscape": landscape([]), "error": f"PubMed unavailable: {e}"}
        _CACHE[key] = (time.time(), (papers, scope))
    client = None
    if use_llm:
        from .llm import LLMClient
        c = LLMClient(provider)
        client = c if c.enabled else None
    base["method"] = ("Rule-based extraction of estimates with 95% CIs from abstracts"
                      + (f", plus {client.provider.name} extraction verified against the abstract text" if client else "")
                      + "; our primary estimate is compared for direction and CI overlap.")
    ours = _ours(results, plan)
    terms = [q["terms"]["outcome"]] + q["terms"]["exposures"]
    rows = []
    for p in papers:
        ex = extract_rules(p["abstract"])
        llm_info = None
        if client:
            llm_info = extract_llm(client, p)
            if llm_info:
                known = {(e["measure"], e["value"], e["lcl"], e["ucl"]) for e in ex["estimates"] + ex["prevalence"]}
                for e in llm_info["estimates"]:
                    if (e["measure"], e["value"], e["lcl"], e["ucl"]) not in known:
                        (ex["prevalence"] if e["measure"] == "Prevalence %" else ex["estimates"]).append(e)
        row = {k: p[k] for k in ("pmid", "title", "journal", "year", "url")}
        row.update({"group": journal_group(p.get("journal_abbrev") or p["journal"]) or "Other journal",
                    "estimates": ex["estimates"], "prevalence": ex["prevalence"], "methods": ex["methods"], "n": ex["n"],
                    "years": ex["years"], "llm": ({"rejected": llm_info["rejected"], "kept": len(llm_info["estimates"])} if llm_info else None)})
        row["comparison"] = compare(ours, row, terms)
        rows.append(row)
    order = {"Consistent": 0, "Same direction, different size": 1, "Opposite direction": 2, "One estimate is null": 3,
             "Different measure": 4, "No numbers in abstract": 5, "Not compared": 6}
    rows.sort(key=lambda r: (r["group"] == "Other journal", order.get(r["comparison"]["verdict"], 9)))
    out = {**base, "scope": scope, "ours": ours, "papers": rows, "summary": _summary(rows), "landscape": landscape(rows),
           "llm": ({"provider": client.provider.name, "model": client.provider.model} if client else None), "error": None}
    try:
        remember(plan, out)
    except Exception:  # noqa: BLE001
        pass
    return out


def to_markdown(ev: dict) -> str:
    s = ev["summary"]
    L = ["# Checked against published NHANES studies", "",
         f"**{s['label']}** - {s['papers']} paper(s) found ({ev.get('scope', '')}); {s['comparable']} report a comparable estimate; "
         f"{s['same_direction']} agree in direction, {s['consistent']} with overlapping 95% CIs.", ""]
    if ev.get("ours"):
        o = ev["ours"]
        L.append(f"This study: {o['measure']} {o['value']:.3g} (95% CI {o['lcl']:.3g}-{o['ucl']:.3g}).\n")
    L.append("| Verdict | Published estimate | Journal (year) | Paper |\n|---|---|---|---|")
    for r in ev["papers"]:
        e = r["comparison"].get("published")
        est = f"{e['measure']} {e['value']:g} ({e['lcl']:g}-{e['ucl']:g})" if e else "-"
        L.append(f"| {r['comparison']['verdict']} | {est} | {r['journal']} ({r['year']}) | [{r['title'][:90]}]({r['url']}) |")
    lm = ev.get("landscape", {}).get("counts") or {}
    if lm:
        L.append("\n**Methods used in these papers:** " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in lm.items()))
    L.append(f"\n_{ev['method']} {ev['caveat']}_")
    if ev.get("error"):
        L.append(f"\n_{ev['error']}_")
    return "\n".join(L) + "\n"
