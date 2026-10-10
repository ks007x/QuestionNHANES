#!/usr/bin/env python3
"""Build the full NHANES variable catalog (thousands of variables) used by Q2E's
dictionary fallback and answerability engine.

Two sources (use either or both):

  1. CDC variable lists (needs internet access to wwwn.cdc.gov):
       python scripts/build_nhanes_catalog.py --cdc --cycles 2015-2016 2017-2018 2017-2020 2021-2023

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
SUFFIX = {"_I": "I", "_J": "J", "_L": "L", "_H": "H", "_G": "G"}


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
    merged: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r["variable"] in ("SEQN",):
            continue
        stem, cy = split_file(r["file"])
        key = (r["variable"], stem)
        m = merged.setdefault(key, {"variable": r["variable"], "file": stem, "label": r["label"], "component": r["component"], "cycles": set()})
        if cy:
            m["cycles"].add(cy)
        if not m["label"] and r["label"]:
            m["label"] = r["label"]
    out = []
    for m in merged.values():
        out.append({**m, "cycles": ";".join(sorted(m["cycles"])), "weight_level": weight_level(m["file"], m["component"], m["variable"]),
                    "type_guess": type_guess(m["label"], m["variable"])})
    return sorted(out, key=lambda x: (x["file"], x["variable"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cdc", action="store_true", help="fetch variable lists from wwwn.cdc.gov")
    ap.add_argument("--cycles", nargs="*", default=["2015-2016", "2017-2018", "2017-2020", "2021-2023"])
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
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["variable", "file", "label", "component", "cycles", "weight_level", "type_guess"])
        w.writeheader()
        w.writerows(cat)
    print(f"Wrote {len(cat)} variables to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
