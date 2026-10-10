# -----------------------------------------------------------------------------
# Blinded feasibility probe: counts only, run BEFORE protocol approval.
# Returns eligible n per cycle, non-missingness, complete-case n, design df,
# subgroup sizes, exposure SD/level counts and the outcome rate rounded to a
# 5-percentage-point band. No effect estimates and no exact prevalence are
# produced, so the protocol cannot be tuned to the results.
# -----------------------------------------------------------------------------
run_probe <- function(plan_path, outdir) {
  dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
  spec <- jsonlite::fromJSON(plan_path, simplifyVector = FALSE)
  ld <- if (identical(spec$dataset$type, "nhanes")) load_nhanes(spec, message) else load_generic(spec, message)
  dat <- clean_raw_variables(ld$data, spec$raw_variables)$data
  for (r in spec$raw_variables) if (!r$variable %in% names(dat)) dat[[r$variable]] <- NA_real_
  dat <- derive_variables(dat, spec$derived, message)$data
  pf <- apply_population(dat, spec)
  dat <- pf$data
  y <- spec$outcome$name; x <- spec$exposure$name
  covs <- unlist(spec$covariates)
  an <- dat[dat$.in_analytic & dat$.design_ok, , drop = FALSE]
  per_cycle <- lapply(unique(dat$.cycle), function(cy) {
    d <- dat[dat$.cycle == cy, ]
    pop <- d$.in_pop & d$.design_ok
    list(cycle = cy, n_records = nrow(d), n_weighted = sum(d$.design_ok), n_population = sum(pop),
         n_outcome = sum(pop & !is.na(d[[y]])),
         n_exposure = if (!is.null(x)) sum(pop & !is.na(d[[x]])) else NA,
         n_analytic = sum(d$.in_analytic & d$.design_ok), n_complete_case = sum(d$.in_cc & d$.design_ok))
  })
  band <- NULL; sd_y <- NULL
  yv <- an[[y]]
  if (spec$outcome$type == "binary") {
    p <- stats::weighted.mean(yv == 1, an$.wt, na.rm = TRUE)
    lo <- floor(p * 20) / 20
    band <- c(lo, lo + 0.05)
  } else if (spec$outcome$type == "continuous") {
    sd_y <- signif(stats::sd(yv, na.rm = TRUE), 2)
  }
  expo <- NULL
  if (!is.null(x)) {
    xv <- an[[x]]
    if (is.numeric(xv) && !all(xv %in% c(0, 1, NA))) expo <- list(type = "continuous", sd = signif(stats::sd(xv, na.rm = TRUE), 3))
    else {
      tb <- table(if (is.factor(xv)) as.character(xv) else ifelse(xv == 1, "Yes", "No"))
      expo <- list(type = "categorical", levels = lapply(names(tb), function(l) list(level = l, n = as.integer(tb[[l]]))))
    }
  }
  subgroups <- list()
  for (g in unlist(spec$analysis$prevalence$by)) {
    if (!g %in% names(an)) next
    gv <- an[[g]]
    tb <- table(if (is.factor(gv)) as.character(gv) else ifelse(gv == 1, "Yes", "No"))
    for (l in names(tb)) subgroups[[length(subgroups) + 1]] <- list(var = g, level = l, n = as.integer(tb[[l]]))
  }
  n_par <- 1L
  for (v in unique(c(x, covs))) {
    if (!v %in% names(an)) next
    n_par <- n_par + if (is.factor(an[[v]])) max(length(unique(stats::na.omit(an[[v]]))) - 1L, 1L) else 1L
  }
  pop <- dat[dat$.in_pop & dat$.design_ok, , drop = FALSE]
  cov_miss <- lapply(covs[covs %in% names(pop)], function(v) list(var = v, n_missing = sum(is.na(pop[[v]])),
                                                                 pct = round(100 * mean(is.na(pop[[v]])), 1)))
  ds <- list(analytic_psu = nrow(unique(an[, c(".strata", ".psu")])), analytic_strata = length(unique(an$.strata)))
  ds$analytic_df <- ds$analytic_psu - ds$analytic_strata
  res <- list(blinded = TRUE, flow = pf$flow, per_cycle = per_cycle,
              n_analytic = nrow(an), n_complete_case = sum(dat$.in_cc & dat$.design_ok),
              outcome = list(type = spec$outcome$type, rate_band = band, sd = sd_y),
              exposure = expo, subgroups = subgroups, n_parameters = n_par, covariate_missing = cov_miss, design = ds,
              weight_variable = paste(unique(dat$.weight_var), collapse = ", "),
              missing_vars = ld$missing_vars,
              synthetic = any(vapply(ld$files, function(f) isTRUE(f$synthetic), TRUE)))
  writeLines(jsonlite::toJSON(res, auto_unbox = TRUE, null = "null", na = "null", pretty = TRUE), file.path(outdir, "probe.json"))
  invisible(res)
}
