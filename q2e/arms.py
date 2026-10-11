"""Multi-arm comparisons: "Toxoplasma vs Toxocara vs healthy controls for eosinophilia".

The arms become ONE categorical exposure with mutually exclusive groups and an explicit reference group:

    Control (reference) | <Arm A> only | <Arm B> only | Both ...

Control groups are defined, not assumed:
    seronegative  - negative for every arm (all comparison conditions absent)            [default]
    healthy       - seronegative AND free of conditions that independently change the outcome
                    (domain-specific, e.g. asthma/COPD for eosinophilia) and of major chronic disease
Selecting "healthy" controls only for the reference group biases estimates away from the null (healthy-control bias),
so the alternative definition always runs as a prespecified sensitivity analysis and the design auditor flags it.
"""
from __future__ import annotations

import re
from typing import Any

from .knowledge import Knowledge

VS = re.compile(r"\s(?:vs\.?|versus|v\.|compared (?:with|to)|against)\s")
# when the question is clearly a group comparison, plain list words also separate groups:
# "higher in Toxocara than Toxoplasma and healthy adults", "between Toxocara, Toxoplasma and healthy people"
CUE = re.compile(r"\b(?:vs\.?|versus|compar\w*|between|than|differ\w*|difference)\b|\bhealthy\b|\bcontrols?\b")
LIST_SEP = re.compile(r"(?:\s(?:than|and|or|&)\s|,\s|\s/\s)")
CONTROL_WORDS = re.compile(r"\b(healthy controls?|healthy (?:participants|people|adults|individuals|subjects|children|persons)|"
                           r"healthy|controls?|uninfected|seronegative|negative controls?|unexposed|neither|non-?infected|"
                           r"without (?:either|any|infection))\b")
HEALTHY_WORDS = re.compile(r"\bhealthy\b")
OUTCOME_LEADS = re.compile(r"\b(?:for|on|in terms of|regarding|with respect to|risk of|rates? of|prevalence of|odds of|levels? of)\s")

# conditions that independently change an outcome domain; excluded from HEALTHY controls (and adjusted elsewhere)
HEALTHY_EXCLUSIONS = {
    "hematology": [("asthma", "Asthma"), ("copd", "COPD")],
    "iron": [("ckd", "Chronic kidney disease")],
    "glycemia": [],
    "kidney": [("diabetes", "Diabetes")],
}
GENERAL_HEALTHY = [("diabetes", "Diabetes"), ("cvd", "Cardiovascular disease"), ("ckd", "Chronic kidney disease"),
                   ("cancer_hx", "Cancer history"), ("liver_hx", "Liver disease")]


def detect(q: str, ordered: list[dict], k: Knowledge, concept_of) -> dict | None:
    """Return {arms, outcome, control_mode} when the question compares 2+ groups (or 1 group vs controls) on an outcome.

    Arms are the concepts sitting directly on either side of a 'vs / versus / compared with' separator; the outcome is
    the remaining clinical concept ("... for eosinophilia", "eosinophilia in A vs B", "is X more common with A than ...")."""
    seps = list(VS.finditer(q))
    if CUE.search(q):
        seps = sorted(seps + [m for m in LIST_SEP.finditer(q) if not any(v.start() <= m.start() < v.end() for v in seps)],
                      key=lambda m: m.start())
    if not seps:
        return None
    clinical = sorted([c for c in ordered if concept_of(c["concept"]).get("domain") not in ("demographic",)], key=lambda c: c["pos"])
    if len(clinical) < 2:
        return None

    def can_be_arm(cid: str) -> bool:      # a group is a yes/no condition (infection, disease), never a lab level
        cc = concept_of(cid)
        defs = [d for d in (cc.get("definitions") or []) if k.definitions.get(d, {}).get("type") == "binary"]
        return bool(defs) or cid.startswith("dict:") or k.blocks.get(cc.get("block", ""), {}).get("type") == "binary"

    def end(c):
        return c["pos"] + len(c["phrase"])

    arm_ids: list[str] = []
    for m in seps:
        def adjacent(gap: str) -> bool:     # nothing but a few filler words; a control group or "for ..." breaks adjacency
            return len(gap.split()) <= 4 and not CONTROL_WORDS.search(gap) and not OUTCOME_LEADS.search(" " + gap + " ")
        before = [c for c in clinical if end(c) <= m.start() + 1 and adjacent(q[end(c):m.start()])]
        after = [c for c in clinical if c["pos"] >= m.end() - 1 and adjacent(q[m.end():c["pos"]])]
        pair = ([before[-1]] if before else []) + ([after[0]] if after else [])
        if not VS.fullmatch(m.group(0)) and m.group(0).strip() not in ("than",) and not all(can_be_arm(c["concept"]) for c in pair):
            continue        # "eosinophil count and Toxocara": a list word only joins two groups, not an outcome and a group
        for c in pair:
            if c["concept"] not in arm_ids and can_be_arm(c["concept"]):
                arm_ids.append(c["concept"])
    rest = [c for c in clinical if c["concept"] not in arm_ids]
    if not rest:
        return None
    led = [c for c in rest if OUTCOME_LEADS.search(q[max(0, c["pos"] - 25):c["pos"]] + " ")]
    outcome = (led or rest)[0]
    arms = list(arm_ids)
    if not arms:
        return None
    first_arm = min(c["pos"] for c in clinical if c["concept"] in arms)
    m = CONTROL_WORDS.search(q[first_arm:])
    if len(arms) < 2 and not m:
        return None          # one exposure and no explicit control group = ordinary association
    mode = "healthy" if m and HEALTHY_WORDS.search(m.group(0)) else "seronegative"
    return {"arms": arms, "outcome": outcome["concept"], "control_mode": mode, "control_mentioned": bool(m)}


