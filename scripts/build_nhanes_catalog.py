#!/usr/bin/env python3
"""Build the full NHANES variable catalog (thousands of variables) used by Q2E's
dictionary fallback and answerability engine.

Two sources (use either or both):

  1. CDC variable lists (needs internet access to wwwn.cdc.gov):
       python scripts/build_nhanes_catalog.py --cdc            # all cycles 1999-2000 ... 2021-2023

  2. Labels exported from local .xpt files (works offline with the hackathon files):
       Rscript scripts/verify_nhanes_dictionary.R data/nhanes labels.csv
       python scripts/build_nhanes_catalog.py --from-labels labels.csv

Output: knowledge/nhanes/catalog.csv  (variable, file, label, component, cycles, weight_level, type_guess)
Variables already in the curated dictionary keep their curated metadata; catalog rows are
marked uncurated and every mapping that uses them must be confirmed by the investigator.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "knowledge" / "nhanes" / "catalog.csv"
COMPONENTS = ["Demographics", "Dietary", "Examination", "Laboratory", "Questionnaire"]
FASTING_FILES = {"GLU", "INS", "TRIGLY", "OGTT", "FASTQX"}
SUFFIX = {"_B": "B", "_C": "C", "_D": "D", "_E": "E", "_F": "F", "_G": "G", "_H": "H", "_I": "I", "_J": "J", "_L": "L"}
CYCLE_CODE = {"1999-2000": "A", "2001-2002": "B", "2003-2004": "C", "2005-2006": "D", "2007-2008": "E", "2009-2010": "F",
              "2011-2012": "G", "2013-2014": "H", "2015-2016": "I", "2017-2018": "J", "2017-2020": "P", "2021-2023": "L"}
ALL_CYCLES = list(CYCLE_CODE)


def split_file(fname: str) -> tuple[str, str | None]:
    """'P_FERTIN' -> ('FERTIN','P'); 'FERTIN_J' -> ('FERTIN','J')."""
    f = fname.strip().upper()
    if f.startswith("P_"):
        return f[2:], "P"
    for suf, cy in SUFFIX.items():
        if f.endswith(suf):
            return f[: -len(suf)], cy
    return f, None


def weight_level(stem: str, component: str, variable: str) -> str:
    if stem in FASTING_FILES:
        return "fasting"
    c = (component or "").lower()
    if c.startswith("diet") or variable.startswith(("DR1", "DR2", "DRX")):
        return "diet"
    if c.startswith(("lab", "exam")) or variable.startswith(("LBX", "LBD", "URX", "URD", "BMX", "BPX", "LUX", "DXX", "AUX", "OHX", "MGX")):
        return "mec"
    return "interview"


def type_guess(label: str, variable: str) -> str:
    l = label.lower()
    if re.search(r"\b(ever told|ever been told|doctor told|do you now|have you ever|are you now|taking .* now|covered by)\b", l):
        return "yesno"
    if re.search(r"\b(status|category|race|gender|education|marital|country|reason|which|type of)\b", l):
        return "categorical"
    return "continuous"


class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_variable_list(html: str) -> list[dict]:
    """Parse a CDC NHANES 'variablelist.aspx' page into rows."""
    p = _Table()
    p.feed(html)
    out, header = [], None
    for r in p.rows:
        low = [c.lower() for c in r]
        if "variable name" in low and "data file name" in low:
            header = low
            continue
        if header and len(r) == len(header):
            d = dict(zip(header, r))
            out.append({"variable": d["variable name"].strip().upper(), "label": d.get("variable description", ""),
                        "file": d["data file name"].strip().upper(), "component": d.get("component", "")})
    return out


def fetch_cdc(cycles: list[str]) -> list[dict]:
    import httpx
    rows = []
    for cyc in cycles:
        for comp in COMPONENTS:
            url = f"https://wwwn.cdc.gov/nchs/nhanes/search/variablelist.aspx?Component={comp}&Cycle={cyc}"
            try:
                r = httpx.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (Q2E catalog builder)"}, follow_redirects=True)
                r.raise_for_status()
                got = parse_variable_list(r.text)
                for g in got:
                    g["cycle"] = CYCLE_CODE.get(cyc)
                print(f"  {cyc} {comp}: {len(got)} variables")
                rows += got
            except Exception as e:  # noqa: BLE001
                print(f"  {cyc} {comp}: FAILED ({e})", file=sys.stderr)
    return rows


def from_labels(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append({"variable": r["variable"].upper(), "label": r.get("label", ""), "file": r["file"].upper(), "component": ""})
    return rows


def build(rows: list[dict]) -> list[dict]:
    """One row per variable: the most recent file stem, every cycle it appears in, and the exact file per cycle."""
    order = list(CYCLE_CODE.values())
    merged: dict[str, dict] = {}
    for r in rows:
        if r["variable"] in ("SEQN",):
            continue
        stem, cy = split_file(r["file"])
        cy = r.get("cycle") or cy
        m = merged.setdefault(r["variable"], {"variable": r["variable"], "label": r["label"], "component": r["component"],
                                              "files": {}, "stems": {}})
        if cy:
            fs = m["files"].setdefault(cy, [])
            if r["file"].upper() not in fs:
                fs.append(r["file"].upper())
            m["stems"].setdefault(cy, stem)
        if r["label"] and (not m["label"] or (cy and order.index(cy) >= max([order.index(c) for c in m["files"] if c != cy] or [0]))):
            m["label"] = r["label"]
    out = []
    for m in merged.values():
        cys = sorted(m["files"], key=order.index)
        latest = cys[-1] if cys else None
        stem = m["stems"].get(latest, "")
        out.append({"variable": m["variable"], "file": stem, "label": m["label"], "component": m["component"],
                    "cycles": ";".join(cys), "files": ";".join(f"{c}:{'|'.join(m['files'][c])}" for c in cys),
                    "weight_level": weight_level(stem, m["component"], m["variable"]),
                    "type_guess": type_guess(m["label"], m["variable"])})
    return sorted(out, key=lambda x: (x["file"], x["variable"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cdc", action="store_true", help="fetch variable lists from wwwn.cdc.gov")
    ap.add_argument("--cycles", nargs="*", default=ALL_CYCLES)
    ap.add_argument("--from-labels", type=Path, help="CSV exported by scripts/verify_nhanes_dictionary.R")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    rows = []
    if a.cdc:
        rows += fetch_cdc(a.cycles)
    if a.from_labels:
        rows += from_labels(a.from_labels)
    if not rows:
        ap.error("nothing to do: use --cdc and/or --from-labels")
    cat = build(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["variable", "file", "label", "component", "cycles", "files", "weight_level", "type_guess"])
        w.writeheader()
        w.writerows(cat)
    print(f"Wrote {len(cat)} variables to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
