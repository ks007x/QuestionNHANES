# Install the R packages used by the Q2E biostatistics engine.
# Installs into your personal R library, so no administrator rights are needed.
pkgs <- c("survey", "jsonlite", "haven", "ggplot2", "mice", "mitools", "yaml", "testthat")
lib <- Sys.getenv("R_LIBS_USER")
if (nzchar(lib)) {
  lib <- path.expand(strsplit(lib, .Platform$path.sep)[[1]][1])
  dir.create(lib, recursive = TRUE, showWarnings = FALSE)
  .libPaths(c(lib, .libPaths()))
}
missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) {
  cat("Installing:", paste(missing, collapse = ", "), "\n")
  install.packages(missing, lib = .libPaths()[1], repos = Sys.getenv("CRAN_REPO", "https://cloud.r-project.org"))
}
still <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(still)) stop("These R packages could not be installed: ", paste(still, collapse = ", "))
cat("R packages ready:", paste(pkgs, collapse = ", "), "\n")
