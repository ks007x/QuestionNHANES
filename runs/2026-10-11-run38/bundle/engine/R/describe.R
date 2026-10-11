# -----------------------------------------------------------------------------
# Descriptive statistics: survey-weighted Table 1 and prevalence estimates with
# Korn-Graubard (beta) confidence intervals and NCHS presentation standards.
# -----------------------------------------------------------------------------

# NCHS Data Presentation Standards for Proportions (Parker et al., Vital Health
# Stat 2(175), 2017).
nchs_flag <- function(p, lcl, ucl, n_eff, df) {
  if (is.na(p)) return("not estimable")
  if (p == 0 || p == 1) return("review: estimate of 0% or 100% (report with upper/lower bound)")
  w <- ucl - lcl
  if (!is.na(n_eff) && n_eff < 30) return("suppress: effective n < 30")
  if (!is.na(w) && w >= 0.30) return("suppress: CI width >= 30 points")
  if (!is.na(w) && w > 0.05 && p > 0) {
    rel <- w / p
    if (rel > 1.30) return("suppress: relative CI width > 130%")
  }
  if (!is.na(df) && df < 8) return("review: df < 8")
  "meets standard"
}

.subset_df <- function(dat_sub) {
  if (nrow(dat_sub) == 0) return(0)
  nrow(unique(dat_sub[, c(".strata", ".psu")])) - length(unique(dat_sub$.strata))
}

.var_label <- function(spec, v) {
  m <- spec$variables_meta[[v]]
  if (!is.null(m) && !is.null(m$label)) m$label else v
}

# One prevalence estimate for logical indicator `ind` (column name) within design d.
.prev_one <- function(d, ind, dat_sub) {
  f <- stats::as.formula(paste0("~", ind))
  ci <- tryCatch(survey::svyciprop(f, d, method = "beta", na.rm = TRUE), error = function(e) NULL)
  mn <- tryCatch(survey::svymean(f, d, na.rm = TRUE), error = function(e) NULL)
  tot <- tryCatch(survey::svytotal(f, d, na.rm = TRUE), error = function(e) NULL)
  if (is.null(ci) || is.null(mn)) return(NULL)
  p <- as.numeric(ci)
  lims <- as.numeric(attr(ci, "ci"))
  n_raw <- sum(!is.na(dat_sub[[ind]])); k_raw <- sum(dat_sub[[ind]] == 1, na.rm = TRUE)
  if (k_raw == 0 || is.na(lims[1])) lims[1] <- if (k_raw == 0) 0 else lims[1]
  if (k_raw == 0 || is.na(lims[2])) lims[2] <- 1 - 0.025^(1 / max(n_raw, 1))   # exact upper bound when no events
  if (k_raw == n_raw && n_raw > 0) { lims[1] <- 0.025^(1 / n_raw); lims[2] <- 1 }
  se <- as.numeric(survey::SE(mn))[1]
  n <- sum(!is.na(dat_sub[[ind]]))
  n_eff <- if (!is.na(se) && se > 0) p * (1 - p) / se^2 else NA
  df_sub <- .subset_df(dat_sub)
  list(est = p, lcl = lims[1], ucl = lims[2], se = se, n = n,
       events = sum(dat_sub[[ind]] == 1, na.rm = TRUE),
       n_eff = if (is.na(n_eff)) NA else min(n_eff, n), df = df_sub,
       pop_millions = if (!is.null(tot)) round(as.numeric(tot)[1] / 1e6, 2) else NA,
       nchs = nchs_flag(p, lims[1], lims[2], if (is.na(n_eff)) NA else min(n_eff, n), df_sub))
}

