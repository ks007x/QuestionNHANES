"""Comparison results in words (each group's value, percentage points, ratio with CI) and the Bedrock rewrite guard."""
import json

import pytest

from q2e import agents, llm, report

PLAN = {"population": [{"label": "Age >=18 years", "enabled": True, "expr": "age >= 18"}], "study_type": "prevalence",
        "outcome": {"label": "Diagnosed diabetes", "concept_label": "Diagnosed diabetes"}, "refined_question": "q"}
PE = {"effect": "difference", "est": 0.012, "lcl": -0.012, "ucl": 0.035, "p": 0.31, "est_level": 0.077, "est_ref": 0.065,
      "ratio": 1.18, "ratio_lcl": 0.85, "ratio_ucl": 1.65, "binary": True, "level": "Male", "reference": "Female", "basis": "crude"}


def test_plain_language_states_each_group_not_the_difference():
    txt = report._plain_language(PLAN, PE, 6413, False)
    assert "About 8 in every 100 men and about 7 in every 100 women" in txt   # not "1 in every 100 adults"
    assert "could be due to chance" in txt


def test_formal_wording_uses_percentage_points_and_ratio_ci():
    f = report.comparison_words(PE, PLAN)["formal"]
    assert f.startswith("7.7% in men and 6.5% in women")
    assert "+1.2 percentage points [95% CI, -1.2 to +3.5]" in f and "prevalence ratio, 1.18 [95% CI, 0.85-1.65]" in f


def test_significant_difference_in_words():
    pe = {**PE, "est": 0.075, "lcl": 0.05, "ucl": 0.10, "p": 1e-5, "est_level": 0.538, "est_ref": 0.463, "ratio": 1.16}
    w = report.comparison_words(pe, PLAN)
    assert w["significant"] and "16% higher in men" in w["plain"] and "P < .001" in w["formal"]


def test_children_and_age_groups():
    kids = {**PLAN, "population": [{"label": "Children aged 2-17", "enabled": True, "expr": "age < 18"}]}
    assert report.group_words("Male", kids) == "boys"
    assert report.group_words("60+", PLAN) == "people aged 60+"


def _sections():
    return {"plain_language": report._plain_language(PLAN, PE, 6413, False),
            "key_points": {"findings": "the weighted prevalence was " + report.comparison_words(PE, PLAN)["formal"]}}


@pytest.mark.parametrize("reply,rejected", [
    ({"plain": "About 8 in every 100 men and 7 in every 100 women had diagnosed diabetes; this could be due to chance.",
      "key_point": "Prevalence was 7.7% in men and 6.5% in women (P = .31)."}, []),
    ({"plain": "Men had 40% more diabetes.", "key_point": "ok"}, ["plain: introduced numbers"]),
    ({"plain": "Diabetes was more common in women than in men.", "key_point": "ok"}, ["plain: stated the difference in the wrong direction"]),
    ({"plain": "Being male raises diabetes risk.", "key_point": "ok"}, ["plain: causal wording"]),
])
def test_ai_rewrite_is_checked(monkeypatch, reply, rejected):
    class F(llm.BaseProvider):
        name, model = "bedrock", "check-" + str(abs(hash(json.dumps(reply))))
        def available(self):
            return True, ""
        def complete(self, system, user, max_tokens=2000):
            return json.dumps(reply)
    monkeypatch.setattr(llm, "get_provider", lambda name=None: F())
    monkeypatch.setattr(llm.privacy, "provider_allowed", lambda p: (True, "ok"))
    out = agents.explain(PLAN, {"primary_estimate": PE}, _sections(), "bedrock")
    assert out["available"]
    assert [r for r in out["rejected"] if any(r.startswith(x) for x in rejected)] or not rejected
    if not rejected:
        assert out["rejected"] == [] and out["plain"] == reply["plain"]
    else:
        assert out["plain"] == _sections()["plain_language"]                  # the checked fallback


def test_explain_off_without_ai():
    assert agents.explain(PLAN, {"primary_estimate": PE}, _sections(), "offline")["available"] is False
