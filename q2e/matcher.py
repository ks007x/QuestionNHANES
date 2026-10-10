"""Concept-to-variable matching against any data dictionary.

Hybrid retrieval: BM25 over (variable name + label + table + tags) with clinical
synonym expansion from the concept ontology, plus exact-name boosts. Scores are
squashed into a 0-1 confidence. Used for:
  * evidence shown next to every NHANES mapping ("why this variable"),
  * mapping building blocks onto arbitrary uploaded datasets,
  * grounding concepts an LLM could not map to the curated ontology.
"""
from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

_SPLIT = re.compile(r"[^a-z0-9]+")
_STOP = {"the", "of", "and", "in", "to", "a", "an", "for", "with", "or", "on", "at", "by", "past", "ever", "you", "your",
         "had", "have", "told", "is", "was", "are", "level", "levels", "value", "total", "count", "number", "1", "2", "yes", "no",
         "serum", "plasma", "blood", "urine", "urinary", "measured", "measurement", "percent", "ratio", "index", "status"}


def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    toks = [t for t in _SPLIT.split(text.lower()) if t and t not in _STOP]
    out = []
    for t in toks:
        out.append(t)
        if len(t) > 4 and t.endswith("s"):
            out.append(t[:-1])
    return out


@dataclass
class DictEntry:
    variable: str
    label: str
    table: str = ""
    type: str = ""
    units: str = ""
    tags: str = ""
    extra: dict | None = None

    def text(self) -> str:
        return " ".join([self.variable, self.label, self.table, self.tags, self.units])


class BM25Index:
    def __init__(self, entries: Iterable[DictEntry], k1: float = 1.4, b: float = 0.7):
        self.entries = list(entries)
        self.docs = [tokens(e.text()) for e in self.entries]
        self.k1, self.b = k1, b
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def score(self, query_tokens: list[str], i: int) -> float:
        s = 0.0
        dl = len(self.docs[i])
        for t in set(query_tokens):
            if t not in self.tf[i]:
                continue
            f = self.tf[i][t]
            s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: str | list[str], top_k: int = 5, exact_names: Iterable[str] = ()) -> list[dict[str, Any]]:
        q = tokens(" ".join(query) if isinstance(query, list) else query)
        phrases = [set(tokens(p)) for p in (query if isinstance(query, list) else [query])]
        exact = {e.lower() for e in exact_names}
        scored = []
        for i, e in enumerate(self.entries):
            s = self.score(q, i)
            if s > 0 and any(ph and ph <= set(self.docs[i]) for ph in phrases):
                s += 2.5   # every token of a clinical phrase present in this entry
            if e.variable.lower() in exact:
                s += 6.0
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        out = []
        for rank, (s, i) in enumerate(scored[:top_k]):
            e = self.entries[i]
            second = scored[1][0] if rank == 0 and len(scored) > 1 else None
            conf = 1 - math.exp(-s / 3.5)
            if second is not None and s > 0:
                conf = min(0.99, conf * (0.75 + 0.25 * min(1.0, (s - second) / s + 0.5)))
            out.append({"variable": e.variable, "label": e.label, "table": e.table, "type": e.type, "units": e.units,
                        "score": round(s, 3), "confidence": round(min(conf, 0.99), 2)})
        return out


def entries_from_nhanes(dictionary: dict[str, dict]) -> list[DictEntry]:
    return [DictEntry(variable=v, label=r["label"], table=r["file"], type=r["type"], units=r.get("units", ""),
                      tags=r.get("tags", ""), extra={"cycles": r["cycles"]}) for v, r in dictionary.items()
            if r["type"] not in ("weight", "design", "id")]


# ---------------------------------------------------------------------------
# Generic data dictionaries (CSV) - flexible header detection
# ---------------------------------------------------------------------------
_HEADER_ALIASES = {
    "variable": ["variable", "variable_name", "varname", "name", "field", "column", "column_name", "code"],
    "label": ["label", "description", "variable_label", "desc", "definition", "question", "title"],
    "table": ["table", "file", "dataset", "form", "component", "module", "category"],
    "type": ["type", "data_type", "datatype", "class", "format"],
    "units": ["units", "unit", "measure", "uom"],
    "values": ["values", "value_labels", "codes", "categories", "allowed_values"],
}


def parse_dictionary_csv(text: str) -> list[DictEntry]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("Dictionary CSV has no header row")
    lower = {f.lower().strip(): f for f in reader.fieldnames}
    colmap = {}
    for key, aliases in _HEADER_ALIASES.items():
        for a in aliases:
            if a in lower:
                colmap[key] = lower[a]
                break
    if "variable" not in colmap:
        raise ValueError(f"Could not find a variable-name column in {reader.fieldnames}")
    out = []
    for row in reader:
        var = (row.get(colmap["variable"]) or "").strip()
        if not var:
            continue
        out.append(DictEntry(variable=var, label=(row.get(colmap.get("label", ""), "") or "").strip(),
                             table=(row.get(colmap.get("table", ""), "") or "").strip(),
                             type=(row.get(colmap.get("type", ""), "") or "").strip(),
                             units=(row.get(colmap.get("units", ""), "") or "").strip(),
                             tags=(row.get(colmap.get("values", ""), "") or "").strip()))
    return out


def infer_dictionary_from_data(text: str, max_rows: int = 5000) -> tuple[list[DictEntry], dict]:
    """Build a minimal dictionary from a CSV data file's header and values."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    cols: dict[str, list[str]] = {h: [] for h in header}
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        for h, v in zip(header, row):
            cols[h].append(v)
    entries, design = [], {}
    for h, vals in cols.items():
        nonmiss = [v for v in vals if v not in ("", "NA", "na", "NaN", ".")]
        nums = []
        for v in nonmiss:
            try:
                nums.append(float(v))
            except ValueError:
                nums = None
                break
        if nums is None:
            t = "categorical"
            units = ""
            label = h.replace("_", " ")
        else:
            uniq = set(nums)
            t = "binary" if uniq <= {0.0, 1.0} else ("categorical" if len(uniq) <= 8 and all(float(x).is_integer() for x in uniq) else "continuous")
            label = h.replace("_", " ")
            units = ""
        entries.append(DictEntry(variable=h, label=label, type=t, units=units,
                                 extra={"min": min(nums) if nums else None, "max": max(nums) if nums else None,
                                        "n_missing": len(vals) - len(nonmiss)}))
        hl = h.lower()
        if re.search(r"(^wt|wt$|_wt|wgt|sampl\w*_?weight|survey_?weight|weight_?survey|pweight|^weights?$|finalwt|wtmec|wtint)", hl) and "weight" not in design:
            design["weight"] = h
        elif re.search(r"strat", hl) and "strata" not in design:
            design["strata"] = h
        elif re.search(r"(psu|cluster)", hl) and "psu" not in design:
            design["psu"] = h
        elif re.search(r"^(id|seqn|subject_?id|participant_?id|record_?id)$", hl) and "id_var" not in design:
            design["id_var"] = h
    return entries, design
