"""Sample size/power, covariate suggestions, PICO novelty, option novelty, methods summary/limitations and GRADE-informed certainty."""
import pytest
from fastapi.testclient import TestClient

from q2e import appraisal, covariates, novelty, planner, power

ARMS_Q = "Toxoplasma vs Toxocara vs healthy control for eosinophilia"


@pytest.fixture(scope="module")
def arms_plan():
    return planner.draft(ARMS_Q, ["G"])


# ------------------------------------------------------------------ power
def test_power_math_sane():
    za, zb = power._z(0.05, 0.80)
    mde = power.mde_ratio(0.031, 1883, 206, 1.8, za, zb)
    assert 2.0 < mde < 3.5                                  # small arm, rare outcome -> only large effects detectable
    assert power.power_at(0.10, 1.5, 5000, 5000, 1.8, za) > 0.95
    assert power.mde_ratio(0.10, 20000, 20000, 1.8, za, zb) < power.mde_ratio(0.10, 200, 200, 1.8, za, zb)


def test_power_from_probe_groups_with_bonferroni(arms_plan):
    ref = arms_plan["arms"]["reference"]
    probe = {"n_complete_case": 2400, "outcome": {"rate_band": [0.0, 0.05]},
             "exposure": {"type": "categorical", "levels": [{"level": ref, "n": 1883}, {"level": arms_plan["arms"]["levels"][1], "n": 206},
                                                             {"level": arms_plan["arms"]["levels"][2], "n": 300}]}}
    a = power.assess(arms_plan, probe)
    assert len(a["comparisons"]) == 2 and all(c["mde"] for c in a["comparisons"])
    assert any("Bonferroni" in s for s in a["assumptions"])
    assert a["verdict"].startswith(("Underpowered", "Powered for some", "Adequately"))
    assert "Alpha 0.05" in power.summary_text(a)


def test_set_power_op_validates(arms_plan):
    p = planner.apply_fix(arms_plan, {"op": "set_power", "value": {"alpha": 0.01, "power": 0.9, "multiplicity": "none"}})
    assert power.settings_of(p)["alpha"] == 0.01 and power.settings_of(p)["power"] == 0.9
    with pytest.raises(ValueError):
        planner.apply_fix(arms_plan, {"op": "set_power", "value": {"alpha": 0.9}})
    with pytest.raises(ValueError):
        planner.apply_fix(arms_plan, {"op": "set_power", "value": {"bogus": 1}})


def test_post_run_mde_from_design_se(arms_plan):
    res = {"primary_estimate": {"effect": "PR", "est": 1.2, "lcl": 0.8, "ucl": 1.8, "n": 2000, "label": "x"}}
    a = power.assess(arms_plan, None, res)
    assert a["post_run"] and a["post_run"][0]["mde"] > 1


# ------------------------------------------------------------------ covariates
def test_covariate_suggestions_roles(arms_plan):
    s = covariates.suggest(arms_plan)["suggestions"]
    names = {x["variable"]: x for x in s}
    assert names, "expected suggestions"
    for x in s:
        assert x["variable"] not in arms_plan["covariates"]
        if x["role"] != "confounder" and x["fix"]:
            assert x["fix"]["op"] == "add_sensitivity"          # mediators never go into the primary model
    conf = next((x for x in s if x["role"] == "confounder" and x["fix"]), None)
    if conf:
        p2 = planner.apply_fix(arms_plan, conf["fix"])
        assert conf["variable"] in p2["covariates"]


def test_covariates_prevalence_note():
    p = planner.draft("What is the prevalence of functional iron deficiency?")
    assert covariates.suggest(p)["suggestions"] == []


# ------------------------------------------------------------------ PICO novelty
def test_novelty_queries_cover_every_arm(arms_plan):
    q = novelty.queries(arms_plan)
    assert len(q["pairs"]) == 2
    assert "toxocar" in q["exact"].lower() and "toxoplasm" in q["exact"].lower() and "eosinophil" in q["exact"].lower()


def test_known_pair_lowers_novelty(arms_plan, monkeypatch):
    """Toxocara x eosinophilia is a known association - the score must fall even if the 3-way NHANES query is empty."""
    monkeypatch.setattr(novelty.literature, "pubmed_search", lambda *a, **k: [])
    monkeypatch.setattr(novelty, "_count", lambda term, mindate=None: 0)
    clean = novelty.novelty(arms_plan)
    novelty._CACHE.clear()

    def counts(term, mindate=None):
        tl = term.lower()
        if "toxocar" in tl and "toxoplasm" not in tl:
            return 12 if "nhanes" in tl else 150
        return 0
    monkeypatch.setattr(novelty, "_count", counts)
    known = novelty.novelty(arms_plan)
    assert known["score"] < clean["score"]
    assert "Toxocara" in known["summary"] or "toxocara" in known["summary"].lower()


