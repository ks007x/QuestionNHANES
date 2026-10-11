"""Fixes learned from the accuracy benchmark against published NCHS/JAMA NHANES estimates."""
from q2e import agents
from q2e.compiler import compile_plan
from q2e.evidence import is_nhanes_analysis


def _plan(q, cycles=("P",)):
    return agents.design_study(q, list(cycles), {"type": "nhanes", "cycles": list(cycles), "source": "cdc"})


def _crit(p):
    return [c["expr"] for c in p["population"] if c.get("enabled", True)]


def test_threshold_in_question_selects_published_definition():
    assert _plan("What is the prevalence of severe obesity (BMI 40 or higher) among US adults aged 20 and over?")["outcome"]["variable"] == "severe_obesity_cdc"
    assert _plan("What is the prevalence of absolute iron deficiency (ferritin below 30 ng/mL) among US adults?")["outcome"]["variable"] == "aid_tawfik2024"
    assert _plan("Prevalence of high total cholesterol (240 mg/dL or higher) in adults aged 20 and over", ["L"])["outcome"]["variable"] == "high_tc_240"
    assert _plan("Prevalence of low HDL cholesterol (below 40 mg/dL) in adults aged 20 and over", ["L"])["outcome"]["variable"] == "low_hdl_40"


def test_threshold_without_library_definition_becomes_yes_no_variable():
    p = _plan("What is the prevalence of elevated CRP (above 3 mg/L) among US adults?")
    assert p["study_type"] == "prevalence" and p["outcome"]["type"] == "binary"
    assert any(c["expr"] == "crp > 3" for c in p["custom_variables"])


def test_ages_are_not_read_as_thresholds():
    p = _plan("What is the prevalence of obesity among US adults aged 20 and over?")
    assert p["outcome"]["variable"] == "obesity_bmi30" and "age >= 20" in _crit(p)


def test_children_never_get_adult_cutoffs():
    p = _plan("What is the prevalence of obesity among US children and adolescents aged 2 to 19 years?")
    assert p["outcome"]["variable"] == "obesity_cdc"
    c = compile_plan(p)
    assert any("cdc_bmi_pct" in d["expr"] for d in c["derived"])


def test_national_diabetes_prevalence_uses_nchs_definition_and_fasting_weight():
    for cy, w in (("P", "WTSAFPRP"), ("L", "WTSAF2YR")):
        p = _plan("What is the prevalence of diabetes among US adults aged 20 and over?", [cy])
        assert p["outcome"]["variable"] == "diabetes_nchs"
        c = compile_plan(p)
        assert c["weight_level"] == "fasting" and c["cycles_meta"][cy]["weights"]["fasting"] == w
    # association studies keep the full-sample definition
    assert _plan("Is physical activity associated with diabetes?")["outcome"]["variable"] == "diabetes_ada"


def test_hypertension_2021_2023_uses_exam_weight_and_new_medication_item():
    c = compile_plan(_plan("What is the prevalence of hypertension among US adults aged 18 and over?", ["L"]))
    assert c["weight_level"] == "mec" and c["cycles_meta"]["L"]["weights"]["mec"] == "WTMEC2YR"
    assert "BPQ150" in {r["variable"] for r in c["raw_variables"]}
    assert any("mean_of(BPXOSY1" in d["expr"] for d in c["derived"])
    assert c["weight_notes"], "lab-based Table 1 extras are dropped with a note instead of changing the weight"


def test_anemia_needs_only_hemoglobin_and_excludes_pregnancy():
    p = _plan("What is the prevalence of anemia in the US population aged 2 years and older?", ["L"])
    assert not any("ferritin" in e or "tsat" in e for e in _crit(p))
    assert "pregnant == 1" in _crit(p)
    c = compile_plan(p)
    assert c["weight_level"] == "phlebotomy" and c["cycles_meta"]["L"]["weights"]["phlebotomy"] == "WTPH2YR"


def test_published_benchmarks_attach_by_cycle_and_age():
    assert [b["label"] for b in _plan("What is the prevalence of hypertension among US adults aged 18 and over?", ["L"])["benchmarks"]] \
        == ["NCHS Data Brief 511, adults 18+, Aug 2021-Aug 2023 (crude)"]
    assert _plan("What is the prevalence of hypertension among US adults aged 40 and over?", ["L"])["benchmarks"] == []


def test_papers_that_only_cite_nhanes_are_not_compared():
    assert not is_nhanes_analysis({"title": "Prevalence and Severity of Chronic Kidney Disease in Haiti.",
                                   "abstract": "Rates were compared with US NHANES data."})
    assert is_nhanes_analysis({"title": "CKD awareness among US adults", "abstract": "Data from NHANES 2017-2020 were analysed."})


def test_survey_wording_is_not_read_as_a_variable():
    p = _plan("What percentage of US adults aged 60 and over have severe obesity?")
    assert p["outcome"]["variable"] == "severe_obesity_cdc" and p["study_type"] == "prevalence"


def test_diagnosed_and_undiagnosed_diabetes():
    assert _plan("Prevalence of diagnosed diabetes among US adults aged 20 and over", ["L"])["outcome"]["variable"] == "diabetes_diagnosed"
    p = _plan("Prevalence of undiagnosed diabetes among US adults aged 20 and over", ["L"])
    assert p["outcome"]["variable"] == "diabetes_undiagnosed" and compile_plan(p)["weight_level"] == "fasting"


def test_ages_missing_from_public_files_are_flagged():
    p = _plan("What is the prevalence of depression among US adolescents aged 12 to 19?", ["L"])
    assert any(i["severity"] == "blocker" and "12-17" in i["title"] for i in p["review"])
    p = _plan("What is the prevalence of depression among US adolescents and adults aged 12 and over?", ["L"])
    assert "age >= 18" in _crit(p) and any(i["severity"] == "warning" for i in p["review"] if i["id"].startswith("data_limit"))
