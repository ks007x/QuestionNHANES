#!/usr/bin/env Rscript
# -----------------------------------------------------------------------------
# Verify Q2E's curated NHANES dictionary against real NHANES .xpt files and
# export every variable label found (a full machine-readable data dictionary).
#
#   Rscript scripts/verify_nhanes_dictionary.R <folder-with-xpt-files> [out.csv]
#
# Reads the SAS transport labels embedded in each file (no internet needed - works
# with the hackathon-provided NHANES extracts). Reports curated variables that are
# missing from the files for each cycle so the dictionary can be corrected.
# -----------------------------------------------------------------------------
suppressPackageStartupMessages({ library(haven); library(yaml) })
`%||%` <- function(a, b) if (is.null(a)) b else a
args <- commandArgs(trailingOnly = TRUE)
dir <- if (length(args)) args[1] else "data/nhanes"
out <- if (length(args) > 1) args[2] else "nhanes_full_dictionary.csv"
root <- normalizePath(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))), ".."))
cur <- read.csv(file.path(root, "knowledge", "nhanes", "dictionary.csv"), stringsAsFactors = FALSE)
cycles <- yaml::read_yaml(file.path(root, "knowledge", "nhanes", "cycles.yaml"))$cycles
files <- list.files(dir, pattern = "\\.xpt$", ignore.case = TRUE, full.names = TRUE)
if (!length(files)) stop("No .xpt files in ", dir)
rows <- list()
for (f in files) {
  d <- haven::read_xpt(f, n_max = 0)
  for (v in names(d)) rows[[length(rows) + 1]] <- data.frame(file = sub("\\.xpt$", "", basename(f), ignore.case = TRUE), variable = v,
                                                             label = attr(d[[v]], "label") %||% "", stringsAsFactors = FALSE)
}
full <- do.call(rbind, rows)
write.csv(full, out, row.names = FALSE)
cat(sprintf("Exported %d variables from %d files to %s\n", nrow(full), length(files), out))
present_files <- unique(toupper(full$file))
problems <- 0
for (cy in names(cycles)) {
  pat <- cycles[[cy]]$file_pattern
  for (i in seq_len(nrow(cur))) {
    if (!grepl(cy, cur$cycles[i])) next
    fname <- toupper(sub("{stem}", cur$file[i], pat, fixed = TRUE))
    if (!fname %in% present_files) next
    if (!cur$variable[i] %in% full$variable[toupper(full$file) == fname]) {
      cat(sprintf("MISSING  %-9s not in %s (cycle %s) - curated label: %s\n", cur$variable[i], fname, cy, cur$label[i]))
      problems <- problems + 1
    }
  }
}
cat(if (problems) sprintf("%d curated entries need correction.\n", problems) else "All curated variables present in the supplied files.\n")
