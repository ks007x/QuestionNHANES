"""The readable analysis.R must reproduce what the engine reported, on the same data."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import requires_r
from test_end_to_end import _approve

from q2e import agents, r_script
from q2e.config import find_rscript, settings
from q2e.runner import get_run, load_results, start_run
from q2e.store import store


def _run(question, drop=("mi", "exposure_quartiles")):
    plan = agents.design_study(question, ["P"], {"type": "nhanes", "cycles": ["P"], "source": "synthetic"})
    for s in plan["sensitivity"]:
        if s["type"] in drop:
            s["enabled"] = False
    proj = store.create("rscript", plan)
    _approve(proj)
    run = start_run(proj["id"], wait=True)
    run = get_run(proj["id"], run["id"])
    assert run["status"] == "completed", run.get("error")
    return store.get(proj["id"]), run, load_results(proj["id"], run["id"])


def _execute(proj, run, res, tmp_path):
    spec = json.loads((Path(run["dir"]) / "compiled_plan.json").read_text(encoding="utf-8"))
    script = r_script.build(spec, proj, res)
    f = tmp_path / "analysis.R"
    f.write_text(script, encoding="utf-8")
    env = {**os.environ, "NHANES_DIR": str(settings.synthetic_dir)}
    out = subprocess.run([find_rscript(os.environ.get("Q2E_RSCRIPT", "")), str(f)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return script, out.stdout


@requires_r
@pytest.mark.parametrize("question", [
    "Is abdominal obesity linked to worse glycemic control?",                       # gaussian, continuous exposure
    "Is higher liver stiffness associated with thrombocytopenia in US adults?",     # quasipoisson prevalence ratio
])
def test_readable_script_reproduces_engine(question, tmp_path):
    proj, run, res = _run(question)
    script, stdout = _execute(proj, run, res, tmp_path)
    assert "svydesign(ids = ~.psu, strata = ~.strata, weights = ~.wt, nest = TRUE" in script
    assert "Matches the Q2E run: TRUE" in stdout, stdout[-3000:]
    # interaction tests now run in the engine (product terms were being dropped)
    if res.get("interactions"):
        assert any(i["p_interaction"] is not None for i in res["interactions"])
