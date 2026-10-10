"""Novelty score (PubMed mocked) and design audit rules."""
from q2e import novelty, planner


def test_novelty_scoring(monkeypatch):
    plan = planner.draft("I have noticed that adults with greater abdominal obesity may have worse blood sugar control even at similar weight.")
    counts = {"exact": 13}
    monkeypatch.setattr(novelty, "_count", lambda term, mindate=None: 13 if "NHANES" in term else 900)
    monkeypatch.setattr(novelty.literature, "pubmed_search", lambda *a, **k: [{"title": "t", "journal": "j", "url": "u", "pubdate": "2025"}])
    nv = novelty.novelty(plan)
    assert nv["exact"] == counts["exact"] and nv["label"] == "Low" and nv["suggestions"]
    novelty._CACHE.clear()                                  # results are cached for 24 h per query set
    monkeypatch.setattr(novelty, "_count", lambda term, mindate=None: 0)
    assert novelty.novelty(plan)["label"] == "High"


def test_novelty_offline():
    plan = planner.draft("What is the prevalence of functional iron deficiency?")
    nv = novelty.novelty(plan, live=False)
    assert nv["score"] is None and nv["label"] == "Not checked"


def _audit(q):
    return {c["id"]: c for c in planner.draft(q)["design_audit"]["checks"]}


def test_treatment_comparator_fails():
    a = _audit("Is antihypertensive medication use associated with chronic kidney disease?")
    assert a["comparator"]["status"] == "fail"


def test_reverse_causation_fix_and_review_item():
    p = planner.draft("Is physical activity associated with diabetes?")
    t = next(c for c in p["design_audit"]["checks"] if c["id"] == "temporality")
    assert t["status"] == "caution" and t["fix"]["op"] == "add_sensitivity"
    issue = next(i for i in p["review"] if i["id"] == "audit_temporality")
    p2 = planner.apply_fix(p, issue["fix"])
    from q2e import agents
    p2 = agents.refresh_plan(p2)
    assert next(c for c in p2["design_audit"]["checks"] if c["id"] == "temporality")["status"] == "pass"


def test_validated_instrument_and_objective_outcomes_pass():
    assert _audit("Is insomnia associated with depression in adults?")["outcome_ascertainment"]["status"] == "pass"
    assert _audit("Is waist circumference associated with HbA1c?")["outcome_ascertainment"]["status"] == "pass"


def test_direct_precedent_penalty(monkeypatch):
    plan = planner.draft("What is the prevalence of functional iron deficiency?")
    monkeypatch.setattr(novelty, "_count", lambda term, mindate=None: 2)
    monkeypatch.setattr(novelty.literature, "pubmed_search", lambda *a, **k: [
        {"title": "Absolute and Functional Iron Deficiency in the US, 2017-2020.", "journal": "JAMA network open", "url": "u", "pubdate": "2024"},
        {"title": "Microalbuminuria and Functional Iron Deficiency are Risk Factors for Hearing Loss", "journal": "Laryngoscope", "url": "u", "pubdate": "2024"}])
    nv = novelty.novelty(plan)
    assert len(nv["direct_precedents"]) == 1 and nv["penalty"] == 25
    assert nv["label"] in ("Moderate", "Low") and nv["suggestions"][0].startswith("Direct precedent")
