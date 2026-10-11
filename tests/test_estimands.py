"""Age-adjusted prevalence, trends, means/percentiles, counts and pitfall warnings."""
from conftest import requires_r
from test_end_to_end import _approve

from q2e import agents, estimands
from q2e.compiler import compile_plan
from q2e.runner import get_run, load_results, start_run
from q2e.store import store


def _plan(q, cycles=("P",)):
    return agents.design_study(q, list(cycles) if cycles else None,
                               {"type": "nhanes", "cycles": list(cycles), "source": "cdc"} if cycles else None)


def test_nchs_standard_population():
    b = estimands.age_bands(20, None)
    assert [x["label"] for x in b] == ["20-39", "40-59", "60+"]
    assert [x["proportion"] for x in b] == [0.396579, 0.371795, 0.231626]          # NHANES tutorial table
    assert [x["proportion"] for x in estimands.age_bands(18, None)] == [0.420263, 0.357202, 0.222535]
    assert estimands.age_bands(60, None) is None and estimands.age_bands(2, 19) is None and estimands.age_bands(25, None) is None


def test_age_adjusted_prevalence_is_planned_and_primary_when_asked():
    p = _plan("What is the age-adjusted prevalence of obesity among US adults aged 20 and over?")
    assert p["age_adjust"]["enabled"] and p["age_adjust"]["primary"]
    assert "agecat_nchs20" in p["prevalence_by"]
    c = compile_plan(p)
    assert c["analysis"]["age_adjust"]["bands"][0]["population"] == 77670
    q = _plan("What is the prevalence of obesity among US adults aged 20 and over?")
    assert q["age_adjust"]["enabled"] and not q["age_adjust"]["primary"]       # reported alongside crude
    assert not _plan("Is obesity associated with hypertension?")["age_adjust"]["enabled"]


def test_trend_question_selects_two_year_cycles():
    p = _plan("How has obesity prevalence among US adults aged 20 and over changed from 1999 to 2018?", None)
    assert p["trend"]["enabled"] and p["dataset"]["cycles"] == list("ABCDEFGHIJ")
    assert p["estimand"]["kind"] == "trend" and p["age_adjust"]["primary"]


def test_descriptive_wording_gives_mean_or_median():
    p = _plan("What is the average total cholesterol in US adults aged 20 and over?", ["L"])
    assert p["study_type"] == "prevalence" and p["outcome"]["variable"] == "tc" and p["estimand"]["kind"] == "mean"
    assert _plan("What is the median ferritin in US women aged 20 to 49?")["estimand"]["median"]


def test_pitfalls_are_anticipated():
    p = _plan("How has the prevalence of hypertension among US adults aged 18 and over changed from 2011 to 2023?", None)
    titles = [i["title"] for i in p["review"]]
    assert any("Blood pressure method changed" in t for t in titles)
    assert any(i["severity"] == "blocker" for i in _plan("Prevalence of diabetes among adults aged 85 and over", ["L"])["review"])
    assert any("recalibration" in i["title"] for i in _plan("Is chronic kidney disease associated with anemia?", ["A", "D"])["review"])


@requires_r
def test_age_adjusted_and_mean_estimands_run():
    for q, check in (("What is the age-adjusted prevalence of obesity among US adults aged 20 and over?",
                      lambda r: r["primary_estimate"]["effect_label"] == "Age-adjusted prevalence"
                      and all(p.get("adj_est") is not None for p in r["prevalence"] if p["group_var"] in ("Overall", "sex"))
                      and all(p.get("adj_est") is None for p in r["prevalence"] if p["group_var"] == "agecat_nchs20")),
                     ("What is the average total cholesterol in US adults aged 20 and over?",
                      lambda r: r["primary_estimate"]["effect"] == "mean" and r["means"][0]["quantiles"] and r["means"][0].get("adj_est")),
                     ("How many Americans aged 20 and over have obesity?",
                      lambda r: r["primary_estimate"].get("count_millions") and r["primary_estimate"]["count_lcl"] < r["primary_estimate"]["count_millions"])):
        plan = agents.design_study(q, ["P"], {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
        proj = store.create("est", plan)
        _approve(proj)
        run = get_run(proj["id"], start_run(proj["id"], wait=True)["id"])
        assert run["status"] == "completed", run.get("error")
        assert check(load_results(proj["id"], run["id"])), q