def _arm_var(cid: str, k: Knowledge, concept_of, choose) -> dict:
    v = choose(cid, "exposure", {"prefer": [], "upgrade": {}}, k)
    if v["type"] != "binary":
        raise ValueError(f"Arm '{v['concept_label']}' is not a yes/no measure; cannot form comparison groups.")
    return v


def control_criteria(mode: str, outcome_domain: str, k: Knowledge) -> list[tuple[str, str]]:
    if mode != "healthy":
        return []
    crit = [x for x in HEALTHY_EXCLUSIONS.get(outcome_domain, [])] + GENERAL_HEALTHY
    seen, out = set(), []
    for name, label in crit:
        if name not in seen and (name in k.blocks or name in k.definitions):
            seen.add(name)
            out.append((name, label))
    return out


def build_exposure(spec: dict, outcome: dict, k: Knowledge, concept_of, choose, both: str = "separate") -> dict:
    arms = [_arm_var(c, k, concept_of, choose) for c in spec["arms"]]
    mode = spec.get("control_mode", "seronegative")
    crit = control_criteria(mode, outcome.get("domain", "default"), k)
    dropped = []
    if crit:
        # never screen controls on the outcome itself (or anything sharing its source items): that would force the
        # control group's outcome rate towards zero
        from .planner import _raw_dependencies
        ocustom = {outcome["custom"]["name"]: outcome["custom"]} if outcome.get("custom") else {}
        oraw = set(_raw_dependencies(outcome["variable"], k, ocustom)) - {"RIAGENDR", "RIDAGEYR", "RIDEXPRG"}
        crit_ok = []
        arm_vars = {a["variable"] for a in arms} | {a["concept"] for a in arms} | {k.concepts.get(a["concept"], {}).get("block") for a in arms}
        for c, lab in crit:
            if c in arm_vars:
                continue            # already excluded: controls are negative for every arm
            if c == outcome["variable"] or (set(_raw_dependencies(c, k, {})) & oraw):
                dropped.append((c, lab + " (part of the outcome)"))
            else:
                crit_ok.append((c, lab))
        crit = crit_ok
    if crit:
        from .planner import available_cycles, best_cycles, usable_cycles
        custom = {a["custom"]["name"]: a["custom"] for a in arms if a.get("custom")}
        arm_cy = usable_cycles([a["variable"] for a in arms], k, custom)     # weight-aware (surplus sera etc.)
        target = set(best_cycles(arm_cy, k)) if arm_cy else set()
        keep = []
        for c, lab in crit:
            (keep if target <= available_cycles(c, k) else dropped).append((c, lab))
        crit = keep
    names = [a["variable"] for a in arms]
    short = [re.sub(r"\s*(seropositivity|seropositive|\(.*?\))\s*", " ", a["concept_label"]).strip() or a["concept_label"] for a in arms]
    pos = [f"coalesce({n}, 0) == 1" for n in names]
    any_missing = " | ".join(f"is.na({n})" for n in names)
    healthy = " & ".join(f"coalesce({c}, 0) == 0" for c, _ in crit)
    control_cond = " & ".join(f"{n} == 0" for n in names) + (f" & {healthy}" if healthy else "")
    control_label = "Healthy controls" if mode == "healthy" else ("Controls (negative for all)" if len(arms) > 1 else f"No {short[0].lower()}")
    clauses, levels = [f"{any_missing}", "NA"], [control_label]
    if len(arms) > 1:
        if both == "separate":
            clauses += [" & ".join(pos), '"Both positive"' if len(arms) == 2 else '"More than one positive"']
        else:
            clauses += [" & ".join(pos), "NA"]
    for i, (n, lab) in enumerate(zip(names, short)):
        others = [f"coalesce({o}, 0) == 0" for j, o in enumerate(names) if j != i]
        cond = " & ".join([pos[i]] + others) if len(arms) > 1 else pos[i]
        level = f"{lab} only" if len(arms) > 1 else lab
        clauses += [cond, f'"{level}"']
        levels.append(level)
    if len(arms) > 1 and both == "separate":
        levels.append("Both positive" if len(arms) == 2 else "More than one positive")
    clauses += [control_cond, f'"{control_label}"']
    expr = "cases(" + ", ".join(clauses) + ")"
    expr = expr.replace('NA, ', 'NA_character_, ', 1) if False else expr
    label = " vs ".join(short) + f" vs {control_label.lower()}"
    alt = None
    if mode == "healthy":
        alt = {"type": "alt_exposure", "label": "Alternative control group: everyone negative for all groups, no health screening (healthy-control bias check)",
               "exposure": "arms_seroneg"}
    cid = "arms:" + "+".join(spec["arms"])
    return {
        "concept": cid, "concept_label": label, "variable": "arms", "kind": "custom", "type": "categorical", "label": label,
        "definition_id": None, "alternatives": [], "companions": [], "domain": arms[0]["domain"],
        "custom": {"name": "arms", "expr": expr, "label": label, "type": "categorical", "levels": levels, "source": "comparison arms"},
        "arms": {"arms": [{"concept": a["concept"], "variable": a["variable"], "label": a["concept_label"]} for a in arms],
                 "control_mode": mode, "control_label": control_label,
                 "control_criteria": [{"variable": c, "label": l} for c, l in crit],
                 "control_criteria_unavailable": [l for _, l in dropped],
                 "both": both, "levels": levels, "reference": control_label},
        "alt_seroneg": _seroneg_custom(names, short, both) if mode == "healthy" else None,
        "arm_custom": [a["custom"] for a in arms if a.get("custom")],
        "alt_sensitivity": alt,
    }


