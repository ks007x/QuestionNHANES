"""Protocol agent: the analyst asks for changes in plain words, the AI applies them, and every change is
logged with a timestamp so the lead investigator can follow along."""
from fastapi.testclient import TestClient

from q2e import protocol_chat
from q2e.server import app

client = TestClient(app)
Q = "Is short sleep associated with hypertension in US adults?"


def _project():
    return client.post("/api/projects", json={"question": Q, "source": "synthetic"}).json()


def _say(pid, msg):
    return client.post(f"/api/projects/{pid}/protocol-chat", json={"message": msg}).json()


def test_requests_are_applied_and_logged_with_timestamps():
    pid = _project()["id"]
    pj = _say(pid, "only adults over 40")
    assert any("40" in c["expr"] for c in pj["plan"]["population"] if c["enabled"])
    pj = _say(pid, "report odds ratios")
    assert pj["plan"]["model"]["family"] == "quasibinomial"
    pj = _say(pid, "adjust for alcohol")
    assert "alcohol_dpd" in pj["plan"]["covariates"]
    pj = _say(pid, "don't adjust for income")
    assert "pir_cat" not in pj["plan"]["covariates"]
    ams = pj["amendments"]
    assert len(ams) == 4 and all(a["at"] and a["summary"] for a in ams)
    assert [a["version_after"] for a in ams] == [2, 3, 4, 5]
    assert pj["chain"]["valid"]


def test_request_it_cannot_ground_changes_nothing_and_asks():
    pid = _project()["id"]
    pj = _say(pid, "add pizza toppings")
    assert not pj.get("amendments")
    assert pj["plan"]["version"] == 1
    assert "couldn't" in pj["protocol_chat"][-1]["text"]


def test_already_adjusted_is_explained_not_logged():
    pid = _project()["id"]
    pj = _say(pid, "also adjust for smoking")
    assert not pj.get("amendments")
    assert "already adjusts" in pj["protocol_chat"][-1]["text"]


def test_swap_keeps_earlier_changes_and_undo_restores():
    pid = _project()["id"]
    _say(pid, "report odds ratios")
    pj = _say(pid, "swap the exposure and outcome")
    assert pj["plan"]["model"]["family"] == "quasibinomial"
    assert pj["plan"]["outcome"]["concept"] == "short_sleep"
    am = pj["amendments"][-1]
    pj = client.post(f"/api/projects/{pid}/amendments/{am['id']}/undo", json={}).json()
    assert pj["plan"]["outcome"]["concept"] == "hypertension"
    assert pj["amendments"][-2]["undone"] and pj["amendments"][-1]["source"] == "undo"
    assert pj["chain"]["valid"]


def test_only_latest_change_can_be_undone_and_reason_is_optional():
    pid = _project()["id"]
    _say(pid, "report odds ratios")
    pj = _say(pid, "use 2015-2018 data")
    first, second = pj["amendments"]
    assert first["reason"] is None
    assert client.post(f"/api/projects/{pid}/amendments/{first['id']}/undo", json={}).status_code == 409
    pj = client.post(f"/api/projects/{pid}/amendments/{second['id']}/reason", json={"reason": "match the 2018 guideline"}).json()
    assert pj["amendments"][1]["reason"] == "match the 2018 guideline"
    assert "2015-2016" in pj["plan"]["title"]


def test_manual_edits_also_appear_in_history():
    pj = _project()
    crit = next(c for c in pj["plan"]["population"] if c["enabled"])
    pj = client.post(f"/api/projects/{pj['id']}/edit", json={"fix": {"op": "enable_criterion", "id": crit["id"], "value": False}}).json()
    assert pj["amendments"][-1]["source"] == "edit"
    assert pj["amendments"][-1]["summary"]


def test_diff_is_plain_language():
    old = {"model": {"family": "quasipoisson"}, "covariates": ["age"], "population": []}
    new = {"model": {"family": "quasibinomial"}, "covariates": ["age", "smoking"], "population": []}
    lines = protocol_chat.summary_lines(protocol_chat.diff_plans(old, new))
    assert "Effect measure: prevalence ratio → odds ratio" in lines
    assert any(l.startswith("Adjusted for: added:") for l in lines)
