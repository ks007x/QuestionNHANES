# Association of Liver Stiffness With Thrombocytopenia Among US Adults: NHANES 2017-March 2020 pre-pandemic
# Question: Among noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years), is greater liver stiffness (VCTE median) (per 5 kPa) associated with a higher prevalence of thrombocytopenia - platelets <150 x10^9/L, after adjustment for age, sex, race and ethnicity, income-to-poverty ratio, body mass index, diabetes (self-report, medication, or HbA1c >=6.5%), and smoking status?
# Plan plan_b2cc741679 v1, sha256 0f5ba7ba4cf71b92...  Written by Q2E on 2026-10-11.
#
# A stand-alone, readable version of the approved analysis: the same files, recodes, eligibility steps, survey
# design and models the Q2E engine ran. Needs R >= 4.2 with the survey and haven packages:
#   install.packages(c("survey", "haven"))
# Run with:  Rscript analysis.R      (or source it in RStudio and inspect `dat`, `des` and the model objects)
#
# Sections: helper functions, then 1 Data, 2 Recodes, 3 Eligibility, 4 Survey design, 5 Prevalence/means,
#           6 Regression models, 7 Effect modification, 8 Sensitivity analyses, and a check against the Q2E run.

suppressPackageStartupMessages({ library(survey); library(haven) })
options(survey.lonely.psu = "adjust")
set.seed(2026)

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
any_of <- function(...) {                        # TRUE if any is TRUE; FALSE if none is TRUE and at least one is known
  a <- lapply(list(...), as_lgl); n <- max(lengths(a)); a <- lapply(a, rep_len, n)
  out <- rep(NA, n); out[Reduce(`|`, lapply(a, Negate(is.na)))] <- FALSE; out[Reduce(`|`, lapply(a, function(v) !is.na(v) & v))] <- TRUE; out
}
all_of <- function(...) {                        # FALSE if any is FALSE; TRUE only if all are known and TRUE
  a <- lapply(list(...), as_lgl); n <- max(lengths(a)); a <- lapply(a, rep_len, n)
  out <- rep(NA, n); out[Reduce(`&`, lapply(a, Negate(is.na)))] <- TRUE; out[Reduce(`|`, lapply(a, function(v) !is.na(v) & !v))] <- FALSE; out
}
mean_of <- function(...) {                       # mean of the available values ("average of up to 3 readings")
  m <- do.call(cbind, lapply(list(...), as.numeric)); out <- rowMeans(m, na.rm = TRUE); out[is.nan(out)] <- NA; out
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
  if (family == "quasipoisson" && any(rows)) {   # start values help log-link models converge
    mm <- model.matrix(f, model.frame(f, design$variables[rows, , drop = FALSE]))
    start <- c(log(max(mean(design$variables[[y]][rows]), 1e-4)), rep(0, ncol(mm) - 1))
  }
  if (!any(rows)) { message("  ", deparse1(f), ": no participants with complete data - not estimable"); return(invisible(data.frame())) }
  fit <- tryCatch(svyglm(f, design = design, family = fam, start = start),
                  error = function(e) { message("  ", deparse1(f), ": not estimable (", conditionMessage(e), ")"); NULL })
  if (is.null(fit)) return(invisible(data.frame()))
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
  if (!nrow(m)) return(m)
  r <- m[startsWith(m$term, x) & !grepl(":", m$term), , drop = FALSE]; r[if (first) 1 else nrow(r), , drop = FALSE]
}

