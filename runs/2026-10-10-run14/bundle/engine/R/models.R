# -----------------------------------------------------------------------------
# Regression models: survey-weighted GLMs (quasi-Poisson -> prevalence ratios,
# quasi-binomial -> odds ratios, Gaussian -> mean differences), adjustment
# sets, effect modification, multiple imputation, E-values.
# -----------------------------------------------------------------------------

family_info <- function(fam) {
  switch(fam,
    quasipoisson = list(family = stats::quasipoisson(link = "log"), effect = "PR", exp = TRUE, label = "Prevalence ratio"),
    quasibinomial = list(family = stats::quasibinomial(link = "logit"), effect = "OR", exp = TRUE, label = "Odds ratio"),
    gaussian = list(family = stats::gaussian(), effect = "Beta", exp = FALSE, label = "Mean difference"),
    stop("Unsupported model family: ", fam))
}

.term_labels <- function(fit, spec, dat) {
  mm_names <- names(stats::coef(fit))
  labs <- character(length(mm_names)); vars <- character(length(mm_names)); lvls <- character(length(mm_names))
  model_vars <- all.vars(stats::formula(fit))[-1]
  for (i in seq_along(mm_names)) {
    nm <- mm_names[i]
    if (nm == "(Intercept)") { labs[i] <- "Intercept"; vars[i] <- "(Intercept)"; next }
    if (grepl(":", nm, fixed = TRUE)) { labs[i] <- paste("Interaction:", nm); vars[i] <- nm; next }
    matched <- FALSE
    for (v in model_vars[order(-nchar(model_vars))]) {
      if (startsWith(nm, v)) {
        lvl <- substring(nm, nchar(v) + 1)
        vl <- .var_label(spec, v)
        if (nzchar(lvl) && is.factor(dat[[v]])) {
          labs[i] <- sprintf("%s: %s (vs %s)", vl, lvl, levels(dat[[v]])[1])
        } else {
          sc <- spec$variables_meta[[v]]$per
          labs[i] <- if (!is.null(sc)) sprintf("%s (per %s)", vl, sc) else vl
        }
        vars[i] <- v; lvls[i] <- lvl; matched <- TRUE; break
      }
    }
    if (!matched) { labs[i] <- nm; vars[i] <- nm }
  }
  list(labels = labs, vars = vars, levels = lvls)
}

# Fit one survey GLM, capturing warnings; returns a serialisable summary + the fit.
fit_svyglm <- function(design, outcome, terms, fam, spec, id, label, data_for_labels) {
  fi <- family_info(fam)
  rhs <- if (length(terms)) paste(terms, collapse = " + ") else "1"
  f <- stats::as.formula(paste(outcome, "~", rhs))
  warn <- character(0)
  y <- design$variables[[outcome]]
  start <- NULL
  if (fam == "quasipoisson") {
    mm <- stats::model.matrix(f, stats::model.frame(f, design$variables))
    pos <- stats::weights(design) > 0
    start <- c(log(max(mean(y[pos], na.rm = TRUE), 1e-4)), rep(0, ncol(mm) - 1))
  }
  fit <- withCallingHandlers(
    tryCatch(survey::svyglm(f, design = design, family = fi$family, start = start),
             error = function(e) { warn <<- c(warn, paste("ERROR:", conditionMessage(e))); NULL }),
    warning = function(w) { warn <<- c(warn, conditionMessage(w)); invokeRestart("muffleWarning") })
  call_txt <- sprintf("svyglm(%s, design = <%s>, family = %s)", deparse1(f), id, fam)
  if (is.null(fit)) return(list(summary = list(id = id, label = label, family = fam, effect = fi$effect, formula = deparse1(f),
                                                call = call_txt, converged = FALSE, warnings = as.list(warn), terms = list()), fit = NULL))
  cf <- summary(fit, df.resid = Inf)$coefficients
  df_r <- fit$df.residual
  # Wald inference on the design degrees of freedom (#PSU - #strata), as recommended
  # for NHANES; residual df (design df - parameters) can be <1 for rich models.
  ddf <- max(survey::degf(design), 1)
  tq <- stats::qt(0.975, df = ddf)
  tl <- .term_labels(fit, spec, data_for_labels)
  terms_out <- list()
  for (i in seq_len(nrow(cf))) {
    b <- cf[i, 1]; se <- cf[i, 2]; p <- 2 * stats::pt(-abs(b / se), df = ddf)
    est <- if (fi$exp) exp(b) else b
    lcl <- if (fi$exp) exp(b - tq * se) else b - tq * se
    ucl <- if (fi$exp) exp(b + tq * se) else b + tq * se
    terms_out[[i]] <- list(term = rownames(cf)[i], variable = tl$vars[i], level = tl$levels[i], label = tl$labels[i],
                           beta = b, se = se, est = est, lcl = lcl, ucl = ucl, p = p)
  }
  n_used <- length(fit$y)
  list(summary = list(id = id, label = label, family = fam, effect = fi$effect, effect_label = fi$label,
                      formula = deparse1(f), call = call_txt, n = n_used,
                      events = if (fam != "gaussian") sum(fit$y == 1) else NA,
                      df_residual = df_r, df_design = ddf, n_params = nrow(cf), converged = isTRUE(fit$converged), warnings = as.list(unique(warn)),
                      dispersion = summary(fit)$dispersion[1], terms = terms_out),
       fit = fit)
}

# Pull the exposure term(s) from a model summary.
exposure_terms <- function(msum, exposure) {
  if (is.null(exposure)) return(list())
  Filter(function(t) identical(t$variable, exposure), msum$terms)
}

