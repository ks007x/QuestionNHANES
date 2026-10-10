"""Where next? journal match, conference windows and funding leads (offline paths)."""
import datetime as dt

from q2e import planner, venues


def _plan(q):
    return planner.draft(q)


def test_journal_scores_offline_and_domain_fit():
    w = venues.where_next(_plan("What is the prevalence of functional iron deficiency?"), live=False, today=dt.date(2026, 10, 10))
    names = [j["journal"] for j in w["journals"]]
    assert "Blood Advances" in names and "Hepatology" not in names
    assert all(0 <= j["score"] <= 100 for j in w["journals"])


def test_precedent_raises_score():
    p = _plan("Is insomnia associated with depression in adults?")
    base = {j["journal"]: j["score"] for j in venues.journal_matches(p, None)}
    prec = {"counts": {venues._norm_journal("Journal of Affective Disorders"): 6, venues._norm_journal("Sleep Health"): 1},
            "names": {}}
    live = {j["journal"]: j for j in venues.journal_matches(p, prec)}
    assert live["Journal of Affective Disorders"]["score"] > live["Sleep Health"]["score"]
    assert live["Journal of Affective Disorders"]["similar_papers"] == 6
    assert base  # offline path works too


def test_conference_windows_roll_to_next_year():
    w = venues.conference_windows(_plan("What is the prevalence of functional iron deficiency?"), today=dt.date(2026, 10, 10))
    ash = next(c for c in w if c["conference"] == "ASH Annual Meeting")
    assert ash["deadline_estimate"] == "August 2027" and ash["meeting"] == "December 2027"
    assert all(c["days_until_estimate"] >= 0 for c in w)
    assert [c["days_until_estimate"] for c in w] == sorted(c["days_until_estimate"] for c in w)


def test_sleep_keywords_and_funders():
    p = _plan("Is insomnia associated with depression in adults?")
    w = venues.where_next(p, live=False, today=dt.date(2026, 10, 10))
    assert any(c["conference"] == "SLEEP Annual Meeting" for c in w["conferences"])
    assert "NIMH" in [i["ic"] for i in w["funding"]["institutes"]]
    md = venues.to_markdown(w)
    assert "Journal match" in md and "Specific Aims seed" in md


def test_aims_seed_uses_result():
    p = _plan("I have noticed that adults with greater abdominal obesity may have worse blood sugar control even at similar weight.")
    txt = venues.aims_seed(p, {"primary_estimate": {"est": 0.15, "lcl": 0.10, "ucl": 0.21, "n": 6610, "effect": "beta", "effect_label": "Beta"}})
    assert "6,610" in txt and "0.15" in txt