def _seroneg_custom(names: list[str], short: list[str], both: str) -> dict:
    pos = [f"coalesce({n}, 0) == 1" for n in names]
    clauses = [" | ".join(f"is.na({n})" for n in names), "NA"]
    levels = ["Controls (negative for all)"]
    if len(names) > 1:
        clauses += [" & ".join(pos), '"Both positive"' if both == "separate" else "NA"]
    for i, (n, lab) in enumerate(zip(names, short)):
        others = [f"coalesce({o}, 0) == 0" for j, o in enumerate(names) if j != i]
        clauses += [" & ".join([pos[i]] + others), f'"{lab} only"' if len(names) > 1 else f'"{lab}"']
        levels.append(f"{lab} only" if len(names) > 1 else lab)
    if len(names) > 1 and both == "separate":
        levels.append("Both positive")
    clauses += [" & ".join(f"{n} == 0" for n in names), '"Controls (negative for all)"']
    return {"name": "arms_seroneg", "expr": "cases(" + ", ".join(clauses) + ")", "label": "Comparison groups (all seronegative controls)",
            "type": "categorical", "levels": levels, "source": "comparison arms (sensitivity)"}


def describe(arms: dict) -> list[str]:
    out = [f"Groups are mutually exclusive; reference group: {arms['reference']}."]
    if arms["control_mode"] == "healthy":
        crit = ", ".join(c["label"].lower() for c in arms["control_criteria"]) or "none"
        out.append(f"Healthy controls: negative for every arm and free of {crit}.")
        out.append("Healthy controls are healthier than the arms by construction (healthy-control bias); controls negative for every group (no health screening) run as a sensitivity analysis.")
    else:
        out.append("Controls: negative for every arm (no health restriction).")
    if arms["both"] == "separate":
        out.append("Participants positive for more than one arm form their own group (not counted in either single arm).")
    return out
