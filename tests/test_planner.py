import pytest

from q2e import planner
from q2e.compiler import compile_plan, plan_hash
from q2e.knowledge import get_knowledge
from q2e.language_guard import scan_causal
from q2e.privacy import scrub


def test_fid_prevalence_plan():
    p = planner.draft("Do a research study on the prevalence of functional iron deficiency in US adults.")
    assert p["study_type"] == "prevalence"
    assert p["outcome"]["variable"] == "fid_tawfik2024"
    assert p["model"]["family"] == "quasipoisson"
    assert any(b["outcome"] == "fid_tawfik2024" for b in p["benchmarks"])
    assert any("!is.na(ferritin)" in c["expr"] for c in p["population"])


def test_challenge_example_association():
    p = planner.draft("I have noticed that adults with greater abdominal obesity may have worse blood sugar control even at similar weight.")
    assert p["study_type"] == "association"
    assert p["exposure"]["variable"] == "waist" and p["exposure"]["scale"] == 10
    assert p["outcome"]["variable"] == "hba1c"
    assert "bmi" in p["covariates"]            # 'at similar weight'
    assert "diabetes" not in p["covariates"]   # mediator / outcome-defined
    assert p["model"]["family"] == "gaussian"
    assert any(s["type"] == "mi" for s in p["sensitivity"])


def test_guideline_hint_kdigo_restricts_population():
    p = planner.draft("What is the prevalence of iron deficiency in adults with chronic kidney disease using KDIGO 2026 criteria?")
    assert p["outcome"]["variable"].startswith("ckd_")
    assert any(c["expr"] == "ckd == 1" for c in p["population"])


def test_baveno_and_ash_hints():
    p = planner.draft("Prevalence of clinically significant portal hypertension by Baveno VIII among adults")
    assert p["outcome"]["variable"] == "csph_baveno8"
    p = planner.draft("How common is iron deficiency among women of reproductive age under ASH 2026 thresholds?")
    assert p["outcome"]["variable"] == "id_ash2026"
    assert "sex" not in p["subgroups"]


def test_reviewer_blocks_overlapping_cycles_and_fix():
    p = planner.draft("Prevalence of anemia in US adults", cycles=["J", "P"])
    ids = {i["id"] for i in p["review"]}
    assert "cycle_overlap" in ids
    fix = next(i for i in p["review"] if i["id"] == "cycle_overlap")["fix"]
    p2 = planner.apply_fix(p, fix)
    assert p2["dataset"]["cycles"] == ["P"]
    assert "cycle_overlap" not in {i["id"] for i in planner.review_plan(p2)}


def test_definitional_overlap_removed():
    p = planner.draft("Is higher liver stiffness associated with thrombocytopenia in US adults?")
    assert "fib4" not in p["covariates"]


def test_edit_changes_hash_and_compiles():
    p = planner.draft("Is higher liver stiffness associated with thrombocytopenia in US adults?")
    h = plan_hash(p)
    p2 = planner.apply_fix(p, {"op": "set", "path": "model.family", "value": "quasibinomial"})
    assert plan_hash(p2) != h
    assert any(i["id"] == "or_common" for i in planner.review_plan(p2))
    c = compile_plan(p2)
    assert c["exposure"]["name"] == "lsm_per5"


def test_compiler_topological_and_weights():
    k = get_knowledge()
    for ex in k.examples:
        c = compile_plan(planner.draft(ex["question"]))
        defined = {r["variable"] for r in c["raw_variables"]}
        from q2e.expressions import identifiers
        for d in c["derived"]:
            assert set(identifiers(d["expr"])) <= defined, d
            defined.add(d["name"])
        assert c["weight_level"] in ("mec", "fasting", "interview")


def test_fasting_variable_switches_weight():
    p = planner.draft("Is waist circumference associated with fasting glucose in adults?")
    p = planner.apply_fix(p, {"op": "add_covariate", "name": "fpg"}) if p["outcome"]["variable"] != "fpg" else p
    c = compile_plan(p)
    assert c["weight_level"] == "fasting"


def test_unknown_question_raises():
    with pytest.raises(ValueError):
        planner.draft("Tell me something interesting about the weather today")


def test_causal_guard_and_privacy():
    assert scan_causal("Obesity causes diabetes")
    assert not scan_causal("Obesity is associated with diabetes")
    txt, f = scrub("Patient John Smith MRN: 12345678, call 732-555-1234 or j@x.org on 03/04/2025")
    assert "John" not in txt and "12345678" not in txt and "j@x.org" not in txt and len(f) >= 4
