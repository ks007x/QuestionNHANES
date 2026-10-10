# -----------------------------------------------------------------------------
# Q2E safe expression language
#
# Derived variables and inclusion criteria are written in a small subset of R.
# Expressions are parsed, every node of the syntax tree is checked against a
# whitelist, and evaluation happens in an environment whose parent is
# emptyenv(), so nothing outside the whitelist (system(), file I/O, assignment,
# library(), ...) can be reached - even if an LLM proposed the expression.
# -----------------------------------------------------------------------------

q2e_coalesce <- function(x, y) {
  if (is.factor(x)) x <- as.character(x)
  if (length(y) == 1L) y <- rep(y, length(x))
  out <- x
  miss <- is.na(out)
  out[miss] <- y[miss]
  out
}

.as_lgl <- function(v) {
  if (is.logical(v)) return(v)
  if (is.numeric(v)) return(ifelse(is.na(v), NA, v != 0))
  as.logical(v)
}

q2e_any_of <- function(...) {
  args <- lapply(list(...), .as_lgl)
  n <- max(vapply(args, length, 1L))
  args <- lapply(args, function(v) if (length(v) == 1L) rep(v, n) else v)
  hit <- Reduce(`|`, lapply(args, function(v) !is.na(v) & v))
  known <- Reduce(`|`, lapply(args, function(v) !is.na(v)))
  out <- rep(NA, n)
  out[known] <- FALSE
  out[hit] <- TRUE
  out
}

q2e_all_of <- function(...) {
  args <- lapply(list(...), .as_lgl)
  n <- max(vapply(args, length, 1L))
  args <- lapply(args, function(v) if (length(v) == 1L) rep(v, n) else v)
  fail <- Reduce(`|`, lapply(args, function(v) !is.na(v) & !v))
  allknown <- Reduce(`&`, lapply(args, function(v) !is.na(v)))
  out <- rep(NA, n)
  out[allknown] <- TRUE
  out[fail] <- FALSE
  out
}

# cases(cond1, "label1", cond2, "label2", ..., .default = "other")
# First TRUE condition wins. Rows where no condition is TRUE get .default only
# if every condition was evaluable (non-NA); otherwise NA. Level order follows
# the order of appearance, so the first label is the reference category.
q2e_cases <- function(..., .default = NULL) {
  args <- list(...)
  if (length(args) %% 2L != 0L) stop("cases() needs condition/label pairs")
  conds <- args[seq(1, length(args), by = 2)]
  labels <- vapply(args[seq(2, length(args), by = 2)], as.character, "")
  n <- max(vapply(conds, length, 1L))
  conds <- lapply(conds, function(v) { v <- .as_lgl(v); if (length(v) == 1L) rep(v, n) else v })
  out <- rep(NA_character_, n)
  assigned <- rep(FALSE, n)
  anyna <- rep(FALSE, n)
  for (i in seq_along(conds)) {
    c_i <- conds[[i]]
    hit <- !assigned & !is.na(c_i) & c_i
    out[hit] <- labels[i]
    assigned <- assigned | hit
    anyna <- anyna | (!assigned & is.na(c_i))
  }
  lv <- unique(labels)
  if (!is.null(.default)) {
    fill <- !assigned & !anyna
    out[fill] <- as.character(.default)
    lv <- unique(c(lv, as.character(.default)))
  }
  factor(out, levels = lv)
}

.q2e_functions <- list(
  "+" = base::`+`, "-" = base::`-`, "*" = base::`*`, "/" = base::`/`, "^" = base::`^`,
  "(" = base::`(`, "<" = base::`<`, ">" = base::`>`, "<=" = base::`<=`, ">=" = base::`>=`,
  "==" = base::`==`, "!=" = base::`!=`, "&" = base::`&`, "|" = base::`|`, "!" = base::`!`,
  "%in%" = base::`%in%`, "c" = base::c, "ifelse" = base::ifelse,
  "coalesce" = q2e_coalesce, "any_of" = q2e_any_of, "all_of" = q2e_all_of, "cases" = q2e_cases,
  "pmin" = function(...) base::pmin(..., na.rm = FALSE),
  "pmax" = function(...) base::pmax(..., na.rm = FALSE),
  "log" = function(x) suppressWarnings(base::log(x)), "log10" = function(x) suppressWarnings(base::log10(x)),
  "exp" = base::exp, "sqrt" = function(x) suppressWarnings(base::sqrt(x)), "abs" = base::abs,
  "is.na" = base::is.na, "round" = base::round, "as.numeric" = base::as.numeric
)

