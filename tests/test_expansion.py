"""Expanded ontology, dictionary/catalog fallback, CDC catalog parsing, answerability and the blinded probe."""
import shutil
from pathlib import Path

import pytest
from conftest import requires_r

from q2e import answerability, planner
from q2e.knowledge import Knowledge, get_knowledge

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("q,outcome,exposure", [
    ("Is sodium intake associated with hypertension in US adults?", "hypertension", "sodium_intake"),
    ("Is blood lead associated with chronic kidney disease among adults?", "ckd", "lead_exposure"),
    ("Does obesity lead to diabetes?", "diabetes", "obesity"),
    ("Is neutrophil-to-lymphocyte ratio associated with depressive symptoms?", "depression", "nlr"),
])
def test_expanded_concepts_and_roles(q, outcome, exposure):
    p = planner.parse_question(q)
    assert p["outcome_concept"] == outcome and p["exposure_concept"] == exposure
    assert not p["dictionary_matches"]          # 'lead to' must not match blood lead


def test_ontology_size():
    k = get_knowledge()
    assert len(k.concepts) >= 85 and len(k.tables) > 300


def test_not_in_nhanes_and_components():
    p = planner.parse_question("Is hearing loss associated with dementia in older adults?")
    assert [n["phrase"] for n in p["not_in_nhanes"]] == ["dementia"]
    assert p["component_matches"][0]["tables"][0] == "AUX"
    a = answerability.assess_question("Is hearing loss associated with dementia in older adults?")
    assert a["status"] == "fail"


def test_cycle_availability_with_alternatives():
    k = get_knowledge()
    assert planner.available_cycles("sbp", k) >= {"I", "J", "P", "L"}       # coalesce(oscillometric, auscultatory)
    assert planner.available_cycles("lsm", k) >= {"J", "P"}               # (CDC catalog adds 2021-2023)
    a = answerability.assess_question("Is vitamin D deficiency associated with depression?", ["P"])
    assert any(c["dimension"] == "Co-measurement" and c["status"] == "fail" for c in a["checks"])
    a = answerability.assess_question("Is vitamin D deficiency associated with depression?", ["J"])
    assert not any(c["dimension"] == "Co-measurement" and c["status"] == "fail" for c in a["checks"])


def test_answerable_question():
    a = answerability.assess_question("What is the prevalence of neutropenia by race in US adults?")
    assert a["status"] == "ok"


def test_dictionary_fallback_with_catalog(tmp_path):
    kd = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", kd)
    (kd / "nhanes" / "catalog.csv").write_text(
        "variable,file,label,component,cycles,weight_level,type_guess\n"
        "HUQ071,HUQ,Overnight hospital patient in last year,Questionnaire,J;P,interview,yesno\n"
        "OHQ845,OHQ,Rate the health of your teeth and gums,Questionnaire,J;P,interview,categorical\n")
    k = Knowledge(kd)
    assert k.catalog_size == 2 and not k.dictionary["HUQ071"]["curated"]
    p = planner.parse_question("Is an overnight hospital stay associated with depression in adults?", k)
    assert p["dictionary_matches"] and p["dictionary_matches"][0]["variable"] == "HUQ071"
    plan = planner.build_plan("q", p, ["P"], None, k)
    roles = {plan["outcome"]["variable"], (plan.get("exposure") or {}).get("variable")}
    assert "nh_huq071" in roles
    cv = next(c for c in plan["custom_variables"] if c["name"] == "nh_huq071")
    assert cv["expr"] == "HUQ071 == 1" and cv["source"] == "dictionary"
    assert any(i["id"] == "custom_nh_huq071" for i in planner.review_plan(plan, k))


