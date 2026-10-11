"""Model advisor (AI statistician) and the published-evidence check (PubMed mocked)."""
import pytest

from q2e import evidence, model_advisor, planner

Q = "I have noticed that adults with greater abdominal obesity may have worse blood sugar control even at similar weight."

ABSTRACTS = [
    {"pmid": "1", "title": "Waist circumference and glycated hemoglobin among US adults, NHANES 2011-2018", "journal": "JAMA Network Open",
     "journal_abbrev": "JAMA Netw Open", "year": "2023", "url": "u1",
     "abstract": "RESULTS: Among 9 812 adults from NHANES 2011-2018, each 10-cm greater waist circumference was associated with higher HbA1c "
                 "(β = 0.12; 95% CI, 0.08-0.16) in survey-weighted linear regression. Restricted cubic splines showed linearity."},
    {"pmid": "2", "title": "Central adiposity and glycemic control: a cross-sectional NHANES analysis", "journal": "Diabetes Care",
     "journal_abbrev": "Diabetes Care", "year": "2021", "url": "u2",
     "abstract": "Waist circumference was associated with HbA1c (β 0.30, 95% CI 0.25 to 0.35) using linear regression with multiple imputation."},
    {"pmid": "3", "title": "Abdominal obesity and poor glycemic control in NHANES", "journal": "Obesity (Silver Spring)",
     "journal_abbrev": "Obesity (Silver Spring)", "year": "2020", "url": "u3",
     "abstract": "Abdominal obesity was associated with poor glycemic control (OR, 1.62; 95% CI, 1.31-2.01) in logistic regression."},
]


@pytest.fixture
def mocked(monkeypatch):
    evidence._CACHE.clear()
    monkeypatch.setattr(evidence.literature, "pubmed_search", lambda term, retmax=8, **k: [{"pmid": a["pmid"]} for a in ABSTRACTS])
    monkeypatch.setattr(evidence, "fetch_abstracts", lambda ids: [a for a in ABSTRACTS if a["pmid"] in ids])
    yield
    evidence._CACHE.clear()


def test_query_targets_high_impact_journals():
    q = evidence.queries(planner.draft(Q))
    assert '"JAMA Netw Open"[jour]' in q["high_impact"] and '"Lancet"[jour]' in q["high_impact"] and '"Blood"[jour]' in q["high_impact"]
    assert '"J Hepatol"[jour]' in q["high_impact"] and '"Am J Gastroenterol"[jour]' in q["high_impact"] and "NHANES" in q["high_impact"]


def test_rule_extraction_formats():
    r = evidence.extract_rules("aOR = 2.10, 95% CI: 1.33, 3.31; HR 1.32 (1.10−1.58); prevalence 14.0% (95% CI, 12.3%-15.8%) among 10,234 adults")
    got = {(e["measure"], e["value"], e["lcl"], e["ucl"]) for e in r["estimates"]}
    assert ("OR", 2.1, 1.33, 3.31) in got and ("HR", 1.32, 1.1, 1.58) in got
    assert r["prevalence"][0]["value"] == 14.0 and r["n"] == 10234


def test_check_compares_direction_and_overlap(mocked):
    plan = planner.draft(Q)
    res = {"primary_estimate": {"effect": "Beta", "est": 0.15, "lcl": 0.10, "ucl": 0.21, "label": "waist"}}
    ev = evidence.check(plan, res, use_llm=False)
    v = {r["pmid"]: r["comparison"]["verdict"] for r in ev["papers"]}
    assert v["1"] == "Consistent" and v["2"] == "Same direction, different size" and v["3"] == "Different measure"
    assert ev["summary"]["comparable"] == 2 and ev["summary"]["same_direction"] == 2 and ev["summary"]["score"] == 100
    assert ev["landscape"]["counts"].get("linear") == 2 and "spline" in ev["landscape"]["counts"]
    md = evidence.to_markdown(ev)
    assert "Consistent" in md and "JAMA Network Open" in md


