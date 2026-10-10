# Reproduce Q2E analysis plan_666a8f675a (plan sha256 780f3a793976e5b3911be4ffb120ad59f194624e55fa4a64bfe1e441d32607a1)
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
