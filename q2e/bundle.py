"""Reproducibility bundle: everything another analyst needs to re-run and audit a study."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .config import settings
from .store import ProjectStore

REPRODUCE_R = """# Reproduce Q2E analysis {plan_id} (plan sha256 {plan_hash})
# Requirements: R >= 4.2 with survey, jsonlite, haven, ggplot2, mice, mitools
#   install.packages(c("survey", "jsonlite", "haven", "ggplot2", "mice", "mitools"))
# Data: put the NHANES .xpt files listed in compiled_plan.json in ./data, or leave
# allow_download = TRUE to fetch them from CDC. Synthetic runs: run
#   Rscript engine/synth/make_synthetic_nhanes.R data 12000 20261010
source("engine/run_pipeline.R")
q2e_source_engine("engine")
res <- run_pipeline("compiled_plan.json", "reproduced_results")
orig <- jsonlite::fromJSON("results/results.json", simplifyVector = FALSE)
cat("Primary estimate - original:", orig$primary_estimate$est, " reproduced:", res$primary_estimate$est, "\\n")
stopifnot(isTRUE(all.equal(orig$primary_estimate$est, res$primary_estimate$est, tolerance = 1e-8)))
cat("Reproduction successful.\\n")
"""


def build_bundle(proj: dict, run: dict, report_html: str | None, report_md: str | None, store: ProjectStore) -> bytes:
    run_dir = Path(run["dir"])
    compiled = json.loads((run_dir / "compiled_plan.json").read_text())
    ds = compiled["dataset"]
    if ds.get("type") == "nhanes":
        synthetic = ds.get("source") == "synthetic"
        ds["local_dir"] = "data"
        ds["synthetic_dir"] = "data" if synthetic else None
        ds["cache_dir"] = "data/cache"
        ds["allow_download"] = not synthetic
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("compiled_plan.json", json.dumps(compiled, indent=2))
        z.writestr("study_plan.json", json.dumps(proj["plan"], indent=2, default=str))
        z.writestr("provenance.json", json.dumps({"events": proj["events"], "history": proj["history"],
                                                  "chain": store.verify_chain(proj), "signoff": proj.get("signoff")}, indent=2, default=str))
        z.writestr("reproduce.R", REPRODUCE_R.format(plan_id=compiled["plan_id"], plan_hash=compiled["plan_hash"]))
        for f in (run_dir / "out").glob("*"):
            z.write(f, f"results/{f.name}")
        if (run_dir / "run_log.txt").exists():
            z.write(run_dir / "run_log.txt", "results/run_log.txt")
        eng = settings.root / "r" / "engine"
        z.write(eng / "run_pipeline.R", "engine/run_pipeline.R")
        for f in (eng / "R").glob("*.R"):
            z.write(f, f"engine/R/{f.name}")
        z.write(settings.synth_script, "engine/synth/make_synthetic_nhanes.R")
        if ds.get("type") == "nhanes" and ds.get("source") == "synthetic":
            for f in settings.synthetic_dir.glob("*"):
                if f.suffix.lower() in (".xpt", ".txt"):
                    z.write(f, f"data/{f.name}")
        if report_html:
            z.writestr("manuscript.html", report_html)
        if report_md:
            z.writestr("manuscript.md", report_md)
        z.writestr("README.md", f"# Reproducibility bundle - {proj['plan']['title']}\n\n"
                                f"* Plan `{compiled['plan_id']}` v{compiled['plan_version']}, sha256 `{compiled['plan_hash']}`\n"
                                f"* Run `{run['id']}` ({run.get('data_source')})\n"
                                f"* `Rscript reproduce.R` re-executes the analysis and asserts the primary estimate matches.\n"
                                f"* `provenance.json` is a hash-chained ledger of every human and AI action.\n")
    return buf.getvalue()
