# Reproducibility bundle - Association of Liver Stiffness With Thrombocytopenia Among US Adults: NHANES 2017-March 2020 pre-pandemic

* Plan `plan_b2cc741679` v1, sha256 `0f5ba7ba4cf71b92984ebfca05f23e5bbba3345662805a16e978b5c3d21f0680`
* Run `run_80504146` (cdc)
* `analysis.R` is the whole analysis as one readable script (survey + haven only): files, recodes, eligibility, design, models.
* `Rscript reproduce.R` re-executes the analysis with the Q2E engine and asserts the primary estimate matches.
* `protocol_and_sap.md` is the approved study protocol and statistical analysis plan.
* `provenance.json` is a hash-chained ledger of every human and AI action.