def test_option_novelty_endpoint(monkeypatch):
    from q2e.server import app
    monkeypatch.setattr(novelty.literature, "pubmed_search", lambda *a, **k: [])
    monkeypatch.setattr(novelty, "_count", lambda term, mindate=None: 3)
    c = TestClient(app)
    q = "Is dietary fat associated with obesity?"
    cl = c.post("/api/clarify", json={"question": q}).json()
    if not cl.get("questions"):
        pytest.skip("no clarifying question for this wording")
    qid = cl["questions"][0]["id"]
    r = c.post("/api/clarify/novelty", json={"question": q, "qid": qid, "answers": {}, "level": cl.get("level_used")})
    assert r.status_code == 200
    opts = r.json()["options"]
    assert opts and any(v.get("score") is not None for v in opts.values())


# ------------------------------------------------------------------ appraisal / certainty
def _res(est, lcl, ucl, sens=(), synthetic=False, df=18):
    return {"primary_estimate": {"effect": "PR", "est": est, "lcl": lcl, "ucl": ucl, "n": 5000, "p": 0.01},
            "sensitivity": [{"label": f"s{i}", "type": "exclude", "effect": "PR", "est": e, "lcl": l, "ucl": u} for i, (e, l, u) in enumerate(sens)],
            "design": {"analytic_df": df, "weight_variable": "WTMEC2YR"}, "checks": [], "meta": {"synthetic": synthetic},
            "evalue": {"point": 1.5}}


def test_certainty_imprecise_null_downgrades(arms_plan):
    c = appraisal.certainty(arms_plan, _res(0.9, 0.5, 1.6), {"checks": []}, None)
    assert c["level"] == "Very low" and any(d["domain"] == "Imprecision" and d["change"] < 0 for d in c["domains"])
    assert "single" in c["framework"].lower()


def test_certainty_large_precise_effect_upgrades(arms_plan):
    c = appraisal.certainty(arms_plan, _res(3.0, 2.2, 4.1, sens=[(2.8, 2.0, 3.9), (3.2, 2.1, 4.8)]), {"checks": []}, None)
    assert c["level"] == "Moderate" and c["net_up"] == 1


def test_certainty_inconsistency(arms_plan):
    c = appraisal.certainty(arms_plan, _res(1.5, 1.2, 1.9, sens=[(0.6, 0.4, 0.8)]), {"checks": []}, None)
    assert next(d for d in c["domains"] if d["domain"] == "Inconsistency")["change"] == -1


def test_certainty_not_estimable_is_not_rated(arms_plan):
    c = appraisal.certainty(arms_plan, _res(1e8, 1e7, 1e9), {"checks": []}, None)
    assert c["assessed"] is False


def test_methods_and_limitations(arms_plan):
    ap = appraisal.appraise(arms_plan, _res(0.9, 0.5, 1.6, synthetic=True, df=6), arms_plan["design_audit"],
                            {"verdict": "Underpowered for the target effect", "settings": {"target_ratio": 1.5}})
    assert ap["methods"].startswith("Design: cross-sectional") and "NHANES" in ap["methods"]
    areas = {l["area"] for l in ap["limitations"]}
    assert {"Temporality", "Confounding", "Precision", "Data"} <= areas
    assert ap["limitations"][0]["impact"] == "major"
    assert "GRADE-informed" in appraisal.certainty_line(ap["certainty"])


def test_large_but_imprecise_effect_not_rated_up(arms_plan):
    c = appraisal.certainty(arms_plan, _res(2.0, 1.16, 3.47), {"checks": []},
                            {"verdict": "Underpowered for the target effect", "settings": {"target_ratio": 1.5}})
    assert c["net_up"] == 0 and c["level"] == "Very low"


def test_no_estimable_effect_is_not_rated(arms_plan):
    r = _res(1, 1, 1); r["primary_estimate"] = None
    c = appraisal.certainty(arms_plan, r, {"checks": []}, None)
    assert c["level"] == "Not rated" and c["assessed"] is False
