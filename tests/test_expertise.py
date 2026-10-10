"""Interviewer agent: expertise is inferred from wording, follow-ups adapt to it."""
from fastapi.testclient import TestClient

from q2e import expertise

NOVICE_Q = "is being fat bad for your blood sugar?"
EXPERT_Q = ("Among US adults aged 20-79 in NHANES 2017-March 2020, is waist circumference associated with HbA1c, "
            "adjusting for BMI, using survey-weighted linear regression?")


def test_levels_detected_from_wording():
    assert expertise.clarify(NOVICE_Q)["expertise"]["level"] == "novice"
    assert expertise.clarify(EXPERT_Q)["expertise"]["level"] == "expert"
    mid = expertise.clarify("Is higher liver stiffness associated with thrombocytopenia in US adults?")
    assert mid["expertise"]["level"] == "intermediate"


def test_precise_question_gets_fewer_follow_ups():
    novice, expert = expertise.clarify(NOVICE_Q), expertise.clarify(EXPERT_Q)
    assert len(expert["questions"]) < len(novice["questions"])
    assert all(q["why"] for q in novice["questions"])          # beginners are told why we ask
    assert not any(q["why"] for q in expert["questions"])


def test_method_words_are_not_asked_about():
    terms = expertise.unclear_terms({"unmapped_terms": ["survey-weighted linear regression", "fat bad", "ratios"]})
    assert terms == ["fat"]


def test_wording_changes_with_level():
    q = "anemia"
    texts = {lvl: expertise.clarify(q, level=lvl)["questions"][0]["text"] for lvl in expertise.LEVELS}
    assert len(set(texts.values())) == 3


def test_answers_refine_question_and_fixes():
    q = "In NHANES 2017-March 2020 adults, is hypertension associated with diabetes?"
    r = expertise.apply_answers(q, {"direction": {"option": "swap"}, "estimand": {"option": "or"}}, level="expert")
    ops = [f["op"] for f in r["fixes"]]
    assert "swap_roles" in ops and "set" in ops
    r = expertise.apply_answers("anemia", {"aim": {"option": "prev"}, "population": {"option": "older"}}, level="novice")
    assert "prevalence" in r["question"] and "older adults" in r["question"]


def test_free_text_only_used_with_matching_option():
    r = expertise.apply_answers("anemia", {"aim": {"option": "prev", "text": "smoking"}}, level="novice")
    assert "smoking" not in r["question"]
    r = expertise.apply_answers("anemia", {"aim": {"option": "assoc", "text": "smoking"}}, level="novice")
    assert "associated with smoking" in r["question"]


def test_unknown_options_are_ignored():
    r = expertise.apply_answers("anemia", {"aim": {"option": "rm -rf"}, "made_up": {"option": "x"}}, level="novice")
    assert r["fixes"] == [] and r["record"] == []


def test_api_clarify_and_create_with_answers():
    from q2e.server import app
    c = TestClient(app)
    out = c.post("/api/clarify", json={"question": "anemia in people"}).json()
    assert out["questions"] and out["level_used"] in expertise.LEVELS
    pj = c.post("/api/projects", json={"question": "Is hypertension associated with diabetes in US adults?",
                                       "source": "synthetic", "answers": {"direction": {"option": "swap"}}}).json()
    plan = pj["plan"]
    assert plan["clarification"]["record"]
    assert plan["exposure"]["concept"] == "diabetes" and plan["outcome"]["concept"] == "hypertension"
    assert plan["agent_dialogue"][0]["agent"] == "Interviewer"
    assert any(e["action"] == "clarification_answered" for e in pj["events"]) and pj["chain"]["valid"]