def test_llm_numbers_must_appear_in_abstract():
    class Fake:
        def complete_json(self, *a, **k):
            return {"estimates": [{"measure": "Beta", "value": 0.12, "lcl": 0.08, "ucl": 0.16},
                                  {"measure": "OR", "value": 3.9, "lcl": 2.0, "ucl": 7.7}]}   # second is invented
    out = evidence.extract_llm(Fake(), ABSTRACTS[0])
    assert len(out["estimates"]) == 1 and out["rejected"] == 1


def test_advisor_continuous_outcome_and_literature(mocked):
    plan = planner.draft(Q)
    land = evidence.check(plan, None, use_llm=False)["landscape"]
    a = model_advisor.advise(plan, None, None, land, use_llm=False)
    ids = [o["id"] for o in a["options"]]
    assert "linear" in ids and "loglinear" in ids and a["recommended"] == "linear"
    lin = next(o for o in a["options"] if o["id"] == "linear")
    assert lin["current"] and "similar NHANES papers" in lin["literature"]


def test_advisor_binary_common_outcome_prefers_pr_and_fix_applies():
    plan = planner.draft("Is hypertension associated with chronic kidney disease in US adults?")
    plan = planner.apply_fix(plan, {"op": "set", "path": "model.family", "value": "quasibinomial"})
    probe = {"outcome": {"rate_band": [0.15, 0.20]}}
    a = model_advisor.advise(plan, probe, None, None, use_llm=False)
    assert a["recommended"] == "pr"
    o = next(o for o in a["options"] if o["id"] == "or")
    assert any("Overstates" in c for c in o["cons"])
    pr = next(o for o in a["options"] if o["id"] == "pr")
    p2 = planner.apply_fix(plan, pr["fix"])
    assert p2["model"]["family"] == "quasipoisson"


def test_loglinear_batch_fix_compiles():
    from q2e.compiler import compile_plan
    plan = planner.draft("What is the association between hypertension and ferritin in US adults?")
    if plan["outcome"]["type"] != "continuous":
        pytest.skip("outcome parsed as binary")
    o = next(o for o in model_advisor.options(plan) if o["id"] == "loglinear")
    p2 = planner.apply_fix(plan, o["fix"])
    assert any(s["type"] == "alt_outcome" and s["outcome"].startswith("log_") for s in p2["sensitivity"])
    compile_plan(p2)


def test_tools_expose_ai_statistician():
    from q2e import tools
    assert {"suggest_models", "apply_model_option", "check_literature"} <= set(tools.BY_NAME)


def test_learned_evidence_is_remembered(mocked):
    plan = planner.draft(Q)
    evidence.check(plan, None, use_llm=False)
    mem = evidence.recall(plan)
    assert mem and mem["landscape"]["papers"] == 3


def test_tops_up_from_other_journals_when_few_high_impact(monkeypatch):
    evidence._CACHE.clear()
    calls = []

    def search(term, retmax=8, **k):
        calls.append(term)
        return [{"pmid": "1"}] if '[jour]' in term else [{"pmid": "2"}, {"pmid": "3"}]
    monkeypatch.setattr(evidence.literature, "pubmed_search", search)
    monkeypatch.setattr(evidence, "fetch_abstracts", lambda ids: [a for a in ABSTRACTS if a["pmid"] in ids])
    ev = evidence.check(planner.draft(Q), None, use_llm=False)
    assert len(calls) == 2 and "topped up" in ev["scope"] and len(ev["papers"]) >= 2
    evidence._CACHE.clear()


def test_bedrock_without_credentials_is_reported_not_ready(monkeypatch):
    from q2e.llm import LLMClient
    for k in ("AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "Q2E_BEDROCK_MODEL_ID"):
        monkeypatch.delenv(k, raising=False)
    st = LLMClient("bedrock").status()
    assert st["provider"] == "bedrock" and st["enabled"] is False and st["why"]
