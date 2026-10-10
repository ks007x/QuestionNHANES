"""Loads the curated knowledge base: NHANES cycles + data dictionary, building blocks,
versioned guideline definitions, the clinical concept ontology and example questions."""
from __future__ import annotations

import csv
import re
import functools
from pathlib import Path
from typing import Any

import yaml

from .config import settings

RAW_VAR_RANK = {"interview": 1, "mec": 2, "diet": 3, "fasting": 4, "subsample": 5}


CYCLE_ORDER = list("ABCDEFGHIJ") + ["P", "L"]


def _stem_of(f: str, c: str) -> str:
    f = f.strip().upper()
    if f.startswith("P_"):
        return f[2:]
    if len(f) > 2 and f[-2] == "_" and f[-1] == c:
        return f[:-2]
    m = re.match(rf"^(.*)_{c}_R$", f)          # restricted/revised variants e.g. TRIC_H_R
    if m:
        return m.group(1) + "_R"
    return f


def _files(files: str) -> dict:
    """'G:SSHOLO_G|SSTOCA_G;P:P_CBC' -> {'G': ['SSHOLO_G', 'SSTOCA_G'], 'P': ['P_CBC']}"""
    out = {}
    for part in (files or "").split(";"):
        if ":" in part:
            c, fs = part.split(":", 1)
            out[c] = [f.strip().upper() for f in fs.split("|") if f.strip()]
    return out


def _stems(files: str) -> dict:
    """'A:LAB25;B:L25_B;P:P_CBC' -> {'A': 'LAB25', 'B': 'L25', 'P': 'CBC'} (first file's stem per cycle)."""
    return {c: _stem_of(fs[0], c) for c, fs in _files(files).items() if fs}


WEIGHT_SKIP = re.compile(r"jack ?knife|\brep(licate)?\b|brr|\b4[- ]?y(ea)?r|99-02|4 year", re.I)
STANDARD_WEIGHTS = re.compile(r"^WT(INT|MEC|SAF|DRD|DR2|DRX|DR4)")