# ---- 1. Data ----------------------------------------------------------------------------------------
# NHANES public-use files. Put the .xpt files in data_dir, or they are downloaded from CDC once and kept there.
data_dir <- Sys.getenv("NHANES_DIR", "data")
dir.create(data_dir, showWarnings = FALSE, recursive = TRUE)
read_nhanes <- function(fname, url, vars) {
  hit <- list.files(data_dir, full.names = TRUE)
  path <- hit[tolower(basename(hit)) == tolower(paste0(fname, ".xpt"))][1]
  if (is.na(path)) { path <- file.path(data_dir, paste0(fname, ".xpt")); download.file(url, path, mode = "wb", quiet = TRUE) }
  d <- as.data.frame(read_xpt(path)); d[] <- lapply(d, function(v) { attributes(v) <- NULL; v })   # drop SAS labels
  d[, intersect(vars, names(d)), drop = FALSE]
}

cycles <- list(
  P = list(  # NHANES 2017-March 2020 pre-pandemic
    weight = "WTMECPRP", psu = "SDMVPSU", strata = "SDMVSTRA", years = 3.2,
    files = list(
      P_DEMO = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DEMO.xpt",
                  vars = c("SEQN", "DMDEDUC2", "INDFMPIR", "RIAGENDR", "RIDAGEYR", "RIDRETH1", "RIDRETH3", "RIDSTATR", "SDMVPSU", "SDMVSTRA", "WTMECPRP")),
      P_ALQ = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_ALQ.xpt",
                  vars = c("SEQN", "ALQ130")),
      P_BMX = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_BMX.xpt",
                  vars = c("SEQN", "BMXBMI")),
      P_DIQ = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DIQ.xpt",
                  vars = c("SEQN", "DIQ010", "DIQ050", "DIQ070")),
      P_HEQ = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_HEQ.xpt",
                  vars = c("SEQN", "HEQ010", "HEQ030")),
      P_GHB = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_GHB.xpt",
                  vars = c("SEQN", "LBXGH")),
      P_CBC = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_CBC.xpt",
                  vars = c("SEQN", "LBXPLTSI")),
      P_LUX = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_LUX.xpt",
                  vars = c("SEQN", "LUXSMED")),
      P_SMQ = list(url = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_SMQ.xpt",
                  vars = c("SEQN", "SMQ020", "SMQ040"))
    ))
)

per_cycle <- lapply(names(cycles), function(cy) {
  cm <- cycles[[cy]]; d <- NULL
  for (fn in names(cm$files)) {                 # one row per participant; merge on SEQN, keeping everyone in DEMO
    f <- read_nhanes(fn, cm$files[[fn]]$url, cm$files[[fn]]$vars)
    d <- if (is.null(d)) f else merge(d, f, by = "SEQN", all.x = TRUE, sort = FALSE)
  }
  d$.cycle <- cy; d$.psu <- d[[cm$psu]]; d$.strata <- paste0(cy, "_", d[[cm$strata]])   # distinct strata across cycles
  d$.wt <- d[[cm$weight]] * cm$years / 3.2   # single cycle: weight used as is
  d
})
all_cols <- unique(unlist(lapply(per_cycle, names)))
dat <- do.call(rbind, lapply(per_cycle, function(d) { d[setdiff(all_cols, names(d))] <- NA; d[all_cols] }))
for (v in c("ALQ130", "BMXBMI", "DIQ010", "DIQ050", "DIQ070", "DMDEDUC2", "HEQ010", "HEQ030", "INDFMPIR", "LBXGH", "LBXPLTSI", "LUXSMED", "RIAGENDR", "RIDAGEYR", "RIDRETH1", "RIDRETH3", "SMQ020", "SMQ040")) if (!v %in% names(dat)) dat[[v]] <- NA
cat("Records loaded:", nrow(dat), "\n")

# ---- 2. Non-response codes and derived variables --------------------------------------------------------
# Refused / don't know codes become missing
dat$ALQ130[dat$ALQ130 %in% c(777, 999)] <- NA
dat$DIQ010[dat$DIQ010 %in% c(7, 9)] <- NA
dat$DIQ050[dat$DIQ050 %in% c(7, 9)] <- NA
dat$DIQ070[dat$DIQ070 %in% c(7, 9)] <- NA
dat$DMDEDUC2[dat$DMDEDUC2 %in% c(7, 9)] <- NA
dat$HEQ010[dat$HEQ010 %in% c(7, 9)] <- NA
dat$HEQ030[dat$HEQ030 %in% c(7, 9)] <- NA
dat$SMQ020[dat$SMQ020 %in% c(7, 9)] <- NA
dat$SMQ040[dat$SMQ040 %in% c(7, 9)] <- NA

