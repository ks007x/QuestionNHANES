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
               "table1_by", "benchmarks", "custom_variables", "generic_mapping", "age_adjust", "trend", "estimand"]


class CompileError(ValueError):
    pass


def _not_in_cycles(name: str, cycles: list[str], k: Knowledge, plan: dict) -> bool:
    """Building blocks that cannot exist in the selected cycles (e.g. the 1999-2004 arm of a coalesce()) - expected to be empty."""
    from .planner import available_cycles
    try:
        custom = {c["name"]: c for c in plan.get("custom_variables", [])}
        return not (available_cycles(name, k, custom) & set(cycles))
    except Exception:  # noqa: BLE001
        return False


def _with_subsample(cm: dict, subs: dict | None) -> dict:
    for level, sub in (subs or {}).items():
        cm = {**cm, "weights": {**cm["weights"], level: sub["weight"]}, "weight_files": {**cm.get("weight_files", {}), level: sub["file"]}}
    return cm


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
            levels = c.get("levels")
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
        names += list(s.get("covariates") or [])
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
                             "missing_codes": r["missing_codes"], "weight_level": r["weight_level"], "label": r["label"],
                             "stems": {c: st for c, st in (r.get("stems") or {}).items() if c in cycles}})
            meta.setdefault(v, {"label": r["label"], "units": r.get("units", "")})
        # laboratory subsamples (surplus sera, environmental chemicals, special panels) carry their own weights
        subsample: dict[str, dict] = {}
        for c in cycles:
            for r in raw_vars:
                if r["weight_level"] not in ("mec", "fasting") or c not in (r["cycles"] or []):
                    continue
                hit = k.subsample_weight(r["variable"], c)
                if hit:
                    level = "phlebotomy" if hit[0].upper().startswith("WTPH") else "subsample"
                    subsample.setdefault(c, {}).setdefault(level, {"weight": hit[0], "file": hit[1], "because": r["variable"]})
                    if r["weight_level"] == "mec" or level == "subsample":
                        r["weight_level"] = level
        # The analysis weight is set by the variables that define the analytic sample - outcome, exposure, model
        # covariates and eligibility criteria. Descriptive extras (Table 1 columns, other prevalence outcomes,
        # subgroups, sensitivity analyses) must not switch the whole study to a smaller subsample weight: those
        # that would need one are left out and listed (e.g. HbA1c in a 2021-2023 hypertension Table 1 forced the
        # phlebotomy weight and moved hypertension prevalence 10 points from the NCHS estimate).
        by_var = {r["variable"]: r for r in raw_vars}
        dexpr = {d["name"]: d["expr"] for d in derived}

        def deps(name: str, seen: set | None = None) -> set:
            seen = seen if seen is not None else set()
            if name in seen:
                return set()
            seen.add(name)
            if name in by_var:
                return {name}
            if name in dexpr:
                out: set = set()
                for i in expressions.identifiers(dexpr[name]):
                    out |= deps(i, seen)
                return out
            return set()

        def level_of(names) -> str:
            lv = [by_var[v]["weight_level"] for n in names for v in deps(n) if by_var[v]["type"] not in ("weight", "design", "id")]
            return max(lv, key=lambda x: RAW_VAR_RANK.get(x, 0)) if lv else "interview"
        core = [outcome] + ([exposure] if exposure else [])
        if exposure:     # covariates only enter models when there is an exposure
            core += list(plan.get("covariates", []))
            for a in plan.get("adjustment_sets", []):
                core += a["covariates"]
        for c in population:
            core += expressions.validate(c["expr"])
        weight_level = level_of(core)
        rank = RAW_VAR_RANK.get(weight_level, 0)
        too_strict = {n for n in names if RAW_VAR_RANK.get(level_of([n]), 0) > rank}
        if weight_level in ("subsample", "phlebotomy"):
            missing_w = [c for c in cycles if weight_level not in subsample.get(c, {})]
            if missing_w:
                raise CompileError(f"Subsample variables need subsample weights, but none were found for cycle(s) {', '.join(missing_w)}.")
    else:
        too_strict = set()
        cycles = []
        for v in sorted(raw):
            raw_vars.append({"variable": v, "file": "data", "cycles": [], "type": "unknown", "min": None, "max": None,
                             "missing_codes": [], "weight_level": "interview"})
        weight_level = "analysis"

    sets = []
    for a in plan.get("adjustment_sets", []):
        sets.append({"id": a["id"], "label": a["label"], "covariates": [c for c in a["covariates"] if c != exposure]})
    sens_out = []
    weight_notes = []
    for s in sens:
        item = {k2: v for k2, v in s.items() if k2 not in ("enabled",)}
        used = ([item["outcome"]] if item.get("outcome") else []) + ([item["exposure"]] if item.get("exposure") else []) \
            + list(item.get("covariates") or []) + (expressions.validate(item["expr"]) if item.get("expr") else [])
        if any(u in too_strict for u in used):
            weight_notes.append(f"Sensitivity analysis '{item.get('label', item.get('type'))}' left out: it needs a subsample weight "
                                f"the primary analysis does not use.")
            continue
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
        "cycles_meta": ({c: _with_subsample(k.cycles[c], subsample.get(c)) for c in cycles} if is_nhanes else {}),
        "subsample_weights": {c: v.get(weight_level) or next(iter(v.values())) for c, v in subsample.items()} if is_nhanes else {},
        "weight_level": weight_level,
        "raw_variables": raw_vars,
        "derived": derived,
        "variables_meta": meta,
        "population": [{"id": c["id"], "label": c["label"], "expr": c["expr"], "kind": c.get("kind", "inclusion")} for c in population],
        "outcome": {"name": outcome, "type": plan["outcome"]["type"], "label": meta.get(outcome, {}).get("label", outcome)},
        "exposure": ({"name": exp_name, "type": plan["exposure"]["type"], "label": meta.get(exp_name, {}).get("label", exp_name),
                      "arms": plan.get("arms")}
                     if exposure else None),
        "covariates": [c for c in plan.get("covariates", []) if c != exposure],
        "subgroups": [g for g in plan.get("subgroups", []) if g not in too_strict],
        "analysis": {
            "estimand": plan["study_type"],
            "table1_vars": [v for v in plan.get("table1_vars", []) if v not in too_strict],
            "table1_by": plan.get("table1_by") if plan.get("table1_by") not in too_strict else None,
            "prevalence": {"outcomes": [v for v in plan.get("prevalence_outcomes", []) if v not in too_strict],
                           "by": [v for v in plan.get("prevalence_by", []) if v not in too_strict]},
            "model": {"family": plan["model"]["family"], "primary_set": plan["model"].get("primary_set", "full")},
            "adjustment_sets": sets,
            "interactions": [v for v in plan.get("interactions", []) if v not in too_strict],
            "missing": {"method": plan.get("missing_data", {}).get("method", "complete_case"), "m": 10},
            "sensitivity": sens_out,
            "benchmarks": plan.get("benchmarks", []),
            "distribution_var": None,
            "age_adjust": plan.get("age_adjust") if (plan.get("age_adjust") or {}).get("enabled") and is_nhanes else {"enabled": False},
            "trend": plan.get("trend") if (plan.get("trend") or {}).get("enabled") and is_nhanes else {"enabled": False},
            "median": bool((plan.get("estimand") or {}).get("median")),
            "count": bool((plan.get("estimand") or {}).get("count")),
        },
        "options": {"seed": 2026, "alpha": 0.05},
        "weight_notes": weight_notes + [f"'{meta.get(v, {}).get('label', v)}' left out of descriptive tables: it is measured in a subsample "
                                        f"with its own weight, and the primary analysis uses the {weight_level} weight." for v in sorted(too_strict)
                                        if v in set(plan.get("table1_vars", [])) | set(plan.get("prevalence_outcomes", [])) | set(plan.get("prevalence_by", []))],
        "unavailable_measures": unavailable + ([d["name"] for d in derived if _not_in_cycles(d["name"], cycles, k, plan)] if is_nhanes else []),
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
    path.write_text(json.dumps(compiled, indent=2, default=str), encoding="utf-8")
    return path
