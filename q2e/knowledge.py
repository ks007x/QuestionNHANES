"""Loads the curated knowledge base: NHANES cycles + data dictionary, building blocks,
versioned guideline definitions, the clinical concept ontology and example questions."""
from __future__ import annotations

import csv
import functools
from pathlib import Path
from typing import Any

import yaml

from .config import settings

RAW_VAR_RANK = {"interview": 1, "mec": 2, "diet": 3, "fasting": 4}


class Knowledge:
    def __init__(self, root: Path | None = None):
        root = Path(root or settings.knowledge_dir)
        self.root = root
        self.cycles: dict[str, dict] = yaml.safe_load((root / "nhanes" / "cycles.yaml").read_text())["cycles"]
        self.default_cycles: list[str] = yaml.safe_load((root / "nhanes" / "cycles.yaml").read_text()).get("default_cycles", ["P"])
        self.dictionary: dict[str, dict] = {}
        with open(root / "nhanes" / "dictionary.csv", newline="") as fh:
            for row in csv.DictReader(fh):
                row["cycles"] = [c for c in row["cycles"].split(";") if c]
                row["missing_codes"] = [float(x) for x in row["missing_codes"].split(";") if x.strip()]
                row["min"] = float(row["min"]) if row["min"] not in ("", None) else None
                row["max"] = float(row["max"]) if row["max"] not in ("", None) else None
                row["curated"] = True
                self.dictionary[row["variable"]] = row
        # Full NHANES catalog (optional; built by scripts/build_nhanes_catalog.py) - uncurated fallback
        self.catalog_size = 0
        cat = root / "nhanes" / "catalog.csv"
        if cat.exists():
            with open(cat, newline="") as fh:
                for r in csv.DictReader(fh):
                    v = r["variable"]
                    if v in self.dictionary or not r.get("cycles"):
                        continue
                    tg = r.get("type_guess", "continuous")
                    wl = r.get("weight_level", "interview")
                    codes = [7.0, 9.0] if tg == "yesno" else ([777.0, 999.0, 7777.0, 9999.0, 77777.0, 99999.0]
                                                              if wl == "interview" and tg == "continuous" else [])
                    self.dictionary[v] = {"variable": v, "file": r["file"], "label": r.get("label", v),
                                          "type": "categorical" if tg in ("yesno", "categorical") else "continuous",
                                          "units": "", "min": None, "max": None, "weight_level": wl,
                                          "cycles": [c for c in r["cycles"].split(";") if c], "missing_codes": codes,
                                          "tags": r.get("component", ""), "curated": False, "type_guess": tg}
                    self.catalog_size += 1
        # NHANES table (component) catalog, all cycles 1999-2023 - from the nhanesdata package (MIT)
        self.tables: list[dict] = []
        tf = root / "nhanes" / "tables.csv"
        if tf.exists():
            with open(tf, newline="") as fh:
                self.tables = list(csv.DictReader(fh))
        blocks = yaml.safe_load((root / "building_blocks.yaml").read_text())["blocks"]
        self.blocks: dict[str, dict] = {b["name"]: b for b in blocks}
        self.definitions: dict[str, dict] = {}
        for f in sorted((root / "definitions").glob("*.yaml")):
            for d in yaml.safe_load(f.read_text()).get("definitions", []):
                d["_file"] = f.name
                self.definitions[d["id"]] = d
        c = yaml.safe_load((root / "concepts.yaml").read_text())
        self.concepts: dict[str, dict] = {x["id"]: x for x in c["concepts"]}
        self.populations: list[dict] = c["populations"]
        self.domains: dict[str, dict] = c["domains"]
        self.causal_flags: list[dict] = c.get("causal_flags", [])
        self.component_synonyms: list[dict] = c.get("component_synonyms", [])
        self.not_in_nhanes: list[dict] = c.get("not_in_nhanes", [])
        self._var_index = None
        self.examples: list[dict] = yaml.safe_load((root / "examples.yaml").read_text())["examples"]

    # ------------------------------------------------------------------
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


@functools.lru_cache(maxsize=1)
def get_knowledge() -> Knowledge:
    return Knowledge()
