"""Bring-your-own dataset: upload CSV + dictionary, auto-map, prune, compile (and run if R present)."""
import csv
import io
import random
import time

from conftest import requires_r
from fastapi.testclient import TestClient


def _csv(n=1500, seed=7):
    rnd = random.Random(seed)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["participant_id", "age_years", "sex_female", "serum_ferritin", "transferrin_saturation", "body_mass_index", "survey_weight", "strata", "psu"])
    for i in range(n):
        fem = rnd.random() < 0.5
        fer = round(rnd.lognormvariate(3.7 if fem else 4.8, 0.9), 1)
        w.writerow([i + 1, rnd.randint(18, 80), int(fem), fer, round(max(3, rnd.gauss(28, 8)), 1), round(rnd.gauss(28, 5), 1),
                    round(rnd.uniform(5000, 50000)), rnd.randint(1, 10), rnd.randint(1, 2)])
    d = io.StringIO()
    dw = csv.writer(d)
    dw.writerow(["variable", "description"])
    for v, lab in [("participant_id", "ID"), ("age_years", "Age in years"), ("sex_female", "Female sex (1=yes)"),
                   ("serum_ferritin", "Serum ferritin ng/mL"), ("transferrin_saturation", "Transferrin saturation percent"),
                   ("body_mass_index", "Body mass index"), ("survey_weight", "Sample weight"), ("strata", "Stratum"), ("psu", "PSU")]:
        dw.writerow([v, lab])
    return buf.getvalue().encode(), d.getvalue().encode()


def _client():
    from q2e.server import app
    return TestClient(app)


def test_upload_map_and_approve():
    c = _client()
    data, dct = _csv()
    ds = c.post("/api/datasets", data={"name": "test extract"}, files={"data": ("d.csv", data), "dictionary": ("dd.csv", dct)}).json()
    assert ds["design"] == {"id_var": "participant_id", "weight": "survey_weight", "strata": "strata", "psu": "psu"}
    p = c.post("/api/projects", json={"question": "Prevalence of functional iron deficiency in adults", "dataset_id": ds["id"]}).json()
    gm = p["plan"]["generic_mapping"]
    assert gm["ferritin"] == "serum_ferritin" and gm["tsat_reported"] == "transferrin_saturation" and gm["female"] == "sex_female == 1"
    assert "race_eth" not in p["plan"]["covariates"]
    assert not [i for i in p["plan"]["review"] if i["severity"] == "blocker"]
    for _ in range(3):
        for i in p["plan"]["review"]:
            if (i.get("fix") or {}).get("op") == "acknowledge":
                p = c.post(f"/api/projects/{p['id']}/edit", json={"fix": i["fix"]}).json()
                break
    r = c.post(f"/api/projects/{p['id']}/approve", json={"by": "Tester"})
    assert r.status_code == 200, r.json()


@requires_r
def test_generic_run():
    c = _client()
    data, dct = _csv()
    ds = c.post("/api/datasets", data={"name": "test extract"}, files={"data": ("d.csv", data), "dictionary": ("dd.csv", dct)}).json()
    p = c.post("/api/projects", json={"question": "Prevalence of functional iron deficiency in adults", "dataset_id": ds["id"]}).json()
    pid = p["id"]
    for _ in range(3):
        for i in p["plan"]["review"]:
            if (i.get("fix") or {}).get("op") == "acknowledge":
                p = c.post(f"/api/projects/{pid}/edit", json={"fix": i["fix"]}).json()
                break
    assert c.post(f"/api/projects/{pid}/approve", json={"by": "Tester"}).status_code == 200
    rid = c.post(f"/api/projects/{pid}/run").json()["id"]
    for _ in range(120):
        s = c.get(f"/api/projects/{pid}/runs/{rid}").json()
        if s["status"] != "running":
            break
        time.sleep(1)
    assert s["status"] == "completed", s.get("error")
    res = c.get(f"/api/projects/{pid}/runs/{rid}/results").json()
    assert 0 < res["primary_estimate"]["est"] < 1
    assert res["design"]["weight_variable"] == "survey_weight"
    assert not [x for x in res["checks"] if x["status"] == "fail"]
