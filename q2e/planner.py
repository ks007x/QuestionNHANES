"""Rule-based research agents (always on).

These deterministic agents turn a natural-language question into a complete draft
study plan and critique it. They run with no network access, and they are also the
safety baseline when an LLM is configured: LLM output is merged into - and checked
against - what these rules produce (see agents.py).

Agents
  Investigator    - parses the question into PICO, study type and population
  Data Steward    - maps concepts to building blocks / guideline definitions / raw variables
  Epidemiologist  - confounders, mediators, definitional overlap, limitations
  Statistician    - estimands, model family, adjustment sets, missing data, sensitivity analyses
  Reviewer        - "Reviewer 2": blockers / major / minor issues with one-click fixes
"""
from __future__ import annotations

import copy
import datetime as _dt
import re
import uuid
from typing import Any

from . import expressions
from .knowledge import Knowledge, RAW_VAR_RANK, get_knowledge
from .language_guard import scan_causal

PREVALENCE_CUES = ["prevalence", "to estimate", "estimate the", "describe", "characterize", "cascade", "how common", "how many", "proportion", "burden", "frequency", "how frequent",
                   "percentage", "percent of", "what share", "estimate the number", "rate of", "distribution of"]
ASSOC_CUES = ["associat", "relationship", "related to", "relation", "linked", "link between", "correlat", "risk of",
              "worse", "better", "higher", "lower", "greater", "predict", "effect", "impact", "influence", "affect",
              "compare", "versus", " vs ", "differ", "tied to", "connected"]
SAME_WEIGHT_CUES = ["similar weight", "same weight", "independent of weight", "independent of bmi", "regardless of bmi",
                    "beyond bmi", "similar bmi", "same bmi", "adjusting for bmi", "adjusted for bmi", "independent of body mass",
                    "regardless of weight", "even at similar", "controlling for bmi", "accounting for bmi"]
OUT_OF_SCOPE_CUES = {"mortality": "mortality requires the NCHS linked mortality files",
                     "death": "deaths require the NCHS linked mortality files",
                     "survival": "survival requires longitudinal follow-up (linked mortality files)",
                     "incidence": "incidence requires longitudinal follow-up; NHANES is cross-sectional",
                     "over time": "temporal change requires multiple cycles and trend methods",
                     "trend": "trend analyses require multiple cycles",
                     "develop": "developing a condition implies incidence, which a cross-sectional survey cannot measure"}
GUIDELINE_HINTS: list[tuple[str, dict]] = [
    (r"kdigo\s*2012", {"prefer": ["ckd_iron_kdigo2012"], "upgrade": {"iron_deficiency": "ckd_iron_deficiency"}}),
    (r"kdigo", {"prefer": ["ckd_id_kdigo2026", "ckd_ire_kdigo2026"],
                "upgrade": {"iron_deficiency": "ckd_iron_deficiency", "functional_iron_deficiency": "ckd_iron_deficiency"}}),
    (r"\bash\b|american society of hematology", {"prefer": ["id_ash2026", "ida_ash2026"]}),
    (r"\bwho\b|world health organi[sz]ation", {"prefer": ["id_who2020", "anemia_who"]}),
    (r"baveno\s*(?:viii|8)", {"prefer": ["csph_baveno8", "cacld_baveno8"]}),
    (r"baveno\s*(?:vii|7)\b", {"prefer": ["csph_baveno7", "cacld_bin_baveno"]}),
    (r"\besc\b|heart[- ]failure definition", {"prefer": ["fid_esc_hf"]}),
    (r"tawfik|jama network open", {"prefer": ["fid_tawfik2024", "aid_tawfik2024"]}),
]
DEMOGRAPHIC_DOMAINS = {"demographic"}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


_STOP = set("""a an the of in on at to for with and or but by from as is are was were be been being do does did have has had may
might can could would should will shall i we you they he she it this that these those there their our my your its not no if than
then so such very more most less least about into over under among between within without across per vs versus what which who whom
whose how when where why whether any all each both either neither some many much also only just even after before
during following since""".split())
_RESEARCH_WORDS = set("""study studies research analysis analyze analyse investigate examine evaluate assess estimate estimating prevalence
association associations associated relationship relationships relation link links linked correlation correlated correlate risk risks
effect effects impact impacts influence influences higher lower greater worse better increased decreased elevated reduced level levels
people persons patients participants individuals adults adult population populations united states american americans nhanes national
survey data dataset noticed notice observed observe seems seem appear appears similar same likely common commonly frequency proportion
rate rates burden using use used based new current guideline guidelines criteria definition definitions years year old aged among
group groups compared compare comparing versus factor factors status measured measure measures having those whether something
amount amounts number numbers lead leads led cause causes caused causing result results contribute contributes drive drives
affect affects predict predicts worsen worsens improve improves explain explains like likes interested look looking want""".split())


_GENERIC = set("""treatment treatments treated medication medications medicine medicines therapy use user users status aware awareness
control controlled uncontrolled history problem problems condition conditions disease diseases test tests testing care health risk
factor factors cell cells count counts level levels value values score scores total infection infections outcome outcomes exposure
recommendation recommendations visit visits change changes""".split())


class HardStop(ValueError):
    """The question is outside what the dataset can answer; no plan is drafted."""
    def __init__(self, items):
        self.items = items
        super().__init__("Not answerable with NHANES: " + "; ".join(f"'{i['phrase']}' - {i['reason']}" for i in items))


AGE_PATTERNS = [
    (r"aged?\s+(\d{1,2})\s*(?:to|-|–|through|and)\s*(\d{1,2})", "range"),
    (r"(\d{1,2})\s*(?:to|-|–)\s*(\d{1,2})\s*(?:years|y\b|yrs)", "range"),
    (r"aged?\s+(\d{1,2})\s*(?:years\s*)?(?:and|or)\s*(?:older|over|above)", "min"),
    (r"(?:>=|≥|older than|over)\s*(\d{1,2})\s*(?:years|y\b|yrs)", "min"),
    (r"(?:<|younger than|under)\s*(\d{1,2})\s*(?:years|y\b|yrs)", "max"),
]


def parse_age(q: str) -> tuple[int | None, int | None]:
    for pat, kind in AGE_PATTERNS:
        m = re.search(pat, q)
        if m:
            if kind == "range":
                return int(m.group(1)), int(m.group(2))
            if kind == "min":
                return int(m.group(1)), None
            return None, int(m.group(1)) - 1
    return None, None


def _concept(cid: str, k: Knowledge) -> dict:
    """Curated concept, or a pseudo-concept for a dictionary-matched variable ('dict:VAR')."""
    if cid in k.concepts:
        return k.concepts[cid]
    if cid.startswith("dict:"):
        var = cid[5:]
        row = k.dictionary.get(var, {})
        return {"id": cid, "label": row.get("label", var), "domain": "default", "dict_var": var, "synonyms": []}
    raise KeyError(cid)


def _is_yesno(row: dict) -> bool:
    lab = row.get("label", "").lower()
    return row.get("type_guess") == "yesno" or "1=yes" in lab.replace(" ", "")


def residual_phrases(q: str, taken: list[tuple[int, int]]) -> list[str]:
    """Content-word chunks of the question not explained by any matched concept/population."""
    chars = list(q)
    for a, b in taken:
        for i in range(a, b):
            chars[i] = "|"
    text = "".join(chars)
    chunks, cur = [], []
    for tok in re.findall(r"[a-z0-9][a-z0-9\-']*|[^a-z0-9\s]", text):
        word = tok.strip("'")
        if (not re.match(r"[a-z]", word)) or word in _STOP or word in _RESEARCH_WORDS or len(word) < 3:
            if cur:
                chunks.append(" ".join(cur)); cur = []
            continue
        cur.append(word)
    if cur:
        chunks.append(" ".join(cur))
    return [c for c in dict.fromkeys(chunks)]


def dictionary_lookup(phrase: str, k: Knowledge) -> dict | None:
    """Best dataset variable for a free-text phrase; requires every content token to appear in the entry."""
    from .matcher import tokens as _tok
    want = set(_tok(phrase))
    if not want:
        return None
    if len(want) == 1:
        w = next(iter(want))
        idx0 = k.var_index()
        df = sum(1 for d in idx0.docs if w in d)
        if w in _GENERIC or df > 3 or len(w) < 5:
            return None     # a lone generic word ("treatment", "cell") is not a variable
    idx = k.var_index()
    for h in idx.search([phrase], top_k=5):
        doc = set(idx.docs[[e.variable for e in idx.entries].index(h["variable"])])
        if want <= doc and h["confidence"] >= 0.5:
            row = k.dictionary[h["variable"]]
            return {"phrase": phrase, "variable": h["variable"], "label": row["label"], "file": row["file"],
                    "cycles": row["cycles"], "curated": row.get("curated", False), "confidence": h["confidence"],
                    "binary": _is_yesno(row), "type": row["type"]}
    return None


