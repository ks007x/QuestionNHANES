"""Readable, stand-alone R script for one approved study.

The Q2E engine (r/engine) is generic: it reads compiled_plan.json and runs any study. Reviewers and statisticians
usually want to read the analysis itself, top to bottom, the way they would write it. This module writes that
script from the same compiled plan: the NHANES files and variables, every recode, the eligibility steps, the
survey design, and each svyglm call, using only the survey and haven packages. Run on the same data it gives the
same estimates as the engine (checked by tests/test_r_script.py).
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

CDC = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{folder}/DataFiles/{fname}.xpt"


def _s(x: Any) -> str:
    """R string literal."""
    return json.dumps(str(x), ensure_ascii=False)


def _vec(xs) -> str:
    xs = [x for x in xs if x is not None]
    return "c(" + ", ".join(_s(x) for x in xs) + ")" if xs else "character(0)"


def _num(x) -> str:
    return "NULL" if x is None else repr(float(x)).replace("inf", "Inf")


def _nhanes_files(spec: dict) -> dict[str, dict]:
    """Per cycle: file name -> variables, in the same order the engine merges them."""
    out = {}
    raw = spec["raw_variables"]
    level = spec["weight_level"]
    for cy in spec["dataset"]["cycles"]:
        cm = spec["cycles_meta"][cy]
        wvar = cm["weights"][level]
        wfile = (cm.get("weight_files") or {}).get(level) or "DEMO"

        def stem_for(r, cy=cy):
            s = (r.get("stems") or {}).get(cy)
            return s if s else r["file"]
        stems = list(dict.fromkeys(["DEMO"] + [stem_for(r) for r in raw] + [wfile]))
        files = {}
        for stem in stems:
            vs = ["SEQN"] + [r["variable"] for r in raw if stem_for(r) == stem and cy in r.get("cycles", [])]
            if stem == "DEMO":
                vs += ["RIDSTATR", cm["psu"], cm["strata"]]
            if stem == wfile:
                vs.append(wvar)
            vs = list(dict.fromkeys(vs))
            if len(vs) <= 1 and stem != "DEMO":
                continue
            fname = cm["file_pattern"].replace("{stem}", stem)
            files[fname] = {"vars": vs, "url": CDC.format(folder=cm["url_folder"], fname=fname)}
        out[cy] = {"label": cm.get("label", cy), "files": files, "weight": wvar, "psu": cm["psu"], "strata": cm["strata"],
                   "years": cm["years"]}
    return out


HELPERS = r'''
# ---- Helper functions -------------------------------------------------------------------------------
# The recodes below use four small helpers. They behave like dplyr's case_when()/coalesce(), with one
# NHANES-specific rule: a row stays missing when a condition it needs is missing.
cases <- function(..., .default = NULL) {        # cases(cond1, "label1", cond2, "label2", ...): first TRUE wins
  a <- list(...); conds <- a[seq(1, length(a), 2)]; labels <- vapply(a[seq(2, length(a), 2)], as.character, "")
  n <- max(lengths(conds)); conds <- lapply(conds, function(v) rep_len(as_lgl(v), n))
  out <- rep(NA_character_, n); done <- rep(FALSE, n); anyna <- rep(FALSE, n)
  for (i in seq_along(conds)) {
    hit <- !done & !is.na(conds[[i]]) & conds[[i]]
    out[hit] <- labels[i]; done <- done | hit; anyna <- anyna | (!done & is.na(conds[[i]]))
  }
  lv <- unique(labels)
  if (!is.null(.default)) { out[!done & !anyna] <- as.character(.default); lv <- unique(c(lv, as.character(.default))) }
  factor(out, levels = lv)                        # first label = reference category
}
coalesce <- function(x, ...) {                   # first non-missing value
  if (is.factor(x)) x <- as.character(x)
  for (y in list(...)) { if (is.factor(y)) y <- as.character(y); y <- rep_len(y, length(x)); x[is.na(x)] <- y[is.na(x)] }
  x
}
as_lgl <- function(v) if (is.logical(v)) v else if (is.numeric(v)) ifelse(is.na(v), NA, v != 0) else as.logical(v)
any_of <- function(...) {                        # TRUE if any is TRUE; FALSE only if all are known
  a <- lapply(list(...), as_lgl); n <- max(lengths(a)); a <- lapply(a, rep_len, n)
  out <- rep(NA, n); out[Reduce(`|`, lapply(a, Negate(is.na)))] <- FALSE; out[Reduce(`|`, lapply(a, function(v) !is.na(v) & v))] <- TRUE; out
}
all_of <- function(...) {                        # FALSE if any is FALSE; TRUE only if all are known and TRUE
  a <- lapply(list(...), as_lgl); n <- max(lengths(a)); a <- lapply(a, rep_len, n)
  out <- rep(NA, n); out[Reduce(`&`, lapply(a, Negate(is.na)))] <- TRUE; out[Reduce(`|`, lapply(a, function(v) !is.na(v) & !v))] <- FALSE; out
}
as_type <- function(x, type, levels = NULL) {    # store each variable as binary (0/1), continuous or factor
  x <- rep_len(x, nrow(dat))
  switch(type,
    binary = as.integer(as_lgl(if (is.factor(x)) as.character(x) else x)),
    continuous = { v <- suppressWarnings(as.numeric(x)); v[!is.finite(v)] <- NA; v },
    categorical = if (is.factor(x)) (if (is.null(levels)) x else factor(as.character(x), levels = levels))
                  else factor(as.character(x), levels = if (is.null(levels)) sort(unique(na.omit(as.character(x)))) else levels))
}

# Survey-weighted GLM with Wald CIs on the design degrees of freedom (#PSU - #strata), as NCHS recommends.
# Covariates that are constant in the rows analysed are dropped (with a message) instead of stopping the run.
fit_model <- function(design, y, terms, family = c("gaussian", "quasipoisson", "quasibinomial"), show = TRUE) {
  family <- match.arg(family)
  rows <- weights(design) > 0
  for (v in unique(unlist(strsplit(c(y, terms), ":", fixed = TRUE)))) rows <- rows & !is.na(design$variables[[v]])
  keep <- character(0)
  for (t in terms) {
    if (grepl(":", t, fixed = TRUE)) { if (all(strsplit(t, ":", fixed = TRUE)[[1]] %in% keep)) keep <- c(keep, t); next }
    vals <- design$variables[[t]][rows]
    if (length(unique(na.omit(vals))) < 2) { message("  dropped '", t, "': constant in the rows analysed"); next }
    if (is.factor(vals)) design$variables[[t]] <- factor(as.character(design$variables[[t]]), levels = levels(droplevels(vals)))
    keep <- c(keep, t)
  }
  f <- as.formula(paste(y, "~", if (length(keep)) paste(keep, collapse = " + ") else "1"))
  fam <- switch(family, gaussian = gaussian(), quasipoisson = quasipoisson(link = "log"), quasibinomial = quasibinomial(link = "logit"))
  start <- NULL
  if (family == "quasipoisson") {                # start values help log-link models converge
    mm <- model.matrix(f, model.frame(f, design$variables[rows, , drop = FALSE]))
    start <- c(log(max(mean(design$variables[[y]][rows]), 1e-4)), rep(0, ncol(mm) - 1))
  }
  fit <- svyglm(f, design = design, family = fam, start = start)
  cf <- summary(fit, df.resid = Inf)$coefficients
  ddf <- max(degf(design), 1); tq <- qt(0.975, ddf)
  tf <- if (family == "gaussian") identity else exp
  out <- data.frame(term = rownames(cf), est = tf(cf[, 1]), lcl = tf(cf[, 1] - tq * cf[, 2]), ucl = tf(cf[, 1] + tq * cf[, 2]),
                    p = 2 * pt(-abs(cf[, 1] / cf[, 2]), ddf), row.names = NULL)
  attr(out, "n") <- length(fit$y); attr(out, "fit") <- fit; attr(out, "formula") <- deparse1(f)
  if (show) {
    cat(sprintf("\n%s   [n = %s, design df = %d, effect = %s]\n", deparse1(f), format(length(fit$y), big.mark = ","), ddf,
                c(gaussian = "mean difference", quasipoisson = "prevalence ratio", quasibinomial = "odds ratio")[family]))
    print(transform(out, est = signif(est, 4), lcl = signif(lcl, 4), ucl = signif(ucl, 4), p = signif(p, 3)), row.names = FALSE)
  }
  invisible(out)
}
exposure_row <- function(m, x, first = FALSE) {   # the exposure coefficient (first arm vs control for multi-arm studies)
  r <- m[startsWith(m$term, x) & !grepl(":", m$term), , drop = FALSE]; r[if (first) 1 else nrow(r), , drop = FALSE]
}
'''


def build(spec: dict, proj: dict | None = None, results: dict | None = None) -> str:
    plan = (proj or {}).get("plan") or {}
    nh = spec["dataset"]["type"] == "nhanes"
    x = (spec.get("exposure") or {}).get("name")
    y = spec["outcome"]["name"]
    an = spec["analysis"]
    fam = (an.get("model") or {}).get("family") or "quasipoisson"
    sets = an.get("adjustment_sets") or []
    primary_id = (an.get("model") or {}).get("primary_set") or (sets[-1]["id"] if sets else None)
    prim = next((s for s in sets if s["id"] == primary_id), None)
    base_terms = list(dict.fromkeys(([x] if x else []) + (prim["covariates"] if prim else [])))
    L: list[str] = []
    w = L.append

    q = plan.get("refined_question") or plan.get("question") or ""
    w(f"# {spec.get('title') or 'Q2E study'}")
    if q:
        w(f"# Question: {q}")
    w(f"# Plan {spec['plan_id']} v{spec.get('plan_version', 1)}, sha256 {spec['plan_hash'][:16]}...  Written by Q2E on {dt.date.today().isoformat()}.")
    w("#")
    w("# A stand-alone, readable version of the approved analysis: the same files, recodes, eligibility steps, survey")
    w("# design and models the Q2E engine ran. Needs R >= 4.2 with the survey and haven packages:")
    w("#   install.packages(c(\"survey\", \"haven\"))")
    w("# Run with:  Rscript analysis.R      (or source it in RStudio and inspect `dat`, `des` and the model objects)")
    w("#")
    w("# Sections: helper functions, then 1 Data, 2 Recodes, 3 Eligibility, 4 Survey design, 5 Prevalence/means,")
    w("#           6 Regression models, 7 Effect modification, 8 Sensitivity analyses, and a check against the Q2E run.")
    w("")
    w("suppressPackageStartupMessages({ library(survey); library(haven) })")
    w("options(survey.lonely.psu = \"adjust\")")
    w(f"set.seed({int((spec.get('options') or {}).get('seed') or 2026)})")
    w(HELPERS.rstrip())
    w("")

    # ---------------------------------------------------------------- 1. data
    w("# ---- 1. Data ----------------------------------------------------------------------------------------")
    if nh:
        files = _nhanes_files(spec)
        w("# NHANES public-use files. Put the .xpt files in data_dir, or they are downloaded from CDC once and kept there.")
        w("data_dir <- Sys.getenv(\"NHANES_DIR\", \"data\")")
        w("dir.create(data_dir, showWarnings = FALSE, recursive = TRUE)")
        w("read_nhanes <- function(fname, url, vars) {")
        w("  hit <- list.files(data_dir, full.names = TRUE)")
        w("  path <- hit[tolower(basename(hit)) == tolower(paste0(fname, \".xpt\"))][1]")
        w("  if (is.na(path)) { path <- file.path(data_dir, paste0(fname, \".xpt\")); download.file(url, path, mode = \"wb\", quiet = TRUE) }")
        w("  d <- as.data.frame(read_xpt(path)); d[] <- lapply(d, function(v) { attributes(v) <- NULL; v })   # drop SAS labels")
        w("  d[, intersect(vars, names(d)), drop = FALSE]")
        w("}")
        w("")
        cyc = spec["dataset"]["cycles"]
        total_years = sum(files[c]["years"] for c in cyc)
        w("cycles <- list(")
        for i, c in enumerate(cyc):
            f = files[c]
            w(f"  {c} = list(  # {f['label']}")
            w(f"    weight = {_s(f['weight'])}, psu = {_s(f['psu'])}, strata = {_s(f['strata'])}, years = {f['years']},")
            w("    files = list(")
            items = list(f["files"].items())
            for j, (fn, info) in enumerate(items):
                w(f"      {fn} = list(url = {_s(info['url'])},")
                w(f"                  vars = {_vec(info['vars'])}){',' if j < len(items) - 1 else ''}")
            w("    ))" + ("," if i < len(cyc) - 1 else ""))
        w(")")
        w("")
        w("per_cycle <- lapply(names(cycles), function(cy) {")
        w("  cm <- cycles[[cy]]; d <- NULL")
        w("  for (fn in names(cm$files)) {                 # one row per participant; merge on SEQN, keeping everyone in DEMO")
        w("    f <- read_nhanes(fn, cm$files[[fn]]$url, cm$files[[fn]]$vars)")
        w("    d <- if (is.null(d)) f else merge(d, f, by = \"SEQN\", all.x = TRUE, sort = FALSE)")
        w("  }")
        w("  d$.cycle <- cy; d$.psu <- d[[cm$psu]]; d$.strata <- d[[cm$strata]]")
        w(f"  d$.wt <- d[[cm$weight]] * cm$years / {total_years:g}   # " + ("multi-cycle weight: share of the total years covered"
                                                                         if len(cyc) > 1 else "single cycle: weight used as is"))
        w("  d")
        w("})")
        w("all_cols <- unique(unlist(lapply(per_cycle, names)))")
        w("dat <- do.call(rbind, lapply(per_cycle, function(d) { d[setdiff(all_cols, names(d))] <- NA; d[all_cols] }))")
        w(f"for (v in {_vec([r['variable'] for r in spec['raw_variables']])}) if (!v %in% names(dat)) dat[[v]] <- NA")
    else:
        ds = spec["dataset"]
        w("# Uploaded dataset(s)")
        paths = [f["path"] for f in ds.get("files") or []]
        w(f"files <- {_vec(paths)}   # edit the paths if the files moved")
        w("dat <- NULL")
        w("for (p in files) { d <- read.csv(p, stringsAsFactors = FALSE, check.names = FALSE)")
        w(f"  dat <- if (is.null(dat)) d else merge(dat, d, by = {_s(ds.get('id_var') or 'id')}, all.x = TRUE, sort = FALSE) }}")
        w(f"dat$.wt <- {('as.numeric(dat[[' + _s(ds['weight']) + ']])') if ds.get('weight') else '1'}")
        w(f"dat$.psu <- {('dat[[' + _s(ds['psu']) + ']]') if ds.get('psu') else 'seq_len(nrow(dat))'}")
        w(f"dat$.strata <- {('dat[[' + _s(ds['strata']) + ']]') if ds.get('strata') else '1'}")
    w("cat(\"Records loaded:\", nrow(dat), \"\\n\")")
    w("")

    # ---------------------------------------------------------------- 2. cleaning + derivations
    w("# ---- 2. Non-response codes and derived variables --------------------------------------------------------")
    codes = [(r["variable"], r.get("missing_codes") or []) for r in spec["raw_variables"] if r.get("missing_codes")]
    if codes:
        w("# Refused / don't know codes become missing")
        for v, cs in codes:
            w(f"dat${v}[dat${v} %in% c({', '.join(f'{c:g}' for c in cs)})] <- NA")
    w("")
    meta = spec.get("variables_meta") or {}
    for d in spec["derived"]:
        lab = (meta.get(d["name"]) or {}).get("label") or d.get("label") or ""
        units = (meta.get(d["name"]) or {}).get("units")
        levels = d.get("levels")
        lv = f", levels = {_vec(levels)}" if levels else ""
        w(f"dat${d['name']} <- as_type(with(dat, {d['expr']}), {_s(d['type'])}{lv})   # {lab}{f' ({units})' if units else ''}")
    w("")

    # ---------------------------------------------------------------- 3. eligibility
    w("# ---- 3. Eligibility (participant flow) -----------------------------------------------------------------")
    w("flow <- data.frame(step = \"In source files\", n = nrow(dat))")
    w("step <- function(label, keep) { flow[nrow(flow) + 1, ] <<- list(label, sum(keep)); keep }")
    if nh:
        lbl = {"mec": "Examined in the MEC (positive MEC weight)", "fasting": "In fasting subsample (positive fasting weight)",
               "interview": "Interviewed (positive interview weight)"}.get(spec["weight_level"], "Positive analysis weight")
    else:
        lbl = "Positive analysis weight"
    w(f"keep <- step({_s(lbl)}, !is.na(dat$.wt) & dat$.wt > 0)")
    w("dat$.design_ok <- keep")
    for c in spec["population"]:
        w(f"v <- as_lgl(with(dat, {c['expr']}))")
        if c.get("kind") == "exclusion":
            w(f"keep <- step({_s('Excluded: ' + c['label'])}, keep & !(!is.na(v) & v))")
        else:
            w(f"keep <- step({_s(c['label'])}, keep & !is.na(v) & v)")
    w("dat$.in_pop <- keep")
    w(f"keep <- step({_s('Non-missing outcome (' + spec['outcome'].get('label', y) + ')')}, keep & !is.na(dat${y}))")
    if x:
        w(f"keep <- step({_s('Non-missing exposure (' + spec['exposure'].get('label', x) + ')')}, keep & !is.na(dat${x}))")
    w("dat$.in_analytic <- keep")
    covs = spec.get("covariates") or []
    w(f"for (cv in {_vec(covs)}) keep <- keep & !is.na(dat[[cv]])")
    w("dat$.in_cc <- step(\"Complete covariate data (model sample)\", keep)")
    w("print(flow, row.names = FALSE)")
    used = list(dict.fromkeys([y] + ([x] if x else []) + covs + (spec.get("subgroups") or []) + (an.get("table1_vars") or [])
                              + ((an.get("prevalence") or {}).get("by") or [])))
    w(f"for (v in intersect({_vec(used)}, names(dat))) if (is.factor(dat[[v]]))   # drop categories nobody in the study has")
    w("  dat[[v]] <- factor(as.character(dat[[v]]), levels = levels(dat[[v]])[levels(dat[[v]]) %in% dat[[v]][dat$.in_analytic]])")
    w("")

    # ---------------------------------------------------------------- 4. design
    w("# ---- 4. Survey design -----------------------------------------------------------------------------------")
    w("# Built on everyone with a positive weight; the study population is then selected with subset(), never by")
    w("# dropping rows first, so variance estimation keeps every PSU.")
    if nh or spec["dataset"].get("strata"):
        w("des <- svydesign(ids = ~.psu, strata = ~.strata, weights = ~.wt, nest = TRUE, data = dat[dat$.design_ok, ])")
    elif spec["dataset"].get("psu"):
        w("des <- svydesign(ids = ~.psu, weights = ~.wt, data = dat[dat$.design_ok, ])")
    else:
        w("des <- svydesign(ids = ~1, weights = ~.wt, data = dat[dat$.design_ok, ])")
    w("d_cc <- subset(des, .in_cc)             # complete-case model sample")
    w("d_an <- subset(des, .in_analytic)       # analytic population (descriptive estimates)")
    w("cat(\"\\nDesign df:\", degf(des), \"  model-sample df:\", degf(d_cc), \"\\n\")")
    w("")

    # ---------------------------------------------------------------- 5. descriptive
    prev = (an.get("prevalence") or {}).get("outcomes") or []
    w("# ---- 5. Weighted prevalence / means ---------------------------------------------------------------------")
    dtype = {d["name"]: d for d in spec["derived"]}
    for p in prev:
        lab = (meta.get(p) or {}).get("label", p)
        if (dtype.get(p) or {}).get("type") == "categorical":
            w(f"for (l in levels(des$variables${p})) {{   # {lab}: share in each category")
            w(f"  des$variables$.ind <- as.integer(as.character(des$variables${p}) == l)")
            w(f"  cat(l, \": \"); print(svyciprop(~.ind, subset(des, .in_analytic & !is.na(.ind)), method = \"beta\"))")
            w("}")
            continue
        ind = f".ind_{p}"
        w(f"des$variables${ind} <- as.integer(des$variables${p} == 1)")
        w(f"print(svyciprop(~{ind}, subset(des, .in_analytic & !is.na({ind})), method = \"beta\"))   # {lab}, overall")
        for g in (an.get("prevalence") or {}).get("by") or []:
            if g != p:
                w(f"print(svyby(~{ind}, ~{g}, subset(des, .in_analytic & !is.na({ind})), svyciprop, method = \"beta\", vartype = \"ci\"))")
    if spec["outcome"]["type"] == "continuous":
        w(f"print(svymean(~{y}, d_an, na.rm = TRUE))")
    w("")

    # ---------------------------------------------------------------- 6. models
    if x:
        w("# ---- 6. Regression models ----------------------------------------------------------------------------")
        w(f"# Outcome {y} ({spec['outcome'].get('label', y)}), exposure {x} ({spec['exposure'].get('label', x)}), family {fam}.")
        w("models <- list()")
        for s in sets:
            terms = list(dict.fromkeys([x] + list(s["covariates"])))
            star = "   # PRIMARY" if s["id"] == primary_id else ""
            w(f"models${s['id']} <- fit_model(d_cc, {_s(y)}, {_vec(terms)}, {_s(fam)})   # {s['label']}{star}")
        w("")
        if prim:
            arms = bool((spec.get("exposure") or {}).get("arms"))
            w(f"primary <- exposure_row(models${primary_id}, {_s(x)}{', first = TRUE' if arms else ''})")
            w("cat(\"\\nPRIMARY ESTIMATE:\", sprintf(\"%s %.4f (95%% CI %.4f to %.4f), p = %.3g\\n\", primary$term, primary$est, primary$lcl, primary$ucl, primary$p))")
            w("")
        # effect modification
        ints = [m for m in an.get("interactions") or [] if m != x]
        if ints and prim:
            w("# ---- 7. Effect modification (Wald test of the product term) --------------------------------------------")
            for mod in ints:
                t2 = list(dict.fromkeys([x] + [c for c in prim["covariates"] if c != mod] + [mod, f"{x}:{mod}"]))
                w(f"m_int <- fit_model(d_cc, {_s(y)}, {_vec(t2)}, {_s(fam)}, show = FALSE)")
                w(f"print(regTermTest(attr(m_int, \"fit\"), ~{x}:{mod}, df = max(degf(d_cc), 1)))   # by {(meta.get(mod) or {}).get('label', mod)}")
            w("")
        # sensitivity
        sens = an.get("sensitivity") or []
        if sens:
            w("# ---- 8. Sensitivity analyses ---------------------------------------------------------------------------")
            for s in sens:
                t = s.get("type")
                w(f"# {s.get('id', '')}: {s.get('label', t)}")
                if t in ("exclude", "restrict"):
                    w(f"v <- as_lgl(with(des$variables, {s['expr']}))")
                    w("sel <- !(!is.na(v) & v)" if t == "exclude" else "sel <- !is.na(v) & v")
                    w(f"exposure_row(fit_model(subset(des, .in_cc & sel), {_s(y)}, {_vec(base_terms)}, {_s(fam)}), {_s(x)})")
                elif t == "alt_outcome":
                    yo = s["outcome"]
                    w(f"sel <- with(des$variables, (.in_cc | (.in_pop & !is.na({x}))) & !is.na({yo}))")
                    w(f"for (cv in {_vec(base_terms)}) sel <- sel & !is.na(des$variables[[cv]])")
                    w(f"exposure_row(fit_model(subset(des, sel), {_s(yo)}, {_vec(base_terms)}, {_s(s.get('family') or fam)}), {_s(x)})")
                elif t == "add_covariates":
                    extra = [c for c in s.get("covariates") or [] if c not in base_terms]
                    w(f"sel <- des$variables$.in_cc; for (cv in {_vec(extra)}) sel <- sel & !is.na(des$variables[[cv]])")
                    w(f"exposure_row(fit_model(subset(des, sel), {_s(y)}, {_vec(base_terms + extra)}, {_s(fam)}), {_s(x)})")
                elif t == "alt_exposure":
                    xe = s["exposure"]; rest = [c for c in base_terms if c != x]
                    w(f"sel <- with(des$variables, .in_pop & !is.na({y}) & !is.na({xe})); for (cv in {_vec(rest)}) sel <- sel & !is.na(des$variables[[cv]])")
                    w(f"exposure_row(fit_model(subset(des, sel), {_s(y)}, {_vec([xe] + rest)}, {_s(fam)}), {_s(xe)})")
                elif t == "alt_family":
                    w(f"exposure_row(fit_model(d_cc, {_s(y)}, {_vec(base_terms)}, {_s(s['family'])}), {_s(x)})")
                elif t == "unweighted":
                    fam_r = {"gaussian": "gaussian()", "quasipoisson": "quasipoisson(link = \"log\")", "quasibinomial": "quasibinomial()"}[fam]
                    w(f"summary(glm({y} ~ {' + '.join(base_terms)}, data = des$variables[des$variables$.in_cc, ], family = {fam_r}))$coefficients   # ignores the design")
                elif t == "mi":
                    w("#   Multiple imputation (mice, then svyglm on each imputed design and Rubin's rules) is run by the Q2E engine;")
                    w("#   see reproduce.R in the bundle. It is not repeated here to keep this script short.")
                elif t == "exposure_quartiles":
                    w(f"q <- svyquantile(~{x}, d_cc, c(.25, .5, .75), ci = FALSE)[[1]]")
                    w(f"des$variables${x}_q <- cut(des$variables${x}, c(-Inf, q, Inf), labels = paste0(\"Q\", 1:4), right = FALSE)")
                    w(f"fit_model(subset(des, .in_cc), {_s(y)}, {_vec([x + '_q'] + [c for c in base_terms if c != x])}, {_s(fam)})")
                else:
                    w(f"#   ({t}: run by the Q2E engine; see reproduce.R)")
            w("")
    else:
        w("# Descriptive study: the weighted prevalence / mean above is the primary estimate.")
        w("")

    pe = (results or {}).get("primary_estimate") or {}
    if pe.get("est") is not None and x:
        w("# ---- Check against the Q2E run ---------------------------------------------------------------------------")
        w(f"q2e_primary <- {pe['est']!r}   # {pe.get('label', '')} reported by the Q2E engine")
        w("if (exists(\"primary\")) cat(\"Matches the Q2E run:\", isTRUE(all.equal(primary$est, q2e_primary, tolerance = 1e-6)), \"\\n\")")
    return "\n".join(L) + "\n"
