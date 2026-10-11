# -----------------------------------------------------------------------------
# Descriptive estimands beyond a single prevalence:
#   * trends across survey cycles: per-cycle crude and age-adjusted estimates, change first -> last cycle,
#     and a test for linear trend (survey-weighted regression on cycle order, age groups as covariates when
#     age-adjusting - the NCHS approach);
#   * means, medians and percentiles of a measurement, overall and by subgroup (age-adjusted means too);
#   * weighted population counts with confidence intervals.
# -----------------------------------------------------------------------------

.cycle_order <- function(spec) unlist(spec$analysis$trend$cycles)

trend_estimates <- function(des, spec, y, binary = TRUE, by = "sex", pop_flag = ".in_analytic") {
  tc <- spec$analysis$trend
  if (is.null(tc) || !isTRUE(tc$enabled)) return(NULL)
  cyc <- .cycle_order(spec)
  cfg <- spec$analysis$age_adjust
  adj <- !is.null(cfg) && isTRUE(cfg$enabled)
  v <- des$variables
  des$variables$.ty <- if (binary) as.integer(v[[y]] == 1) else as.numeric(v[[y]])
  des$variables$.tc <- factor(v$.cycle, levels = cyc)
  des$variables$.tper <- match(as.character(v$.cycle), cyc) - 1
  if (adj) des$variables$.agestd <- .agestd_factor(v[[cfg$age_var %||% "age"]], cfg$bands)
  sel <- des$variables[[pop_flag]] & !is.na(des$variables$.ty) & !is.na(des$variables$.tc) & (if (adj) !is.na(des$variables$.agestd) else TRUE)
  groups <- list(list(var = NULL, level = "Overall"))
  if (!is.null(by) && by %in% names(v)) for (l in levels(factor(v[[by]]))) groups[[length(groups) + 1]] <- list(var = by, level = l)
  f <- ~.ty
  rows <- list(); tests <- list()
  for (g in groups) {
    gs <- sel & (if (is.null(g$var)) TRUE else (!is.na(des$variables[[g$var]]) & as.character(des$variables[[g$var]]) == g$level))
    des$variables$.tsel <- gs
    d <- subset(des, .tsel)
    ddf <- max(survey::degf(d), 1)
    present <- table(as.character(des$variables$.tc[gs]))
    cy_ok <- cyc[cyc %in% names(present)[present > 0]]
    for (cy in cy_ok) {
      dc <- subset(d, as.character(.tc) == cy)
      crude <- if (binary) tryCatch(survey::svyciprop(f, dc, method = "beta"), error = function(e) NULL) else survey::svymean(f, dc)
      row <- list(cycle = cy, group_var = g$var %||% "Overall", group = g$level, n = sum(gs & as.character(des$variables$.tc) == cy))
      if (!is.null(crude)) {
        row$est <- as.numeric(crude)
        row$lcl <- if (binary) as.numeric(attr(crude, "ci"))[1] else as.numeric(crude) - stats::qt(0.975, ddf) * as.numeric(survey::SE(crude))
        row$ucl <- if (binary) as.numeric(attr(crude, "ci"))[2] else as.numeric(crude) + stats::qt(0.975, ddf) * as.numeric(survey::SE(crude))
      }
      rows[[length(rows) + 1]] <- row
    }
    if (adj) {
      pops <- vapply(cfg$bands, function(b) as.numeric(b$population), 0)
      ds <- tryCatch(survey::svystandardize(d, by = ~.agestd, over = ~.tc, population = pops), error = function(e) NULL)
      if (!is.null(ds)) {
        for (cy in cy_ok) {
          dc <- subset(ds, as.character(.tc) == cy)
          a <- if (binary) tryCatch(survey::svyciprop(f, dc, method = "beta", df = ddf), error = function(e) NULL) else survey::svymean(f, dc)
          if (is.null(a)) next
          i <- which(vapply(rows, function(r) identical(r$cycle, cy) && identical(r$group, g$level) && identical(r$group_var, g$var %||% "Overall"), TRUE))
          if (!length(i)) next
          se <- as.numeric(survey::SE(survey::svymean(f, dc)))
          rows[[i]]$adj_est <- as.numeric(a); rows[[i]]$adj_se <- se
          lims <- if (binary) as.numeric(attr(a, "ci")) else as.numeric(a) + c(-1, 1) * stats::qt(0.975, ddf) * se
          rows[[i]]$adj_lcl <- lims[1]; rows[[i]]$adj_ucl <- lims[2]
        }
      }
    }
    # test for linear trend over survey cycles (equal spacing; age groups as covariates when age-adjusting)
    form <- stats::as.formula(paste(".ty ~ .tper", if (adj) "+ .agestd" else ""))
    fit <- tryCatch(survey::svyglm(form, design = d, family = if (binary) stats::quasibinomial() else stats::gaussian()), error = function(e) NULL)
    p_lin <- if (!is.null(fit)) tryCatch(as.numeric(survey::regTermTest(fit, ~.tper, df = ddf)$p), error = function(e) NA) else NA
    # change from the first to the last cycle (age-adjusted when available)
    first <- Filter(function(r) identical(r$cycle, cy_ok[1]) && identical(r$group, g$level), rows)[[1]]
    last <- Filter(function(r) identical(r$cycle, cy_ok[length(cy_ok)]) && identical(r$group, g$level), rows)[[1]]
    key <- if (adj && !is.null(first$adj_est) && !is.null(last$adj_est)) "adj_" else ""
    e1 <- first[[paste0(key, "est")]]; e2 <- last[[paste0(key, "est")]]
    se1 <- if (key == "adj_") first$adj_se else (first$ucl - first$lcl) / (2 * 1.96)
    se2 <- if (key == "adj_") last$adj_se else (last$ucl - last$lcl) / (2 * 1.96)
    diff <- e2 - e1; sed <- sqrt(se1^2 + se2^2)                    # independent samples in different cycles
    tests[[length(tests) + 1]] <- list(group_var = g$var %||% "Overall", group = g$level, first_cycle = cy_ok[1], last_cycle = cy_ok[length(cy_ok)],
                                       change = diff, change_lcl = diff - 1.96 * sed, change_ucl = diff + 1.96 * sed,
                                       p_change = 2 * stats::pnorm(-abs(diff / sed)), p_linear_trend = p_lin,
                                       basis = if (key == "adj_") "age-adjusted" else "crude", n_cycles = length(cy_ok))
  }
  list(rows = rows, tests = tests, cycles = cyc, age_adjusted = adj, binary = binary)
}

