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


class InterviewerProvider(FakeProvider):
    calls = 0

    def complete(self, system, user, max_tokens=2000):
        assert "QUESTIONS Q2E IS ALREADY ASKING" in user
        InterviewerProvider.calls += 1
        return json.dumps({"questions": [
            {"text": "Which group of people should be studied?", "why": "Hypertension differs a lot by group.",
             "options": [{"group": "women"}, {"group": "diabetes"}, {"group": "martians"},       # not in the catalog
                         {"age_from": 40, "age_to": 59}, {"outcome": "made_up_topic"}]},
            {"text": "Should results be split by a subgroup?", "why": "", "options": [{"subgroup": "nonsense"}, {"group": "aliens"}]},
            {"text": "Does salt cause hypertension?", "why": "", "options": [{"group": "men"}, {"group": "women"}]},  # causal
        ]})


def test_ai_interviewer_only_offers_choices_nhanes_has(monkeypatch):
    from q2e import ai_interview, expertise
    monkeypatch.setattr(llm, "get_provider", lambda name=None: InterviewerProvider())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    ai_interview._CACHE.clear()
    idea = "How common is hypertension among US adults?"
    c = expertise.clarify(idea, provider="fake")
    assert c["ai"]["enabled"]
    ai = [q for q in c["questions"] if q.get("source") == "ai"]
    assert len(ai) == 1                          # no real choices / causal wording -> question dropped
    labels = [o["label"] for o in ai[0]["options"]]
    assert labels == ["Women", "People with diabetes", "Age 40 to 59"]     # made-up groups and topics removed
    # answering uses the same (cached) questions, and the choice reaches the study
    r = expertise.apply_answers(idea, {ai[0]["id"]: {"option": ai[0]["options"][2]["id"]}}, provider="fake")
    assert "Study people aged 40 to 59." in r["question"] and r["record"][-1]["source"] == "ai"
    assert InterviewerProvider.calls == 1


def test_rule_questions_come_first_and_ai_questions_separately(monkeypatch):
    from q2e import ai_interview, expertise
    monkeypatch.setattr(llm, "get_provider", lambda name=None: InterviewerProvider())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    ai_interview._CACHE.clear()
    idea = "How common is hypertension among US adults?"
    fast = expertise.clarify(idea, provider="fake", use_ai=False)
    assert not any(q.get("source") == "ai" for q in fast["questions"]) and fast["ai"]["enabled"]
    extra = expertise.ai_questions(idea, provider="fake")
    assert [q["source"] for q in extra["questions"]] == ["ai"]
    # the full list (used when answers are applied) is the rule questions followed by the same AI questions
    assert expertise.clarify(idea, provider="fake")["questions"] == fast["questions"] + extra["questions"]


def test_ai_interviewer_failure_falls_back_to_rules(monkeypatch):
    from q2e import ai_interview, expertise

    class Down(FakeProvider):
        def complete(self, system, user, max_tokens=2000):
            raise RuntimeError("expired token")
    monkeypatch.setattr(llm, "get_provider", lambda name=None: Down())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    ai_interview._CACHE.clear()
    c = expertise.clarify("How common is hypertension in seniors?", provider="fake")
    assert "ages" in [q["id"] for q in c["questions"]]          # rule-based questions still asked
    assert not any(q.get("source") == "ai" for q in c["questions"]) and "unavailable" in c["ai"]["note"]