def test_cdc_variable_list_parser():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bnc", ROOT / "scripts" / "build_nhanes_catalog.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    html = """<table id="GridView1"><tr><th>Variable Name</th><th>Variable Description</th><th>Data File Name</th>
    <th>Data File Description</th><th>Begin Year</th><th>EndYear</th><th>Component</th><th>Use Constraints</th></tr>
    <tr><td>LBXFER</td><td>Ferritin (ng/mL)</td><td>P_FERTIN</td><td>Ferritin</td><td>2017</td><td>2020</td><td>Laboratory</td><td>None</td></tr>
    <tr><td>LBXFER</td><td>Ferritin (ng/mL)</td><td>FERTIN_J</td><td>Ferritin</td><td>2017</td><td>2018</td><td>Laboratory</td><td>None</td></tr>
    <tr><td>MCQ160B</td><td>Ever told had congestive heart failure</td><td>P_MCQ</td><td>Medical Conditions</td><td>2017</td><td>2020</td><td>Questionnaire</td><td>None</td></tr>
    <tr><td>LBXGLU</td><td>Fasting Glucose (mg/dL)</td><td>P_GLU</td><td>Plasma Fasting Glucose</td><td>2017</td><td>2020</td><td>Laboratory</td><td>None</td></tr></table>"""
    rows = m.build(m.parse_variable_list(html))
    by = {r["variable"]: r for r in rows}
    assert by["LBXFER"]["cycles"] == "J;P" and by["LBXFER"]["file"] == "FERTIN" and by["LBXFER"]["weight_level"] == "mec"
    assert by["MCQ160B"]["type_guess"] == "yesno" and by["LBXGLU"]["weight_level"] == "fasting"