# Means, medians and percentiles of a continuous measurement.
mean_estimates <- function(des, spec, y, by_vars, pop_flag = ".in_analytic", probs = c(0.05, 0.25, 0.5, 0.75, 0.95)) {
  if (!is.null(spec$analysis$percentile)) probs <- sort(unique(c(probs, as.numeric(spec$analysis$percentile))))
  out <- list()
  f <- stats::as.formula(paste0("~", y))
  one <- function(d, gv, g, n) {
    m <- survey::svymean(f, d, na.rm = TRUE); ddf <- max(survey::degf(d), 1); tq <- stats::qt(0.975, ddf)
    q <- tryCatch(survey::svyquantile(f, d, probs, ci = TRUE, na.rm = TRUE)[[1]], error = function(e) NULL)
    qs <- if (!is.null(q)) lapply(seq_along(probs), function(i) list(p = probs[i], est = unname(q[i, 1]), lcl = unname(q[i, 2]), ucl = unname(q[i, 3]))) else list()
    list(group_var = gv, group = g, n = n, mean = as.numeric(m), mean_lcl = as.numeric(m) - tq * as.numeric(survey::SE(m)),
         mean_ucl = as.numeric(m) + tq * as.numeric(survey::SE(m)), se = as.numeric(survey::SE(m)), quantiles = qs)
  }
  sel <- des$variables[[pop_flag]] & !is.na(des$variables[[y]])
  des$variables$.msel <- sel
  out[[1]] <- one(subset(des, .msel), "Overall", "Overall", sum(sel))
  for (gname in by_vars) {
    if (!gname %in% names(des$variables) || identical(gname, y)) next
    gv <- des$variables[[gname]]
    for (l in (if (is.factor(gv)) levels(gv) else sort(unique(stats::na.omit(gv))))) {
      s2 <- sel & !is.na(gv) & as.character(gv) == as.character(l)
      if (sum(s2) < 2) next
      des$variables$.msel <- s2
      out[[length(out) + 1]] <- one(subset(des, .msel), gname, as.character(l), sum(s2))
    }
  }
  adj <- tryCatch(age_adjusted_means(des, spec, y, by_vars, pop_flag), error = function(e) list())
  for (a in adj) {
    i <- which(vapply(out, function(o) identical(o$group_var, a$group_var) && identical(as.character(o$group), as.character(a$group)), TRUE))
    if (length(i)) out[[i[1]]] <- c(out[[i[1]]], a[c("adj_est", "adj_lcl", "adj_ucl", "adj_se")])
  }
  out
}

