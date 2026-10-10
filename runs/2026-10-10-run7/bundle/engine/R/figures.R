# -----------------------------------------------------------------------------
# Publication-style figures (ggplot2). Neutral palette; one accent colour.
# -----------------------------------------------------------------------------

.q2e_theme <- function() {
  ggplot2::theme_minimal(base_size = 11) +
    ggplot2::theme(panel.grid.minor = ggplot2::element_blank(),
                   panel.grid.major.y = ggplot2::element_blank(),
                   strip.text = ggplot2::element_text(face = "bold", hjust = 0),
                   plot.title = ggplot2::element_text(face = "bold", size = 12), plot.title.position = "plot", plot.caption.position = "plot",
                   plot.subtitle = ggplot2::element_text(colour = "#555555", size = 9),
                   plot.caption = ggplot2::element_text(colour = "#777777", size = 8, hjust = 0),
                   axis.title = ggplot2::element_text(size = 10))
}
.accent <- "#1F5A85"
.lc1 <- function(s) { w <- sub(" .*", "", s); if (grepl("^[A-Z][a-z]*$", w)) paste0(tolower(substr(s, 1, 1)), substring(s, 2)) else s }
.wrap_lab <- function(x) vapply(x, function(s) paste(strwrap(s, 40), collapse = "\n"), "")
.wrap <- function(s, w = 62) paste(strwrap(s, w), collapse = "\n")
.left_strips <- function() ggplot2::theme(strip.placement = "outside",
  strip.text.y.left = ggplot2::element_text(angle = 0, hjust = 1, vjust = 0.5, face = "bold", size = 9),
  panel.spacing.y = grid::unit(6, "pt"))
.muted <- "#8A8F98"

fig_prevalence <- function(prev, outcome, outdir, synthetic = FALSE) {
  rows <- Filter(function(p) p$outcome == outcome && (is.null(p$outcome_level) || is.na(p$outcome_level)), prev)
  if (!length(rows)) rows <- Filter(function(p) p$outcome == outcome, prev)
  if (!length(rows)) return(NULL)
  df <- data.frame(group_var = vapply(rows, function(r) r$group_label, ""), group = vapply(rows, function(r) as.character(r$group), ""),
                   level = vapply(rows, function(r) if (is.null(r$outcome_level) || is.na(r$outcome_level)) "" else as.character(r$outcome_level), ""),
                   est = 100 * vapply(rows, function(r) r$est, 0), lcl = 100 * vapply(rows, function(r) r$lcl, 0),
                   ucl = 100 * vapply(rows, function(r) r$ucl, 0), flag = vapply(rows, function(r) r$nchs, ""), stringsAsFactors = FALSE)
  df$label <- ifelse(nzchar(df$level), paste0(df$group, " - ", df$level), df$group)
  df$group_var <- factor(df$group_var, levels = unique(df$group_var))
  df$label <- factor(df$label, levels = rev(unique(df$label)))
  df$reliable <- ifelse(df$flag == "meets standard", "Meets NCHS standard", "Flagged (NCHS)")
  title <- rows[[1]]$outcome_label
  p <- ggplot2::ggplot(df, ggplot2::aes(x = est, y = label)) +
    ggplot2::geom_errorbarh(ggplot2::aes(xmin = lcl, xmax = ucl), height = 0.18, colour = .muted) +
    ggplot2::geom_point(ggplot2::aes(shape = reliable), colour = .accent, size = 2.4) +
    ggplot2::scale_shape_manual(values = c("Meets NCHS standard" = 16, "Flagged (NCHS)" = 1), name = NULL) +
    ggplot2::scale_y_discrete(labels = .wrap_lab) +
    ggplot2::facet_grid(group_var ~ ., scales = "free_y", space = "free_y", switch = "y",
                        labeller = ggplot2::labeller(group_var = ggplot2::label_wrap_gen(16))) +
    ggplot2::labs(x = "Weighted prevalence, % (95% CI)", y = NULL, title = .wrap(paste("Prevalence of", .lc1(title))),
                  subtitle = "Survey-weighted; Korn-Graubard 95% CIs",
                  caption = if (synthetic) "SYNTHETIC DATA - not valid population estimates" else NULL) +
    .q2e_theme() + .left_strips() + ggplot2::theme(legend.position = "bottom")
  h <- max(3, 0.32 * nrow(df) + 1.8)
  f <- file.path(outdir, "fig_prevalence.png")
  ggplot2::ggsave(f, p, width = 7, height = h, dpi = 200, bg = "white")
  list(id = "prevalence", title = paste("Weighted prevalence of", .lc1(title)), file = basename(f))
}

