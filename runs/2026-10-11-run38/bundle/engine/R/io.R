# -----------------------------------------------------------------------------
# Data loading: NHANES (local XPT folder / cache / CDC download / synthetic) and
# generic tabular datasets (CSV) with optional survey design columns.
# -----------------------------------------------------------------------------

nhanes_file_name <- function(stem, cycle_meta) {
  sub("{stem}", stem, cycle_meta$file_pattern, fixed = TRUE)
}

.find_local_file <- function(fname, dirs) {
  for (d in dirs) {
    if (is.null(d) || !nzchar(d) || !dir.exists(d)) next
    cand <- list.files(d, full.names = TRUE, recursive = FALSE)
    hit <- cand[tolower(basename(cand)) == tolower(paste0(fname, ".xpt"))]
    if (length(hit)) return(hit[[1]])
  }
  NULL
}

.download_nhanes <- function(fname, cycle_meta, cache_dir, log) {
  url <- sprintf("https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/%s/DataFiles/%s.xpt", cycle_meta$url_folder, fname)
  dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)
  dest <- file.path(cache_dir, paste0(fname, ".xpt"))
  log(sprintf("Downloading %s", url))
  old_to <- getOption("timeout"); options(timeout = max(600, old_to)); on.exit(options(timeout = old_to), add = TRUE)
  is_xpt <- function(f) file.exists(f) && file.info(f)$size >= 1000 &&
    identical(substr(rawToChar(readBin(f, "raw", 20)), 1, 20), "HEADER RECORD*******")
  ok <- FALSE
  for (attempt in 1:3) {
    ok <- tryCatch({
      utils::download.file(url, dest, mode = "wb", quiet = TRUE)
      TRUE
    }, error = function(e) { log(sprintf("Download attempt %d failed for %s: %s", attempt, fname, conditionMessage(e))); FALSE },
       warning = function(w) { log(sprintf("Download attempt %d warning for %s: %s", attempt, fname, conditionMessage(w))); FALSE })
    if (ok && is_xpt(dest)) break
    if (ok) log(sprintf("%s did not return a SAS transport file (CDC may have served an HTML page)", url))
    ok <- FALSE; if (file.exists(dest)) unlink(dest)
    Sys.sleep(2 * attempt)
  }
  if (!ok) return(NULL)
  list(path = dest, url = url)
}

.file_md5 <- function(path) unname(tools::md5sum(path))

