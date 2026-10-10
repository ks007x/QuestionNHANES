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


def test_questions_follow_doubts_not_level():
    # anything the idea already states is not asked again, at any level
    expert = [q["id"] for q in expertise.clarify(EXPERT_Q)["questions"]]
    assert "population" not in expert and "bmi" not in expert and "topic" not in expert
    # a beginner who does not say who to study is asked, in plain words
    novice = expertise.clarify(NOVICE_Q)
    assert any(q["id"] == "population" for q in novice["questions"])
    assert all(q["why"] for q in novice["questions"])          # everyone is told why we ask


def test_method_words_are_not_asked_about():
    terms = expertise.unclear_terms({"unmapped_terms": ["survey-weighted linear regression", "fat bad", "ratios", "learn", "stop"]})
    assert terms == ["fat"]


def test_every_question_and_choice_is_explained_at_every_level():
    for lvl in expertise.LEVELS:
        for q in expertise.clarify(NOVICE_Q, level=lvl)["questions"]:
            assert q["why"]
            assert all(o.get("hint") for o in q["options"])


def test_unknown_word_gets_suggestions_and_keeps_word_order():
    q = expertise.clarify(NOVICE_Q)["questions"][0]
    assert q["id"] == "term0" and any(o["id"] == "c_obesity" for o in q["options"])
    r = expertise.apply_answers(NOVICE_Q, {"term0": {"option": "c_obesity"}})
    from q2e import agents
    p = agents.design_study(r["question"])
    assert p["exposure"]["concept"] == "obesity" and p["outcome"]["concept"] == "glycemic_control"


def test_typo_suggests_the_right_topic():
    q = expertise.clarify("is anemai linked to smoking in adults?")["questions"][0]
    assert q["options"][0]["id"] == "c_anemia"


def test_personal_goal_is_reframed_with_factors():
    q = "I have iron deficiency and want to learn more about how I can stop it"
    c = expertise.clarify(q)
    assert c["notice"]                                   # not medical advice
    goal = next(x for x in c["questions"] if x["id"] == "goal")
    assert any(o["id"] == "dietary_iron" for o in goal["options"])
    r = expertise.apply_answers(q, {"goal": {"option": "dietary_iron"}})
    from q2e import agents
    p = agents.design_study(r["question"])
    assert p["outcome"]["concept"] == "iron_deficiency" and p["exposure"]["concept"] == "dietary_iron"


def test_wording_changes_with_level():
    q = "anemia"
    texts = {lvl: expertise.clarify(q, level=lvl)["questions"][0]["text"] for lvl in expertise.LEVELS}
    assert len(set(texts.values())) == 3


def test_answers_refine_question_and_fixes():
    q = "In NHANES 2017-March 2020 adults, is hypertension associated with diabetes?"
    r = expertise.apply_answers(q, {"direction": {"option": "swap"}, "estimand": {"option": "or"}}, level="expert")
    ops = [f["op"] for f in r["fixes"]]
    assert "swap_roles" in ops and "set" in ops
    r = expertise.apply_answers("anemia", {"aim": {"option": "prev"}, "population": {"option": "older"}}, level="intermediate")
    assert "prevalence" in r["question"] and "older adults" in r["question"]


def test_only_needed_questions_are_asked():
    # a beginner's misspelt topic is read (not asked again); NHANES has no stress/work measure, so proxies are offered honestly
    c = expertise.clarify("I have high cholestrol, how does it relate to the amount of work and stress I have everyday")
    assert "cholesterol" in c["question_used"] and c["level_used"] == "novice"
    assert [q["id"] for q in c["questions"]] == ["term0", "term1", "population"]
    assert all("did not measure" in q["text"] for q in c["questions"][:2])
    assert any(u["label"] == "Health topic" for u in c["understood"])
    # a precise expert question and a short business question need few or no follow-ups
    assert len(expertise.clarify("Among adults 20-59 in NHANES 2015-2018, is HbA1c >= 6.5% associated with ferritin "
                                 "< 30 ng/mL, survey-weighted, adjusted for age, sex, BMI, prevalence ratio")["questions"]) <= 1
    assert expertise.clarify("How common is chronic kidney disease in older adults?")["questions"] == []


def test_extra_topic_the_parser_dropped_is_asked_about():
    q = "My smoker friends drink a lot of coffee, is that bad for their kidneys?"
    focus = next(x for x in expertise.clarify(q)["questions"] if x["id"] == "focus")
    assert any(o["id"] == "o_ckd" for o in focus["options"])
    from q2e import agents
    r = expertise.apply_answers(q, {"focus": {"option": "o_ckd"}})
    p = expertise.apply_fixes(agents.design_study(r["question"]), r["fixes"])
    assert p["outcome"]["concept"] == "ckd"


def test_topic_nhanes_does_not_measure_sends_user_back_to_rewrite():
    c = expertise.clarify("I have high cortisol, how does it relate to the amount of work and stress I have everyday")
    r = c["needs_rewrite"]
    assert c["questions"] == [] and r["missing"] == ["cortisol"] and "did not measure" in r["what_happened"]
    from q2e import planner
    assert r["examples"] and all(planner.parse_question(e)["outcome_concept"] for e in r["examples"])   # every example works
    assert r["related"][0]["label"] and r["all_topics"]
    # a word with close matches still gets the normal follow-up question instead
    assert expertise.clarify("is being fat bad for you")["needs_rewrite"] is None


def test_uncertain_text_search_match_is_confirmed():
    c = expertise.clarify("is coffee bad for kidneys")
    chk = next(q for q in c["questions"] if q["id"] == "check_outcome")
    assert chk["options"][0]["id"] == "keep" and chk["blocking_option"] == "edit"
    assert any(o["id"] == "c_ckd" for o in chk["options"])
    from q2e import agents
    r = expertise.apply_answers("is coffee bad for kidneys", {"check_outcome": {"option": "c_ckd"}})
    assert expertise.apply_fixes(agents.design_study(r["question"]), r["fixes"])["outcome"]["concept"] == "ckd"


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
    assert plan["clarification"]["answers"] == {"direction": {"option": "swap"}}      # can be reopened later
    assert plan["clarification"]["original_question"].startswith("Is hypertension")
    assert plan["exposure"]["concept"] == "diabetes" and plan["outcome"]["concept"] == "hypertension"
    assert plan["agent_dialogue"][0]["agent"] == "Interviewer"
    assert any(e["action"] == "clarification_answered" for e in pj["events"]) and pj["chain"]["valid"]