fig_forest <- function(rows, effect_label, outdir, synthetic = FALSE, file = "fig_forest.png", title = NULL) {
  rows <- Filter(function(r) !is.null(r$est) && is.finite(r$est) && is.finite(r$lcl) && is.finite(r$ucl), rows)
  if (!length(rows)) return(NULL)
  df <- data.frame(section = vapply(rows, function(r) r$section, ""), label = vapply(rows, function(r) r$label, ""),
                   est = vapply(rows, function(r) r$est, 0), lcl = vapply(rows, function(r) r$lcl, 0), ucl = vapply(rows, function(r) r$ucl, 0),
                   stringsAsFactors = FALSE)
  df$section <- factor(df$section, levels = unique(df$section))
  df$label <- make.unique(df$label, sep = " ")
  df$label <- factor(df$label, levels = rev(df$label))
  ratio <- grepl("ratio", tolower(effect_label))
  ref <- if (ratio) 1 else 0
  p <- ggplot2::ggplot(df, ggplot2::aes(x = est, y = label)) +
    ggplot2::geom_vline(xintercept = ref, linetype = "dashed", colour = "#B0B4BA") +
    ggplot2::geom_errorbarh(ggplot2::aes(xmin = lcl, xmax = ucl), height = 0.18, colour = .muted) +
    ggplot2::geom_point(colour = .accent, size = 2.4, shape = 15) +
    ggplot2::facet_grid(section ~ ., scales = "free_y", space = "free_y", switch = "y",
                        labeller = ggplot2::labeller(section = ggplot2::label_wrap_gen(16))) +
    ggplot2::scale_y_discrete(labels = .wrap_lab) +
    ggplot2::labs(x = paste(effect_label, "(95% CI)"), y = NULL, title = .wrap(title %||% "Primary estimate across specifications"),
                  caption = if (synthetic) "SYNTHETIC DATA - not valid population estimates" else NULL) +
    .q2e_theme() + .left_strips()
  if (ratio) p <- p + ggplot2::scale_x_log10()
  h <- max(3, 0.32 * nrow(df) + 1.6)
  f <- file.path(outdir, file)
  ggplot2::ggsave(f, p, width = 7, height = h, dpi = 200, bg = "white")
  list(id = sub("\\.png$", "", sub("^fig_", "", file)), title = title %||% "Primary estimate across specifications", file = basename(f))
}

fig_distribution <- function(des, x, by, spec, outdir, synthetic = FALSE) {
  d <- des$variables[des$variables$.in_analytic, , drop = FALSE]
  if (!x %in% names(d) || !is.numeric(d[[x]])) return(NULL)
  d$.grp <- if (!is.null(by) && by %in% names(d)) {
    g <- d[[by]]
    if (!is.factor(g) && all(g %in% c(0, 1, NA))) factor(ifelse(g == 1, "Yes", "No"), levels = c("No", "Yes")) else factor(g)
  } else factor("All")
  d <- d[!is.na(d[[x]]) & !is.na(d$.grp), ]
  d$.w <- d$.wt / sum(d$.wt)
  rng <- stats::quantile(d[[x]], c(0.005, 0.995), na.rm = TRUE)
  d <- d[d[[x]] >= rng[1] & d[[x]] <= rng[2], ]
  logx <- all(d[[x]] > 0) && (rng[2] / max(rng[1], 1e-6) > 30)
  p <- ggplot2::ggplot(d, ggplot2::aes(x = .data[[x]], weight = .w, colour = .grp)) +
    ggplot2::geom_density(linewidth = 0.8, adjust = 1.2) +
    ggplot2::scale_colour_manual(values = c(.muted, .accent, "#C26A2E", "#5B8C5A", "#7A5195")[seq_along(levels(d$.grp))],
                                 name = if (!is.null(by)) .var_label(spec, by) else NULL) +
    ggplot2::labs(x = paste0(.var_label(spec, x), if (logx) " (log scale)" else ""), y = "Weighted density",
                  title = .wrap(paste("Distribution of", .lc1(.var_label(spec, x)), if (!is.null(by)) paste("by", .lc1(.var_label(spec, by))) else "")),
                  caption = if (synthetic) "SYNTHETIC DATA - not valid population estimates" else NULL) +
    .q2e_theme() + ggplot2::theme(legend.position = "bottom", panel.grid.major.y = ggplot2::element_line(colour = "#EEEEEE"))
  if (logx) p <- p + ggplot2::scale_x_log10()
  f <- file.path(outdir, "fig_distribution.png")
  suppressWarnings(ggplot2::ggsave(f, p, width = 7, height = 3.8, dpi = 200, bg = "white"))
  list(id = "distribution", title = paste("Distribution of", .lc1(.var_label(spec, x))), file = basename(f))
}