prevalence_estimates <- function(des, dat, spec, outcome_names, by_vars, pop_flag = ".in_analytic") {
  out <- list()
  for (y in outcome_names) {
    if (!y %in% names(des$variables)) next
    yv <- des$variables[[y]]
    if (is.factor(yv)) {
      indicators <- lapply(levels(yv), function(l) list(col = paste0(".ind_", make.names(y), "_", make.names(l)),
                                                       val = as.integer(as.character(yv) == l), level = l))
    } else {
      indicators <- list(list(col = paste0(".ind_", make.names(y)), val = as.integer(yv == 1), level = NA))
    }
    for (ind in indicators) {
      des$variables[[ind$col]] <- ind$val
      dsub <- subset(des, des$variables[[pop_flag]] & !is.na(des$variables[[ind$col]]))
      raw_sub <- des$variables[des$variables[[pop_flag]] & !is.na(des$variables[[ind$col]]), , drop = FALSE]
      r <- .prev_one(dsub, ind$col, raw_sub)
      if (!is.null(r)) out[[length(out) + 1]] <- c(list(outcome = y, outcome_label = .var_label(spec, y), outcome_level = ind$level,
                                                         group_var = "Overall", group_label = "Overall", group = "Overall"), r)
      for (g in by_vars) {
        if (!g %in% names(des$variables) || identical(g, y)) next
        gv <- des$variables[[g]]
        lv <- if (is.factor(gv)) levels(gv) else sort(unique(stats::na.omit(gv)))
        for (l in lv) {
          sel <- des$variables[[pop_flag]] & !is.na(des$variables[[ind$col]]) & !is.na(gv) & as.character(gv) == as.character(l)
          if (sum(sel) == 0) next
          dsub <- subset(des, sel)
          raw_sub <- des$variables[sel, , drop = FALSE]
          r <- .prev_one(dsub, ind$col, raw_sub)
          glabel <- if (!is.factor(gv) && all(gv %in% c(0, 1, NA))) ifelse(l == 1, "Yes", "No") else as.character(l)
          if (!is.null(r)) out[[length(out) + 1]] <- c(list(outcome = y, outcome_label = .var_label(spec, y), outcome_level = ind$level,
                                                             group_var = g, group_label = .var_label(spec, g), group = glabel), r)
        }
      }
    }
  }
  out
}

.fmt_num <- function(x, digits = 1) formatC(x, format = "f", digits = digits, big.mark = ",")
.fmt_p <- function(p) {
  if (is.null(p) || is.na(p)) return("")
  if (p < 0.001) return("<.001")
  sub("^0", "", formatC(p, format = "f", digits = if (p < 0.01) 3 else 2))
}