dat$plt <- as_type(with(dat, LBXPLTSI), "continuous")   # Platelet count (x10^9/L)
dat$thrombocytopenia_150 <- as_type(with(dat, plt < 150), "binary")   # Thrombocytopenia - platelets <150 x10^9/L
dat$lsm <- as_type(with(dat, LUXSMED), "continuous")   # Liver stiffness (VCTE median) (kPa)
dat$age <- as_type(with(dat, RIDAGEYR), "continuous")   # Age (years)
dat$female <- as_type(with(dat, RIAGENDR == 2), "binary")   # Female sex
dat$sex <- as_type(with(dat, cases(female == 0, "Male", female == 1, "Female")), "categorical")   # Sex
dat$race_eth <- as_type(with(dat, coalesce(cases(RIDRETH3 == 3, "Non-Hispanic White", RIDRETH3 == 4, "Non-Hispanic Black", RIDRETH3 %in% c(1, 2), "Hispanic", RIDRETH3 == 6, "Non-Hispanic Asian", RIDRETH3 == 7, "Other or multiracial"), cases(RIDRETH1 == 3, "Non-Hispanic White", RIDRETH1 == 4, "Non-Hispanic Black", RIDRETH1 %in% c(1, 2), "Hispanic", RIDRETH1 == 5, "Other or multiracial"))), "categorical")   # Race and ethnicity
dat$pir <- as_type(with(dat, INDFMPIR), "continuous")   # Family income-to-poverty ratio (ratio)
dat$pir_cat <- as_type(with(dat, cases(pir < 1.3, "<1.30", pir < 3.5, "1.30-3.49", pir >= 3.5, "3.50+")), "categorical")   # Income-to-poverty ratio
dat$bmi <- as_type(with(dat, BMXBMI), "continuous")   # Body mass index (kg/m2)
dat$dm_selfreport <- as_type(with(dat, DIQ010 == 1), "binary")   # Self-reported diabetes diagnosis
dat$insulin_use <- as_type(with(dat, DIQ050 == 1), "binary")   # Current insulin use
dat$dm_pills <- as_type(with(dat, DIQ070 == 1), "binary")   # Current oral diabetes medication
dat$hba1c <- as_type(with(dat, LBXGH), "continuous")   # HbA1c (%)
dat$diabetes <- as_type(with(dat, any_of(dm_selfreport, insulin_use, dm_pills, hba1c >= 6.5)), "binary")   # Diabetes (self-report, medication, or HbA1c >=6.5%)
dat$smoking <- as_type(with(dat, cases(SMQ020 == 2, "Never", SMQ040 == 3, "Former", SMQ040 %in% c(1, 2), "Current")), "categorical")   # Smoking status
dat$agecat <- as_type(with(dat, cases(age < 18, "<18", age < 40, "18-39", age < 65, "40-64", age >= 65, "65+")), "categorical")   # Age group (y)
dat$educ <- as_type(with(dat, cases(DMDEDUC2 %in% c(1, 2), "Less than high school", DMDEDUC2 == 3, "High school or GED", DMDEDUC2 == 4, "Some college", DMDEDUC2 == 5, "College graduate or above")), "categorical")   # Educational attainment
dat$alcohol_dpd <- as_type(with(dat, ALQ130), "continuous")   # Alcoholic drinks per drinking day (drinks/day)
dat$hep_b <- as_type(with(dat, HEQ010 == 1), "binary")   # Self-reported hepatitis B
dat$hep_c <- as_type(with(dat, HEQ030 == 1), "binary")   # Self-reported hepatitis C
dat$lsm_per5 <- as_type(with(dat, lsm / 5), "continuous")   # Liver stiffness (VCTE median) (kPa)

