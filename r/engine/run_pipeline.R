#!/usr/bin/env Rscript
# -----------------------------------------------------------------------------
# Q2E biostatistics engine - executes an approved, compiled study plan.
#
#   Rscript r/engine/run_pipeline.R --plan compiled_plan.json --out results_dir
#
# The engine never executes free-form code from the plan: derived variables and
# criteria pass through the whitelisted expression language in R/dsl.R.
# -----------------------------------------------------------------------------
suppressPackageStartupMessages({
  library(survey)
  library(jsonlite)
})

Q2E_ENGINE_VERSION <- "1.0.0"

.script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", args[grepl("^--file=", args)])
  if (length(f)) return(dirname(normalizePath(f[1])))
  if (!is.null(sys.frames()[[1]]$ofile)) return(dirname(normalizePath(sys.frames()[[1]]$ofile)))
  getwd()
}

q2e_source_engine <- function(dir = .script_dir()) {
  for (f in list.files(file.path(dir, "R"), pattern = "\\.R$", full.names = TRUE)) source(f, local = FALSE)
}

run_pipeline <- function(plan_path, outdir) {
  started <- Sys.time()
  dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
  log_lines <- character(0)
  log <- function(...) { msg <- paste0(format(Sys.time(), "%H:%M:%S"), "  ", paste0(...)); log_lines <<- c(log_lines, msg); message(msg) }
  trace <- character(0)
  tr <- function(x) trace <<- c(trace, x)

  spec <- jsonlite::fromJSON(plan_path, simplifyVector = FALSE)
  set.seed(spec$options$seed %||% 2026)
  log("Plan ", spec$plan_id %||% "?", " (hash ", substr(spec$plan_hash %||% "", 1, 12), ") loaded")

  # ---- 1. load ---------------------------------------------------------------
  ld <- if (identical(spec$dataset$type, "nhanes")) load_nhanes(spec, log) else load_generic(spec, log)
  dat <- ld$data
  log(sprintf("Loaded %s records from %d file(s)", format(nrow(dat), big.mark = ","), length(ld$files)))
  tr(sprintf("# data: %s", paste(vapply(ld$files, function(f) f$file, ""), collapse = ", ")))

  # ---- 2. clean + derive -------------------------------------------------------
  cl <- clean_raw_variables(dat, spec$raw_variables)
  dat <- cl$data
  for (r in spec$raw_variables) if (!r$variable %in% names(dat)) dat[[r$variable]] <- NA_real_
  dv <- derive_variables(dat, spec$derived, log)
  dat <- dv$data
  log(sprintf("Derived %d analysis variables", length(spec$derived)))
  for (d in spec$derived) tr(sprintf("%s <- %s", d$name, d$expr))

  # ---- 3. population ----------------------------------------------------------
  pf <- apply_population(dat, spec)
  dat <- pf$data
  for (cr in spec$population) tr(sprintf("# %s: %s", cr$kind %||% "inclusion", cr$expr))
  used_vars <- unique(c(spec$outcome$name, spec$exposure$name, unlist(spec$covariates), unlist(spec$subgroups),
                        unlist(spec$analysis$table1_vars), unlist(spec$analysis$prevalence$by)))
  dat <- tidy_factor_levels(dat, used_vars[used_vars %in% names(dat)])
  log(sprintf("Analytic population: %s", format(sum(dat$.in_analytic), big.mark = ",")))

  # ---- 4. design ----------------------------------------------------------------
  des <- build_design(dat, spec)
  tr("des <- svydesign(ids = ~SDMVPSU, strata = ~SDMVSTRA, weights = ~WT, nest = TRUE, data = <positive-weight records>)")
  tr("options(survey.lonely.psu = 'adjust'); subpopulations via subset(des, ...)")
  results <- list()
  results$design <- design_summary(des, dat, spec)
  results$flow <- pf$flow
  synthetic <- any(vapply(ld$files, function(f) isTRUE(f$synthetic), TRUE))

  # ---- 5. descriptives --------------------------------------------------------
  t1_vars <- unlist(spec$analysis$table1_vars)
  results$table1 <- tryCatch(table_one(des, dat, spec, t1_vars, spec$analysis$table1_by),
                             error = function(e) { log("Table 1 failed: ", conditionMessage(e)); NULL })
  prev_outcomes <- unlist(spec$analysis$prevalence$outcomes)
  results$prevalence <- if (length(prev_outcomes)) prevalence_estimates(des, dat, spec, prev_outcomes, unlist(spec$analysis$prevalence$by)) else list()
  if (length(prev_outcomes)) tr(sprintf("svyciprop(~I(%s == 1), subset(des, analytic), method = 'beta')  # by %s", prev_outcomes[1],
                                         paste(unlist(spec$analysis$prevalence$by), collapse = ", ")))
  log(sprintf("Computed %d prevalence estimates", length(results$prevalence)))

  # ---- 6. models ---------------------------------------------------------------
  y <- spec$outcome$name
  x <- spec$exposure$name
  model_spec <- spec$analysis$model
  fam <- model_spec$family %||% "quasipoisson"
  d_cc <- subset(des, des$variables$.in_cc)
  models <- list(); fits <- list()
  for (aset in spec$analysis$adjustment_sets) {
    terms <- unique(c(x, unlist(aset$covariates)))
    if (!length(terms)) next
    r <- fit_svyglm(d_cc, y, terms, fam, spec, aset$id, aset$label, des$variables)
    models[[length(models) + 1]] <- r$summary; fits[[aset$id]] <- r$fit
    tr(r$summary$call)
  }
  primary_id <- model_spec$primary_set %||% (if (length(spec$analysis$adjustment_sets)) spec$analysis$adjustment_sets[[length(spec$analysis$adjustment_sets)]]$id else NULL)
  prim <- Filter(function(m) identical(m$id, primary_id), models)
  results$primary_model <- if (length(prim)) prim[[1]] else NULL
  results$models <- models
  log(sprintf("Fitted %d models (family %s)", length(models), fam))

  headline_term <- function(msum) {
    if (is.null(msum)) return(NULL)
    et <- exposure_terms(msum, x)
    if (!length(et)) return(NULL)
    et[[length(et)]]
  }
  pe <- NULL
  if (!is.null(x) && !is.null(results$primary_model)) {
    ht <- headline_term(results$primary_model)
    if (!is.null(ht)) pe <- list(effect = results$primary_model$effect, effect_label = results$primary_model$effect_label,
                                 term = ht$term, label = ht$label, est = ht$est, lcl = ht$lcl, ucl = ht$ucl, p = ht$p, n = results$primary_model$n)
  } else if (length(results$prevalence)) {
    ov <- Filter(function(p) p$outcome == y && p$group_var == "Overall", results$prevalence)
    if (length(ov)) pe <- list(effect = "prevalence", effect_label = "Weighted prevalence", term = y, label = ov[[1]]$outcome_label,
                               est = ov[[1]]$est, lcl = ov[[1]]$lcl, ucl = ov[[1]]$ucl, n = ov[[1]]$n, pop_millions = ov[[1]]$pop_millions)
  }
  if (is.null(pe) && identical(spec$outcome$type, "continuous")) {
    dm <- subset(des, des$variables$.in_analytic)
    m <- survey::svymean(stats::as.formula(paste0("~", y)), dm, na.rm = TRUE)
    ci <- stats::confint(m, df = survey::degf(dm))
    pe <- list(effect = "mean", effect_label = "Weighted mean", term = y, label = .var_label(spec, y),
               est = as.numeric(m), lcl = ci[1], ucl = ci[2], n = sum(des$variables$.in_analytic))
  }
  results$primary_estimate <- pe

  # ---- 7. effect modification -----------------------------------------------
  results$interactions <- list()
  if (!is.null(x) && !is.null(primary_id)) {
    full_covs <- unlist(Filter(function(a) identical(a$id, primary_id), spec$analysis$adjustment_sets)[[1]]$covariates)
    for (mod in unlist(spec$analysis$interactions)) {
      if (!mod %in% names(des$variables) || identical(mod, x)) next
      terms <- unique(c(x, setdiff(full_covs, mod), mod, paste0(x, ":", mod)))
      r <- fit_svyglm(d_cc, y, terms, fam, spec, paste0("int_", mod), paste("Interaction with", .var_label(spec, mod)), des$variables)
      p_int <- tryCatch(as.numeric(survey::regTermTest(r$fit, stats::as.formula(paste0("~", x, ":", mod)), df = max(survey::degf(d_cc), 1))$p[1]), error = function(e) NA)
      strata <- list()
      mv <- des$variables[[mod]]
      lv <- if (is.factor(mv)) levels(mv) else sort(unique(stats::na.omit(mv[des$variables$.in_cc])))
      for (l in lv) {
        sel <- des$variables$.in_cc & !is.na(mv) & as.character(mv) == as.character(l)
        if (sum(sel) < 30) next
        ds <- subset(des, sel)
        rs <- fit_svyglm(ds, y, unique(c(x, setdiff(full_covs, mod))), fam, spec, paste0("strat_", mod, "_", l), paste0(.var_label(spec, mod), " = ", l), des$variables)
        ht <- headline_term(rs$summary)
        lab <- if (!is.factor(mv) && all(mv %in% c(0, 1, NA))) ifelse(l == 1, "Yes", "No") else as.character(l)
        if (!is.null(ht)) strata[[length(strata) + 1]] <- list(level = lab, n = rs$summary$n, est = ht$est, lcl = ht$lcl, ucl = ht$ucl, p = ht$p)
      }
      results$interactions[[length(results$interactions) + 1]] <- list(modifier = mod, label = .var_label(spec, mod), p_interaction = p_int, strata = strata)
      tr(sprintf("regTermTest(svyglm(%s ~ ... + %s:%s), ~%s:%s)", y, x, mod, x, mod))
    }
  }

  # ---- 8. sensitivity analyses ------------------------------------------------
  sens <- list()
  base_terms <- if (!is.null(primary_id)) unique(c(x, unlist(Filter(function(a) identical(a$id, primary_id), spec$analysis$adjustment_sets)[[1]]$covariates))) else character(0)
  overall_prev <- function(design, outcome, flag) {
    design$variables$.sflag <- flag
    design$variables$.ind <- as.integer(design$variables[[outcome]] == 1)
    ok <- flag & !is.na(design$variables$.ind)
    r <- .prev_one(subset(design, ok), ".ind", design$variables[ok, , drop = FALSE])
    r
  }
  for (s in spec$analysis$sensitivity) {
    res_s <- tryCatch({
      type <- s$type
      if (type == "exclude" || type == "restrict") {
        v <- .as_lgl(dsl_eval(s$expr, des$variables))
        keep <- if (type == "exclude") !(!is.na(v) & v) else (!is.na(v) & v)
        if (is.null(x)) {
          r <- overall_prev(des, y, des$variables$.in_analytic & keep)
          list(est = r$est, lcl = r$lcl, ucl = r$ucl, n = r$n, effect = "prevalence")
        } else {
          dsx <- subset(des, des$variables$.in_cc & keep)
          rr <- fit_svyglm(dsx, y, base_terms, fam, spec, s$id, s$label, des$variables); ht <- headline_term(rr$summary)
          list(est = ht$est, lcl = ht$lcl, ucl = ht$ucl, n = rr$summary$n, effect = rr$summary$effect)
        }
      } else if (type == "alt_outcome") {
        yo <- s$outcome
        if (is.null(x)) {
          r <- overall_prev(des, yo, des$variables$.in_pop)
          list(est = r$est, lcl = r$lcl, ucl = r$ucl, n = r$n, effect = "prevalence")
        } else {
          fl <- des$variables$.in_cc | (des$variables$.in_pop & !is.na(des$variables[[x]]))
          cc2 <- fl & !is.na(des$variables[[yo]])
          for (cv in base_terms) cc2 <- cc2 & !is.na(des$variables[[cv]])
          rr <- fit_svyglm(subset(des, cc2), yo, base_terms, s$family %||% fam, spec, s$id, s$label, des$variables); ht <- headline_term(rr$summary)
          list(est = ht$est, lcl = ht$lcl, ucl = ht$ucl, n = rr$summary$n, effect = rr$summary$effect)
        }
      } else if (type == "alt_exposure") {
        xe <- s$exposure
        terms2 <- unique(c(xe, setdiff(base_terms, x)))
        cc2 <- des$variables$.in_pop & !is.na(des$variables[[y]]) & !is.na(des$variables[[xe]])
        for (cv in setdiff(base_terms, x)) cc2 <- cc2 & !is.na(des$variables[[cv]])
        rr <- fit_svyglm(subset(des, cc2), y, terms2, fam, spec, s$id, s$label, des$variables)
        et <- Filter(function(t) identical(t$variable, xe), rr$summary$terms)
        ht <- if (length(et)) et[[length(et)]] else NULL
        list(est = ht$est, lcl = ht$lcl, ucl = ht$ucl, n = rr$summary$n, effect = rr$summary$effect, note = ht$label)
      } else if (type == "alt_family") {
        rr <- fit_svyglm(d_cc, y, base_terms, s$family, spec, s$id, s$label, des$variables); ht <- headline_term(rr$summary)
        list(est = ht$est, lcl = ht$lcl, ucl = ht$ucl, n = rr$summary$n, effect = rr$summary$effect)
      } else if (type == "unweighted") {
        cc <- des$variables[des$variables$.in_cc, , drop = FALSE]
        if (is.null(x)) {
          k <- sum(cc[[y]] == 1, na.rm = TRUE); n <- sum(!is.na(cc[[y]]))
          ci <- stats::prop.test(k, n)$conf.int
          list(est = k / n, lcl = ci[1], ucl = ci[2], n = n, effect = "prevalence", note = "Unweighted sample proportion (ignores design)")
        } else {
          fi <- family_info(fam)
          g <- suppressWarnings(stats::glm(stats::as.formula(paste(y, "~", paste(base_terms, collapse = " + "))), data = cc, family = fi$family))
          cf <- summary(g)$coefficients
          rn <- grep(paste0("^", x), rownames(cf), value = TRUE); rn <- rn[length(rn)]
          b <- cf[rn, 1]; se <- cf[rn, 2]
          tf <- if (fi$exp) exp else identity
          list(est = tf(b), lcl = tf(b - 1.96 * se), ucl = tf(b + 1.96 * se), n = nrow(cc), effect = fi$effect, note = "Unweighted GLM (ignores design)")
        }
      } else if (type == "mi") {
        if (is.null(x) || !length(base_terms)) stop("MI applies to regression analyses")
        mi <- fit_mi(des, spec, y, base_terms, fam, m = s$m %||% spec$analysis$missing$m %||% 10, seed = spec$options$seed %||% 2026)
        if (!is.null(mi$error)) stop(mi$error)
        if (!is.null(mi$note)) list(est = pe$est, lcl = pe$lcl, ucl = pe$ucl, n = pe$n, effect = pe$effect, note = mi$note) else {
          ix <- grep(paste0("^", x), mi$names); ix <- ix[length(ix)]
          b <- mi$coef[ix]; se <- mi$se[ix]; tq <- stats::qt(0.975, df = max(mi$df[ix], 3))
          tf <- if (mi$exp) exp else identity
          list(est = tf(b), lcl = tf(b - tq * se), ucl = tf(b + tq * se), n = sum(des$variables$.in_analytic), effect = family_info(fam)$effect,
               note = sprintf("Multiple imputation by chained equations (m = %d; %d rows imputed), Rubin's rules", mi$m, mi$n_imputed_rows))
        }
      } else if (type == "exposure_quartiles") {
        if (is.null(x) || !is.numeric(des$variables[[x]])) stop("Quartile analysis needs a continuous exposure")
        q <- add_quartiles(des, x)
        dq <- subset(q$design, q$design$variables$.in_cc)
        terms_q <- unique(c(q$var, setdiff(base_terms, x)))
        rr <- fit_svyglm(dq, y, terms_q, fam, spec, s$id, s$label, q$design$variables)
        rt <- fit_svyglm(dq, y, unique(c(q$score, setdiff(base_terms, x))), fam, spec, paste0(s$id, "_trend"), "trend", q$design$variables)
        q4 <- Filter(function(t) identical(t$variable, q$var), rr$summary$terms)
        ptrend <- Filter(function(t) identical(t$term, q$score), rt$summary$terms)
        ht <- if (length(q4)) q4[[length(q4)]] else NULL
        list(est = ht$est, lcl = ht$lcl, ucl = ht$ucl, n = rr$summary$n, effect = rr$summary$effect,
             note = sprintf("Highest vs lowest weighted quartile; P for trend %s", if (length(ptrend)) .fmt_p(ptrend[[1]]$p) else "NA"),
             quartile_terms = lapply(q4, function(t) list(label = t$label, est = t$est, lcl = t$lcl, ucl = t$ucl)))
      } else stop("Unknown sensitivity type: ", type)
    }, error = function(e) list(error = conditionMessage(e)))
    sens[[length(sens) + 1]] <- c(list(id = s$id, label = s$label, type = s$type), res_s)
  }
  results$sensitivity <- sens
  log(sprintf("Ran %d sensitivity analyses", length(sens)))

  # ---- 9. E-value ------------------------------------------------------------------
  if (!is.null(pe) && pe$effect %in% c("PR", "OR", "Beta")) {
    yv <- des$variables[[y]][des$variables$.in_cc]
    results$evalue <- e_value(pe$est, pe$lcl, pe$ucl, pe$effect,
                              outcome_prev = if (pe$effect == "OR") mean(yv == 1, na.rm = TRUE) else NA,
                              sd_y = if (pe$effect == "Beta") stats::sd(yv, na.rm = TRUE) else NA)
  }

  # ---- 10. collinearity --------------------------------------------------------------
  results$vif <- if (length(base_terms) > 1) compute_vif(des$variables, base_terms) else list()

  # ---- 11. benchmark against published estimates -----------------------------
  results$benchmarks <- list()
  for (bm in spec$analysis$benchmarks) {
    if (is.null(bm$estimate)) next
    ov <- Filter(function(p) p$outcome == (bm$outcome %||% y) && p$group_var == "Overall", results$prevalence)
    if (!length(ov)) next
    o <- ov[[1]]
    overlap <- !(o$ucl < bm$lcl || o$lcl > bm$ucl)
    results$benchmarks[[length(results$benchmarks) + 1]] <- list(
      outcome = bm$outcome, outcome_label = o$outcome_label, label = bm$label, published = bm$estimate, published_lcl = bm$lcl, published_ucl = bm$ucl,
      published_n = bm$n %||% NA, replicated = o$est, replicated_lcl = o$lcl, replicated_ucl = o$ucl, replicated_n = o$n, overlap = overlap,
      difference_pts = round(100 * (o$est - bm$estimate), 1),
      message = sprintf("%s: Q2E %.1f%% (%.1f-%.1f) vs published %.1f%% (%.1f-%.1f) [%s] - %s", o$outcome_label,
                        100 * o$est, 100 * o$lcl, 100 * o$ucl, 100 * bm$estimate, 100 * bm$lcl, 100 * bm$ucl, bm$label,
                        if (overlap) "confidence intervals overlap (consistent)" else "confidence intervals do not overlap - investigate definitions, population and cycles"))
  }

  # ---- 12. figures -----------------------------------------------------------------
  figs <- list()
  if (requireNamespace("ggplot2", quietly = TRUE)) {
    f1 <- tryCatch(fig_prevalence(results$prevalence, y, outdir, synthetic), error = function(e) { log("prevalence figure: ", conditionMessage(e)); NULL })
    if (!is.null(f1)) figs[[length(figs) + 1]] <- f1
    if (!is.null(pe) && pe$effect %in% c("PR", "OR", "Beta")) {
      rows <- list()
      for (m in models) { ht <- headline_term(m); if (!is.null(ht)) rows[[length(rows) + 1]] <- list(section = "Adjustment", label = m$label, est = ht$est, lcl = ht$lcl, ucl = ht$ucl) }
      for (s in sens) if (!is.null(s$est) && identical(s$effect, pe$effect) && !(s$type %in% c("exposure_quartiles", "alt_exposure"))) rows[[length(rows) + 1]] <- list(section = "Sensitivity", label = s$label, est = s$est, lcl = s$lcl, ucl = s$ucl)
      for (it in results$interactions) for (st in it$strata) rows[[length(rows) + 1]] <- list(section = paste("By", .lc1(it$label)), label = st$level, est = st$est, lcl = st$lcl, ucl = st$ucl)
      f2 <- tryCatch(fig_forest(rows, pe$effect_label, outdir, synthetic, title = paste(pe$label, "and", .lc1(.var_label(spec, y)))),
                     error = function(e) { log("forest figure: ", conditionMessage(e)); NULL })
      if (!is.null(f2)) figs[[length(figs) + 1]] <- f2
    } else if (!is.null(results$primary_model)) {
      rows <- lapply(Filter(function(t) t$term != "(Intercept)", results$primary_model$terms),
                     function(t) if (nzchar(t$level)) list(section = .var_label(spec, t$variable), label = t$level, est = t$est, lcl = t$lcl, ucl = t$ucl)
                                 else list(section = "Clinical factors", label = t$label, est = t$est, lcl = t$lcl, ucl = t$ucl))
      f2 <- tryCatch(fig_forest(rows, results$primary_model$effect_label, outdir, synthetic, file = "fig_correlates.png",
                                title = paste("Adjusted correlates of", .lc1(.var_label(spec, y)))),
                     error = function(e) { log("correlates figure: ", conditionMessage(e)); NULL })
      if (!is.null(f2)) figs[[length(figs) + 1]] <- f2
    }
    dist_var <- if (!is.null(x) && is.numeric(des$variables[[x]])) (spec$exposure$original %||% x) else spec$analysis$distribution_var
    if (!is.null(dist_var)) {
      grp_ok <- function(g) !is.null(g) && g %in% names(des$variables) && (is.factor(des$variables[[g]]) && nlevels(des$variables[[g]]) <= 6 ||
                                                                         all(des$variables[[g]] %in% c(0, 1, NA)))
      grp <- if (!is.null(x) && grp_ok(y)) y else if (grp_ok(spec$analysis$table1_by)) spec$analysis$table1_by else NULL
      f3 <- tryCatch(fig_distribution(des, dist_var, grp, spec, outdir, synthetic),
                     error = function(e) { log("distribution figure: ", conditionMessage(e)); NULL })
      if (!is.null(f3)) figs[[length(figs) + 1]] <- f3
    }
  }
  results$figures <- figs

  # ---- 13. QC checks -----------------------------------------------------------------
  results$derivation_audit <- dv$audit
  results$ranges <- cl$ranges
  results$checks <- run_checks(list(spec = spec, data = dat, results = results, files = ld$files, missing_vars = ld$missing_vars,
                                    ranges = cl$ranges, audit = dv$audit))
  n_fail <- sum(vapply(results$checks, function(c) c$status == "fail", TRUE))
  n_warn <- sum(vapply(results$checks, function(c) c$status == "warn", TRUE))
  log(sprintf("QC: %d checks, %d fail, %d warn", length(results$checks), n_fail, n_warn))

  # ---- 14. provenance ------------------------------------------------------------
  pk <- c("survey", "jsonlite", "ggplot2", "haven", "mice", "mitools")
  results$meta <- list(engine_version = Q2E_ENGINE_VERSION, plan_id = spec$plan_id, plan_hash = spec$plan_hash,
                       r_version = R.version.string, platform = R.version$platform,
                       packages = lapply(setNames(pk, pk), function(p) tryCatch(as.character(utils::packageVersion(p)), error = function(e) NA)),
                       started = format(started, "%Y-%m-%dT%H:%M:%S%z"), finished = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"),
                       seconds = round(as.numeric(difftime(Sys.time(), started, units = "secs")), 1),
                       synthetic = synthetic, files = ld$files, seed = spec$options$seed %||% 2026)
  results$trace <- as.list(trace)
  results$log <- as.list(log_lines)
  writeLines(capture.output(sessionInfo()), file.path(outdir, "sessionInfo.txt"))
  json <- jsonlite::toJSON(results, auto_unbox = TRUE, null = "null", na = "null", digits = 10, pretty = TRUE, force = TRUE)
  writeLines(json, file.path(outdir, "results.json"))
  log("Results written to ", file.path(outdir, "results.json"))
  invisible(results)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  get_arg <- function(flag) { i <- which(args == flag); if (length(i) && i < length(args)) args[i + 1] else NULL }
  plan <- get_arg("--plan"); out <- get_arg("--out")
  if (is.null(plan) || is.null(out)) { cat("Usage: Rscript run_pipeline.R --plan plan.json --out outdir\n"); quit(status = 2) }
  q2e_source_engine()
  probe_mode <- "--probe" %in% args
  status <- tryCatch({ if (probe_mode) run_probe(plan, out) else run_pipeline(plan, out); 0L }, error = function(e) {
    dir.create(out, recursive = TRUE, showWarnings = FALSE)
    msg <- conditionMessage(e)
    writeLines(jsonlite::toJSON(list(error = msg), auto_unbox = TRUE), file.path(out, "error.json"))
    message("ERROR: ", msg); 1L
  })
  quit(status = status)
}