class Knowledge:
    def __init__(self, root: Path | None = None):
        root = Path(root or settings.knowledge_dir)
        self.root = root
        self.cycles: dict[str, dict] = yaml.safe_load((root / "nhanes" / "cycles.yaml").read_text(encoding="utf-8"))["cycles"]
        self.default_cycles: list[str] = yaml.safe_load((root / "nhanes" / "cycles.yaml").read_text(encoding="utf-8")).get("default_cycles", ["P"])
        self.dictionary: dict[str, dict] = {}
        with open(root / "nhanes" / "dictionary.csv", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                row["cycles"] = [c for c in row["cycles"].split(";") if c]
                row["missing_codes"] = [float(x) for x in row["missing_codes"].split(";") if x.strip()]
                row["min"] = float(row["min"]) if row["min"] not in ("", None) else None
                row["max"] = float(row["max"]) if row["max"] not in ("", None) else None
                row["curated"] = True
                self.dictionary[row["variable"]] = row
        # Full NHANES catalog (optional; built by scripts/build_nhanes_catalog.py) - uncurated fallback
        self.catalog_size = 0
        self.subsample_weights: dict[tuple[str, str], list[str]] = {}   # (cycle, FILE) -> weight variables in/for that file
        cat = root / "nhanes" / "catalog.csv"
        if cat.exists():
            with open(cat, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    v = r["variable"]
                    if not r.get("cycles"):
                        continue
                    stems = _stems(r.get("files", ""))
                    self._index_weight(v, r)
                    if v in self.dictionary:
                        # curated row: keep its metadata, but learn the older cycles and their file names from CDC
                        cur = self.dictionary[v]
                        extra = [c for c in r["cycles"].split(";") if c and c not in cur["cycles"]]
                        if extra and stems:
                            cur["cycles"] = sorted(set(cur["cycles"]) | set(extra), key=CYCLE_ORDER.index)
                            cur["stems"] = {c: st for c, st in stems.items() if c in extra or st != cur["file"]}
                        cur["files"] = _files(r.get("files", ""))
                        continue
                    tg = r.get("type_guess", "continuous")
                    wl = r.get("weight_level", "interview")
                    codes = [7.0, 9.0] if tg == "yesno" else ([777.0, 999.0, 7777.0, 9999.0, 77777.0, 99999.0]
                                                              if wl == "interview" and tg == "continuous" else [])
                    self.dictionary[v] = {"variable": v, "file": r["file"], "label": r.get("label", v),
                                          "type": "categorical" if tg in ("yesno", "categorical") else "continuous",
                                          "units": "", "min": None, "max": None, "weight_level": wl,
                                          "cycles": [c for c in r["cycles"].split(";") if c], "missing_codes": codes,
                                          "tags": r.get("component", ""), "curated": False, "type_guess": tg,
                                          "stems": {c: st for c, st in stems.items() if st != r["file"]},
                                          "files": _files(r.get("files", ""))}
                    self.catalog_size += 1
        # NHANES table (component) catalog, all cycles 1999-2023 - from the nhanesdata package (MIT)
        self.tables: list[dict] = []
        tf = root / "nhanes" / "tables.csv"
        if tf.exists():
            with open(tf, newline="", encoding="utf-8") as fh:
                self.tables = list(csv.DictReader(fh))
        blocks = yaml.safe_load((root / "building_blocks.yaml").read_text(encoding="utf-8"))["blocks"]
        self.blocks: dict[str, dict] = {b["name"]: b for b in blocks}
        self.definitions: dict[str, dict] = {}
        for f in sorted((root / "definitions").glob("*.yaml")):
            for d in yaml.safe_load(f.read_text(encoding="utf-8")).get("definitions", []):
                d["_file"] = f.name
                self.definitions[d["id"]] = d
        c = yaml.safe_load((root / "concepts.yaml").read_text(encoding="utf-8"))
        self.concepts: dict[str, dict] = {x["id"]: x for x in c["concepts"]}
        self.populations: list[dict] = c["populations"]
        self.domains: dict[str, dict] = c["domains"]
        self.causal_flags: list[dict] = c.get("causal_flags", [])
        self.component_synonyms: list[dict] = c.get("component_synonyms", [])
        self.not_in_nhanes: list[dict] = c.get("not_in_nhanes", [])
        self._var_index = None
        # human-taught mappings ("learned synonyms"): term -> concept or dataset variable, confirmed by a named person
        self.learned: list[dict] = load_learned()
        self.learned_vars: dict[str, str] = {}
        for e in self.learned:
            kind, _, target = str(e.get("target", "")).partition(":")
            term = str(e.get("term", "")).lower().strip()
            if not term:
                continue
            if kind == "concept" and target in self.concepts:
                syns = self.concepts[target].setdefault("synonyms", [])
                if term not in syns:
                    syns.append(term)
            elif kind == "var" and target in self.dictionary:
                self.learned_vars[term] = target
        self.examples: list[dict] = yaml.safe_load((root / "examples.yaml").read_text(encoding="utf-8"))["examples"]

    # ------------------------------------------------------------------
    def _index_weight(self, v: str, r: dict) -> None:
        lab = r.get("label") or ""
        if not v.startswith("WT") or STANDARD_WEIGHTS.match(v) or WEIGHT_SKIP.search(lab) or WEIGHT_SKIP.search(v):
            return
        for c, fs in _files(r.get("files", "")).items():
            targets = set(fs)
            # "Surplus specimen SSTOCA and SSTOXO 2 year weights" -> also applies to SSTOCA_<c> and SSTOXO_<c>
            for tok in re.findall(r"\b([A-Z][A-Z0-9]{2,})\b", lab):
                targets.add(f"{tok}_{c}" if c not in ("A", "P") else (tok if c == "A" else f"P_{tok}"))
            for f in targets:
                lst = self.subsample_weights.setdefault((c, f), [])
                if v not in lst:
                    lst.append(v)

    def files_for(self, var: str, cycle: str) -> list[str]:
        r = self.dictionary.get(var, {})
        if r.get("files") and cycle in r["files"]:
            return r["files"][cycle]
        cm = self.cycles.get(cycle, {})
        stem = (r.get("stems") or {}).get(cycle, r.get("file", ""))
        return [cm.get("file_pattern", "{stem}").replace("{stem}", stem)] if stem else []

    def subsample_weight(self, var: str, cycle: str) -> tuple[str, str] | None:
        """(weight variable, file stem holding it) when `var` comes from a subsample with its own weights."""
        for f in self.files_for(var, cycle):
            ws = self.subsample_weights.get((cycle, f))
            if ws:
                w = ws[0]
                wr = self.dictionary.get(w, {})
                wfiles = (wr.get("files") or {}).get(cycle) or [f]
                holder = f if f in wfiles else wfiles[0]
                return w, _stem_of(holder, cycle)
        return None

    def label(self, name: str) -> str:
        if name in self.blocks:
            return self.blocks[name].get("label", name)
        if name in self.definitions:
            return self.definitions[name].get("label", name)
        if name in self.dictionary:
            return self.dictionary[name]["label"]
        return name

    def var_type(self, name: str) -> str | None:
        if name in self.blocks:
            return self.blocks[name]["type"]
        if name in self.definitions:
            return self.definitions[name]["type"]
        return None

    def units(self, name: str) -> str:
        if name in self.blocks:
            return self.blocks[name].get("units", "") or ""
        return ""

    def definitions_for(self, concept_id: str) -> list[dict]:
        return [d for d in self.definitions.values() if d.get("concept") == concept_id]

    def raw_available(self, var: str, cycles: list[str]) -> list[str]:
        row = self.dictionary.get(var)
        if not row:
            return []
        return [c for c in cycles if c in row["cycles"]]

    def file_name(self, stem: str, cycle: str) -> str:
        return self.cycles[cycle]["file_pattern"].replace("{stem}", stem)

    def public_summary(self) -> dict[str, Any]:
        return {
            "cycles": {k: {"label": v["label"], "years": v["years"], "note": v.get("note")} for k, v in self.cycles.items()},
            "default_cycles": self.default_cycles,
            "concepts": [{"id": c["id"], "label": c["label"], "domain": c.get("domain")} for c in self.concepts.values()],
            "definitions": [self.definition_card(d) for d in self.definitions.values()],
            "blocks": [{"name": b["name"], "label": b.get("label"), "type": b["type"], "tier": b["tier"], "units": b.get("units", "")}
                       for b in self.blocks.values()],
            "examples": self.examples,
            "dictionary_size": len(self.dictionary),
            "curated_variables": sum(1 for r in self.dictionary.values() if r.get("curated")),
            "catalog_variables": self.catalog_size, "tables": len(self.tables),
        }

    def var_index(self):
        """BM25 index over every dataset variable (curated + catalog)."""
        if self._var_index is None:
            from .matcher import BM25Index, entries_from_nhanes
            self._var_index = BM25Index(entries_from_nhanes(self.dictionary))
        return self._var_index

    def table_description(self, table: str) -> str:
        for t in self.tables:
            if t["table"] == table:
                return t["description"]
        return ""

    @staticmethod
    def definition_card(d: dict) -> dict:
        return {
            "id": d["id"], "concept": d.get("concept"), "label": d.get("label"), "short": d.get("short"),
            "type": d.get("type"), "expr": d.get("expr"), "criteria_text": d.get("criteria_text"),
            "status": d.get("status"), "source": d.get("source", {}), "operational_notes": d.get("operational_notes", []),
            "benchmark": d.get("benchmark"), "population_hint": d.get("population_hint"),
        }


def learned_path() -> Path:
    return Path(settings.workspace) / "learned_synonyms.yaml"


def load_learned() -> list[dict]:
    p = learned_path()
    try:
        return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("learned", []) if p.exists() else []
    except Exception:  # noqa: BLE001
        return []


def save_learned(entry: dict) -> list[dict]:
    items = [e for e in load_learned() if e.get("term", "").lower() != entry["term"].lower()]
    items.append(entry)
    p = learned_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"learned": items}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    get_knowledge.cache_clear()
    return items


@functools.lru_cache(maxsize=1)
def get_knowledge() -> Knowledge:
    return Knowledge()