# Weighted number of people (millions) with 95% CI, for "how many Americans" questions.
count_estimate <- function(des, col, sel) {
  des$variables$.csel <- sel & !is.na(des$variables[[col]])
  d <- subset(des, .csel)
  t <- survey::svytotal(stats::as.formula(paste0("~", col)), d, na.rm = TRUE)
  ci <- stats::confint(t, df = max(survey::degf(d), 1))
  list(millions = as.numeric(t) / 1e6, lcl = ci[1] / 1e6, ucl = ci[2] / 1e6)
}

# Group comparison (e.g. women vs men, Non-Hispanic Black vs Non-Hispanic White): each level against the
# reference level as a difference (percentage points or units) and a ratio, crude and age-adjusted, with a
# design-based test of any difference across all levels.
comparison_estimates <- function(des, spec, y, g, ref = NULL, binary = TRUE, pop_flag = ".in_analytic") {
  v <- des$variables
  if (!g %in% names(v)) return(NULL)
  des$variables$.cy <- if (binary) as.integer(v[[y]] == 1) else as.numeric(v[[y]])
  des$variables$.cg <- droplevels(factor(v[[g]]))
  sel <- des$variables[[pop_flag]] & !is.na(des$variables$.cy) & !is.na(des$variables$.cg)
  des$variables$.csel2 <- sel
  d <- subset(des, .csel2)
  lv <- levels(droplevels(des$variables$.cg[sel]))
  if (length(lv) < 2) return(NULL)
  ref <- if (!is.null(ref) && ref %in% lv) ref else lv[1]
  ddf <- max(survey::degf(d), 1); tq <- stats::qt(0.975, ddf)
  contrasts_for <- function(design, basis) {
    est <- survey::svyby(~.cy, ~.cg, design, survey::svymean, na.rm = TRUE)
    nm <- as.character(est$.cg); co <- stats::coef(est); vc <- stats::vcov(est)
    out <- list()
    for (l in setdiff(nm, ref)) {
      w <- setNames(rep(0, length(nm)), nm); w[l] <- 1; w[ref] <- -1
      dif <- sum(w * co); se <- sqrt(as.numeric(t(w) %*% vc %*% w))
      out[[length(out) + 1]] <- list(level = l, reference = ref, basis = basis, est_level = unname(co[l]), est_ref = unname(co[ref]),
                                     difference = dif, diff_lcl = dif - tq * se, diff_ucl = dif + tq * se, p = 2 * stats::pt(-abs(dif / se), ddf),
                                     ratio = if (co[ref] > 0) unname(co[l] / co[ref]) else NA)
    }
    out
  }
  res <- contrasts_for(d, "crude")
  cfg <- spec$analysis$age_adjust
  if (!is.null(cfg) && isTRUE(cfg$enabled) && !g %in% (unlist(cfg$not_by) %||% character(0))) {
    des$variables$.agestd <- .agestd_factor(v[[cfg$age_var %||% "age"]], cfg$bands)
    des$variables$.csel2 <- sel & !is.na(des$variables$.agestd)
    d2 <- subset(des, .csel2)
    pops <- vapply(cfg$bands, function(b) as.numeric(b$population), 0)
    ds <- tryCatch(survey::svystandardize(d2, by = ~.agestd, over = ~.cg, population = pops), error = function(e) NULL)
    if (!is.null(ds)) res <- c(res, tryCatch(contrasts_for(ds, "age-adjusted"), error = function(e) list()))
  }
  p_global <- tryCatch(if (binary) as.numeric(survey::svychisq(~.cy + .cg, d)$p.value) else
                         as.numeric(survey::regTermTest(survey::svyglm(.cy ~ .cg, d), ~.cg)$p), error = function(e) NA)
  list(group_var = g, group_label = .var_label(spec, g), reference = ref, levels = as.list(lv), contrasts = res,
       p_any_difference = p_global, binary = binary)
}
