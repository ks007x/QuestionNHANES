# -----------------------------------------------------------------------------
# Age-adjusted (directly age-standardized) prevalence and means, as NCHS reports them.
#
# Direct standardization to the 2000 projected U.S. population (NCHS age groups 20-39, 40-59, 60+, or 18-39 for
# adults 18+): survey::svystandardize() reweights the analytic domain so each age group carries its share of the
# standard population, separately within each comparison group (`over`). Estimates for age groups themselves are
# not adjusted. Confidence intervals: Korn-Graubard (beta) for proportions, as for crude estimates.
# -----------------------------------------------------------------------------

.agestd_factor <- function(age, bands) {
  lo <- vapply(bands, function(b) as.numeric(b$lo), 0)
  hi <- vapply(bands, function(b) if (is.null(b$hi)) Inf else as.numeric(b$hi), 0)
  lab <- vapply(bands, function(b) b$label, "")
  out <- rep(NA_character_, length(age))
  for (i in seq_along(lo)) out[!is.na(age) & age >= lo[i] & age <= hi[i]] <- lab[i]
  factor(out, levels = lab)
}

# Age-adjusted estimate for indicator/continuous column `col` in domain `sel`, optionally within `over` groups.
.std_one <- function(des, col, sel, cfg, over = NULL, binary = TRUE) {
  des$variables$.std_sel <- sel & !is.na(des$variables[[col]]) & !is.na(des$variables$.agestd)
  if (!is.null(over)) des$variables$.std_sel <- des$variables$.std_sel & !is.na(des$variables[[over]])
  d <- subset(des, .std_sel)
  if (sum(des$variables$.std_sel) < 2) return(list())
  pops <- vapply(cfg$bands, function(b) as.numeric(b$population), 0)
  # every group needs every age band, otherwise the standard cannot be applied
  present <- if (is.null(over)) list(all = unique(stats::na.omit(as.character(des$variables$.agestd[des$variables$.std_sel])))) else
    tapply(as.character(des$variables$.agestd[des$variables$.std_sel]), as.character(des$variables[[over]][des$variables$.std_sel]), unique)
  ok_groups <- names(present)[vapply(present, function(p) all(levels(des$variables$.agestd) %in% p), TRUE)]
  if (!length(ok_groups)) return(list())
  if (!is.null(over)) {
    des$variables$.std_sel <- des$variables$.std_sel & as.character(des$variables[[over]]) %in% ok_groups
    d <- subset(des, .std_sel)
  }
  ds <- survey::svystandardize(d, by = ~.agestd, over = if (is.null(over)) ~1 else stats::as.formula(paste0("~", over)), population = pops)
  f <- stats::as.formula(paste0("~", col))
  ddf <- max(survey::degf(d), 1)
  groups <- if (is.null(over)) "Overall" else ok_groups
  out <- list()
  for (g in groups) {
    dg <- if (is.null(over)) ds else subset(ds, as.character(ds$variables[[over]]) == g)
    if (binary) {
      ci <- tryCatch(survey::svyciprop(f, dg, method = "beta", df = ddf), error = function(e) NULL)
      if (is.null(ci)) next
      est <- as.numeric(ci); lims <- as.numeric(attr(ci, "ci"))
      se <- as.numeric(survey::SE(survey::svymean(f, dg)))
    } else {
      m <- survey::svymean(f, dg)
      est <- as.numeric(m); se <- as.numeric(survey::SE(m)); tq <- stats::qt(0.975, ddf); lims <- c(est - tq * se, est + tq * se)
    }
    out[[g]] <- list(adj_est = est, adj_lcl = lims[1], adj_ucl = lims[2], adj_se = se)
  }
  out
}

# Adds adj_* fields to crude prevalence entries (overall and by every non-age subgroup).
add_age_adjusted <- function(prev, des, spec, pop_flag = ".in_analytic") {
  cfg <- spec$analysis$age_adjust
  if (is.null(cfg) || !isTRUE(cfg$enabled) || !length(prev)) return(prev)
  age_var <- cfg$age_var %||% "age"
  if (!age_var %in% names(des$variables)) return(prev)
  des$variables$.agestd <- .agestd_factor(des$variables[[age_var]], cfg$bands)
  skip_by <- unlist(cfg$not_by) %||% character(0)
  done <- list()
  for (i in seq_along(prev)) {
    p <- prev[[i]]
    if (p$group_var %in% skip_by) next
    yv <- des$variables[[p$outcome]]
    col <- if (is.na(p$outcome_level %||% NA)) ".std_ind" else ".std_ind"
    des$variables$.std_ind <- if (is.na(p$outcome_level %||% NA)) as.integer(yv == 1) else as.integer(as.character(yv) == p$outcome_level)
    key <- paste(p$outcome, p$outcome_level %||% "", p$group_var, sep = "|")
    if (is.null(done[[key]])) {
      done[[key]] <- tryCatch(.std_one(des, ".std_ind", des$variables[[pop_flag]], cfg,
                                       over = if (identical(p$group_var, "Overall")) NULL else p$group_var),
                              error = function(e) list(.error = conditionMessage(e)))
    }
    res <- done[[key]]
    g <- if (identical(p$group_var, "Overall")) "Overall" else {
      gv <- des$variables[[p$group_var]]
      if (!is.factor(gv) && all(gv %in% c(0, 1, NA))) (if (identical(p$group, "Yes")) "1" else "0") else as.character(p$group)
    }
    if (!is.null(res[[g]])) prev[[i]] <- c(p, res[[g]], list(adj_standard = cfg$standard))
  }
  prev
}

# Age-adjusted mean of a continuous outcome (overall and by subgroup), for the descriptive "mean" estimand.
age_adjusted_means <- function(des, spec, y, by_vars, pop_flag = ".in_analytic") {
  cfg <- spec$analysis$age_adjust
  if (is.null(cfg) || !isTRUE(cfg$enabled)) return(list())
  des$variables$.agestd <- .agestd_factor(des$variables[[cfg$age_var %||% "age"]], cfg$bands)
  out <- list()
  r <- .std_one(des, y, des$variables[[pop_flag]], cfg, NULL, binary = FALSE)
  if (length(r)) out[[1]] <- c(list(group_var = "Overall", group = "Overall"), r[["Overall"]])
  for (g in by_vars) {
    if (g %in% (unlist(cfg$not_by) %||% character(0)) || !g %in% names(des$variables)) next
    r <- .std_one(des, y, des$variables[[pop_flag]], cfg, g, binary = FALSE)
    for (lv in names(r)) out[[length(out) + 1]] <- c(list(group_var = g, group = lv), r[[lv]])
  }
  out
}
