"""Group comparisons: baseline characteristics (sex, age, race, income, education), named age groups, multi-group
(arms) questions in everyday phrasings, and the AI layer not breaking any of them."""
import json

import pytest

from q2e import agents, compiler, llm
from q2e.knowledge import get_knowledge


def _cmp(p):
    return (p.get("estimand") or {}).get("comparison") or {}


@pytest.mark.parametrize("q,var,level,ref", [
    ("Compare hypertension between men and women", "sex", "Male", "Female"),
    ("HTN by gender", "sex", None, None),
    ("Compare obesity prevalence between Black and White adults", "race_eth", "Non-Hispanic Black", "Non-Hispanic White"),
    ("Does diabetes prevalence differ by race/ethnicity?", "race_eth", None, None),
    ("Compare hypertension prevalence across age groups", "agecat_nchs18", "60+", "18-39"),
    ("Does obesity differ by education?", "educ", None, None),
    ("Is hypertension more common in adults 60 and older than adults 20-39?", "age_cmp", "60+", "20-39"),
    ("Compare diabetes in adults 40-59 vs 60+", "age_cmp", "40-59", "60+"),
])
def test_baseline_comparisons(q, var, level, ref):
    p = agents.design_study(q, None)
    c = _cmp(p)
    assert c.get("group_var") == var and c.get("level") == level and c.get("reference") == ref


def test_named_age_groups_compare_not_filter():
    p = agents.design_study("Is hypertension more common in adults 60 and older than adults 20-39?", None)
    pops = [x["label"] for x in p["population"] if x.get("enabled") and x["kind"] == "inclusion"]
    assert pops == ["Age >=20 years"]                                   # both groups kept, not only 60+
    assert any(v["name"] == "age_cmp" for v in p["custom_variables"])
    spec = compiler.compile_plan(p, get_knowledge())
    assert spec["analysis"]["comparison"]["group_var"] == "age_cmp"
    assert "age_cmp" in spec["analysis"]["age_adjust"]["not_by"]


def test_list_of_outcomes_keeps_the_comparison():
    p = agents.design_study("Compare the prevalence of obesity and diabetes between men and women", None)
    assert _cmp(p).get("group_var") == "sex" and p["outcome"]["concept"] == "obesity"


@pytest.mark.parametrize("q", [
    "Toxocara vs Toxoplasma vs healthy for eos",
    "Compare eos between Toxocara, Toxoplasma and healthy people",
    "Is eosinophil count higher in Toxocara positive than Toxoplasma positive and healthy adults?",
    "Compare eosinophil count in Toxocara vs Toxoplasma seropositive vs healthy adults",
])
def test_multi_group_phrasings(q):
    p = agents.design_study(q, None)
    x = p["exposure"]
    assert x.get("arms") and [a["concept"] for a in x["arms"]["arms"]] == ["toxocara", "toxoplasma"]
    assert x["arms"]["control_mode"] == "healthy"
    assert p["outcome"]["concept"] == "eosinophils" and p["outcome"]["type"] == "continuous"   # a count, not eosinophilia


def test_eosinophilia_stays_binary():
    p = agents.design_study("eosinophilia in toxocara vs toxoplasma", None)
    assert p["outcome"]["type"] == "binary" and p["exposure"].get("arms")


@pytest.mark.parametrize("q,out,exp", [
    ("Is HbA1c higher in obese than non-obese adults?", "glycemic_control", "obesity"),
    ("Is anemia more common in adults with CKD?", "anemia", "ckd"),
    ("Compare obesity by insurance status", "obesity", "insurance"),
    ("Is waist circumference associated with HbA1c among US adults?", "glycemic_control", "abdominal_obesity"),
])
def test_roles(q, out, exp):
    p = agents.design_study(q, None)
    assert p["outcome"]["concept"] == out and p["exposure"]["concept"] == exp


def test_not_arms_when_ordinary_association():
    for q in ("Is hypertension associated with diabetes and obesity?", "Is HbA1c higher in obese than non-obese adults?"):
        assert not (agents.design_study(q, None).get("exposure") or {}).get("arms")


class _AI(llm.BaseProvider):
    """Plausible model replies that used to break comparisons: group filters and a demographic 'exposure'."""
    name, model = "fake", "fake-1"

    def available(self):
        return True, ""

    def complete(self, system, user, max_tokens=2000):
        if "RESEARCH IDEA" in user:
            idea = user.split("RESEARCH IDEA:")[1]
            if "race" in idea:
                return json.dumps({"study_type": "association", "exposure_concept": "race",
                                   "populations": ["race_nhblack", "race_hispanic", "race_nhwhite"]})
            if "age groups" in idea:
                return json.dumps({"study_type": "association", "exposure_concept": "age", "populations": ["older_adults"]})
            return json.dumps({"study_type": "association", "exposure_concept": "sex", "populations": ["adults", "men", "women"]})
        if "candidates" in user:
            return json.dumps({"picks": []})
        if "Draft statistical" in user:
            return json.dumps({"rationale": "x", "suggestions": []})
        return json.dumps({"issues": []})


@pytest.mark.parametrize("q,var", [
    ("Is hypertension more common in men than women among US adults?", "sex"),
    ("Does obesity prevalence differ by race and ethnicity?", "race_eth"),
    ("Compare anemia prevalence across age groups", "agecat_nchs18"),
])
def test_ai_cannot_break_a_comparison(monkeypatch, q, var):
    monkeypatch.setattr(llm, "get_provider", lambda name=None: _AI())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    p = agents.design_study(q, ["P"], {"type": "nhanes", "cycles": ["P"], "source": "synthetic"}, provider="fake")
    assert _cmp(p).get("group_var") == var and not p.get("exposure")
    pops = [x["label"] for x in p["population"] if x.get("enabled") and x["kind"] == "inclusion"]
    assert not any(w in " ".join(pops) for w in ("Black", "Hispanic", "White", ">=65", "Male", "Female")), pops
    assert any("Did not apply AI population filters" in d["message"] for d in p["agent_dialogue"]) or var == "sex"
