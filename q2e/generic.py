"""Bring-your-own open dataset: upload a CSV (+ optional data dictionary), auto-detect survey
design columns, and map Q2E building blocks onto the dataset's variables for human review."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import planner
from .config import settings
from .knowledge import Knowledge, get_knowledge
from .matcher import BM25Index, DictEntry, infer_dictionary_from_data, parse_dictionary_csv

BINARY_HINT = {"female": "== 'F' or == 2 depending on coding - confirm", "pregnant": "confirm coding"}


def datasets_dir() -> Path:
    d = Path(settings.workspace) / "datasets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def register_dataset(name: str, data_bytes: bytes, dict_bytes: bytes | None = None) -> dict:
    did = "ds_" + uuid.uuid4().hex[:8]
    d = datasets_dir() / did
    d.mkdir(parents=True)
    (d / "data.csv").write_bytes(data_bytes)
    text = data_bytes.decode("utf-8-sig", errors="replace")
    inferred, design = infer_dictionary_from_data(text)
    entries = inferred
    if dict_bytes:
        (d / "dictionary.csv").write_bytes(dict_bytes)
        parsed = parse_dictionary_csv(dict_bytes.decode("utf-8-sig", errors="replace"))
        by = {e.variable: e for e in parsed}
        entries = []
        for e in inferred:
            p = by.get(e.variable)
            entries.append(DictEntry(variable=e.variable, label=(p.label if p and p.label else e.label), table=(p.table if p else ""),
                                     type=(p.type if p and p.type else e.type), units=(p.units if p else ""), tags=(p.tags if p else ""),
                                     extra=e.extra))
    rec = {"id": did, "name": name, "path": str(d / "data.csv"), "n_columns": len(entries),
           "columns": [e.variable for e in entries], "design": design,
           "dictionary": [{"variable": e.variable, "label": e.label, "type": e.type, "units": e.units, "table": e.table, **(e.extra or {})} for e in entries]}
    (d / "dataset.json").write_text(json.dumps(rec, indent=2))
    return rec


def get_dataset(did: str) -> dict:
    f = datasets_dir() / did / "dataset.json"
    if not f.exists():
        raise KeyError(did)
    return json.loads(f.read_text())


def list_datasets() -> list[dict]:
    out = []
    for f in sorted(datasets_dir().glob("ds_*/dataset.json")):
        r = json.loads(f.read_text())
        out.append({"id": r["id"], "name": r["name"], "n_columns": r["n_columns"], "design": r["design"]})
    return out


def dataset_spec(rec: dict) -> dict:
    return {"type": "generic", "name": rec["name"], "dataset_id": rec["id"], "files": [{"path": rec["path"]}],
            "columns": rec["columns"], "id_var": rec["design"].get("id_var"), "weight": rec["design"].get("weight"),
            "strata": rec["design"].get("strata"), "psu": rec["design"].get("psu")}


def suggest_mapping(plan: dict, rec: dict, k: Knowledge | None = None) -> dict:
    """For every measure-tier building block the plan needs, suggest a dataset column."""
    k = k or get_knowledge()
    entries = [DictEntry(variable=d["variable"], label=d.get("label", ""), table=d.get("table", ""), type=d.get("type", ""),
                         units=d.get("units", "")) for d in rec["dictionary"]]
    idx = BM25Index(entries)
    needed = planner.needed_measures(plan, k)
    mapping, status, cands = {}, {}, []
    for b in sorted(needed):
        blk = k.blocks[b]
        hits = idx.search(blk.get("match_terms", [blk.get("label", b)]), top_k=3, exact_names=[b])
        status[b] = {"label": blk.get("label"), "type": blk["type"], "candidates": hits,
                     "note": "Confirm coding: binary blocks must evaluate to 1 = yes" if blk["type"] == "binary" else
                             ("Categorical: map a column directly or recode with cases(...)" if blk["type"] == "categorical" else "")}
        for h in hits:
            cands.append((h["score"], h["confidence"], b, h["variable"]))
    used: set[str] = set()
    for score, conf, b, col in sorted(cands, reverse=True):   # greedy one-to-one assignment
        if b in mapping or col in used or conf < 0.6:
            continue
        mapping[b] = col if k.blocks[b]["type"] != "binary" else f"{col} == 1"
        used.add(col)
    for b, st in status.items():
        top = mapping.get(b)
        st["needs_review"] = (not top) or k.blocks[b]["type"] in ("binary", "categorical")
    return {"mapping": mapping, "status": status}


def prune_unavailable(plan: dict, k: Knowledge | None = None) -> dict:
    """Drop optional elements (covariates, subgroups, Table 1 rows, sensitivity analyses, optional
    criteria) that need building blocks the uploaded dataset does not provide."""
    k = k or get_knowledge()
    gm = plan.get("generic_mapping", {}) or {}
    from . import expressions

    def ok(name: str) -> bool:
        return not planner.missing_measures(name, k, gm)

    notes = []
    for field in ("covariates", "subgroups", "table1_vars", "interactions", "prevalence_by"):
        keep = [v for v in plan.get(field, []) if ok(v)]
        dropped = [v for v in plan.get(field, []) if v not in keep]
        if dropped and field in ("covariates", "subgroups"):
            notes.append(f"{field}: removed {', '.join(k.label(d) for d in dropped)} (not in dataset)")
        plan[field] = keep
    for a in plan.get("adjustment_sets", []):
        a["covariates"] = [v for v in a["covariates"] if ok(v)]
    plan["prevalence_outcomes"] = [v for v in plan.get("prevalence_outcomes", []) if ok(v)] or plan.get("prevalence_outcomes", [])[:1]
    plan["sensitivity"] = [s for s in plan.get("sensitivity", [])
                           if all(ok(i) for i in (expressions.identifiers(s["expr"]) if s.get("expr") else []) + [s[x] for x in ("outcome", "exposure") if s.get(x)])]
    plan["population"] = [c for c in plan["population"] if c["kind"] == "inclusion" or all(ok(i) for i in expressions.identifiers(c["expr"]))]
    if plan.get("table1_by") and not ok(plan["table1_by"]):
        plan["table1_by"] = None
    for n in notes:
        plan.setdefault("agent_dialogue", []).append({"agent": "Data Steward", "source": "rules", "message": n})
    return plan