# Survey-weighted Table 1: rows = variables, columns = levels of `by` + Overall.
table_one <- function(des, dat, spec, vars, by) {
  d_an <- subset(des, des$variables$.in_analytic)
  an <- des$variables[des$variables$.in_analytic, , drop = FALSE]
  if (!is.null(by) && by %in% names(an)) {
    bv <- an[[by]]
    if (!is.factor(bv)) {
      lbl <- c("0" = "No", "1" = "Yes")
      groups <- sort(unique(stats::na.omit(bv)))
      glabels <- if (all(groups %in% c(0, 1))) unname(lbl[as.character(groups)]) else as.character(groups)
    } else { groups <- levels(bv); glabels <- groups }
  } else { by <- NULL; groups <- character(0); glabels <- character(0) }

  col_defs <- list()
  for (i in seq_along(groups)) {
    sel <- !is.na(an[[by]]) & as.character(an[[by]]) == as.character(groups[i])
    col_defs[[i]] <- list(key = paste0("g", i), label = glabels[i], n = sum(sel),
                          weighted_pct = round(100 * sum(an$.wt[sel]) / sum(an$.wt), 1))
  }
  col_defs[[length(col_defs) + 1]] <- list(key = "overall", label = "Overall", n = nrow(an), weighted_pct = 100)

  dsub_for <- function(i) {
    if (i > length(groups)) return(list(d = d_an, raw = an))
    sel_full <- des$variables$.in_analytic & !is.na(des$variables[[by]]) & as.character(des$variables[[by]]) == as.character(groups[i])
    list(d = subset(des, sel_full), raw = des$variables[sel_full, , drop = FALSE])
  }
  subs <- lapply(seq_along(col_defs), dsub_for)

  rows <- list()
  for (v in vars) {
    if (!v %in% names(an) || identical(v, by)) next
    x <- an[[v]]
    meta <- spec$variables_meta[[v]]
    vtype <- if (is.factor(x)) "categorical" else if (all(x %in% c(0, 1, NA))) "binary" else "continuous"
    pval <- NA
    if (!is.null(by)) {
      pval <- tryCatch({
        if (vtype == "continuous") {
          fit <- survey::svyglm(stats::as.formula(paste0(v, " ~ factor(", by, ")")), design = d_an)
          survey::regTermTest(fit, stats::as.formula(paste0("~factor(", by, ")")))$p[1]
        } else {
          survey::svychisq(stats::as.formula(paste0("~", v, " + ", by)), d_an, statistic = "F")$p.value[[1]]
        }
      }, error = function(e) NA)
    }
    label <- .var_label(spec, v)
    units <- if (!is.null(meta$units) && nzchar(meta$units)) paste0(", ", meta$units) else ""
    if (vtype == "continuous") {
      vals <- list()
      for (j in seq_along(col_defs)) {
        s <- subs[[j]]
        m <- tryCatch(survey::svymean(stats::as.formula(paste0("~", v)), s$d, na.rm = TRUE), error = function(e) NULL)
        q <- tryCatch(survey::svyquantile(stats::as.formula(paste0("~", v)), s$d, c(.25, .5, .75), na.rm = TRUE, ci = FALSE),
                      error = function(e) NULL)
        qq <- if (!is.null(q)) as.numeric(q[[1]]) else rep(NA, 3)
        vals[[col_defs[[j]]$key]] <- list(
          text = if (!is.null(m)) sprintf("%s (%s)", .fmt_num(as.numeric(m)), .fmt_num(as.numeric(survey::SE(m)), 2)) else "",
          median_iqr = sprintf("%s (%s-%s)", .fmt_num(qq[2]), .fmt_num(qq[1]), .fmt_num(qq[3])),
          n_missing = sum(is.na(s$raw[[v]])))
      }
      rows[[length(rows) + 1]] <- list(variable = v, label = paste0(label, units, ", mean (SE)"), level = NULL, type = vtype,
                                       values = vals, p = pval, p_text = .fmt_p(pval), header = TRUE)
    } else {
      levs <- if (vtype == "binary") list(list(lab = NULL, val = 1)) else lapply(levels(x), function(l) list(lab = l, val = l))
      if (vtype == "categorical") rows[[length(rows) + 1]] <- list(variable = v, label = paste0(label, ", No. (weighted %)"), level = NULL,
                                                                   type = vtype, values = list(), p = pval, p_text = .fmt_p(pval), header = TRUE)
      for (lv in levs) {
        vals <- list()
        for (j in seq_along(col_defs)) {
          s <- subs[[j]]
          xv <- s$raw[[v]]
          hit <- !is.na(xv) & as.character(xv) == as.character(lv$val)
          nn <- sum(hit)
          denom_w <- sum(s$raw$.wt[!is.na(xv)])
          pct <- if (denom_w > 0) 100 * sum(s$raw$.wt[hit]) / denom_w else NA
          vals[[col_defs[[j]]$key]] <- list(text = sprintf("%s (%s)", format(nn, big.mark = ","), .fmt_num(pct)),
                                            n = nn, pct = pct, n_missing = sum(is.na(xv)))
        }
        if (vtype == "binary") {
          rows[[length(rows) + 1]] <- list(variable = v, label = paste0(label, ", No. (weighted %)"), level = NULL, type = vtype,
                                           values = vals, p = pval, p_text = .fmt_p(pval), header = TRUE)
        } else {
          rows[[length(rows) + 1]] <- list(variable = v, label = lv$lab, level = lv$lab, type = vtype,
                                           values = vals, p = NA, p_text = "", header = FALSE)
        }
      }
    }
  }
  list(by = by, by_label = if (!is.null(by)) .var_label(spec, by) else NULL, columns = col_defs, rows = rows,
       note = "Counts are unweighted; percentages, means and SEs are survey weighted. P values: design-based Wald F test (continuous) or Rao-Scott F test (categorical).")
}