def _spans(text: str, phrase: str) -> list[tuple[int, int]]:
    pat = r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])"
    return [(m.start(), m.end()) for m in re.finditer(pat, text)]


def _overlaps(a: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(a[0] < b[1] and b[0] < a[1] for b in taken)


# ---------------------------------------------------------------------------
# Investigator agent
# ---------------------------------------------------------------------------
def parse_question(question: str, k: Knowledge | None = None) -> dict[str, Any]:
    k = k or get_knowledge()
    q = " " + question.lower().replace("’", "'") + " "
    taken: list[tuple[int, int]] = []
    pops: list[tuple[int, str]] = []
    pop_phrases = sorted(((p, pop["id"]) for pop in k.populations for p in pop["patterns"]), key=lambda x: -len(x[0]))
    for phrase, pid in pop_phrases:
        for sp in _spans(q, phrase):
            if phrase.startswith("with ") and re.search(r"(associat\w*|link\w*|relat\w*|correlat\w*|connect\w*)\s*$", q[:sp[0]]):
                continue   # "associated with CKD" is an outcome, not a population
            if not _overlaps(sp, taken):
                taken.append(sp)
                pops.append((sp[0], pid))
    # out-of-scope topics and NHANES components without curated variables
    not_in, components = [], []
    for item in k.not_in_nhanes:
        for ph in sorted(item["phrases"], key=len, reverse=True):
            sps = _spans(q, ph)
            if sps:
                not_in.append({"phrase": ph, "severity": item["severity"], "reason": item["reason"], "suggestion": item["suggestion"],
                               "hard_stop": bool(item.get("hard_stop"))})
                taken.extend(sp for sp in sps if not _overlaps(sp, taken))
                break
    for item in k.component_synonyms:
        for ph in sorted(item["phrases"], key=len, reverse=True):
            sps = [sp for sp in _spans(q, ph) if not _overlaps(sp, taken)]
            if sps:
                components.append({"phrase": ph, "tables": item["tables"], "note": item["note"],
                                   "descriptions": {t: k.table_description(t) for t in item["tables"]}})
                taken.extend(sps)
                break
    concepts: list[tuple[int, str, str]] = []
    syns = sorted(((s, c["id"]) for c in k.concepts.values() for s in c["synonyms"]), key=lambda x: -len(x[0]))
    for phrase, cid in syns:
        for sp in _spans(q, phrase):
            if not _overlaps(sp, taken):
                taken.append(sp)
                concepts.append((sp[0], cid, phrase))
    # residual phrases -> full data dictionary (curated + catalog)
    unmapped, dict_matches = [], []
    for ph in residual_phrases(q, taken):
        m = dictionary_lookup(ph, k)
        if not m and " " in ph:          # try the longest sub-phrases
            words = ph.split()
            for n in range(len(words) - 1, 0, -1):
                for i in range(0, len(words) - n + 1):
                    sub = " ".join(words[i:i + n])
                    if len(sub) >= 4:
                        m = dictionary_lookup(sub, k)
                    if m:
                        break
                if m:
                    break
        if m:
            pos = q.find(m["phrase"].split()[0])
            dict_matches.append(m)
            concepts.append((pos if pos >= 0 else len(q), "dict:" + m["variable"], m["phrase"]))
        else:
            unmapped.append(ph)
    concepts.sort()
    pops.sort()
    hints: dict[str, Any] = {"prefer": [], "upgrade": {}, "matched": []}
    for pat, h in GUIDELINE_HINTS:
        if re.search(pat, q):
            hints["prefer"] += [p for p in h.get("prefer", []) if p not in hints["prefer"]]
            for a, b in h.get("upgrade", {}).items():
                hints["upgrade"].setdefault(a, b)
            hints["matched"].append(pat)
    # de-duplicate concepts preserving first occurrence
    seen, ordered = set(), []
    for pos, cid, phrase in concepts:
        cid = hints["upgrade"].get(cid, cid)
        if cid not in seen:
            seen.add(cid)
            ordered.append({"concept": cid, "phrase": phrase, "pos": pos})
    pop_ids = []
    for _, pid in pops:
        if pid not in pop_ids:
            pop_ids.append(pid)
    clinical = [c for c in ordered if _concept(c["concept"], k).get("domain") not in DEMOGRAPHIC_DOMAINS]
    demographic = [c for c in ordered if _concept(c["concept"], k).get("domain") in DEMOGRAPHIC_DOMAINS]
    has_prev = any(cue in q for cue in PREVALENCE_CUES)
    has_assoc = any(cue in q for cue in ASSOC_CUES)
    if len(clinical) >= 2 and (has_assoc or not has_prev):
        study_type = "association"
    elif len(clinical) == 1 and demographic and has_assoc and not has_prev:
        study_type = "association"
    else:
        study_type = "prevalence"
    outcome = exposure = None
    notes: list[str] = []
    if study_type == "association":
        if len(clinical) >= 2:
            first, second = clinical[0], clinical[1]
            between = q[first["pos"]: second["pos"]]
            if re.search(r"\b(among|in)\b.*\b(with|who have|having)\b", between):
                outcome, exposure = first, second
                notes.append("Ordering cue ('<outcome> among people with <exposure>') - first concept treated as outcome.")
            else:
                exposure, outcome = first, second
                notes.append("First clinical concept treated as exposure, second as outcome (swap in the UI if needed).")
        else:
            outcome, exposure = clinical[0], demographic[0]
    else:
        outcome = clinical[0] if clinical else None
    subgroup_concepts = [c["concept"] for c in demographic if not exposure or c["concept"] != exposure["concept"]]
    out_of_scope = [f"'{n['phrase']}': {n['reason']}" for n in not_in]
    return {
        "study_type": study_type,
        "outcome_concept": outcome["concept"] if outcome else None,
        "exposure_concept": exposure["concept"] if exposure else None,
        "extra_concepts": [c["concept"] for c in clinical[2:]] if study_type == "association" else [c["concept"] for c in clinical[1:]],
        "populations": pop_ids,
        "subgroup_concepts": subgroup_concepts,
        "hints": hints,
        "adjust_bmi": any(cue in q for cue in SAME_WEIGHT_CUES),
        "direction_continuous": bool(re.search(r"\b(greater|higher|more|increas\w*|larger|elevated|per)\b", q)),
        "out_of_scope": out_of_scope,
        "notes": notes,
        "matched_phrases": [{"concept": c["concept"], "phrase": c["phrase"]} for c in ordered],
        "not_in_nhanes": not_in,
        "component_matches": components,
        "dictionary_matches": dict_matches,
        "unmapped_terms": unmapped,
        "association_cue": has_assoc and not has_prev,
        "age_range": parse_age(q),
        "hard_stop": [n for n in not_in if n.get("hard_stop")],
    }


# ---------------------------------------------------------------------------
# Data Steward agent
# ---------------------------------------------------------------------------
def choose_variable(concept_id: str, role: str, hints: dict, k: Knowledge, prefer_continuous: bool = False) -> dict:
    if concept_id.startswith("dict:"):
        var = concept_id[5:]
        row = k.dictionary[var]
        binary = _is_yesno(row)
        name = "nh_" + var.lower()
        entry = {"concept": concept_id, "concept_label": row["label"], "variable": name, "kind": "custom",
                 "type": "binary" if binary else ("continuous" if row["type"] == "continuous" else "categorical"),
                 "label": row["label"], "definition_id": None, "alternatives": [], "companions": [], "domain": "default",
                 "custom": {"name": name, "expr": f"{var} == 1" if binary else var, "label": row["label"],
                            "type": "binary" if binary else ("continuous" if row["type"] == "continuous" else "categorical"),
                            "source": "dictionary", "confidence": 0.7 if row.get("curated") else 0.5, "raw": var}}
        if entry["type"] == "continuous" and role == "exposure":
            entry["scale"] = 1
            entry["units"] = row.get("units", "")
        return entry
    c = k.concepts[concept_id]
    defs = list(c.get("definitions", []))
    alt_defs = list(c.get("alt_definitions", []))
    block = c.get("block")
    preferred = [d for d in hints.get("prefer", []) if d in defs or d in alt_defs]
    if preferred:
        name = preferred[0]
        kind = "definition"
    elif defs and not (block and prefer_continuous):
        name, kind = defs[0], "definition"
    elif block:
        name, kind = block, "block"
    elif alt_defs:
        name, kind = alt_defs[0], "definition"
    else:
        raise ValueError(f"Concept {concept_id} has no variable")
    all_defs = [d for d in defs + alt_defs if d != name]
    vtype = k.var_type(name)
    entry = {"concept": concept_id, "concept_label": c["label"], "variable": name, "kind": kind, "type": vtype,
             "label": k.label(name), "definition_id": name if kind == "definition" else None,
             "alternatives": all_defs, "companions": c.get("companion_definitions", []), "domain": c.get("domain", "default")}
    if vtype == "continuous" and role == "exposure":
        entry["scale"] = c.get("default_scale", 1)
        entry["units"] = k.units(name)
    return entry


def _raw_dependencies(name: str, k: Knowledge, custom: dict[str, dict] | None = None, seen: set | None = None) -> set[str]:
    """Raw dataset variables a block/definition ultimately depends on."""
    custom = custom or {}
    seen = seen if seen is not None else set()
    if name in seen:
        return set()
    seen.add(name)
    if name in k.dictionary:
        return {name}
    expr = None
    if name in custom:
        expr = custom[name]["expr"]
    elif name in k.definitions:
        expr = k.definitions[name]["expr"]
    elif name in k.blocks:
        b = k.blocks[name]
        expr = b.get("nhanes") if b["tier"] == "measure" else b.get("expr")
    if not expr:
        return set()
    out: set[str] = set()
    for ident in expressions.identifiers(expr):
        out |= _raw_dependencies(ident, k, custom, seen)
    return out


def measure_dependencies(name: str, k: Knowledge, seen: set | None = None) -> set[str]:
    """Measure-tier building blocks a variable depends on."""
    seen = seen if seen is not None else set()
    if name in seen:
        return set()
    seen.add(name)
    if name in k.blocks and k.blocks[name]["tier"] == "measure":
        return {name}
    expr = k.definitions[name]["expr"] if name in k.definitions else (k.blocks[name].get("expr") if name in k.blocks else None)
    if not expr:
        return set()
    out: set[str] = set()
    for ident in expressions.identifiers(expr):
        out |= measure_dependencies(ident, k, seen)
    return out


def _top_args(expr: str, fn: str) -> list[str] | None:
    """If expr is exactly fn(...), return its top-level arguments."""
    e = expr.strip()
    if not (e.startswith(fn + "(") and e.endswith(")")):
        return None
    body, depth, cur, out, quote = e[len(fn) + 1:-1], 0, "", [], None
    for ch in body:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
        if ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    out.append(cur)
    return [a.strip() for a in out]


def _expr_missing(expr: str, k: Knowledge, gm: dict) -> list[str]:
    for fn in ("coalesce", "any_of"):
        args = _top_args(expr, fn)
        if args is not None:      # alternatives: available if any argument is available
            per = [_expr_missing(a, k, gm) for a in args]
            return [] if any(not m for m in per) else sorted({x for m in per for x in m})
    return sorted({m for i in expressions.identifiers(expr) for m in missing_measures(i, k, gm)})


def missing_measures(v: str, k: Knowledge, gm: dict) -> list[str]:
    """Measures a variable cannot do without in a mapped (generic) dataset. coalesce()/any_of()
    arguments are alternatives (e.g. TSAT from reported TSAT or from iron/TIBC)."""
    if v in k.blocks and k.blocks[v]["tier"] == "measure":
        return [] if gm.get(v) else [v]
    if v in k.blocks:
        return _expr_missing(k.blocks[v]["expr"], k, gm)
    if v in k.definitions:
        return _expr_missing(k.definitions[v]["expr"], k, gm)
    return []


def _expr_of(name: str, k: Knowledge, custom: dict | None = None) -> str | None:
    custom = custom or {}
    if name in custom:
        return custom[name]["expr"]
    if name in k.definitions:
        return k.definitions[name]["expr"]
    if name in k.blocks:
        b = k.blocks[name]
        return b.get("nhanes") if b["tier"] == "measure" else b.get("expr")
    return None


def available_cycles(name: str, k: Knowledge, custom: dict | None = None, _seen: set | None = None) -> set[str]:
    """NHANES cycles in which a variable can be computed. coalesce() arguments are alternative
    measurement protocols (union of cycles); all other inputs are required (intersection)."""
    _seen = _seen if _seen is not None else set()
    if name in k.dictionary:
        return set(k.dictionary[name]["cycles"])
    if name in _seen:
        return set(k.cycles)
    _seen.add(name)
    expr = _expr_of(name, k, custom)
    return _expr_cycles(expr, k, custom, _seen) if expr else set(k.cycles)


def _expr_cycles(expr: str, k: Knowledge, custom: dict | None, _seen: set) -> set[str]:
    args = _top_args(expr, "coalesce")
    if args is not None:
        out: set[str] = set()
        for a in args:
            out |= _expr_cycles(a, k, custom, set(_seen))
        return out
    out = set(k.cycles)
    for i in expressions.identifiers(expr):
        out &= available_cycles(i, k, custom, set(_seen))
    return out


def needed_measures(plan: dict, k: Knowledge) -> set[str]:
    """Measure-tier building blocks required by every variable/criterion in the plan."""
    names = [plan["outcome"]["variable"]] + ([plan["exposure"]["variable"]] if plan.get("exposure") else [])
    names += plan.get("covariates", []) + plan.get("subgroups", []) + plan.get("table1_vars", []) + plan.get("prevalence_outcomes", [])
    for c in plan.get("population", []):
        if c.get("enabled", True):
            names += expressions.identifiers(c["expr"])
    for s in plan.get("sensitivity", []):
        if s.get("enabled", True):
            names += expressions.identifiers(s["expr"]) if s.get("expr") else []
            names += [s[x] for x in ("outcome", "exposure") if s.get(x)]
    out: set[str] = set()
    for n in names:
        out |= measure_dependencies(n, k)
    return out


def variable_map(plan: dict, k: Knowledge) -> list[dict]:
    """Concept -> variable -> raw NHANES variables/files, with availability per cycle."""
    cycles = plan["dataset"].get("cycles", k.default_cycles) if plan["dataset"].get("type", "nhanes") == "nhanes" else []
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    gm = plan.get("generic_mapping", {}) or {}
    rows = []
    names = []
    roles = {}
    if plan.get("outcome"):
        names.append(plan["outcome"]["variable"]); roles[plan["outcome"]["variable"]] = "Outcome"
    if plan.get("exposure"):
        names.append(plan["exposure"]["variable"]); roles[plan["exposure"]["variable"]] = "Exposure"
    for n in plan.get("covariates", []):
        roles.setdefault(n, "Covariate"); names.append(n)
    for n in plan.get("subgroups", []):
        roles.setdefault(n, "Subgroup"); names.append(n)
    for s in plan.get("sensitivity", []):
        for key in ("outcome", "exposure"):
            if s.get(key):
                roles.setdefault(s[key], "Sensitivity"); names.append(s[key])
    for d in plan.get("prevalence_outcomes", []):
        roles.setdefault(d, "Secondary outcome"); names.append(d)
    done = set()
    for n in names:
        if n in done:
            continue
        done.add(n)
        raw = sorted(_raw_dependencies(n, k, custom))
        files = sorted({k.dictionary[r]["file"] for r in raw if r in k.dictionary})
        avc = available_cycles(n, k, custom)
        avail = {cy: cy in avc for cy in cycles}
        if n in custom:
            expr, source, kind = custom[n]["expr"], custom[n].get("source", "investigator"), "custom"
        elif n in k.definitions:
            expr, source, kind = k.definitions[n]["expr"], k.definitions[n]["source"].get("citation", ""), "definition"
        else:
            b = k.blocks.get(n, {})
            expr = b.get("nhanes") if b.get("tier") == "measure" else b.get("expr")
            source, kind = b.get("source", "Q2E building block"), b.get("tier", "block")
        if not cycles and kind == "measure":
            expr = gm.get(n) or ""
            raw = [expr] if expr else []
        direct = kind == "measure" and (expr in k.dictionary or (not cycles and bool(expr)))
        rows.append({
            "variable": n, "label": k.label(n) if n not in custom else custom[n].get("label", n), "role": roles.get(n, ""),
            "kind": kind, "direct": direct, "expr": expr, "raw_variables": raw,
            "files": {cy: [k.file_name(f, cy) for f in files] for cy in cycles},
            "available": avail, "source": source,
            "status": k.definitions[n].get("status") if n in k.definitions else ("ai-proposed" if n in custom and custom[n].get("source") == "ai"
                                                                                  else "dictionary-match" if n in custom and custom[n].get("source") == "dictionary" else "curated"),
            "confidence": 1.0 if n not in custom else custom[n].get("confidence", 0.6),
        })
    return rows


# ---------------------------------------------------------------------------
# Statistician + Epidemiologist agents -> full draft plan
# ---------------------------------------------------------------------------
def _criteria_from_population(pid: str, k: Knowledge) -> list[dict]:
    pop = next(p for p in k.populations if p["id"] == pid)
    return [{"label": c["label"], "expr": c["expr"], "kind": "inclusion", "source": f"question ('{pid}')"} for c in pop["criteria"]]


def build_plan(question: str, parsed: dict, cycles: list[str] | None = None, dataset: dict | None = None,
               k: Knowledge | None = None) -> dict[str, Any]:
    k = k or get_knowledge()
    cycles = cycles or list(k.default_cycles)
    if parsed.get("hard_stop"):
        raise HardStop(parsed["hard_stop"])
    if not parsed.get("outcome_concept"):
        raise ValueError("Could not identify a clinical outcome in the question. Try naming the condition or measurement "
                         "(e.g. 'functional iron deficiency', 'HbA1c', 'liver stiffness').")
    if parsed.get("hard_stop"):
        raise HardStop(parsed["hard_stop"])
    hints = parsed["hints"]
    outcome = choose_variable(parsed["outcome_concept"], "outcome", hints, k)
    exposure = None
    if parsed["study_type"] == "association" and parsed.get("exposure_concept"):
        exposure = choose_variable(parsed["exposure_concept"], "exposure", hints, k, prefer_continuous=parsed.get("direction_continuous", False))
    agent_notes: list[dict] = []
    for n in parsed.get("notes", []):
        agent_notes.append({"agent": "Investigator", "message": n})

    # ---------------- population ----------------
    criteria: list[dict] = []
    pops = list(parsed["populations"])
    lo, hi = parsed.get("age_range") or (None, None)
    if lo is not None or hi is not None:
        pops = [p for p in pops if p not in ("adults", "older_adults", "children")]
        expr = " & ".join(x for x in (f"age >= {lo}" if lo is not None else "", f"age <= {hi}" if hi is not None else "") if x)
        label = f"Age {lo}-{hi} years" if lo is not None and hi is not None else (f"Age >={lo} years" if lo is not None else f"Age <={hi} years")
        criteria.append({"label": label, "expr": expr, "kind": "inclusion", "source": "question (age range)"})
        if (lo or 0) < 18:
            agent_notes.append({"agent": "Epidemiologist", "message": "Population includes participants <18 y: some components (e.g. education, PHQ-9, alcohol) are adult-only; the probe will show real counts."})
    elif not any(p in pops for p in ("adults", "older_adults", "women_repro", "children")):
        pops.insert(0, "adults")
        agent_notes.append({"agent": "Investigator", "message": "No age group specified - defaulted to adults aged >=18 years."})
    for pid in pops:
        criteria += _criteria_from_population(pid, k)
    concept_ids = [outcome["concept"]] + ([exposure["concept"]] if exposure else [])
    for cid in concept_ids:
        imp = _concept(cid, k).get("implies_population")
        if imp and imp not in pops:
            criteria += _criteria_from_population(imp, k)
            pops.append(imp)
            agent_notes.append({"agent": "Epidemiologist", "message": f"'{_concept(cid, k)['label']}' is defined within {imp.upper()} - population restricted accordingly."})
    out_def = k.definitions.get(outcome["variable"]) if outcome["kind"] == "definition" else None
    if out_def and out_def.get("population_hint") and not any(out_def["population_hint"] in c["expr"] for c in criteria):
        hint_ids = expressions.identifiers(out_def["population_hint"])
        if not (("ckd" in hint_ids) and "ckd" in pops):
            criteria.append({"label": f"Definition scope: {out_def['population_hint']}", "expr": out_def["population_hint"],
                             "kind": "inclusion", "source": f"definition {out_def['id']}"})
    domains = []
    for v in (outcome, exposure):
        if v and v["domain"] not in domains:
            domains.append(v["domain"])
    dom_cfgs = [k.domains.get(d, k.domains["default"]) for d in domains] or [k.domains["default"]]
    for d, cfg in zip(domains, dom_cfgs):
        req = cfg.get("required_measures", [])
        if req:
            if req == ["lsm_valid"]:
                expr, label = "lsm_valid == 1", "Reliable liver elastography (complete exam, IQR/median <30%)"
            elif req == ["diet_reliable"]:
                expr, label = "diet_reliable == 1", "Reliable day-1 dietary recall"
            else:
                expr = " & ".join(f"!is.na({r})" for r in req)
                label = "Measured " + ", ".join(k.label(r).lower() for r in req)
            if not any(c["expr"] == expr for c in criteria):
                criteria.append({"label": label, "expr": expr, "kind": "inclusion", "source": f"{d} domain requirement"})
    for cfg in dom_cfgs:
        for ex in cfg.get("exclusions", []):
            if any(c["expr"] == ex["expr"] for c in criteria):
                continue
            if "pregnant" in pops and "pregnant" in ex["expr"]:
                continue
            criteria.append({"label": ex["label"], "expr": ex["expr"], "kind": "exclusion", "source": "domain default",
                             "optional": ex.get("optional", False), "enabled": not ex.get("optional", False)})
    for i, c in enumerate(criteria):
        c.setdefault("enabled", True)
        c["id"] = f"c{i + 1}"
    single_sex = any(p in pops for p in ("women", "men", "women_repro", "pregnant"))

    # ---------------- covariates ----------------
    covs: list[str] = []
    for cfg in dom_cfgs:
        for cv in cfg["covariates"]:
            if cv not in covs:
                covs.append(cv)
    cov_notes: dict[str, str] = {}
    if parsed.get("adjust_bmi") and "bmi" not in covs:
        covs.append("bmi")
        cov_notes["bmi"] = "Added because the question asks about the association 'at similar weight' (independent of BMI)."
    elif parsed.get("adjust_bmi"):
        cov_notes["bmi"] = "Retained - the question asks about the association independent of overall weight."
    if single_sex and "sex" in covs:
        covs.remove("sex")
    if "ckd" in pops and "ckd" in covs:
        covs.remove("ckd")
    # remove covariates that are the outcome/exposure or overlap them definitionally
    key_vars = [v["variable"] for v in (outcome, exposure) if v]
    custom_map = {v["custom"]["name"]: v["custom"] for v in (outcome, exposure) if v and v.get("custom")}
    key_raw = set().union(*[_raw_dependencies(v, k, custom_map) for v in key_vars]) if key_vars else set()
    for cv in list(covs):
        if cv in key_vars:
            covs.remove(cv)
            continue
        overlap = _raw_dependencies(cv, k) & key_raw
        demographic_raw = {"RIAGENDR", "RIDAGEYR", "RIDEXPRG"}
        if overlap - demographic_raw:
            covs.remove(cv)
            agent_notes.append({"agent": "Epidemiologist", "message": f"Removed covariate '{k.label(cv)}': it shares {', '.join(sorted(overlap - demographic_raw))} "
                                                                       f"with the outcome/exposure (definitional overlap)."})
    for flag in k.causal_flags:
        if exposure and ({flag["exposure"], flag["outcome"]} == {exposure["concept"], outcome["concept"]} if flag["role"] == "measurement_overlap"
                         else (flag["exposure"] == exposure["concept"] and flag["outcome"] == outcome["concept"])):
            if flag["role"] in ("mediator_or_outcome", "definitional") and flag["variable"] in covs:
                covs.remove(flag["variable"])
            agent_notes.append({"agent": "Epidemiologist", "message": f"{k.label(flag['variable'])}: {flag['note']}"})
            if flag["role"] == "intended_adjustment":
                cov_notes[flag["variable"]] = flag["note"]

    # ---------------- subgroups ----------------
    subgroups: list[str] = []
    for cfg in dom_cfgs:
        for sg in cfg.get("subgroups", []):
            if sg not in subgroups:
                subgroups.append(sg)
    for cid in parsed.get("subgroup_concepts", []):
        b = _concept(cid, k).get("block")
        if b and b not in subgroups:
            subgroups.append(b)
    if single_sex and "sex" in subgroups:
        subgroups.remove("sex")
    if "older_adults" in pops and "agecat" in subgroups:
        subgroups.remove("agecat")
    if exposure:
        subgroups = [s for s in subgroups if s != exposure["variable"]]

    # ---------------- model ----------------
    otype = outcome["type"]
    study_type = parsed["study_type"]
    if otype == "categorical" and study_type == "association":
        bin_alt = [a for a in outcome["alternatives"] if k.var_type(a) == "binary"]
        if bin_alt:
            agent_notes.append({"agent": "Statistician", "message": f"Categorical outcome replaced by binary definition '{k.label(bin_alt[0])}' for regression; "
                                                                     f"categories reported descriptively."})
            outcome = {**outcome, "variable": bin_alt[0], "label": k.label(bin_alt[0]), "type": "binary", "definition_id": bin_alt[0],
                       "alternatives": [a for a in outcome["alternatives"] if a != bin_alt[0]] + [outcome["variable"]]}
            otype = "binary"
    if otype == "binary":
        family = "quasipoisson"
        rationale = ("Binary outcome: survey-weighted quasi-Poisson regression with log link estimates prevalence ratios (PRs). "
                     "PRs are preferred to odds ratios for cross-sectional data because ORs exaggerate associations when the "
                     "outcome is common (>10%); the quasi-Poisson variance is robust under the design-based (Taylor linearization) "
                     "estimator. Logistic regression is run as a sensitivity analysis.")
    elif otype == "continuous":
        family = "gaussian"
        rationale = ("Continuous outcome: survey-weighted linear regression (design-based Taylor-series SEs) estimates adjusted "
                     "mean differences. A binary clinical threshold of the outcome is analysed as a sensitivity analysis.")
    else:
        family = "quasipoisson"
        rationale = "Categorical outcome: weighted category prevalences with Korn-Graubard CIs; regression on a binary contrast."
    if study_type == "prevalence":
        rationale = ("Prevalence estimand: survey-weighted proportions with Korn-Graubard (beta) 95% CIs, overall and by "
                     "subgroup, assessed against NCHS presentation standards; population counts from weighted totals. "
                     "Adjusted correlates are estimated with survey-weighted quasi-Poisson regression (prevalence ratios). ") + (
                     "" if otype == "binary" else "")

    # adjustment sets
    if study_type == "association":
        demo = [c for c in ("age", "sex", "race_eth") if c in covs]
        adjustment_sets = [{"id": "crude", "label": "Unadjusted", "covariates": []}]
        if demo and demo != covs:
            adjustment_sets.append({"id": "demographic", "label": "Adjusted for " + _join([_lc(k.label(d)) for d in demo]), "covariates": demo})
        adjustment_sets.append({"id": "full", "label": "Fully adjusted (primary)", "covariates": covs})
        interactions = [s for s in subgroups if s in ("sex", "agecat")]
    else:
        corr = []
        for v in subgroups + covs:
            if v == "age" and "agecat" in subgroups:
                continue
            if v == "pir" and "pir_cat" in subgroups:
                continue
            if v not in corr:
                corr.append(v)
        adjustment_sets = [{"id": "full", "label": "Mutually adjusted correlates", "covariates": corr}] if otype == "binary" else []
        interactions = []

    # ---------------- secondary outcomes ----------------
    prevalence_outcomes = []
    if otype in ("binary", "categorical"):
        prevalence_outcomes.append(outcome["variable"])
        for d in outcome.get("companions", []) + outcome.get("alternatives", []):
            if d in k.definitions and d not in prevalence_outcomes and k.definitions[d]["type"] in ("binary", "categorical"):
                prevalence_outcomes.append(d)
    elif study_type == "association":
        prevalence_outcomes = [a for a in outcome.get("alternatives", []) if k.var_type(a) == "binary"][:1]
    co_primary = []
    if study_type == "prevalence":
        for cid in parsed.get("extra_concepts", []):
            try:
                v = choose_variable(cid, "outcome", hints, k)
            except (ValueError, KeyError):
                continue
            if v["type"] in ("binary", "categorical") and v["variable"] not in prevalence_outcomes:
                co_primary.append(v)
                prevalence_outcomes.insert(len(co_primary), v["variable"])
        if co_primary:
            agent_notes.append({"agent": "Statistician", "message": "Co-primary prevalence outcomes: " + ", ".join(v["label"] for v in [outcome] + co_primary) + "."})

    # ---------------- sensitivity analyses ----------------
    sens: list[dict] = []

    def add_s(item: dict) -> None:
        item["id"] = f"s{len(sens) + 1}"
        item.setdefault("enabled", True)
        sens.append(item)

    for alt in outcome.get("alternatives", []):
        if k.var_type(alt) in ("binary",) or (otype == "continuous" and k.var_type(alt) == "binary"):
            fam_override = "quasipoisson" if otype == "continuous" else None
            item = {"type": "alt_outcome", "label": f"Alternative outcome definition: {k.definitions[alt].get('short', alt)}" if alt in k.definitions else f"Alternative outcome: {k.label(alt)}",
                    "outcome": alt}
            if fam_override:
                item["family"] = fam_override
                item["label"] = f"Binary outcome: {k.label(alt)} (PR)"
            add_s(item)
    for cfg in dom_cfgs:
        for s in cfg.get("sensitivity", []):
            if not any(x.get("expr") == s["expr"] for x in sens):
                add_s({"type": s["type"], "label": s["label"], "expr": s["expr"]})
    for c in criteria:
        if c.get("optional") and not c.get("enabled"):
            lab = c["label"].replace("Pregnant at examination", "pregnant participants")
            add_s({"type": "exclude", "label": lab if lab.lower().startswith("exclude") else "Exclude " + lab[0].lower() + lab[1:], "expr": c["expr"]})
    if study_type == "association":
        if otype == "binary":
            add_s({"type": "alt_family", "label": "Logistic regression (odds ratio)", "family": "quasibinomial"})
        add_s({"type": "mi", "label": "Multiple imputation of missing covariates (m = 10)", "m": 10})
        if exposure and exposure["type"] == "continuous":
            add_s({"type": "exposure_quartiles", "label": "Exposure in weighted quartiles (Q4 vs Q1, P for trend)"})
        if exposure:
            for alt in exposure.get("alternatives", []):
                add_s({"type": "alt_exposure", "label": f"Alternative exposure: {k.label(alt)}", "exposure": alt})
    add_s({"type": "unweighted", "label": "Unweighted analysis (design ignored)"})

    # ---------------- table 1 ----------------
    t1 = []
    for v in ["agecat", "sex", "race_eth", "pir_cat", "educ"] + covs:
        if (v == "age" and "agecat" in t1) or (v == "pir" and "pir_cat" in t1):
            continue
        if single_sex and v == "sex":
            continue
        if v not in t1 and v not in key_vars:
            t1.append(v)
    for v in key_vars:
        for m in _key_measures(v, k):
            if m not in t1 and m not in ("age",):
                t1.append(m)
    if study_type == "association" and exposure and exposure["variable"] not in t1:
        t1.append(exposure["variable"])
    if study_type == "association" and outcome["variable"] not in t1 and otype == "continuous":
        t1.append(outcome["variable"])
    if otype == "binary":
        t1_by = outcome["variable"]
    elif exposure and exposure["type"] in ("binary", "categorical"):
        t1_by = exposure["variable"]
    elif exposure and [a for a in exposure.get("alternatives", []) if k.var_type(a) == "binary"]:
        t1_by = [a for a in exposure["alternatives"] if k.var_type(a) == "binary"][0]
    else:
        t1_by = None
    if t1_by and t1_by in t1:
        t1.remove(t1_by)

    # ---------------- benchmark ----------------
    benchmarks = []
    default_pop = all(c.get("source", "").startswith(("question ('adults'", "iron domain", "domain default")) or not c.get("enabled", True)
                      for c in criteria)
    for d in prevalence_outcomes:
        bm = k.definitions.get(d, {}).get("benchmark")
        if bm and set(bm.get("cycles", [])) == set(cycles) and default_pop and study_type == "prevalence":
            benchmarks.append({**bm, "outcome": d})

    # ---------------- text ----------------
    pop_text = _population_text(criteria, cycles, k)
    olabel = outcome["label"]
    if study_type == "prevalence":
        refined = (f"Among {pop_text}, what is the survey-weighted prevalence of {_lc(outcome['concept_label'])} "
                   f"({_crit(outcome, k)})"
                   f"{', overall and by ' + _join([_lc(k.label(s)) for s in subgroups]) if subgroups else ''}?")
        hypothesis = (f"{outcome['concept_label']} is common in this population and varies by "
                      f"{_join([_lc(k.label(s)) for s in subgroups]) or 'demographic characteristics'}.")
        names = [outcome["concept_label"]] + [v["concept_label"] for v in co_primary]
        pop_short = _pop_short(pops)
        if lo is not None or hi is not None:
            noun = "Females" if any(p in pops for p in ("women", "women_repro")) else "Males" if "men" in pops else "Individuals"
            rng = f"Aged {lo}-{hi} Years" if lo is not None and hi is not None else (f"Aged {lo} Years or Older" if lo is not None else f"Younger Than {hi + 1} Years")
            pop_short = f"US {noun} {rng}"
        title = f"Prevalence of {_title(_join(names))} Among {_title(pop_short)}: A Cross-Sectional Analysis of {_cycle_text(cycles, k)}"
        pico = {"population": pop_text, "exposure": "Not applicable (descriptive prevalence); subgroups: " + (_join([k.label(s) for s in subgroups]) or "none"),
                "comparator": "Subgroup contrasts (prevalence ratios)", "outcome": f"{olabel}",
                "covariates": _join([k.label(c) for c in adjustment_sets[0]["covariates"]]) if adjustment_sets else "None (descriptive)",
                "design": "Cross-sectional, nationally representative complex survey"}
    else:
        unit = f" (per {exposure['scale']} {exposure.get('units', '')})".rstrip() if exposure.get("scale", 1) not in (None, 1) else ""
        direction = "higher" if otype == "continuous" else "a higher prevalence of"
        refined = (f"Among {pop_text}, is {('greater ' if exposure['type'] == 'continuous' else '')}{_lc(exposure['label'])}{unit} associated with "
                   f"{direction} {_lc(olabel)}, after adjustment for {_join([_lc(k.label(c)) for c in covs])}?")
        hypothesis = (f"{('Greater ' + _lc(exposure['label'])) if exposure['type'] == 'continuous' else exposure['label']} is associated with {direction} {_lc(olabel)}"
                      f"{' independent of BMI' if 'bmi' in covs and parsed.get('adjust_bmi') else ''}.")
        hypothesis = hypothesis[0].upper() + hypothesis[1:]
        title = f"Association of {_title(exposure['concept_label'])} With {_title(outcome['concept_label'])} Among {_title(_pop_short(pops))}: {_cycle_text(cycles, k)}"
        pico = {"population": pop_text, "exposure": exposure["label"] + unit,
                "comparator": "Lower levels of the exposure (per-unit contrast; quartile 1 in sensitivity analysis)" if exposure["type"] == "continuous" else "Participants without the exposure",
                "outcome": olabel, "covariates": _join([k.label(c) for c in covs]), "design": "Cross-sectional, nationally representative complex survey"}

    limitations = [
        "Cross-sectional design: temporality cannot be established and associations must not be interpreted causally.",
        "Single measurement of laboratory values; within-person variability and chronicity cannot be assessed.",
        "Residual confounding by unmeasured or imperfectly measured factors (e.g., diet, medications, menstrual blood loss).",
        "Self-reported comorbidities and behaviours are subject to recall and social-desirability bias.",
        "NHANES excludes institutionalized and active-duty military populations.",
    ]
    for v in key_vars:
        if v in k.definitions:
            for n in k.definitions[v].get("operational_notes", []):
                limitations.append(f"Operational definition ({k.definitions[v].get('short', v)}): {n}")
    for flag in k.causal_flags:
        if exposure and flag["role"] == "measurement_overlap" and {flag["exposure"], flag["outcome"]} == {exposure["concept"], outcome["concept"]}:
            limitations.append("Measurement overlap: " + flag["note"])
    if any(k.dictionary.get(r, {}).get("weight_level") == "fasting" for v in key_vars + covs for r in _raw_dependencies(v, k)):
        limitations.append("Fasting-subsample variables restrict the analysis to the morning fasting subsample (fasting weights).")
    if parsed.get("out_of_scope"):
        for m in parsed["out_of_scope"]:
            agent_notes.append({"agent": "Epidemiologist", "message": f"Scope: {m}. Q2E will estimate cross-sectional associations only."})

    epi_rationale = _epi_rationale(outcome, exposure, covs, cov_notes, k)
    plan = {
        "plan_id": "plan_" + uuid.uuid4().hex[:10], "version": 1, "status": "draft", "created": _now(),
        "question": question, "refined_question": refined, "title": title, "hypothesis": hypothesis,
        "study_type": study_type, "design": "cross-sectional",
        "dataset": dataset or {"type": "nhanes", "cycles": cycles, "source": "auto"},
        "pico": pico,
        "outcome": outcome, "exposure": exposure,
        "population": criteria,
        "covariates": covs, "covariate_notes": cov_notes,
        "subgroups": subgroups, "interactions": interactions,
        "model": {"family": family, "rationale": rationale, "primary_set": "full"},
        "adjustment_sets": adjustment_sets,
        "missing_data": {"method": "complete_case", "rationale": "Complete-case primary analysis within the design; multiple imputation by chained equations as sensitivity analysis when covariates are missing."},
        "prevalence_outcomes": prevalence_outcomes, "prevalence_by": subgroups,
        "sensitivity": sens,
        "table1_vars": t1, "table1_by": t1_by,
        "benchmarks": benchmarks,
        "custom_variables": [v["custom"] for v in [outcome, exposure] + co_primary if v and v.get("custom")],
        "co_primary": [{"variable": v["variable"], "label": v["label"], "concept": v["concept"]} for v in co_primary],
        "rationale": {"statistician": rationale, "epidemiologist": epi_rationale},
        "limitations": limitations,
        "agent_notes": agent_notes,
        "acknowledgements": {},
        "approvals": [],
        "parsed": parsed,
    }
    if dataset and dataset.get("type") == "generic":
        plan["dataset"] = dataset
    return plan


def _crit(var: dict, k: Knowledge) -> str:
    if var["kind"] == "definition":
        ct = k.definitions[var["variable"]].get("criteria_text", "").strip().rstrip(".")
        if ct and len(ct) <= 130:
            return ct[0].lower() + ct[1:] if not ct[:2].isupper() else ct
        return k.definitions[var["variable"]].get("label", var["label"])
    return var["label"]


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


_SMALL = {"of", "and", "in", "a", "an", "the", "for", "to", "vs", "or", "on", "at", "by"}


def _cap(w: str) -> str:
    for i, ch in enumerate(w):
        if ch.isalpha():
            return w[:i] + ch.upper() + w[i + 1:]
    return w


def _title(s: str) -> str:
    words = s.split()
    return " ".join(w if (any(c.isupper() for c in w[1:]) or (i > 0 and w.lower() in _SMALL)) else _cap(w) for i, w in enumerate(words))


def _lc(label: str) -> str:
    """Lower-case a label for running text but keep acronyms (HbA1c, BMI, CKD)."""
    out = []
    for w in label.split():
        if any(c.isupper() for c in w[1:]) or (len(w) > 1 and w.isupper()):
            out.append(w)
        else:
            out.append(w.lower())
    return " ".join(out)


def _key_measures(v: str, k: Knowledge) -> list[str]:
    """Continuous building blocks directly referenced by a definition (or the block itself)."""
    if v in k.blocks:
        return [v] if k.blocks[v]["type"] == "continuous" else []
    if v in k.definitions:
        return [i for i in expressions.identifiers(k.definitions[v]["expr"]) if i in k.blocks and k.blocks[i]["type"] == "continuous"]
    return []


def _pop_short(pops: list[str]) -> str:
    if "pregnant" in pops:
        return "pregnant individuals in the US"
    if "women_repro" in pops:
        base = "US women of reproductive age"
    elif "women" in pops:
        base = "US women"
    elif "men" in pops:
        base = "US men"
    elif "older_adults" in pops:
        base = "US older adults"
    elif "children" in pops:
        base = "US children and adolescents"
    else:
        base = "US adults"
    if "ckd" in pops:
        base += " with CKD"
    if "diabetes" in pops:
        base += " with diabetes"
    return base


def _cycle_text(cycles: list[str], k: Knowledge) -> str:
    return " + ".join(k.cycles[c]["label"] for c in cycles)


def _population_text(criteria: list[dict], cycles: list[str], k: Knowledge) -> str:
    inc = [c["label"] for c in criteria if c["kind"] == "inclusion" and c.get("enabled", True)]
    exc = [c["label"] for c in criteria if c["kind"] == "exclusion" and c.get("enabled", True)]
    txt = f"noninstitutionalized US participants in {_cycle_text(cycles, k)} ({'; '.join(inc)}"
    if exc:
        txt += "; excluding " + "; ".join(e.lower() for e in exc)
    return txt + ")"


def _epi_rationale(outcome, exposure, covs, cov_notes, k) -> str:
    parts = []
    if exposure:
        parts.append(f"Covariates were selected as plausible common causes of {_lc(exposure['label'])} and {_lc(outcome['label'])} "
                     f"(minimal confounder set from the domain library): {_join([k.label(c) for c in covs])}.")
    else:
        parts.append(f"Correlates model includes {_join([k.label(c) for c in covs])} to describe independent associations with "
                     f"{_lc(outcome['label'])}; these are descriptive, not causal, contrasts.")
    for v, note in cov_notes.items():
        parts.append(f"{k.label(v)}: {note}")
    parts.append("Variables on the causal pathway or sharing laboratory components with the outcome/exposure are excluded to avoid over-adjustment.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Reviewer agent
# ---------------------------------------------------------------------------
def review_plan(plan: dict, k: Knowledge | None = None) -> list[dict]:
    k = k or get_knowledge()
    issues: list[dict] = []

    def add(sev, title, detail, fix=None, iid=None):
        issues.append({"id": iid or f"r{len(issues) + 1}", "severity": sev, "agent": "Reviewer", "title": title,
                       "detail": detail, "fix": fix})

    cycles = plan["dataset"].get("cycles", [])
    if plan["dataset"].get("type") == "generic":
        gm = plan.get("generic_mapping", {}) or {}

        def unmapped_key(v):
            return missing_measures(v, k, gm)
        crit = [plan["outcome"]["variable"]] + ([plan["exposure"]["variable"]] if plan.get("exposure") else []) + plan.get("covariates", [])
        for c in plan["population"]:
            if c.get("enabled") and c["kind"] == "inclusion":
                crit += expressions.identifiers(c["expr"])
        for b in sorted({m for v in crit for m in unmapped_key(v)}):
            add("blocker", f"'{k.label(b)}' not mapped to a dataset column",
                "Map this building block to a column (or expression) in the Data map tab, or remove the variable/criterion that needs it.", None, f"unmapped_{b}")
    if "J" in cycles and "P" in cycles:
        add("blocker", "Overlapping survey cycles", "2017-2018 (J) participants are already inside the 2017-March 2020 pre-pandemic file (P).",
            {"op": "set_cycles", "value": [c for c in cycles if c != "J"]}, "cycle_overlap")
    if plan["dataset"].get("type") == "nhanes":
        for row in variable_map(plan, k):
            missing = [cy for cy, ok in row["available"].items() if not ok]
            if missing and row["role"] in ("Outcome", "Exposure", "Covariate"):
                add("blocker" if row["role"] in ("Outcome", "Exposure") else "major",
                    f"{row['label']} unavailable in {', '.join(missing)}",
                    f"Requires {', '.join(row['raw_variables'])}, not released in cycle(s) {', '.join(missing)}.",
                    {"op": "remove_covariate", "name": row["variable"]} if row["role"] == "Covariate" else None,
                    f"avail_{row['variable']}")
    texts = {"question": plan.get("question", ""), "hypothesis": plan.get("hypothesis", ""), "refined_question": plan.get("refined_question", "")}
    for field, txt in texts.items():
        hits = scan_causal(txt)
        if hits and field != "question":
            add("major", f"Causal language in {field.replace('_', ' ')}", f"'{hits[0]['phrase']}' implies causation; a cross-sectional design supports association only.",
                {"op": "soften_text", "field": field}, f"causal_{field}")
        elif hits:
            add("minor", "Question uses causal language", f"'{hits[0]['phrase']}' - the protocol has been phrased associationally; results will be reported as associations.",
                None, "causal_question")
    if plan["model"]["family"] == "quasibinomial" and plan["outcome"]["type"] == "binary":
        add("major", "Odds ratios for a potentially common outcome", "ORs overstate prevalence ratios when prevalence >10%. Prefer quasi-Poisson PRs.",
            {"op": "set", "path": "model.family", "value": "quasipoisson"}, "or_common")
    outv = plan["outcome"]["variable"]
    ack = plan.get("acknowledgements", {})
    for v in {outv, (plan.get("exposure") or {}).get("variable")} - {None}:
        d = k.definitions.get(v)
        if not d:
            continue
        if d.get("status") == "secondary-source":
            add("minor", f"Definition '{d.get('short', v)}' verified from secondary sources",
                f"Thresholds were taken from {d['source'].get('citation', 'society communications')}; confirm against the full guideline before submission.",
                {"op": "acknowledge", "key": f"verify_{v}"} if not ack.get(f"verify_{v}") else None, f"verify_{v}")
        if d.get("operational_notes") and not ack.get(f"opnotes_{v}"):
            add("major", f"Operational assumptions for {d.get('short', v)} need investigator approval",
                " | ".join(d["operational_notes"]), {"op": "acknowledge", "key": f"opnotes_{v}"}, f"opnotes_{v}")
    if plan.get("exposure"):
        pair = {plan["exposure"]["concept"], plan["outcome"]["concept"]}
        for flag in k.causal_flags:
            if flag["role"] == "measurement_overlap" and {flag["exposure"], flag["outcome"]} == pair:
                role = "outcome" if plan["outcome"]["concept"] == flag["outcome"] else "exposure"
                has_alt = any(s.get("enabled") and s.get("type") == f"alt_{role}" and str(s.get(role, "")).endswith("phq8")
                              for s in plan.get("sensitivity", []))
                item = {"type": f"alt_{role}", "label": f"Alternative {role}: PHQ-8 >=10 (sleep item removed)", role: "depression_phq8"}
                add("minor" if has_alt else "major", "Outcome and exposure share questionnaire items (circularity)", flag["note"],
                    None if has_alt else {"op": "add_sensitivity", "item": item}, f"overlap_{flag['variable']}")
    for cv in plan.get("covariates", []):
        for flag in k.causal_flags:
            if plan.get("exposure") and flag["variable"] == cv and flag["exposure"] == plan["exposure"]["concept"] \
                    and flag["outcome"] == plan["outcome"]["concept"] and flag["role"] in ("mediator_or_outcome", "definitional"):
                add("major", f"Possible over-adjustment for {k.label(cv)}", flag["note"], {"op": "remove_covariate", "name": cv}, f"mediator_{cv}")
    dom = plan["outcome"].get("domain")
    enabled_s = [s for s in plan.get("sensitivity", []) if s.get("enabled")]
    if dom == "iron" and "inflammation" not in plan.get("covariates", []) and not any("crp" in (s.get("expr") or "").lower() or "inflammation" in (s.get("expr") or "") for s in enabled_s):
        add("major", "Ferritin is an acute-phase reactant", "Neither adjustment nor a sensitivity analysis accounts for inflammation (hsCRP).",
            {"op": "add_sensitivity", "item": {"type": "exclude", "label": "Exclude hsCRP >5 mg/L", "expr": "coalesce(inflammation, 0) == 1"}}, "iron_inflammation")
    if dom in ("iron", "glycemia") and not any("pregnant" in c["expr"] and c.get("enabled") for c in plan["population"]) \
            and not any("pregnant" in (s.get("expr") or "") and s.get("enabled") for s in plan.get("sensitivity", [])):
        preg = next((c for c in plan["population"] if "pregnant" in c["expr"]), None)
        add("minor", "Pregnancy not handled", "Pregnancy alters hemoglobin, iron indices and HbA1c.",
            {"op": "enable_criterion", "id": preg["id"]} if preg else None, "pregnancy")
    if plan["study_type"] == "association":
        if not any(s["type"] == "mi" and s.get("enabled") for s in plan.get("sensitivity", [])) and len(plan.get("covariates", [])) >= 4:
            add("minor", "No missing-data sensitivity analysis", "Complete-case analysis assumes covariates are missing completely at random.",
                {"op": "add_sensitivity", "item": {"type": "mi", "label": "Multiple imputation of missing covariates (m = 10)", "m": 10}}, "mi")
        if "bmi" in plan.get("covariates", []) and plan.get("exposure", {}).get("variable") in ("waist", "whtr", "abd_obesity"):
            add("info", "Waist and BMI are strongly correlated", "Adjusting for BMI isolates central adiposity but inflates variance; the engine reports VIFs.", None, "collinearity")
        if len(plan.get("interactions", [])) + len(plan.get("subgroups", [])) > 4:
            add("minor", "Multiplicity", "Many subgroup/interaction tests - interpret as exploratory or adjust for multiple comparisons.", None, "multiplicity")
        exp = plan.get("exposure") or {}
        if exp.get("type") == "continuous" and not exp.get("scale"):
            add("minor", "Exposure scale not specified", "Report effects per clinically meaningful increment.", {"op": "set", "path": "exposure.scale", "value": 1}, "scale")
    if plan["outcome"]["variable"] == "hba1c" or plan["outcome"]["concept"] == "glycemic_control":
        if not any("anemia" in (s.get("expr") or "") for s in enabled_s):
            add("info", "HbA1c is affected by red-cell turnover", "Iron deficiency and anemia shift HbA1c independent of glycemia.",
                {"op": "add_sensitivity", "item": {"type": "exclude", "label": "Exclude anemia (HbA1c unreliable)", "expr": "coalesce(anemia, 0) == 1"}}, "a1c_anemia")
    if any(c["expr"].startswith("pregnant == 1") and c.get("enabled") and c["kind"] == "inclusion" for c in plan["population"]):
        add("major", "Small subpopulation", "Pregnant participants number only a few hundred per cycle; many estimates will fail NCHS reliability standards. Consider pooling cycles.", None, "small_pop")
    for c in plan.get("custom_variables", []):
        if c.get("source") == "ai" and not ack.get(f"custom_{c['name']}"):
            add("blocker", f"AI-proposed variable '{c['name']}' not yet approved", f"Expression: {c['expr']}",
                {"op": "acknowledge", "key": f"custom_{c['name']}"}, f"custom_{c['name']}")
        if c.get("source") == "dictionary" and not ack.get(f"custom_{c['name']}"):
            row = k.dictionary.get(c.get("raw", ""), {})
            add("major", f"Confirm dictionary-matched variable {c.get('raw')} ({c['label']})",
                f"Matched from the {'curated' if row.get('curated') else 'uncurated NHANES catalog'} dictionary; coded as {c['expr']} "
                f"({c['type']}). Check the CDC codebook for coding, eligible ages and non-response codes before approving.",
                {"op": "acknowledge", "key": f"custom_{c['name']}"}, f"custom_{c['name']}")
    return issues


# ---------------------------------------------------------------------------
# Feasibility score
# ---------------------------------------------------------------------------
def feasibility(plan: dict, k: Knowledge | None = None) -> dict:
    k = k or get_knowledge()
    comps = []
    vm = variable_map(plan, k) if plan["dataset"].get("type") == "nhanes" else []
    core = [r for r in vm if r["role"] in ("Outcome", "Exposure")]
    avail = sum(all(r["available"].values()) for r in core) / max(len(core), 1) if vm else 0.8
    comps.append({"name": "Core variables available in selected cycles", "score": round(30 * avail), "max": 30})
    covs = [r for r in vm if r["role"] == "Covariate"]
    cov_ok = sum(all(r["available"].values()) for r in covs) / max(len(covs), 1) if vm else 0.8
    comps.append({"name": "Covariates available", "score": round(10 * cov_ok), "max": 10})
    oos = plan.get("parsed", {}).get("out_of_scope", [])
    comps.append({"name": "Question answerable with cross-sectional data", "score": 6 if oos else 20, "max": 20,
                  "note": "; ".join(oos) if oos else ""})
    statuses = []
    for v in (plan["outcome"]["variable"], (plan.get("exposure") or {}).get("variable")):
        if v in k.definitions:
            statuses.append(k.definitions[v].get("status"))
    sc = 10 if all(s == "verified" for s in statuses) else (7 if all(s in ("verified", "secondary-source") for s in statuses) else 3)
    comps.append({"name": "Definitions verified against sources", "score": sc, "max": 10})
    raw = set()
    for r in vm:
        raw |= set(r["raw_variables"])
    sub = 10
    if any(k.dictionary.get(x, {}).get("weight_level") == "fasting" for x in raw):
        sub = 6
    elif any(x.startswith("LUX") for x in raw):
        sub = 8
    comps.append({"name": "Measured in full exam sample (not a subsample)", "score": sub, "max": 10})
    restrict = [c["expr"] for c in plan["population"] if c.get("enabled") and c["kind"] == "inclusion"]
    size = 10
    if any("pregnant == 1" in e for e in restrict):
        size = 3
    elif any("ckd == 1" in e or "lsm >= 10" in e or "diabetes == 1" in e for e in restrict):
        size = 6
    elif any("female == 1" in e for e in restrict) and any("age <= 49" in e for e in restrict):
        size = 8
    comps.append({"name": "Expected analytic sample size", "score": size, "max": 10})
    issues = review_plan(plan, k)
    blockers = sum(1 for i in issues if i["severity"] == "blocker")
    comps.append({"name": "No unresolved reviewer blockers", "score": 10 if blockers == 0 else 0, "max": 10})
    total = sum(c["score"] for c in comps)
    label = "High" if total >= 80 else "Moderate" if total >= 60 else "Low"
    return {"score": total, "label": label, "components": comps}


# ---------------------------------------------------------------------------
# Plan editing (one-click fixes and UI edits)
# ---------------------------------------------------------------------------
def apply_fix(plan: dict, fix: dict, k: Knowledge | None = None) -> dict:
    k = k or get_knowledge()
    p = copy.deepcopy(plan)
    op = fix.get("op")
    if op == "set":
        obj = p
        parts = fix["path"].split(".")
        for part in parts[:-1]:
            obj = obj.setdefault(part, {})
        obj[parts[-1]] = fix["value"]
    elif op == "set_cycles":
        p["dataset"]["cycles"] = fix["value"]
    elif op == "remove_covariate":
        p["covariates"] = [c for c in p["covariates"] if c != fix["name"]]
        for a in p.get("adjustment_sets", []):
            a["covariates"] = [c for c in a["covariates"] if c != fix["name"]]
    elif op == "add_covariate":
        if fix["name"] not in p["covariates"]:
            p["covariates"].append(fix["name"])
            for a in p.get("adjustment_sets", []):
                if a["id"] == "full":
                    a["covariates"].append(fix["name"])
    elif op == "add_sensitivity":
        item = dict(fix["item"])
        item["id"] = f"s{len(p['sensitivity']) + 1}"
        item["enabled"] = True
        p["sensitivity"].append(item)
    elif op == "enable_sensitivity":
        for s in p["sensitivity"]:
            if s["id"] == fix["id"]:
                s["enabled"] = bool(fix.get("value", True))
    elif op == "enable_criterion":
        for c in p["population"]:
            if c["id"] == fix["id"]:
                c["enabled"] = bool(fix.get("value", True))
    elif op == "acknowledge":
        p.setdefault("acknowledgements", {})[fix["key"]] = {"at": _now(), "by": fix.get("by", "investigator")}
    elif op == "soften_text":
        from .language_guard import soften
        p[fix["field"]] = soften(p[fix["field"]])
    elif op == "swap_roles":
        if p.get("exposure"):
            new_out = choose_variable(p["exposure"]["concept"], "outcome", {}, k)
            new_exp = choose_variable(p["outcome"]["concept"], "exposure", {}, k, prefer_continuous=True)
            q = p["question"]
            parsed = dict(p.get("parsed", {}))
            parsed["outcome_concept"], parsed["exposure_concept"] = new_out["concept"], new_exp["concept"]
            parsed["hints"] = parsed.get("hints", {"prefer": [], "upgrade": {}})
            rebuilt = build_plan(q, parsed, p["dataset"].get("cycles"), p["dataset"], k)
            rebuilt["plan_id"] = p["plan_id"]
            rebuilt["version"] = p.get("version", 1)
            return rebuilt
    elif op == "set_definition":
        role = fix["role"]
        target = p[role]
        d = fix["value"]
        if d in k.definitions or d in k.blocks:
            old = target["variable"]
            target["variable"] = d
            target["label"] = k.label(d)
            target["type"] = k.var_type(d)
            target["definition_id"] = d if d in k.definitions else None
            target["kind"] = "definition" if d in k.definitions else "block"
            target["alternatives"] = [a for a in target.get("alternatives", []) if a != d] + ([old] if old not in target.get("alternatives", []) else [])
            if role == "outcome":
                p["prevalence_outcomes"] = [d] + [x for x in p.get("prevalence_outcomes", []) if x not in (d,)]
                p["benchmarks"] = [b for b in p.get("benchmarks", []) if b.get("outcome") in p["prevalence_outcomes"]]
                for s in p["sensitivity"]:
                    if s["type"] == "alt_outcome" and s.get("outcome") == d:
                        s["outcome"] = old
                        s["label"] = f"Alternative outcome definition: {k.definitions.get(old, {}).get('short', k.label(old))}"
                if p.get("table1_by") == old:
                    p["table1_by"] = d
    elif op == "add_criterion":
        expressions.validate(fix["expr"])
        p["population"].append({"id": f"c{len(p['population']) + 1}", "label": fix.get("label") or fix["expr"], "expr": fix["expr"],
                                "kind": fix.get("kind", "inclusion"), "source": "investigator", "enabled": True})
    elif op == "add_custom_variable":
        expressions.validate(fix["expr"])
        p.setdefault("custom_variables", []).append({"name": fix["name"], "expr": fix["expr"], "type": fix.get("type", "binary"),
                                                     "label": fix.get("label", fix["name"]), "source": fix.get("source", "investigator")})
    elif op in ("set_covariates", "set_subgroups", "set_interactions", "set_table1_vars"):
        field = op.replace("set_", "")
        known = set(k.blocks) | set(k.definitions) | {c["name"] for c in p.get("custom_variables", [])}
        bad = [v for v in fix["value"] if v not in known]
        if bad:
            raise ValueError(f"Unknown variable(s): {', '.join(bad)}")
        p[field] = list(dict.fromkeys(fix["value"]))
        if field == "covariates":
            exp = (p.get("exposure") or {}).get("variable")
            p["covariates"] = [c for c in p["covariates"] if c != exp]
            for a in p.get("adjustment_sets", []):
                if a["id"] == "full":
                    if p["study_type"] == "association":
                        a["covariates"] = list(p["covariates"])
                    else:
                        a["covariates"] = list(dict.fromkeys([g for g in p.get("subgroups", [])] + [c for c in p["covariates"]
                                                             if not (c == "age" and "agecat" in p.get("subgroups", []))]))
                elif a["id"] == "demographic":
                    a["covariates"] = [c for c in a["covariates"] if c in p["covariates"]]
        if field == "subgroups":
            p["prevalence_by"] = list(p["subgroups"])
    elif op == "set_text":
        if fix["field"] not in ("title", "refined_question", "hypothesis"):
            raise ValueError("Only title, refined_question and hypothesis are editable text fields")
        p[fix["field"]] = str(fix["value"])[:1000]
    elif op == "set_source":
        p["dataset"]["source"] = fix["value"]
    elif op == "set_generic_mapping":
        expressions.validate(fix["expr"], set(p["dataset"].get("columns", [])))
        p.setdefault("generic_mapping", {})[fix["block"]] = fix["expr"]
    else:
        raise ValueError(f"Unknown fix operation: {op}")
    return p


def refresh_text(plan: dict, k: Knowledge | None = None) -> dict:
    """Re-derive population text after edits."""
    k = k or get_knowledge()
    plan["pico"]["population"] = _population_text(plan["population"], plan["dataset"].get("cycles", ["P"]), k)
    return plan


def draft(question: str, cycles: list[str] | None = None, dataset: dict | None = None) -> dict:
    k = get_knowledge()
    parsed = parse_question(question, k)
    plan = build_plan(question, parsed, cycles, dataset, k)
    plan["variable_map"] = variable_map(plan, k)
    plan["review"] = review_plan(plan, k)
    plan["feasibility"] = feasibility(plan, k)
    return plan
