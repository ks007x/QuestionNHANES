"""Borderline sleep / functional-status questions: right proxy, honest caveats, honest refusals."""
import pytest

from q2e import answerability, planner


@pytest.mark.parametrize("q,outcome_var,exposure_var", [
    ("Is short sleep duration associated with obesity in US adults?", "obesity_bmi30", "short_sleep_lt7"),
    ("Is obstructive sleep apnea associated with hypertension?", "htn_accaha2017", "osa_symptoms"),
    ("Is daytime sleepiness associated with diabetes?", "diabetes_ada", "excessive_sleepiness"),
    ("Is insomnia associated with depression in adults?", "depression_phq9", "sleep_trouble"),
])
def test_sleep_questions_map_to_binary_proxies(q, outcome_var, exposure_var):
    p = planner.draft(q)
    assert p["outcome"]["variable"] == outcome_var
    assert p["exposure"]["variable"] == exposure_var


@pytest.mark.parametrize("q,outcome_var", [
    ("What is the prevalence of functional limitation among older adults with diabetes?", "mobility_limitation_pfq"),
    ("What is the prevalence of disability among adults with chronic kidney disease?", "disability_wg"),
])
def test_function_questions(q, outcome_var):
    p = planner.draft(q)
    assert p["study_type"] == "prevalence" and p["outcome"]["variable"] == outcome_var


def test_osa_is_flagged_as_symptom_proxy():
    p = planner.draft("Is obstructive sleep apnea associated with hypertension?")
    assert any("polysomnography" in l for l in p["limitations"])
    assert any(r["id"] == "opnotes_osa_symptoms" and r["severity"] == "major" for r in p["review"])


@pytest.mark.parametrize("q", ["Is insomnia associated with depression in adults?",
                               "Is depression associated with short sleep in adults?"])
def test_phq9_sleep_item_circularity(q):
    p = planner.draft(q)
    assert any(r["id"] == "overlap_phq9_sleep_item" for r in p["review"])
    assert any(s.get("outcome") == "depression_phq8" or s.get("exposure") == "depression_phq8" for s in p["sensitivity"])
    assert any(l.startswith("Measurement overlap") for l in p["limitations"])


@pytest.mark.parametrize("q,phrase", [
    ("Is restless legs syndrome associated with iron deficiency?", "restless legs syndrome"),
    ("Is frailty associated with anemia in older adults?", "frailty"),
    ("Does poor sleep cause weight gain over time?", "weight gain"),
])
def test_honest_refusals(q, phrase):
    a = answerability.assess_question(q)
    assert a["verdict"].startswith("Not answerable")
    assert phrase in [n["phrase"] for n in a["parsed"]["not_in_nhanes"]]


@pytest.mark.parametrize("q,component", [
    ("Is shift work associated with short sleep?", "shift work"),
    ("Is low muscle mass associated with insulin resistance?", "low muscle mass"),
])
def test_measured_but_uncurated_points_to_component(q, component):
    a = answerability.assess_question(q)
    assert component in [c["phrase"] for c in a["parsed"]["component_matches"]]
    p = planner.parse_question(q)
    assert "BMXARMC" not in [m["variable"] for m in p["dictionary_matches"]]
