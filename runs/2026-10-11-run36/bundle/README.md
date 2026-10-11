# Reproducibility bundle - Association of Abdominal Obesity (Waist Circumference) With Glycemic Control (HbA1c) Among US Adults: NHANES 2017-March 2020 pre-pandemic

* Plan `plan_ca96564765` v1, sha256 `780f3a793976e5b3911be4ffb120ad59f194624e55fa4a64bfe1e441d32607a1`
* Run `run_e80bddd9` (cdc)
* `analysis.R` is the whole analysis as one readable script (survey + haven only): files, recodes, eligibility, design, models.
* `Rscript reproduce.R` re-executes the analysis with the Q2E engine and asserts the primary estimate matches.
* `protocol_and_sap.md` is the approved study protocol and statistical analysis plan.
* `provenance.json` is a hash-chained ledger of every human and AI action.
