# -----------------------------------------------------------------------------
# Automated quality-control checks. Every check returns a record
#   {id, category, title, status = pass|warn|fail|info, message}
# The UI blocks final sign-off while any check is "fail" unless the
# investigator records an override reason.
# -----------------------------------------------------------------------------

.check <- function(id, category, title, status, message, detail = NULL) {
  list(id = id, category = category, title = title, status = status, message = message, detail = detail)
}

run_checks <- function(ctx) {
  spec <- ctx$spec; dat <- ctx$data; res <- ctx$results
  out <- list()
  add <- function(x) out[[length(out) + 1]] <<- x

  # 1. variable availability --------------------------------------------------
  if (length(ctx$missing_vars)) {
    msg <- paste(vapply(ctx$missing_vars, function(m) sprintf("%s: %s", m$file, paste(unlist(m$variables), collapse = ", ")), ""), collapse = "; ")
    add(.check("variable_availability", "Data", "Requested variables present in source files", "fail",
               paste("Variables not found -", msg, "- derived values depending on them are missing.")))
  } else {
    add(.check("variable_availability", "Data", "Requested variables present in source files", "pass",
               sprintf("All %d raw variables found in %d file(s).", length(spec$raw_variables), length(ctx$files))))
  }

  # 2. synthetic data guard ---------------------------------------------------
  if (any(vapply(ctx$files, function(f) isTRUE(f$synthetic), TRUE))) {
    add(.check("synthetic_data", "Data", "Real vs synthetic data", "warn",
               "SYNTHETIC NHANES-like data were used (offline demo). Estimates are NOT valid population estimates."))
  } else {
    add(.check("synthetic_data", "Data", "Real vs synthetic data", "pass", "Official source files were used (MD5 recorded in provenance)."))
  }

  # 3. cycle overlap ------------------------------------------------------------
  cyc <- unlist(spec$dataset$cycles)
  if (all(c("J", "P") %in% cyc)) add(.check("cycle_overlap", "Design", "Survey cycles do not overlap", "fail",
                                            "2017-2018 (J) is contained in the 2017-March 2020 pre-pandemic file (P); combining double-counts participants."))
  else add(.check("cycle_overlap", "Design", "Survey cycles do not overlap", "pass", sprintf("Cycles: %s", paste(cyc, collapse = ", "))))

  # 4. weights ------------------------------------------------------------------
  levels_needed <- unique(vapply(spec$raw_variables, function(r) r$weight_level %||% "interview", ""))
  rank <- c(interview = 1, mec = 2, diet = 3, fasting = 4)
  needed <- names(rank)[max(rank[levels_needed[levels_needed %in% names(rank)]], 1)]
  wl <- spec$weight_level
  an <- dat[dat$.in_analytic & dat$.design_ok, , drop = FALSE]
  if (identical(spec$dataset$type, "nhanes") && !identical(needed, wl)) {
    add(.check("weight_choice", "Design", "Appropriate sample weight", "fail",
               sprintf("Variables come from the %s component but %s weights were used.", needed, wl)))
  } else {
    add(.check("weight_choice", "Design", "Appropriate sample weight", "pass",
               sprintf("%s weight (%s) matches the most restrictive component used; weights rescaled by cycle length when combining cycles.",
                       wl %||% "analysis", paste(unique(dat$.weight_var), collapse = ", "))))
  }
  nonpos <- sum(is.na(an$.wt) | an$.wt <= 0)
  add(.check("weight_values", "Design", "Analytic weights positive and non-missing",
             if (nonpos == 0) "pass" else "fail",
             sprintf("%d analytic records with missing/zero weight. Weighted population represented: %s million.", nonpos,
                     formatC(sum(an$.wt, na.rm = TRUE) / 1e6, format = "f", digits = 1))))

  # 5. design df ----------------------------------------------------------------
  ds <- res$design
  if (!is.null(ds$analytic_df)) {
    st <- if (ds$analytic_df >= 8) "pass" else "warn"
    add(.check("design_df", "Design", "Design degrees of freedom", st,
               sprintf("Analytic population spans %d PSUs in %d strata (df = %d). NCHS flags estimates with df < 8.",
                       ds$analytic_psu, ds$analytic_strata, ds$analytic_df)))
  }

  # 6. sample size and events -----------------------------------------------------
  n_an <- sum(dat$.in_analytic)
  st <- if (n_an >= 300) "pass" else if (n_an >= 100) "warn" else "fail"
  add(.check("sample_size", "Sample", "Analytic sample size", st, sprintf("Analytic n = %s.", format(n_an, big.mark = ","))))
  prim <- res$primary_model
  if (!is.null(prim) && !is.null(prim$events) && !is.na(prim$events)) {
    p <- max(length(prim$terms) - 1, 1)
    epv <- min(prim$events, prim$n - prim$events) / p
    add(.check("events_per_parameter", "Model", "Events per model parameter", if (epv >= 10) "pass" else "warn",
               sprintf("%d events, %d non-events, %d parameters -> %.1f per parameter (rule of thumb >= 10).", prim$events, prim$n - prim$events, p, epv)))
  }

  # 7. missingness ----------------------------------------------------------------
  pop <- sum(dat$.in_pop)
  miss_out <- pop - sum(dat$.in_pop & !is.na(dat[[spec$outcome$name]]))
  pct_out <- if (pop > 0) 100 * miss_out / pop else 0
  add(.check("missing_outcome", "Missing data", "Outcome missingness", if (pct_out <= 10) "pass" else if (pct_out <= 25) "warn" else "fail",
             sprintf("%.1f%% of the eligible population lacks the outcome (%d of %d). Missing outcome is assumed missing at random within the design.", pct_out, miss_out, pop)))
  for (role in c("outcome", "exposure")) {
    nm <- spec[[role]]$name
    if (is.null(nm) || !nm %in% names(dat) || is.null(spec$exposure$name)) next
    v <- dat[[nm]][dat$.in_cc]; v <- v[!is.na(v)]
    if (length(v) && length(unique(v)) < 2)
      add(.check(paste0("variation_", role), "Data quality", sprintf("No variation in the %s", role), "fail",
                 sprintf("'%s' takes a single value (%s) in all %d analysed participants, so no effect can be estimated. Check the definition thresholds and the coding of the source questions.",
                         nm, format(v[1]), length(v))))
  }
  lost <- sum(dat$.in_analytic) - sum(dat$.in_cc)
  pct_lost <- if (n_an > 0) 100 * lost / n_an else 0
  add(.check("missing_covariates", "Missing data", "Complete-case loss", if (pct_lost <= 10) "pass" else if (pct_lost <= 25) "warn" else "fail",
             sprintf("%.1f%% of the analytic sample (%d) lack >=1 covariate.%s", pct_lost, lost,
                     if (pct_lost > 10) " Multiple-imputation sensitivity analysis recommended." else "")))

  # 8. ranges -------------------------------------------------------------------
  bad <- Filter(function(r) (r$n_below + r$n_above) > 0, ctx$ranges)
  if (length(bad)) {
    add(.check("value_ranges", "Data", "Raw values within plausible ranges", "warn",
               paste("Out-of-range values:", paste(vapply(bad, function(r) sprintf("%s (%d low, %d high)", r$variable, r$n_below, r$n_above), ""), collapse = "; ")),
               detail = bad))
  } else add(.check("value_ranges", "Data", "Raw values within plausible ranges", "pass",
                    sprintf("%d raw variables checked against dictionary ranges; non-response codes recoded to missing.", length(ctx$ranges))))

  # 9. NCHS presentation standards -----------------------------------------------
  if (length(res$prevalence)) {
    flags <- vapply(res$prevalence, function(p) p$nchs, "")
    n_sup <- sum(grepl("^suppress", flags)); n_rev <- sum(grepl("^review", flags))
    add(.check("nchs_standards", "Reporting", "NCHS presentation standards for proportions",
               if (n_sup > 0) "warn" else if (n_rev > 0) "warn" else "pass",
               sprintf("%d of %d estimates meet the standard; %d should be suppressed, %d flagged for review.",
                       sum(flags == "meets standard"), length(flags), n_sup, n_rev)))
  }

  # 10. model convergence / warnings ----------------------------------------------
  allm <- res$models
  if (length(allm)) {
    bad_m <- Filter(function(m) !isTRUE(m$converged) || length(m$warnings) > 0, allm)
    add(.check("model_convergence", "Model", "Models converged without warnings", if (length(bad_m) == 0) "pass" else "warn",
               if (length(bad_m) == 0) sprintf("%d models converged cleanly.", length(allm))
               else paste("Issues:", paste(vapply(bad_m, function(m) sprintf("%s [%s]", m$label, paste(unlist(m$warnings), collapse = " | ")), ""), collapse = "; "))))
    # implausible estimates
    implaus <- list()
    for (m in allm) for (t in m$terms) {
      if (t$term == "(Intercept)") next
      if (m$effect %in% c("PR", "OR")) {
        if (is.finite(t$est) && (t$est > 10 || t$est < 0.1 || t$se > 2.5)) implaus[[length(implaus) + 1]] <- sprintf("%s / %s = %.2f (SE log %.2f)", m$label, t$label, t$est, t$se)
      }
    }
    add(.check("implausible_estimates", "Model", "No implausible effect sizes", if (length(implaus) == 0) "pass" else "warn",
               if (length(implaus) == 0) "All ratio estimates within 0.1-10 with SE(log) < 2.5." else paste("Review:", paste(head(unlist(implaus), 6), collapse = "; "))))
  }

  # 10b. parameters vs design df ------------------------------------------------------
  if (!is.null(prim) && !is.null(prim$n_params) && !is.null(prim$df_design)) {
    add(.check("design_df_params", "Model", "Model size vs design degrees of freedom",
               if (prim$n_params <= prim$df_design) "pass" else "warn",
               sprintf("Primary model has %d parameters; design df = %d. Wald tests and CIs use the design df (t distribution).%s",
                       prim$n_params, prim$df_design, if (prim$n_params > prim$df_design) " More parameters than design df: multivariable Wald tests are unstable - consider a more parsimonious model or pooling cycles." else "")))
  }

  # 11. collinearity --------------------------------------------------------------
  vif_vals <- suppressWarnings(as.numeric(unlist(lapply(res$vif, function(v) v$vif))))
  if (length(vif_vals) && any(!is.na(vif_vals))) {
    mx <- max(vif_vals, na.rm = TRUE)
    worst <- res$vif[[which.max(vif_vals)]]
    add(.check("collinearity", "Model", "Collinearity (generalized VIF)", if (mx < 5) "pass" else "warn",
               sprintf("Maximum VIF %.2f (%s).%s", mx, worst$term, if (mx >= 5) " Consider removing/combining collinear covariates or interpreting with care." else "")))
  }

  # 12. robustness: sensitivity agreement --------------------------------------
  if (length(res$sensitivity) && !is.null(res$primary_estimate)) {
    pe <- res$primary_estimate
    null_of <- function(eff) if (eff %in% c("PR", "OR")) 1 else if (eff == "Beta") 0 else NA
    agree <- 0; total <- 0; flips <- character(0)
    for (s in res$sensitivity) {
      if (is.null(s$est) || is.na(s$est) || is.null(s$effect)) next
      if (identical(pe$effect, "prevalence") && identical(s$type, "alt_outcome")) next  # different construct, not a robustness check
      total <- total + 1
      if (pe$effect == "prevalence" || s$effect == "prevalence") {
        same <- abs(s$est - pe$est) <= max(0.05, 0.35 * pe$est)
      } else {
        same <- sign(s$est - null_of(s$effect)) == sign(pe$est - null_of(pe$effect))
      }
      if (isTRUE(same)) agree <- agree + 1 else flips <- c(flips, s$label)
    }
    if (total > 0) add(.check("robustness", "Robustness", "Sensitivity analyses agree with primary result",
                              if (agree == total) "pass" else "warn",
                              sprintf("%d of %d sensitivity analyses agree in direction (associations) or magnitude (prevalence).%s", agree, total,
                                      if (length(flips)) paste(" Divergent:", paste(flips, collapse = "; ")) else "")))
  }

  # 13. benchmark against published literature ----------------------------------
  for (b in res$benchmarks) {
    add(.check(paste0("benchmark_", b$outcome), "External validity", paste("Replication of published estimate -", b$outcome_label),
               if (isTRUE(b$overlap)) "pass" else "warn", b$message))
  }

  # 14. age top-coding ----------------------------------------------------------
  if (identical(spec$dataset$type, "nhanes") && "age" %in% unlist(c(spec$covariates, spec$exposure$name))) {
    add(.check("age_topcode", "Data", "Age top-coding", "info", "NHANES top-codes age at 80 years; age is modelled as continuous with this censoring."))
  }

  # 15. derived variables audit ---------------------------------------------------
  unav <- unlist(spec$unavailable_measures)
  if (length(unav)) add(.check("unavailable_measures", "Data", "Building blocks not in this dataset", "info",
                               paste("Not provided by the dataset (treated as missing):", paste(unav, collapse = ", "))))
  empty <- Filter(function(a) a$n_nonmissing == 0 && !(a$name %in% unav), ctx$audit)
  add(.check("derivations", "Data", "Derived variables computable", if (length(empty) == 0) "pass" else "fail",
             if (length(empty) == 0) sprintf("%d derived variables computed; see derivation audit.", length(ctx$audit))
             else paste("Entirely missing:", paste(vapply(empty, function(a) a$name, ""), collapse = ", "))))
  out
}

# Generalized VIF on the complete-case model matrix (unweighted approximation).
compute_vif <- function(dat, terms) {
  if (length(terms) < 2) return(list())
  cc <- dat[dat$.in_cc, , drop = FALSE]
  f <- stats::as.formula(paste("~", paste(terms, collapse = " + ")))
  mm <- tryCatch(stats::model.matrix(f, cc)[, -1, drop = FALSE], error = function(e) NULL)
  if (is.null(mm) || ncol(mm) < 2) return(list())
  keep <- apply(mm, 2, stats::sd) > 0
  mm <- mm[, keep, drop = FALSE]
  R <- stats::cor(mm)
  inv <- tryCatch(solve(R), error = function(e) NULL)
  if (is.null(inv)) return(list(list(term = "model matrix singular", vif = Inf)))
  lapply(seq_len(ncol(mm)), function(i) list(term = colnames(mm)[i], vif = round(unname(diag(inv)[i]), 2)))
}