# Load and merge the NHANES component files required by the plan.
# Returns list(data, files, missing_vars)
load_nhanes <- function(spec, log = message) {
  ds <- spec$dataset
  cycles <- unlist(ds$cycles)
  meta <- spec$cycles_meta
  raw <- spec$raw_variables
  # older cycles name files differently (e.g. eosinophils: LAB25 1999-2000, L25_B, L25_C, CBC_D ...): use the per-cycle stem
  stem_for <- function(r, cy) { s <- r$stems[[cy]]; if (is.null(s) || !nzchar(s)) r$file else s }
  dirs <- c(ds$local_dir, ds$synthetic_dir, ds$cache_dir)
  allow_download <- isTRUE(ds$allow_download)
  files_used <- list(); missing_vars <- list(); per_cycle <- list()

  for (cy in cycles) {
    cm <- meta[[cy]]
    if (is.null(cm)) stop("Unknown NHANES cycle: ", cy)
    merged <- NULL
    wvar <- unlist(cm$weights)[[spec$weight_level]]
    wfile <- if (!is.null(cm$weight_files[[spec$weight_level]])) cm$weight_files[[spec$weight_level]] else "DEMO"
    raw_stems <- unique(c("DEMO", vapply(raw, function(r) stem_for(r, cy), "")))
    stems <- unique(c(raw_stems, wfile))
    for (stem in stems) {
      vars_here <- unique(c("SEQN", vapply(Filter(function(r) stem_for(r, cy) == stem && cy %in% unlist(r$cycles), raw), function(r) r$variable, "")))
      if (stem == "DEMO") {
        vars_here <- unique(c(vars_here, "RIDSTATR", cm$psu, cm$strata))
      }
      if (stem == wfile) vars_here <- unique(c(vars_here, wvar))
      if (length(vars_here) <= 1L && stem != "DEMO") next
      fname <- nhanes_file_name(stem, cm)
      path <- .find_local_file(fname, dirs)
      origin <- "local"
      url <- NA_character_
      if (!is.null(path) && !is.null(ds$cache_dir) && nzchar(ds$cache_dir) &&
          identical(normalizePath(dirname(path), mustWork = FALSE), normalizePath(ds$cache_dir, mustWork = FALSE))) {
        origin <- "cdc (cached download)"
        url <- sprintf("https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/%s/DataFiles/%s.xpt", cm$url_folder, fname)
      }
      if (is.null(path) && allow_download) {
        dl <- .download_nhanes(fname, cm, ds$cache_dir, log)
        if (!is.null(dl)) { path <- dl$path; origin <- "cdc"; url <- dl$url }
      }
      if (is.null(path)) {
        stop(sprintf("NHANES file %s.xpt (cycle %s) not found in %s%s", fname, cy,
                     paste(Filter(Negate(is.null), dirs), collapse = ", "),
                     if (allow_download) " and could not be downloaded from CDC" else " (downloads disabled)"))
      }
      df <- as.data.frame(haven::read_xpt(path))
      df[] <- lapply(df, function(col) { attributes(col) <- NULL; col })
      absent <- setdiff(vars_here, names(df))
      if (length(absent)) missing_vars[[length(missing_vars) + 1]] <- list(cycle = cy, file = fname, variables = absent)
      keep <- intersect(vars_here, names(df))
      df <- df[, keep, drop = FALSE]
      if (anyDuplicated(df$SEQN)) stop(sprintf("Duplicate SEQN in %s - unexpected for person-level files", fname))
      files_used[[length(files_used) + 1]] <- list(cycle = cy, file = fname, origin = origin, url = url,
                                                   path = normalizePath(path), md5 = .file_md5(path),
                                                   nrow = nrow(df), synthetic = grepl("synthetic", path, ignore.case = TRUE) ||
                                                     file.exists(file.path(dirname(path), "README_SYNTHETIC.txt")))
      merged <- if (is.null(merged)) df else merge(merged, df, by = "SEQN", all.x = TRUE, sort = FALSE)
    }
    # harmonise design + weight columns
    if (!wvar %in% names(merged)) stop(sprintf("Weight variable %s not found (cycle %s, file %s)", wvar, cy, nhanes_file_name(wfile, cm)))
    merged$.wt_raw <- merged[[wvar]]
    merged$.cycle <- cy
    merged$.wt_raw <- merged[[wvar]]
    merged$.weight_var <- wvar
    merged$.psu <- merged[[cm$psu]]
    merged$.strata <- paste0(cy, "_", merged[[cm$strata]])   # strata codes must stay distinct when cycles are pooled
    merged$.years <- cm$years
    per_cycle[[cy]] <- merged
  }
  all_cols <- unique(unlist(lapply(per_cycle, names)))
  per_cycle <- lapply(per_cycle, function(d) { for (cl in setdiff(all_cols, names(d))) d[[cl]] <- NA; d[, all_cols] })
  dat <- do.call(rbind, per_cycle)
  # variables not collected in any selected cycle exist as NA, so coalesce() fallbacks (e.g. RIDRETH3 -> RIDRETH1) work
  for (r in raw) if (!r$variable %in% names(dat)) dat[[r$variable]] <- NA
  total_years <- sum(vapply(cycles, function(cy) meta[[cy]]$years, 0))
  dat$.wt <- dat$.wt_raw * dat$.years / total_years
  rownames(dat) <- NULL
  list(data = dat, files = files_used, missing_vars = missing_vars)
}