@requires_r
def test_blinded_probe_and_precision():
    from q2e import agents
    from q2e.runner import run_probe
    from q2e.store import store
    plan = agents.design_study("Is sodium intake associated with hypertension in US adults?", ["P"],
                               {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
    proj = store.create("na", plan)
    pr = run_probe(proj["id"])
    assert pr["blinded"] and pr["weight_variable"] == "WTDRD1PP"
    lo, hi = pr["outcome"]["rate_band"]
    assert abs((hi - lo) - 0.05) < 1e-9                    # only a 5-point band is revealed
    assert "est" not in str(pr.get("outcome"))
    proj = store.get(proj["id"])
    proj["plan"] = agents.refresh_plan(proj["plan"])
    av = proj["plan"]["answerability"]
    assert av["probed"] and av["metrics"]["mde_pr_per_unit"] < 1.5
    assert any(e["action"] == "feasibility_probe" for e in proj["events"])


def test_rules_accept_natural_comparisons():
    from q2e.expressions import normalize, validate
    assert normalize("age => 60") == "age >= 60"
    assert normalize("age ≤ 80 & sex = 2") == "age <= 80 & sex == 2"
    assert normalize("age =< 18 || age >= 65") == "age <= 18 | age >= 65"
    assert normalize("ifelse(x == 1, 1, 0)") == "ifelse(x == 1, 1, 0)"
    assert normalize("cases(a, .default = 0)") == "cases(a, .default = 0)"
    validate(normalize("age => 60"))


def test_glossary_explains_codes_from_cdc_files():
    from fastapi.testclient import TestClient
    from q2e.server import app
    c = TestClient(app)
    v = c.post("/api/expressions/validate", json={"expr": "age => 60"}).json()
    assert v["ok"] and v["expr"] == "age >= 60" and v["rewritten"]
    g = c.post("/api/glossary", json={"terms": ["BMXWT", "BMX", "P_BMX", "DMDEDUC2", "MEC", "CIs", "Hello", "XYZZY9"]}).json()
    assert "Weight" in g["BMXWT"]["meaning"] and "Body Measures" in g["BMXWT"]["meaning"]
    assert g["BMX"]["meaning"].endswith("Body Measures") and g["P_BMX"]["kind"] == "file"
    assert "Education" in g["DMDEDUC2"]["meaning"] and "Mobile Examination Center" in g["MEC"]["meaning"]
    assert "CIs" in g and "Hello" not in g and "XYZZY9" not in g


def test_follow_ups_come_from_the_idea_itself():
    from q2e import expertise, planner
    q = "I noticed that high cortisol levels may be due to a lack of inactivity. for pepole aged 18 and under"
    r = expertise.clarify(q)
    assert "inactivity" in r["question_used"] and "nativity" not in r["question_used"].replace("inactivity", "")
    asked = {x.get("term") for x in r["questions"]}
    assert not asked & {"due", "lack", "pepole"} and not any(x["id"] == "population" for x in r["questions"])
    ex = r["needs_rewrite"]["examples"]
    assert ex and all("18 and under" in e for e in ex) and any("sedentary" in e for e in ex)
    assert planner.parse_age("for people aged 18 and under") == (None, 18)
    assert planner.parse_age("in those under the age of 18") == (None, 17)
    assert planner.parse_age("in people over 40") == (40, None)
    assert planner.parse_age("a bmi of 30+ in adults") == (None, None)
    # the "who to study" choices depend on the study: education is only asked from age 20, PHQ-9 from 18
    pop = lambda idea: next(x for x in expertise.clarify(idea)["questions"] if x["id"] == "population")
    edu = pop("Is education associated with weight?")
    assert [o["label"] for o in edu["options"]][0] == "Adults (20+)" and not any("Children" in o["label"] for o in edu["options"])
    iron = pop("is low iron linked to being tired?")
    assert any(o["id"] == "women" for o in iron["options"]) and "nh_" not in iron["why"]
    for qq in expertise.clarify("does a lack of activity make kids fat?")["questions"]:
        labels = [o["label"].lower() for o in qq["options"]]
        assert len(labels) == len(set(labels))


def test_study_never_silently_drops_part_of_the_idea():
    from fastapi.testclient import TestClient
    from q2e.server import app
    c = TestClient(app)
    q = "does high cortisol relate to lack of physical activity?"
    qs = c.post("/api/clarify", json={"question": q}).json()["questions"]
    first = qs[0]
    assert first["id"] == "missing" and "cortisol" in first["text"] and not any(x["id"] == "aim" for x in qs)
    switches = [o for o in first["options"] if o.get("question")]
    assert switches and all("physical activity" in o["question"] for o in switches)
    assert not any("sedentary" in o["question"] for o in switches)
    only = c.post("/api/projects", json={"question": q, "source": "synthetic", "answers": {"missing": {"option": "only"}}}).json()["plan"]
    notes = " ".join(g["note"] for g in only["idea_gaps"])
    assert "cortisol" in notes and "only estimates how common" in notes
    sw = c.post("/api/projects", json={"question": q, "source": "synthetic", "answers": {"missing": {"option": "switch0"}}}).json()["plan"]
    assert sw["study_type"] == "association" and any("cortisol" in g["note"] for g in sw["idea_gaps"])
    assert switches[0]["question"] not in [a["question"] for g in sw["idea_gaps"] for a in g["alternatives"]]
    plain = c.post("/api/projects", json={"question": "Is short sleep associated with hypertension in US adults?", "source": "synthetic"}).json()
    assert plain["plan"]["idea_gaps"] == []


def test_vague_groups_are_asked_never_guessed():
    from fastapi.testclient import TestClient
    from q2e import expertise
    from q2e.server import app
    c = TestClient(app)
    for idea, word in [("Is obesity associated with hypertension in seniors?", "seniors"),
                       ("Is depression linked to smoking among older people?", "older people"),
                       ("is obesity linked to blood pressure in kids?", "kids")]:
        ages = next(x for x in expertise.clarify(idea)["questions"] if x["id"] == "ages")
        assert word in ages["text"] and len(ages["options"]) >= 2 and ages["free_text"]["template"]
    assert not any(x["id"] == "ages" for x in expertise.clarify("Is obesity associated with hypertension in adults aged 40 to 60?")["questions"])
    # built without confirming the ages -> flagged, blocks approval, and one chat message fixes it
    pj = c.post("/api/projects", json={"question": "Is obesity associated with hypertension in seniors?", "source": "synthetic"}).json()
    gap = next(g for g in pj["plan"]["idea_gaps"] if g["status"] == "assumed")
    assert "seniors" in gap["note"] and gap["alternatives"]
    assert any(i["id"].startswith("ages_") for i in pj["plan"]["review"])
    c.post(f"/api/projects/{pj['id']}/protocol-chat", json={"message": gap["alternatives"][0]["question"]})
    pj = c.get(f"/api/projects/{pj['id']}").json()
    assert "Age >=60 years" in [x["label"] for x in pj["plan"]["population"]]
    assert not pj["plan"]["idea_gaps"] and not any(i["id"].startswith("ages_") for i in pj["plan"]["review"])
    # answered up front -> nothing to flag
    pj = c.post("/api/projects", json={"question": "Is obesity associated with hypertension in seniors?", "source": "synthetic",
                                       "answers": {"ages": {"text": "70 and older"}}}).json()
    assert "Age >=70 years" in [x["label"] for x in pj["plan"]["population"]] and not pj["plan"]["idea_gaps"]


def test_missing_r_gives_a_clear_message(monkeypatch):
    from fastapi.testclient import TestClient
    from q2e import runner
    from q2e.server import app
    monkeypatch.setattr(runner, "find_rscript", lambda *_: None)
    c = TestClient(app)
    pj = c.post("/api/projects", json={"question": "Is sodium intake associated with hypertension in US adults?", "source": "synthetic"}).json()
    r = c.post(f"/api/projects/{pj['id']}/probe")
    assert r.status_code == 409 and "R is not installed" in r.json()["error"] and "cran.r-project.org" in r.json()["error"]
    assert c.get("/api/r-status").json()["ready"] is False
    assert len(c.get(f"/api/projects/{pj['id']}").json()["runs"]) == 0


def test_hard_stop_cdiff_after_allohct():
    from fastapi.testclient import TestClient
    from q2e.server import app
    q = "Study the incidence of C. difficile infection after allogeneic hematopoietic cell transplantation."
    a = answerability.assess_question(q)
    assert a.get("hard_stop") and a["verdict"].startswith("Not answerable")
    phrases = {n["phrase"] for n in a["parsed"]["not_in_nhanes"]}
    assert {"incidence", "c. difficile infection", "hematopoietic cell transplantation"} <= phrases
    r = TestClient(app).post("/api/projects", json={"question": q, "source": "synthetic"})
    assert r.status_code == 422 and r.json()["hard_stop"] is True          # no plan is drafted
    with pytest.raises(planner.HardStop):
        planner.draft(q)


def test_ckm_not_substituted_with_metabolic_syndrome():
    p = planner.parse_question("To estimate the prevalence of cardiovascular-kidney-metabolic syndrome stages among US adults.")
    assert p["outcome_concept"] is None and p["not_in_nhanes"]


def test_jama_style_objectives():
    p = planner.draft("To estimate the prevalence of iron deficiency and iron-deficiency anemia among US females aged 12 to 21 years.")
    assert any(c["expr"] == "age >= 12 & age <= 21" for c in p["population"]) and not any(c["expr"] == "age >= 18" for c in p["population"])
    assert "ida_ash2026" in p["prevalence_outcomes"] and "Females Aged 12-21" in p["title"]
    p = planner.draft("To estimate awareness of hypertension status, treatment recommendations, and antihypertensive medication use "
                      "among US adults with uncontrolled hypertension.")
    assert p["study_type"] == "prevalence" and p["prevalence_outcomes"][:3] == ["htn_aware", "bp_meds_advised", "bp_meds"]
    assert any("sbp >= 130" in c["expr"] for c in p["population"])


def test_generic_single_words_not_matched():
    k = get_knowledge()
    assert planner.dictionary_lookup("treatment", k) is None and planner.dictionary_lookup("cell", k) is None