# ---- 3. Eligibility (participant flow) -----------------------------------------------------------------
flow <- data.frame(step = "In source files", n = nrow(dat))
step <- function(label, keep) { flow[nrow(flow) + 1, ] <<- list(label, sum(keep)); keep }
keep <- step("Examined in the MEC (positive MEC weight)", !is.na(dat$.wt) & dat$.wt > 0)
dat$.design_ok <- keep
v <- as_lgl(with(dat, age >= 18))
keep <- step("Age >=18 years", keep & !is.na(v) & v)
dat$.in_pop <- keep
keep <- step("Non-missing outcome (Thrombocytopenia - platelets <150 x10^9/L)", keep & !is.na(dat$thrombocytopenia_150))
keep <- step("Non-missing exposure (Liver stiffness (VCTE median))", keep & !is.na(dat$lsm_per5))
dat$.in_analytic <- keep
for (cv in c("age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking")) keep <- keep & !is.na(dat[[cv]])
dat$.in_cc <- step("Complete covariate data (model sample)", keep)
print(flow, row.names = FALSE)
for (v in intersect(c("thrombocytopenia_150", "lsm_per5", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking", "agecat", "educ", "plt", "lsm"), names(dat))) if (is.factor(dat[[v]]))   # drop categories nobody in the study has
  dat[[v]] <- factor(as.character(dat[[v]]), levels = levels(dat[[v]])[levels(dat[[v]]) %in% dat[[v]][dat$.in_analytic]])

# ---- 4. Survey design -----------------------------------------------------------------------------------
# Built on everyone with a positive weight; the study population is then selected with subset(), never by
# dropping rows first, so variance estimation keeps every PSU.
des <- svydesign(ids = ~.psu, strata = ~.strata, weights = ~.wt, nest = TRUE, data = dat[dat$.design_ok, ])
d_cc <- subset(des, .in_cc)             # complete-case model sample
d_an <- subset(des, .in_analytic)       # analytic population (descriptive estimates)
cat("\nDesign df:", degf(des), "  model-sample df:", degf(d_cc), "\n")

# ---- 5. Weighted prevalence / means ---------------------------------------------------------------------
des$variables$.ind_thrombocytopenia_150 <- as.integer(des$variables$thrombocytopenia_150 == 1)
print(svyciprop(~.ind_thrombocytopenia_150, subset(des, .in_analytic & !is.na(.ind_thrombocytopenia_150)), method = "beta"))   # Thrombocytopenia - platelets <150 x10^9/L, overall
print(svyby(~.ind_thrombocytopenia_150, ~sex, subset(des, .in_analytic & !is.na(.ind_thrombocytopenia_150)), svyciprop, method = "beta", vartype = "ci"))
print(svyby(~.ind_thrombocytopenia_150, ~agecat, subset(des, .in_analytic & !is.na(.ind_thrombocytopenia_150)), svyciprop, method = "beta", vartype = "ci"))

# ---- 6. Regression models ----------------------------------------------------------------------------
# Outcome thrombocytopenia_150 (Thrombocytopenia - platelets <150 x10^9/L), exposure lsm_per5 (Liver stiffness (VCTE median)), family quasipoisson.
models <- list()
models$crude <- fit_model(d_cc, "thrombocytopenia_150", c("lsm_per5"), "quasipoisson")   # Unadjusted
models$demographic <- fit_model(d_cc, "thrombocytopenia_150", c("lsm_per5", "age", "sex", "race_eth"), "quasipoisson")   # Adjusted for age, sex, and race and ethnicity
models$full <- fit_model(d_cc, "thrombocytopenia_150", c("lsm_per5", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking"), "quasipoisson")   # Fully adjusted (primary)   # PRIMARY

primary <- exposure_row(models$full, "lsm_per5")
cat("\nPRIMARY ESTIMATE:", sprintf("%s %.4f (95%% CI %.4f to %.4f), p = %.3g\n", primary$term, primary$est, primary$lcl, primary$ucl, primary$p))

# ---- 7. Effect modification (Wald test of the product term) --------------------------------------------
m_int <- fit_model(d_cc, "thrombocytopenia_150", c("lsm_per5", "age", "race_eth", "pir_cat", "bmi", "diabetes", "smoking", "sex", "lsm_per5:sex"), "quasipoisson", show = FALSE)
if (!is.null(attr(m_int, "fit")) && any(grepl(":", m_int$term))) print(regTermTest(attr(m_int, "fit"), ~lsm_per5:sex, df = max(degf(d_cc), 1))) else message("  interaction with sex: not estimable")   # by Sex
m_int <- fit_model(d_cc, "thrombocytopenia_150", c("lsm_per5", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking", "agecat", "lsm_per5:agecat"), "quasipoisson", show = FALSE)
if (!is.null(attr(m_int, "fit")) && any(grepl(":", m_int$term))) print(regTermTest(attr(m_int, "fit"), ~lsm_per5:agecat, df = max(degf(d_cc), 1))) else message("  interaction with agecat: not estimable")   # by Age group

# ---- 8. Sensitivity analyses ---------------------------------------------------------------------------
# s1: Exclude heavy alcohol (>2 drinks/day men, >1 women)
v <- as_lgl(with(des$variables, coalesce(alcohol_dpd, 0) > ifelse(female == 1, 1, 2)))
sel <- !(!is.na(v) & v)
exposure_row(fit_model(subset(des, .in_cc & sel), "thrombocytopenia_150", c("lsm_per5", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking"), "quasipoisson"), "lsm_per5")
# s2: Exclude self-reported hepatitis B or C
v <- as_lgl(with(des$variables, coalesce(hep_b, 0) == 1 | coalesce(hep_c, 0) == 1))
sel <- !(!is.na(v) & v)
exposure_row(fit_model(subset(des, .in_cc & sel), "thrombocytopenia_150", c("lsm_per5", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking"), "quasipoisson"), "lsm_per5")
# s3: Logistic regression (odds ratio)
exposure_row(fit_model(d_cc, "thrombocytopenia_150", c("lsm_per5", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking"), "quasibinomial"), "lsm_per5")
# s4: Multiple imputation of missing covariates (m = 10)
#   Multiple imputation (mice, then svyglm on each imputed design and Rubin's rules) is run by the Q2E engine;
#   see reproduce.R in the bundle. It is not repeated here to keep this script short.
# s5: Exposure in weighted quartiles (Q4 vs Q1, P for trend)
q <- svyquantile(~lsm_per5, d_cc, c(.25, .5, .75), ci = FALSE)[[1]]
des$variables$lsm_per5_q <- cut(des$variables$lsm_per5, c(-Inf, q, Inf), labels = paste0("Q", 1:4), right = FALSE)
fit_model(subset(des, .in_cc), "thrombocytopenia_150", c("lsm_per5_q", "age", "sex", "race_eth", "pir_cat", "bmi", "diabetes", "smoking"), "quasipoisson")
# s6: Unweighted analysis (design ignored)
summary(glm(thrombocytopenia_150 ~ lsm_per5 + age + sex + race_eth + pir_cat + bmi + diabetes + smoking, data = des$variables[des$variables$.in_cc, ], family = quasipoisson(link = "log")))$coefficients   # ignores the design

# ---- Check against the Q2E run ---------------------------------------------------------------------------
q2e_primary <- 1.1949309728   # Liver stiffness (VCTE median) (per 5 kPa) reported by the Q2E engine
if (exists("primary")) cat("Matches the Q2E run:", isTRUE(all.equal(primary$est, q2e_primary, tolerance = 1e-6)), "\n")