# Generic dataset: one or more CSV files joined on an id column.
load_generic <- function(spec, log = message) {
  ds <- spec$dataset
  files_used <- list(); dat <- NULL
  for (f in ds$files) {
    path <- f$path
    if (!file.exists(path)) stop("Data file not found: ", path)
    df <- utils::read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
    files_used[[length(files_used) + 1]] <- list(file = basename(path), origin = "upload", path = normalizePath(path),
                                                 md5 = .file_md5(path), nrow = nrow(df), synthetic = FALSE)
    if (is.null(dat)) dat <- df else {
      if (is.null(ds$id_var)) stop("Multiple files require dataset.id_var for joining")
      dat <- merge(dat, df, by = ds$id_var, all.x = TRUE, sort = FALSE)
    }
  }
  needed <- vapply(spec$raw_variables, function(r) r$variable, "")
  absent <- setdiff(needed, names(dat))
  missing_vars <- if (length(absent)) list(list(cycle = "-", file = "uploaded data", variables = absent)) else list()
  dat$.cycle <- "generic"
  dat$.wt <- if (!is.null(ds$weight) && nzchar(ds$weight)) as.numeric(dat[[ds$weight]]) else 1
  dat$.weight_var <- if (!is.null(ds$weight) && nzchar(ds$weight)) ds$weight else "(none - equal weights)"
  dat$.psu <- if (!is.null(ds$psu) && nzchar(ds$psu)) dat[[ds$psu]] else seq_len(nrow(dat))
  dat$.strata <- if (!is.null(ds$strata) && nzchar(ds$strata)) dat[[ds$strata]] else 1
  list(data = dat, files = files_used, missing_vars = missing_vars)
}

# Replace documented non-response codes (refused / don't know) with NA and
# count out-of-range values for QC.
clean_raw_variables <- function(dat, raw) {
  range_report <- list()
  for (r in raw) {
    v <- r$variable
    if (!v %in% names(dat)) next
    codes <- unlist(r$missing_codes)
    if (length(codes)) {
      n_codes <- sum(dat[[v]] %in% codes)
      dat[[v]][dat[[v]] %in% codes] <- NA
    } else n_codes <- 0L
    x <- suppressWarnings(as.numeric(dat[[v]]))
    lo <- if (is.null(r$min) || is.na(r$min)) NA else as.numeric(r$min)
    hi <- if (is.null(r$max) || is.na(r$max)) NA else as.numeric(r$max)
    n_low <- if (!is.na(lo)) sum(x < lo, na.rm = TRUE) else 0L
    n_high <- if (!is.na(hi)) sum(x > hi, na.rm = TRUE) else 0L
    range_report[[v]] <- list(variable = v, n_nonmissing = sum(!is.na(x)), n_nonresponse_codes = n_codes,
                              n_below = n_low, n_above = n_high, min_allowed = lo, max_allowed = hi,
                              observed_min = if (any(!is.na(x))) min(x, na.rm = TRUE) else NA,
                              observed_max = if (any(!is.na(x))) max(x, na.rm = TRUE) else NA)
  }
  list(data = dat, ranges = unname(range_report))
}

# Evaluate derived variables in dependency order (Python supplies topological order).
derive_variables <- function(dat, derived, log = message) {
  audit <- list()
  for (d in derived) {
    val <- tryCatch(dsl_eval(d$expr, dat),
                    error = function(e) stop(sprintf("Derivation of '%s' failed: %s", d$name, conditionMessage(e))))
    dat[[d$name]] <- dsl_coerce(val, d$type, unlist(d$levels))
    x <- dat[[d$name]]
    entry <- list(name = d$name, expr = d$expr, type = d$type, n_nonmissing = sum(!is.na(x)))
    if (d$type == "binary") entry$n_positive <- sum(x == 1, na.rm = TRUE)
    if (d$type == "continuous" && any(!is.na(x))) {
      q <- stats::quantile(x, c(0, .25, .5, .75, 1), na.rm = TRUE, names = FALSE)
      entry$quantiles <- round(q, 3)
    }
    if (d$type == "categorical") entry$levels <- as.list(table(x, useNA = "no"))
    audit[[length(audit) + 1]] <- entry
  }
  list(data = dat, audit = audit)
}
