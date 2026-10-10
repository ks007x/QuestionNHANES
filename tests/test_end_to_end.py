import json
import zipfile
import io

from conftest import requires_r

from q2e import agents, planner, report
from q2e.bundle import build_bundle
from q2e.compiler import plan_hash
from q2e.runner import RunError, get_run, load_results, start_run
from q2e.store import store


def _approve(proj, by="Test Investigator"):
    for i in list(proj["plan"]["review"]):
        if (i.get("fix") or {}).get("op") == "acknowledge":
            proj["plan"] = planner.apply_fix(proj["plan"], {**i["fix"], "by": by})
    proj["plan"] = agents.refresh_plan(proj["plan"])
    proj["plan"]["approvals"].append({"by": by, "plan_hash": plan_hash(proj["plan"])})
    store.save(proj)


def test_run_requires_approval():
    plan = agents.design_study("Prevalence of anemia in US adults", ["P"], {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
    proj = store.create("q", plan)
    try:
        start_run(proj["id"])
        assert False, "should require approval"
    except RunError:
        pass


@requires_r
def test_fid_end_to_end_synthetic():
    plan = agents.design_study("Do a research study on the prevalence of functional iron deficiency in US adults.", ["P"],
                               {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
    proj = store.create("fid", plan)
    _approve(proj)
    run = start_run(proj["id"], wait=True)
    run = get_run(proj["id"], run["id"])
    assert run["status"] == "completed", run.get("error")
    res = load_results(proj["id"], run["id"])
    pe = res["primary_estimate"]
    assert pe["effect"] == "prevalence" and 0 < pe["lcl"] < pe["est"] < pe["ucl"] < 1
    assert res["meta"]["synthetic"] is True
    ids = {c["id"]: c["status"] for c in res["checks"]}
    assert ids["synthetic_data"] == "warn" and ids["weight_choice"] == "pass" and ids["cycle_overlap"] == "pass"
    assert res["design"]["weight_variable"] == "WTMECPRP"
    assert res["benchmarks"]
    proj = store.get(proj["id"])
    assert store.verify_chain(proj)["valid"]
    html = report.build_html(proj, run, res)
    assert "Key Points" in html and "SYNTHETIC" in html and "Korn-Graubard" in html
    z = zipfile.ZipFile(io.BytesIO(build_bundle(proj, run, html, None, store)))
    names = set(z.namelist())
    assert {"reproduce.R", "compiled_plan.json", "provenance.json", "results/results.json", "engine/run_pipeline.R"} <= names


@requires_r
def test_association_end_to_end_synthetic():
    plan = agents.design_study("Is higher liver stiffness associated with thrombocytopenia in US adults?", ["P"],
                               {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
    for s in plan["sensitivity"]:
        if s["type"] == "mi":
            s["enabled"] = False   # keep CI fast
    proj = store.create("lsm", plan)
    _approve(proj)
    run = start_run(proj["id"], wait=True)
    res = load_results(proj["id"], run["id"])
    pe = res["primary_estimate"]
    assert pe["effect"] == "PR" and pe["est"] > 1 and pe["lcl"] > 1
    assert res["evalue"]["point"] > 1
    assert len(res["models"]) == 3
    assert all(m["converged"] for m in res["models"])


def test_tampered_ledger_detected():
    plan = agents.design_study("Prevalence of anemia in US adults", ["P"], {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
    proj = store.create("q", plan)
    assert store.verify_chain(proj)["valid"]
    proj["events"][0]["actor"] = "someone else"
    assert not store.verify_chain(proj)["valid"]
