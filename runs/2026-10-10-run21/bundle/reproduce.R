# Reproduce Q2E analysis plan_6ff354c999 (plan sha256 1649016233e18f465801c12407c258357948dec26760cc91375ade506dc0adb0)
# Requirements: R >= 4.2 with survey, jsonlite, haven, ggplot2, mice, mitools
#   install.packages(c("survey", "jsonlite", "haven", "ggplot2", "mice", "mitools"))
# Data: put the NHANES .xpt files listed in compiled_plan.json in ./data, or leave
# allow_download = TRUE to fetch them from CDC. Synthetic runs: run
#   Rscript engine/synth/make_synthetic_nhanes.R data 12000 20261010
source("engine/run_pipeline.R")
q2e_source_engine("engine")
res <- run_pipeline("compiled_plan.json", "reproduced_results")
orig <- jsonlite::fromJSON("results/results.json", simplifyVector = FALSE)
cat("Primary estimate - original:", orig$primary_estimate$est, " reproduced:", res$primary_estimate$est, "\n")
stopifnot(isTRUE(all.equal(orig$primary_estimate$est, res$primary_estimate$est, tolerance = 1e-8)))
cat("Reproduction successful.\n")