q2e_allowed_functions <- function() names(.q2e_functions)

.q2e_constants <- c("Inf", "NaN", "T", "F", "TRUE", "FALSE", "NA")

# Return character vector of variable names used by an expression (after validation).
dsl_validate <- function(expr_str, allowed_vars = NULL) {
  if (!is.character(expr_str) || length(expr_str) != 1L || !nzchar(trimws(expr_str))) {
    stop("Expression must be a single non-empty string")
  }
  ex <- tryCatch(parse(text = expr_str, keep.source = FALSE),
                 error = function(e) stop(sprintf("Cannot parse expression '%s': %s", expr_str, conditionMessage(e))))
  if (length(ex) != 1L) stop(sprintf("Expression '%s' must contain exactly one statement", expr_str))
  used <- character(0)
  fns <- q2e_allowed_functions()
  walk <- function(e) {
    if (is.call(e)) {
      head <- e[[1]]
      if (!is.name(head)) stop(sprintf("Illegal construct in '%s'", expr_str))
      fname <- as.character(head)
      if (!fname %in% fns) stop(sprintf("Function '%s' is not allowed in Q2E expressions ('%s')", fname, expr_str))
      args <- as.list(e)[-1]
      for (a in args) walk(a)
    } else if (is.name(e)) {
      nm <- as.character(e)
      if (!nzchar(nm) || nm %in% .q2e_constants) return(invisible())
      if (!is.null(allowed_vars) && !nm %in% allowed_vars) {
        stop(sprintf("Unknown variable '%s' in expression '%s'", nm, expr_str))
      }
      used <<- c(used, nm)
    } else if (is.numeric(e) || is.character(e) || is.logical(e) || is.null(e)) {
      return(invisible())
    } else {
      stop(sprintf("Illegal token in '%s'", expr_str))
    }
  }
  walk(ex[[1]])
  unique(used)
}

# Evaluate a validated expression against a data.frame. Returns a vector of nrow(data).
dsl_eval <- function(expr_str, data) {
  dsl_validate(expr_str, allowed_vars = names(data))
  env <- new.env(parent = emptyenv())
  for (nm in names(.q2e_functions)) assign(nm, .q2e_functions[[nm]], envir = env)
  assign("Inf", Inf, envir = env); assign("NaN", NaN, envir = env)
  assign("T", TRUE, envir = env); assign("F", FALSE, envir = env)
  for (nm in names(data)) {
    v <- data[[nm]]
    assign(nm, v, envir = env)
  }
  out <- eval(parse(text = expr_str, keep.source = FALSE)[[1]], envir = env)
  if (length(out) == 1L && nrow(data) != 1L) out <- rep(out, nrow(data))
  if (length(out) != nrow(data)) stop(sprintf("Expression '%s' returned %d values for %d rows", expr_str, length(out), nrow(data)))
  out
}

# Coerce an evaluated vector to the declared Q2E type.
dsl_coerce <- function(x, type, levels = NULL) {
  switch(type,
    binary = {
      if (is.factor(x)) x <- as.character(x)
      v <- .as_lgl(x)
      as.integer(v)
    },
    continuous = {
      v <- suppressWarnings(as.numeric(x))
      v[!is.finite(v)] <- NA_real_
      v
    },
    categorical = {
      if (is.factor(x)) {
        if (!is.null(levels)) factor(as.character(x), levels = levels) else x
      } else {
        lv <- if (!is.null(levels)) levels else sort(unique(stats::na.omit(as.character(x))))
        factor(as.character(x), levels = lv)
      }
    },
    stop("Unknown variable type: ", type)
  )
}
