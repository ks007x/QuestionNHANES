"""Full CDC catalog (1999-2023): parasites, eosinophils, subsample weights, auto cycle choice, learned synonyms."""
import pytest
from fastapi.testclient import TestClient

from q2e import compiler, planner
from q2e.knowledge import get_knowledge

k = get_knowledge()
needs_catalog = pytest.mark.skipif(k.catalog_size < 10000, reason="full CDC catalog not present")


@needs_catalog
def test_catalog_spans_all_cycles_with_per_cycle_files():
    r = k.dictionary["LBDEONO"]
    assert {"A", "G", "L"} <= set(r["cycles"]) and r["stems"]["A"] == "LAB25"


@needs_catalog
def test_surplus_specimen_weights():
    assert k.subsample_weight("SSTCAR", "G") == ("WTSSTT2Y", "SSTOCA")
    assert k.subsample_weight("SSTCAR", "H") is None          # current release lacks 2013-2014 weights


@needs_catalog
@pytest.mark.parametrize("q,y,x,cycles", [
    ("What is the prevalence of parasitic infections in US adults?", "parasite_any_2011", None, ["G"]),
    ("Do a research study on parasite", "parasite_any_2011", None, ["G"]),
    ("Is Toxocara seropositivity associated with eosinophilia?", "eosinophilia_05", "toxocara_seropos", ["G"]),
    ("Are parasites associated with hypereosinophilia?", "hypereosinophilia_15", "parasite_any_2011", ["G"]),
    ("What is the prevalence of hypereosinophilia?", "hypereosinophilia_15", None, ["P"]),
])
def test_parasite_and_eosinophil_questions(q, y, x, cycles):
    p = planner.draft(q)
    assert p["outcome"]["variable"] == y and (p.get("exposure") or {}).get("variable") == x
    assert p["dataset"]["cycles"] == cycles
    assert not [r for r in p["review"] if r["severity"] == "blocker"]


@needs_catalog
def test_parasite_prevalence_compiles_with_surplus_weights():
    p = planner.draft("What is the prevalence of parasitic infections in US adults?")
    c = compiler.compile_plan(p)
    assert c["weight_level"] == "subsample" and c["subsample_weights"]["G"]["weight"] == "WTSSTT2Y"
    assert c["cycles_meta"]["G"]["weights"]["subsample"] == "WTSSTT2Y"
    assert {"toxocara_seropos", "toxoplasma_seropos"} <= set(p["prevalence_outcomes"])


@needs_catalog
@pytest.mark.parametrize("q,var", [
    ("What is the prevalence of hepatitis E antibody?", "LBDHEG"),
    ("Is herpes simplex 2 associated with depression?", "LBXHE2"),
    ("Is vitamin B12 deficiency associated with anemia?", "LBDB12SI"),
    ("Is dietary caffeine associated with sleep duration?", "DR1TCAFF"),
    ("Is urinary arsenic associated with diabetes?", "URXUAS"),
])
def test_catalog_lookup_precision(q, var):
    assert var in [m["variable"] for m in planner.parse_question(q)["dictionary_matches"]]


@needs_catalog
def test_incidental_label_words_do_not_match():
    assert not planner.parse_question("Tell me something interesting about the weather today")["dictionary_matches"]


def test_learned_synonym_round_trip(tmp_path, monkeypatch):
    from q2e import knowledge
    from q2e.config import settings
    from q2e.server import app
    monkeypatch.setattr(settings, "workspace", tmp_path)
    knowledge.get_knowledge.cache_clear()
    c = TestClient(app)
    assert c.post("/api/learn", json={"term": "sugar control", "target": "var:LBXGH", "by": "Dr Test"}).status_code == 200
    p = planner.parse_question("Is sugar control associated with sleep duration?", knowledge.get_knowledge())
    assert "dict:LBXGH" in [m["concept"] for m in p["matched_phrases"]]
    assert c.post("/api/learn", json={"term": "x y", "target": "var:NOPE", "by": "Dr Test"}).status_code == 422
    knowledge.get_knowledge.cache_clear()
