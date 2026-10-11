# -----------------------------------------------------------------------------
# Population flow and survey design.
# NHANES subpopulations are analysed with subset(design, ...) on the full
# design (never by dropping rows before svydesign) so variance estimation
# keeps every PSU - the most common NHANES analytic error.
# -----------------------------------------------------------------------------

apply_population <- function(dat, spec) {
  flow <- list()
  n0 <- nrow(dat)
  flow[[1]] <- list(step = "source", label = sprintf("Participants in source files (%s)", paste(unique(dat$.cycle), collapse = ", ")),
                    n = n0, excluded = 0L)
  keep <- !is.na(dat$.wt) & dat$.wt > 0
  wl <- spec$weight_level
  lbl <- switch(wl %||% "none", mec = "Examined in the MEC (positive MEC weight)", fasting = "In fasting subsample (positive fasting weight)",
                interview = "Interviewed (positive interview weight)", "Positive analysis weight")
  flow[[2]] <- list(step = "weight", label = lbl, n = sum(keep), excluded = n0 - sum(keep))
  dat$.design_ok <- keep
  cur <- keep
  for (cr in spec$population) {
    v <- tryCatch(dsl_eval(cr$expr, dat), error = function(e) stop(sprintf("Criterion '%s' failed: %s", cr$label, conditionMessage(e))))
    v <- .as_lgl(v)
    if (identical(cr$kind, "exclusion")) {
      drop <- !is.na(v) & v
      new <- cur & !drop
      lab <- paste0("Excluded: ", cr$label)
    } else {
      new <- cur & !is.na(v) & v
      lab <- cr$label
    }
    flow[[length(flow) + 1]] <- list(step = cr$id %||% "criterion", label = lab, kind = cr$kind %||% "inclusion",
                                      n = sum(new), excluded = sum(cur) - sum(new))
    cur <- new
  }
  dat$.in_pop <- cur
  y <- spec$outcome$name
  new <- cur & !is.na(dat[[y]])
  flow[[length(flow) + 1]] <- list(step = "outcome", label = sprintf("Non-missing outcome (%s)", spec$outcome$label %||% y),
                                    n = sum(new), excluded = sum(cur) - sum(new))
  cur <- new
  if (!is.null(spec$exposure) && !is.null(spec$exposure$name)) {
    x <- spec$exposure$name
    new <- cur & !is.na(dat[[x]])
    flow[[length(flow) + 1]] <- list(step = "exposure", label = sprintf("Non-missing exposure (%s)", spec$exposure$label %||% x),
                                      n = sum(new), excluded = sum(cur) - sum(new))
    cur <- new
  }
  dat$.in_analytic <- cur
  covs <- unlist(spec$covariates)
  cc <- cur
  for (cv in covs) if (cv %in% names(dat)) cc <- cc & !is.na(dat[[cv]])
  dat$.in_cc <- cc
  flow[[length(flow) + 1]] <- list(step = "complete_case", label = "Complete covariate data (complete-case model sample)",
                                    n = sum(cc), excluded = sum(cur) - sum(cc))
  list(data = dat, flow = flow)
}

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

# Drop factor levels that do not occur in the analytic population so models do
# not carry empty contrasts.
tidy_factor_levels <- function(dat, vars) {
  for (v in vars) {
    if (v %in% names(dat) && is.factor(dat[[v]])) {
      present <- levels(dat[[v]])[levels(dat[[v]]) %in% unique(as.character(dat[[v]][dat$.in_analytic]))]
      dat[[v]] <- factor(as.character(dat[[v]]), levels = present)
    }
  }
  dat
}

build_design <- function(dat, spec) {
  base <- dat[dat$.design_ok, , drop = FALSE]
  options(survey.lonely.psu = "adjust")
  if (identical(spec$dataset$type, "nhanes") || (!is.null(spec$dataset$strata) && nzchar(spec$dataset$strata %||% ""))) {
    des <- survey::svydesign(ids = ~.psu, strata = ~.strata, weights = ~.wt, nest = TRUE, data = base)
  } else if (!is.null(spec$dataset$psu) && nzchar(spec$dataset$psu %||% "")) {
    des <- survey::svydesign(ids = ~.psu, weights = ~.wt, data = base)
  } else {
    des <- survey::svydesign(ids = ~1, weights = ~.wt, data = base)
  }
  des
}

design_summary <- function(des, dat, spec) {
  an <- dat[dat$.in_analytic & dat$.design_ok, , drop = FALSE]
  n_psu_all <- nrow(unique(des$variables[, c(".strata", ".psu")]))
  n_str_all <- length(unique(des$variables$.strata))
  n_psu_an <- nrow(unique(an[, c(".strata", ".psu")]))
  n_str_an <- length(unique(an$.strata))
  list(
    weight_variable = paste(unique(dat$.weight_var), collapse = ", "),
    weight_level = spec$weight_level,
    cycles = as.list(unique(dat$.cycle)),
    n_strata = n_str_all, n_psu = n_psu_all, design_df = survey::degf(des),
    analytic_strata = n_str_an, analytic_psu = n_psu_an, analytic_df = n_psu_an - n_str_an,
    sum_weights_millions = round(sum(an$.wt) / 1e6, 2),
    lonely_psu = "adjust"
  )
}
