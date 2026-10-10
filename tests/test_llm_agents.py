"""LLM agents with a fake provider: outputs are validated, merged under the rules, and audited."""
import json

from q2e import agents, llm


class FakeProvider(llm.BaseProvider):
    name = "fake"
    model = "fake-1"

    def available(self):
        return True, ""

    def complete(self, system, user, max_tokens=2000):
        if "RESEARCH IDEA" in user:
            return "```json\n" + json.dumps({
                "study_type": "association", "outcome_concept": "glycemic_control", "exposure_concept": "abdominal_obesity",
                "populations": ["adults"], "preferred_definitions": [], "adjust_bmi": True,
                "refined_question": "Among US adults, is waist circumference associated with HbA1c independent of BMI?",
                "hypothesis": "Abdominal obesity causes poor glycemic control.",   # causal -> must be rejected
                "clarifying_questions": ["Include people with diagnosed diabetes?"],
                "unmapped": [{"phrase": "visceral fat index", "role": "exposure", "label": "Waist-hip proxy", "type": "continuous",
                              "proposed_expression": "waist / height_cm"},
                             {"phrase": "bad", "role": "covariate", "label": "bad", "proposed_expression": "system('rm -rf /')"}]}) + "\n```"
        if "Draft statistical analysis plan" in user:
            return json.dumps({"rationale": "Survey-weighted linear regression.", "suggestions": ["Consider WHtR."]})
        return json.dumps({"issues": [{"severity": "major", "title": "Residual confounding by diet", "detail": "HEI not included."}]})


def test_llm_merge(monkeypatch):
    monkeypatch.setattr(llm, "get_provider", lambda name=None: FakeProvider())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    plan = agents.design_study("adults with greater abdominal obesity may have worse blood sugar control even at similar weight",
                               ["P"], {"type": "nhanes", "cycles": ["P"], "source": "synthetic"}, provider="fake")
    assert plan["refined_question_llm"].startswith("Among US adults")
    assert "hypothesis_llm" not in plan                      # causal language rejected
    names = [c["name"] for c in plan["custom_variables"]]
    assert len(names) == 1 and plan["custom_variables"][0]["source"] == "ai"   # unsafe expression rejected
    assert any(i["agent"] == "Reviewer (LLM)" for i in plan["review"])
    assert any(i["severity"] == "blocker" and i["id"].startswith("custom_") for i in plan["review"])   # needs human approval
    assert plan["rationale"]["statistician_llm"]
    assert all(c["payload_sha256"] for c in plan["llm"]["calls"]) and len(plan["llm"]["calls"]) == 3