# Weighted quartiles of a continuous exposure in the analytic population.
add_quartiles <- function(des, x, pop_flag = ".in_cc") {
  dsub <- subset(des, des$variables[[pop_flag]])
  q <- as.numeric(survey::svyquantile(stats::as.formula(paste0("~", x)), dsub, c(.25, .5, .75), ci = FALSE, na.rm = TRUE)[[1]])
  brks <- c(-Inf, q, Inf)
  qn <- paste0(x, "_q")
  lab <- c(sprintf("Q1 (<%.3g)", q[1]), sprintf("Q2 (%.3g-%.3g)", q[1], q[2]), sprintf("Q3 (%.3g-%.3g)", q[2], q[3]), sprintf("Q4 (>=%.3g)", q[3]))
  des$variables[[qn]] <- cut(des$variables[[x]], breaks = unique(brks), labels = lab[seq_len(length(unique(brks)) - 1)], right = FALSE)
  # median of each quartile for P-trend
  med <- tapply(des$variables[[x]], des$variables[[qn]], stats::median, na.rm = TRUE)
  des$variables[[paste0(qn, "_score")]] <- as.numeric(med[as.character(des$variables[[qn]])])
  list(design = des, var = qn, score = paste0(qn, "_score"), cutpoints = q)
}

# E-value (VanderWeele & Ding 2017) for a ratio estimate and its CI.
e_value <- function(est, lcl, ucl, effect, outcome_prev = NA, sd_y = NA) {
  conv <- function(x) {
    if (is.na(x)) return(NA)
    if (effect == "OR" && !is.na(outcome_prev) && outcome_prev > 0.15) return(sqrt(x))
    if (effect == "Beta") return(if (!is.na(sd_y) && sd_y > 0) exp(0.91 * x / sd_y) else NA)
    x
  }
  rr <- conv(est); lo <- conv(lcl); hi <- conv(ucl)
  if (is.na(rr)) return(NULL)
  ev <- function(r) { if (is.na(r)) return(NA); if (r < 1) r <- 1 / r; r + sqrt(r * (r - 1)) }
  ci_lim <- if (rr >= 1) lo else hi
  ev_ci <- if (is.na(ci_lim)) NA else if ((rr >= 1 && ci_lim <= 1) || (rr < 1 && ci_lim >= 1)) 1 else ev(ci_lim)
  list(point = ev(rr), ci = ev_ci, rr_scale = rr,
       note = switch(effect, OR = if (!is.na(outcome_prev) && outcome_prev > 0.15) "OR converted to RR by square root (common outcome)" else "Rare outcome: OR approximates RR",
                     Beta = "Mean difference converted via standardized effect (RR ~ exp(0.91 d))", "Prevalence ratio used directly"))
}

# Multiple imputation of covariates (outcome and exposure are complete by design
# of the analytic population). Imputation is performed within the analytic
# population and then embedded back into the full design so subpopulation
# variance estimation is preserved.
fit_mi <- function(des, spec, outcome, terms, fam, m = 10, seed = 2026) {
  if (!requireNamespace("mice", quietly = TRUE) || !requireNamespace("mitools", quietly = TRUE)) {
    return(list(error = "Packages 'mice' and 'mitools' are required for multiple imputation"))
  }
  vars <- unique(c(outcome, all.vars(stats::as.formula(paste("~", paste(terms, collapse = "+"))))))
  idx <- which(des$variables$.in_analytic)
  sub <- des$variables[idx, vars, drop = FALSE]
  for (v in names(sub)) if (is.integer(sub[[v]]) && all(sub[[v]] %in% c(0L, 1L, NA))) sub[[v]] <- factor(sub[[v]], levels = c(0, 1))
  n_inc <- sum(!stats::complete.cases(sub))
  if (n_inc == 0) return(list(note = "No missing covariate data; multiple imputation not needed", n_imputed_rows = 0))
  set.seed(seed)
  imp <- tryCatch(mice::mice(sub, m = m, printFlag = FALSE, seed = seed), error = function(e) e)
  if (inherits(imp, "error")) return(list(error = paste("mice failed:", conditionMessage(imp))))
  fi <- family_info(fam)
  coefs <- list(); vcovs <- list()
  for (i in seq_len(m)) {
    comp <- mice::complete(imp, i)
    d_i <- des
    for (v in vars) {
      val <- comp[[v]]
      if (is.factor(val) && !is.factor(des$variables[[v]])) val <- as.integer(as.character(val))
      d_i$variables[[v]][idx] <- val
    }
    d_i$variables$.in_mi <- seq_len(nrow(d_i$variables)) %in% idx
    dsub <- subset(d_i, d_i$variables$.in_mi)
    f <- stats::as.formula(paste(outcome, "~", paste(terms, collapse = " + ")))
    start <- NULL
    if (fam == "quasipoisson") {
      mm <- stats::model.matrix(f, stats::model.frame(f, dsub$variables))
      start <- c(log(max(mean(dsub$variables[[outcome]][dsub$variables$.in_mi], na.rm = TRUE), 1e-4)), rep(0, ncol(mm) - 1))
    }
    fit <- suppressWarnings(survey::svyglm(f, design = dsub, family = fi$family, start = start))
    coefs[[i]] <- stats::coef(fit); vcovs[[i]] <- stats::vcov(fit)
  }
  comb <- mitools::MIcombine(coefs, vcovs)
  s <- summary(comb)
  list(coef = stats::coef(comb), se = sqrt(diag(stats::vcov(comb))), df = comb$df,
       names = names(stats::coef(comb)), n_imputed_rows = n_inc, m = m, exp = fi$exp,
       missing_by_var = as.list(colSums(is.na(sub))))
}
