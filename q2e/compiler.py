"""Compile a human-approved study plan into the executable specification consumed by the
R engine: resolves every variable to an expression in dependency order, collects the raw
dataset variables and files, selects the survey weight, and fingerprints the plan."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import expressions
from .config import settings
from .knowledge import RAW_VAR_RANK, Knowledge, get_knowledge

HASH_FIELDS = ["dataset", "outcome", "exposure", "population", "covariates", "subgroups", "interactions", "model",
               "adjustment_sets", "missing_data", "prevalence_outcomes", "prevalence_by", "sensitivity", "table1_vars",
               "table1_by", "benchmarks", "custom_variables", "generic_mapping"]


class CompileError(ValueError):
    pass


def plan_hash(plan: dict) -> str:
    core = {f: plan.get(f) for f in HASH_FIELDS}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def _scaled_name(x: str, scale: float) -> str:
    s = ("%g" % scale).replace(".", "_")
    return f"{x}_per{s}"


def compile_plan(plan: dict, k: Knowledge | None = None) -> dict[str, Any]:
    k = k or get_knowledge()
    ds = plan["dataset"]
    is_nhanes = ds.get("type", "nhanes") == "nhanes"
    custom = {c["name"]: c for c in plan.get("custom_variables", [])}
    generic_cols: set[str] = set(ds.get("columns", [])) if not is_nhanes else set()
    gmap: dict[str, str] = plan.get("generic_mapping", {}) or {}
    derived: list[dict] = []
    done: set[str] = set()
    raw: set[str] = set()
    stack: list[str] = []
    meta: dict[str, dict] = {}
    unavailable: list[str] = []

    def resolve(name: str) -> None:
        if name in done:
            return
        if name in stack:
            raise CompileError(f"Circular definition involving '{name}'")
        if is_nhanes and name in k.dictionary:
            raw.add(name); done.add(name); return
        if not is_nhanes and name in generic_cols and name not in k.blocks and name not in k.definitions and name not in custom:
            raw.add(name); done.add(name); return
        stack.append(name)
        levels = None
        if name in custom:
            c = custom[name]
            expr, vtype, label, units = c["expr"], c.get("type", "binary"), c.get("label", name), c.get("units", "")
        elif name in k.definitions:
            d = k.definitions[name]
            if d.get("status") == "proposed":
                raise CompileError(f"Definition '{name}' is an unapproved AI proposal")
            expr, vtype, label, units = d["expr"], d["type"], d.get("label", name), ""
        elif name in k.blocks:
            b = k.blocks[name]
            if b["tier"] == "measure":
                expr = b.get("nhanes") if is_nhanes else (gmap.get(name) or "NA")
                if expr == "NA":
                    unavailable.append(name)
            else:
                expr = b["expr"]
            vtype, label, units = b["type"], b.get("label", name), b.get("units", "")
        else:
            raise CompileError(f"Unknown variable '{name}'")
        try:
            ids = expressions.validate(expr)
        except expressions.ExpressionError as e:
            raise CompileError(f"Invalid expression for '{name}': {e}") from e
        for ident in ids:
            resolve(ident)
        stack.pop()
        derived.append({"name": name, "expr": expr, "type": vtype, "label": label, "levels": levels})
        meta[name] = {"label": label, "units": units}
        done.add(name)

    outcome = plan["outcome"]["variable"]
    exposure = (plan.get("exposure") or {}).get("variable")
    names: list[str] = [outcome]
    if exposure:
        names.append(exposure)
    names += plan.get("covariates", []) + plan.get("subgroups", []) + plan.get("interactions", [])
    names += plan.get("table1_vars", []) + ([plan["table1_by"]] if plan.get("table1_by") else [])
    names += plan.get("prevalence_outcomes", []) + plan.get("prevalence_by", [])
    for a in plan.get("adjustment_sets", []):
        names += a["covariates"]
    population = [c for c in plan.get("population", []) if c.get("enabled", True)]
    sens = [s for s in plan.get("sensitivity", []) if s.get("enabled", True)]
    for c in population:
        names += expressions.validate(c["expr"])
    for s in sens:
        if s.get("expr"):
            names += expressions.validate(s["expr"])
        for key in ("outcome", "exposure"):
            if s.get(key):
                names.append(s[key])
    for n in dict.fromkeys(names):
        resolve(n)

    # exposure scaling
    exp_name = exposure
    if exposure and plan["exposure"].get("type") == "continuous":
        sc = plan["exposure"].get("scale") or 1
        if float(sc) != 1.0:
            exp_name = _scaled_name(exposure, float(sc))
            units = k.units(exposure) or plan["exposure"].get("units", "")
            derived.append({"name": exp_name, "expr": f"{exposure} / {sc}", "type": "continuous",
                            "label": meta.get(exposure, {}).get("label", exposure), "levels": None})
            meta[exp_name] = {"label": meta.get(exposure, {}).get("label", exposure), "units": units, "per": f"{sc:g} {units}".strip()}

    # raw variables + weight
    raw_vars = []
    if is_nhanes:
        cycles = ds.get("cycles") or list(k.default_cycles)
        for v in sorted(raw):
            r = k.dictionary[v]
            raw_vars.append({"variable": v, "file": r["file"], "cycles": r["cycles"], "type": r["type"], "min": r["min"], "max": r["max"],
                             "missing_codes": r["missing_codes"], "weight_level": r["weight_level"], "label": r["label"]})
            meta.setdefault(v, {"label": r["label"], "units": r.get("units", "")})
        levels = [r["weight_level"] for r in raw_vars if r["type"] not in ("weight", "design", "id")]
        weight_level = max(levels, key=lambda x: RAW_VAR_RANK.get(x, 0)) if levels else "interview"
    else:
        cycles = []
        for v in sorted(raw):
            raw_vars.append({"variable": v, "file": "data", "cycles": [], "type": "unknown", "min": None, "max": None,
                             "missing_codes": [], "weight_level": "interview"})
        weight_level = "analysis"

    sets = []
    for a in plan.get("adjustment_sets", []):
        sets.append({"id": a["id"], "label": a["label"], "covariates": [c for c in a["covariates"] if c != exposure]})
    sens_out = []
    for s in sens:
        item = {k2: v for k2, v in s.items() if k2 not in ("enabled",)}
        if item.get("type") == "alt_exposure" and plan["exposure"].get("type") == "continuous" and k.var_type(item["exposure"]) == "continuous":
            pass
        sens_out.append(item)

    dataset_spec: dict[str, Any] = {"type": "nhanes" if is_nhanes else "generic"}
    if is_nhanes:
        src = ds.get("source", "auto")
        dataset_spec.update({
            "cycles": cycles,
            "source": src,
            "local_dir": None if src == "synthetic" else str(ds.get("local_dir") or settings.nhanes_dir),
            "synthetic_dir": str(settings.synthetic_dir) if src == "synthetic" else None,
            "cache_dir": str(settings.cache_dir),
            "allow_download": bool(settings.allow_download and src in ("auto", "cdc")),
        })
    else:
        dataset_spec.update({k2: ds.get(k2) for k2 in ("files", "id_var", "weight", "strata", "psu", "name")})

    compiled = {
        "plan_id": plan["plan_id"], "plan_version": plan.get("version", 1), "plan_hash": plan_hash(plan),
        "title": plan.get("title"), "study_type": plan["study_type"],
        "dataset": dataset_spec,
        "cycles_meta": {c: k.cycles[c] for c in cycles} if is_nhanes else {},
        "weight_level": weight_level,
        "raw_variables": raw_vars,
        "derived": derived,
        "variables_meta": meta,
        "population": [{"id": c["id"], "label": c["label"], "expr": c["expr"], "kind": c.get("kind", "inclusion")} for c in population],
        "outcome": {"name": outcome, "type": plan["outcome"]["type"], "label": meta.get(outcome, {}).get("label", outcome)},
        "exposure": ({"name": exp_name, "type": plan["exposure"]["type"], "label": meta.get(exp_name, {}).get("label", exp_name)}
                     if exposure else None),
        "covariates": [c for c in plan.get("covariates", []) if c != exposure],
        "subgroups": plan.get("subgroups", []),
        "analysis": {
            "estimand": plan["study_type"],
            "table1_vars": plan.get("table1_vars", []),
            "table1_by": plan.get("table1_by"),
            "prevalence": {"outcomes": plan.get("prevalence_outcomes", []), "by": plan.get("prevalence_by", [])},
            "model": {"family": plan["model"]["family"], "primary_set": plan["model"].get("primary_set", "full")},
            "adjustment_sets": sets,
            "interactions": plan.get("interactions", []),
            "missing": {"method": plan.get("missing_data", {}).get("method", "complete_case"), "m": 10},
            "sensitivity": sens_out,
            "benchmarks": plan.get("benchmarks", []),
            "distribution_var": None,
        },
        "options": {"seed": 2026, "alpha": 0.05},
        "unavailable_measures": unavailable,
    }
    if plan["study_type"] == "prevalence":
        # distribution figure for the key continuous component of the outcome definition (e.g. ferritin)
        if outcome in k.definitions:
            comps = [i for i in expressions.identifiers(k.definitions[outcome]["expr"]) if k.var_type(i) == "continuous"]
            if comps:
                compiled["analysis"]["distribution_var"] = comps[0]
    if exposure and exp_name != exposure:
        compiled["exposure"]["original"] = exposure
    return compiled


def write_compiled(compiled: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compiled, indent=2, default=str))
    return path
