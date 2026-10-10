# Reproduce Q2E analysis plan_0c372636b9 (plan sha256 5a458b4208e11b29b04076aabe513b3f94216cd0a231412f0f7800592af46fc9)
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
