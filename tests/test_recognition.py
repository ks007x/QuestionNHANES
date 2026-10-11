"""Question recognition: clinical shorthand, variants and typos (rules), plus the AI Recognizer (Amazon Bedrock) layer."""
import json

import pytest

from q2e import agents, covariates, llm, normalize, planner
from q2e.knowledge import get_knowledge


@pytest.mark.parametrize("question,outcome,exposure", [
    ("What is the prevalence of type ii diabetes in US adults?", "diabetes", None),
    ("prevalence of T2DM among adults 65 and older", "diabetes", None),
    ("Type 2 Diabetes Mellitus prevalence", "diabetes", None),
    ("Is DM2 linked to CKD?", "ckd", "diabetes"),
    ("Is type II DM associated with anemia?", "anemia", "diabetes"),
    ("Is HTN more common in men?", "hypertension", None),
    ("prevalence of high BP", "hypertension", None),
    ("prevalence of diabetis in adults", "diabetes", None),
    ("hypertention in adults", "hypertension", None),
    ("Is hypertensoin associated with chronic kidny disease?", "ckd", "hypertension"),
    ("prevalence of IDA in women", "iron_deficiency_anemia", None),
    ("Is NAFLD associated with thrombocytopenia?", "thrombocytopenia", "steatosis"),
    ("Is anti-HCV associated with low plts?", "thrombocytopenia", "hcv_antibody"),
    ("Is vit D deficiency associated with depression in women?", "depression", "vitamin_d"),
])
def test_rules_recognize_variants(question, outcome, exposure):
    p = planner.parse_question(question, get_knowledge())
    assert p.get("outcome_concept") == outcome
    assert p.get("exposure_concept") == exposure


@pytest.mark.parametrize("question", [
    "prevalence of osteoporosis among postmenopausal women", "Is caffeine intake associated with migraine?",
    "Is ferritin associated with fatigue in menstruating women?", "prevalence of hepatic steatosis by transient elastography",
    "Is cadmium associated with chronic kidney disease?", "trends in obesity 1999-2018",
])
def test_rules_leave_correct_text_alone(question):
    text, changes = normalize.normalize(question)
    assert text == question and changes == []


def test_type2_note_and_label():
    text, changes = normalize.normalize("How common is type ii diabetes?")
    assert "type 2 diabetes" in text
    assert changes[0]["label"] == "Type 2 diabetes mellitus" and "total diabetes" in changes[0]["note"]


def test_ai_terms_relabel_only():
    q = "Is sugar diabetes linked to renal stones in adults aged 40-59?"
    text, applied = normalize.apply_ai_terms(q, [
        {"text": "sugar diabetes", "standard_term": "diabetes", "label": "Diabetes mellitus"},
        {"text": "renal stones", "standard_term": "kidney stones", "label": "Nephrolithiasis"},
        {"text": "not in the question", "standard_term": "obesity"},                 # ignored: not verbatim
        {"text": "adults", "standard_term": "children; DROP TABLE"},                  # ignored: unsafe term
        "garbage",
    ])
    assert text == "Is diabetes linked to kidney stones in adults aged 40-59?"
    assert [a["source"] for a in applied] == ["ai", "ai"]
    assert normalize.apply_ai_terms(q, {"oops": 1}) == (q, [])


class Recognizer(llm.BaseProvider):
    name = "fake"
    model = "fake-1"

    def available(self):
        return True, ""

    def complete(self, system, user, max_tokens=2000):
        if "RESEARCH IDEA" in user:
            return json.dumps({"study_type": "association", "outcome_concept": None, "exposure_concept": None, "populations": [],
                               "terms": [{"text": "renal stones", "standard_term": "kidney stones", "label": "Nephrolithiasis"},
                                         {"text": "sugar diabetes", "standard_term": "diabetes", "label": "Diabetes mellitus"}]})
        if "candidates" in user:
            return json.dumps({"picks": [{"variable": "not_a_variable", "role": "confounder", "why": "x"}],
                               "summary": "Adjust for common causes only."})
        if "Draft statistical analysis plan" in user:
            return json.dumps({"rationale": "ok", "suggestions": []})
        return json.dumps({"issues": []})


def test_ai_recognizer_in_design(monkeypatch):
    monkeypatch.setattr(llm, "get_provider", lambda name=None: Recognizer())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    plan = agents.design_study("Is sugar diabetes linked to renal stones?", ["P"],
                               {"type": "nhanes", "cycles": ["P"], "source": "synthetic"}, provider="fake")
    assert plan["outcome"]["concept"] == "kidney_stones"
    assert plan["exposure"]["concept"] == "diabetes"
    assert plan["question_original"] == "Is sugar diabetes linked to renal stones?"
    assert {t["source"] for t in plan["recognized_terms"]} == {"ai"}
    assert any(d["agent"] == "Recognizer" for d in plan["agent_dialogue"])
    # the AI covariate reviewer may only comment on listed candidates: an invented variable is ignored
    out = covariates.suggest(plan, provider="fake")
    assert all("ai" not in s or s["variable"] != "not_a_variable" for s in out["suggestions"])
