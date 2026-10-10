"""Multi-arm comparisons with explicit control groups."""
import pytest

from q2e import compiler, planner
from q2e.knowledge import get_knowledge
from conftest import requires_r

k = get_knowledge()
needs_catalog = pytest.mark.skipif(k.catalog_size < 10000, reason="full CDC catalog not present")


@pytest.mark.parametrize("q,arms,outcome,mode", [
    ("Diabetes vs hypertension vs healthy controls for chronic kidney disease", ["diabetes", "hypertension"], "ckd", "healthy"),
    ("Compare anemia in diabetes versus CKD versus controls", ["diabetes", "ckd"], "anemia", "seronegative"),
])
def test_detects_arms_outcome_and_control(q, arms, outcome, mode):
    p = planner.parse_question(q)
    assert p["arms"]["arms"] == arms and p["outcome_concept"] == outcome and p["arms"]["control_mode"] == mode


def test_plain_association_is_not_multi_arm():
    assert planner.parse_question("Is waist circumference associated with HbA1c?")["arms"] is None


def test_controls_never_screened_on_outcome_and_levels_ordered():
    p = planner.draft("Diabetes vs hypertension vs healthy controls for chronic kidney disease")
    a = p["arms"]
    assert a["levels"][0] == "Healthy controls" and "Both positive" in a["levels"]
    assert "ckd" not in [c["variable"] for c in a["control_criteria"]]
    assert "diabetes" not in [c["variable"] for c in a["control_criteria"]]       # arms are not repeated as criteria
    assert any(s.get("exposure") == "arms_seroneg" for s in p["sensitivity"])      # healthy-control bias check
    assert next(c for c in p["design_audit"]["checks"] if c["id"] == "comparator")["status"] == "caution"
    c = compiler.compile_plan(p)
    assert next(d for d in c["derived"] if d["name"] == "arms")["levels"][0] == "Healthy controls"


def test_set_arms_edit_switches_control_definition():
    p = planner.draft("Diabetes vs hypertension vs healthy controls for chronic kidney disease")
    p2 = planner.apply_fix(p, {"op": "set_arms", "control_mode": "seronegative", "both": "exclude"})
    assert p2["arms"]["control_mode"] == "seronegative" and "Both positive" not in p2["arms"]["levels"]


@needs_catalog
def test_parasite_arms_use_surplus_cycle():
    p = planner.draft("Toxoplasma vs Toxocara vs healthy control for eosinophilia")
    assert p["dataset"]["cycles"] == ["G"] and p["outcome"]["variable"] == "eosinophilia_05"
    assert p["arms"]["levels"] == ["Healthy controls", "Toxoplasma gondii only", "Toxocara only", "Both positive"]
    assert compiler.compile_plan(p)["subsample_weights"]["G"]["weight"] == "WTSSTT2Y"


@requires_r
def test_arm_contrasts_run(tmp_path):
    from q2e.__main__ import main
    assert main(["study", "Diabetes vs hypertension vs healthy controls for chronic kidney disease", "--out", str(tmp_path)]) == 0
    md = (tmp_path / "manuscript.md").read_text()
    assert "## Comparison groups" in md and "Diabetes only | Hypertension only" in md
