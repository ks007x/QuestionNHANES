#!/usr/bin/env Rscript
# -----------------------------------------------------------------------------
# Generate SYNTHETIC NHANES-like XPT files for offline demos and CI.
#
#   Rscript r/synth/make_synthetic_nhanes.R [outdir] [n] [seed]
#
# The files mimic NHANES 2017-March 2020 pre-pandemic (P_*) file names,
# variable names, codes, complex design (strata/PSU) and weights, with
# clinically plausible correlations (e.g., central adiposity -> HbA1c beyond
# BMI; inflammation -> higher ferritin / lower TSAT; liver stiffness ->
# lower platelets). They are NOT real NHANES data and every Q2E output
# produced from them is watermarked as synthetic.
# -----------------------------------------------------------------------------
suppressPackageStartupMessages(library(haven))

args <- commandArgs(trailingOnly = TRUE)
outdir <- if (length(args) >= 1) args[1] else "data/synthetic"
n <- if (length(args) >= 2) as.integer(args[2]) else 12000L
seed <- if (length(args) >= 3) as.integer(args[3]) else 20261010L
set.seed(seed)
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

rbern <- function(p) stats::rbinom(length(p), 1, pmin(pmax(p, 0), 1))
inv_logit <- function(x) 1 / (1 + exp(-x))
na_frac <- function(x, frac) { x[stats::runif(length(x)) < frac] <- NA; x }

SEQN <- 109263L + seq_len(n)
# ---- design: 15 strata x 2-3 PSUs ------------------------------------------------
SDMVSTRA <- sample(173:187, n, replace = TRUE)
SDMVPSU <- ifelse(SDMVSTRA %% 4 == 0, sample(1:3, n, replace = TRUE), sample(1:2, n, replace = TRUE))
psu_id <- paste(SDMVSTRA, SDMVPSU)
psu_eff <- stats::setNames(stats::rnorm(length(unique(psu_id)), 0, 0.12), unique(psu_id))[psu_id]

# ---- demographics --------------------------------------------------------------------
RIAGENDR <- sample(1:2, n, replace = TRUE, prob = c(0.49, 0.51))
RIDAGEYR <- pmin(80L, as.integer(round(c(stats::runif(round(n * 0.28), 0, 18), stats::runif(n - round(n * 0.28), 18, 86)))))[sample(n)]
RIDRETH3 <- sample(c(1, 2, 3, 4, 6, 7), n, replace = TRUE, prob = c(.14, .10, .34, .25, .11, .06))
INDFMPIR <- round(pmin(5, 5 * stats::rbeta(n, 1.6, 1.4) - 0.25 * (RIDRETH3 %in% c(1, 2, 4))), 2)
INDFMPIR[INDFMPIR < 0] <- 0
INDFMPIR <- na_frac(INDFMPIR, 0.10)
DMDEDUC2 <- ifelse(RIDAGEYR >= 20, sample(1:5, n, replace = TRUE, prob = c(.07, .10, .25, .31, .27)), NA)
DMDEDUC2[!is.na(DMDEDUC2) & stats::runif(n) < 0.004] <- 9
female <- RIAGENDR == 2
RIDEXPRG <- ifelse(female & RIDAGEYR >= 20 & RIDAGEYR <= 44, ifelse(stats::runif(n) < 0.035, 1, 2), NA)
RIDSTATR <- ifelse(stats::runif(n) < 0.94, 2L, 1L)
examined <- RIDSTATR == 2

# weights: over-sampling of Black/Hispanic/Asian/older/low-income -> smaller weights
base_w <- 26000 * exp(stats::rnorm(n, 0, 0.45)) * ifelse(RIDRETH3 %in% c(1, 2, 4, 6), 0.55, 1.25) * ifelse(RIDAGEYR >= 80, 0.7, 1)
WTINTPRP <- base_w * 330e6 / sum(base_w)
WTMECPRP <- ifelse(examined, WTINTPRP / 0.94 * exp(stats::rnorm(n, 0, 0.05)), 0)

adult <- RIDAGEYR >= 18
# ---- anthropometry ---------------------------------------------------------------------
BMXHT <- ifelse(adult, ifelse(female, stats::rnorm(n, 161.5, 7), stats::rnorm(n, 175, 7.5)), 75 + RIDAGEYR * 5.6 + stats::rnorm(n, 0, 6))
BMXBMI <- ifelse(adult, exp(stats::rnorm(n, log(29) - 0.03 * (RIDRETH3 == 6), 0.21)), exp(stats::rnorm(n, log(16 + 0.25 * RIDAGEYR), 0.15)))
BMXWT <- BMXBMI * (BMXHT / 100)^2
central <- stats::rnorm(n, 0, 1)  # visceral adiposity phenotype independent of BMI
BMXWAIST <- ifelse(adult, 18 + 2.35 * BMXBMI + 4.5 * (!female) + 0.10 * RIDAGEYR + 4.2 * central, 35 + 2.0 * BMXBMI + stats::rnorm(n, 0, 3))
BMXHIP <- BMXWAIST * stats::rnorm(n, 1.06, 0.05)
bmx_miss <- !examined | stats::runif(n) < 0.03
for (v in c("BMXHT", "BMXBMI", "BMXWT", "BMXWAIST", "BMXHIP")) assign(v, ifelse(bmx_miss, NA, round(get(v), 1)))

# ---- inflammation / iron -----------------------------------------------------------------
LBXHSCRP <- round(exp(stats::rnorm(n, log(1.6) + 0.045 * (ifelse(is.na(BMXBMI), 28, BMXBMI) - 28) + 0.35 * female, 1.05)), 2)
infl <- log1p(LBXHSCRP)
menstrual <- female & RIDAGEYR >= 12 & RIDAGEYR < 51
logfer <- ifelse(female, ifelse(menstrual, 3.42, 4.38), 4.92) + 0.004 * pmax(RIDAGEYR - 18, 0) * (!female) + 0.22 * infl + psu_eff + stats::rnorm(n, 0, 0.92)
LBXFER <- round(exp(logfer), 1)
LBXFER[sample(which(examined & adult), 3)] <- c(9999, 8500, 0.2)   # implausible values: QC should catch these
TSAT <- 32.8 - 3.6 * infl - 7.5 * (LBXFER < 20) + stats::rnorm(n, 0, 7.6) - 1.8 * female
TSAT <- pmin(pmax(TSAT, 2), 95)
LBDTIB <- round(stats::rnorm(n, 335, 48) + 45 * (LBXFER < 30) - 20 * infl, 0)
LBXIRN <- round(TSAT * LBDTIB / 100, 0)
LBXUIB <- LBDTIB - LBXIRN
LBDPCT <- round(100 * LBXIRN / LBDTIB, 0)
iron_lab <- examined & RIDAGEYR >= 12 & stats::runif(n) > 0.08
LBXFER[!iron_lab] <- NA; LBXIRN[!iron_lab] <- NA; LBDTIB[!iron_lab] <- NA; LBXUIB[!iron_lab] <- NA; LBDPCT[!iron_lab] <- NA
LBXHSCRP[!(examined & RIDAGEYR >= 1) | stats::runif(n) < 0.06] <- NA

# ---- kidney ------------------------------------------------------------------------------------
LBXSCR <- round(exp(stats::rnorm(n, log(ifelse(female, 0.74, 0.95)) + 0.006 * pmax(RIDAGEYR - 40, 0), 0.19)), 2)
URDACT <- round(exp(stats::rnorm(n, log(8) + 0.012 * pmax(RIDAGEYR - 40, 0), 1.05)), 1)
KIQ025 <- ifelse(adult, ifelse(stats::runif(n) < 0.003, 1, 2), NA)
LBXSCR[KIQ025 %in% 1] <- round(stats::runif(sum(KIQ025 %in% 1), 4, 9), 2)
KIQ022 <- ifelse(adult, ifelse(LBXSCR > 1.6 & stats::runif(n) < 0.5 | stats::runif(n) < 0.02, 1, 2), NA)

# ---- glycemia ------------------------------------------------------------------------------------
bmi0 <- ifelse(is.na(BMXBMI), 29, BMXBMI); waist0 <- ifelse(is.na(BMXWAIST), 98, BMXWAIST)
p_dm <- inv_logit(-5.3 + 0.045 * (RIDAGEYR) + 0.040 * (bmi0 - 28) + 0.42 * central + 0.35 * (RIDRETH3 %in% c(1, 4, 6)))
dm <- adult & rbern(p_dm) == 1
LBXGH <- round(5.25 + 0.006 * RIDAGEYR + 0.006 * (bmi0 - 28) + 0.085 * central + 0.12 * (RIDRETH3 == 4) +
               dm * stats::rnorm(n, 1.9, 1.3) + stats::rnorm(n, 0, 0.28), 1)
LBXGH <- pmax(LBXGH, 4.0)
DIQ010 <- ifelse(RIDAGEYR >= 1, ifelse(dm & stats::runif(n) < 0.78, 1, ifelse(stats::runif(n) < 0.03, 3, 2)), NA)
DIQ010[stats::runif(n) < 0.002 & !is.na(DIQ010)] <- 9
DIQ050 <- ifelse(DIQ010 %in% 1 & stats::runif(n) < 0.3, 1, ifelse(!is.na(DIQ010), 2, NA))
DIQ070 <- ifelse(DIQ010 %in% 1 & stats::runif(n) < 0.7, 1, ifelse(DIQ010 %in% c(1, 3), 2, NA))
fasting <- examined & RIDAGEYR >= 12 & stats::runif(n) < 0.45
WTSAFPRP <- ifelse(fasting, WTMECPRP * 2.2 * exp(stats::rnorm(n, 0, 0.08)), 0)
LBXGLU <- ifelse(fasting, round(28.7 * LBXGH - 46.7 + stats::rnorm(n, 0, 9)), NA)
LBXIN <- ifelse(fasting, round(exp(stats::rnorm(n, log(9) + 0.05 * (bmi0 - 28), 0.5)), 2), NA)
LBXTR <- ifelse(fasting, round(exp(stats::rnorm(n, log(105) + 0.02 * (bmi0 - 28), 0.5))), NA)
LBXGH[!(examined & RIDAGEYR >= 12) | stats::runif(n) < 0.04] <- NA

# ---- liver -------------------------------------------------------------------------------------------
LBXSATSI <- round(exp(stats::rnorm(n, log(20) + 0.025 * (bmi0 - 28) + 0.2 * (!female), 0.45)))
LBXSASSI <- round(exp(stats::rnorm(n, log(21) + 0.3 * log(LBXSATSI / 20), 0.3)))
HEQ030 <- ifelse(RIDAGEYR >= 6, ifelse(stats::runif(n) < 0.012, 1, 2), NA)
HEQ010 <- ifelse(RIDAGEYR >= 6, ifelse(stats::runif(n) < 0.007, 1, 2), NA)
ALQ130 <- ifelse(adult, pmax(1, round(stats::rgamma(n, 1.4, 0.6))), NA)
ALQ121 <- ifelse(adult, sample(0:10, n, replace = TRUE, prob = c(.25, .02, .04, .06, .08, .1, .1, .1, .1, .1, .05)), NA)
ALQ130[ALQ121 %in% 0] <- NA
loglsm <- log(4.8) + 0.022 * (bmi0 - 28) + 0.35 * dm + 0.25 * log(LBXSATSI / 20) + 0.9 * (HEQ030 %in% 1) +
          0.06 * pmax(ifelse(is.na(ALQ130), 0, ALQ130) - 2, 0) + stats::rnorm(n, 0, 0.33)
cirr <- stats::runif(n) < 0.012
loglsm[cirr] <- log(stats::runif(sum(cirr), 12, 45))
LUXSMED <- round(exp(loglsm), 1)
LUAXSTAT <- ifelse(examined & RIDAGEYR >= 12, sample(1:3, n, replace = TRUE, prob = c(.91, .06, .03)), NA)
LUXSIQR <- round(LUXSMED * stats::runif(n, 0.04, 0.36), 1)
LUXCAPM <- round(pmin(400, pmax(100, 238 + 3.6 * (bmi0 - 28) + 12 * dm + stats::rnorm(n, 0, 38))))
nolux <- !(LUAXSTAT %in% 1)
LUXSMED[nolux] <- NA; LUXSIQR[nolux] <- NA; LUXCAPM[nolux] <- NA

# ---- blood count -----------------------------------------------------------------------------------
LBXHGB <- round(ifelse(female, 13.4, 15.1) - 1.1 * (LBXFER < 15 & !is.na(LBXFER)) - 0.35 * (LBXFER < 30 & !is.na(LBXFER)) -
                0.9 * (LBXSCR > 1.5) - 0.25 * infl + stats::rnorm(n, 0, 0.95), 1)
LBXHGB[!is.na(RIDEXPRG) & RIDEXPRG == 1] <- LBXHGB[!is.na(RIDEXPRG) & RIDEXPRG == 1] - 1.0
LBXMCVSI <- round(89 - 6 * (LBXFER < 15 & !is.na(LBXFER)) + stats::rnorm(n, 0, 4.5), 1)
LBXRDW <- round(13.3 + 1.4 * (LBXFER < 15 & !is.na(LBXFER)) + stats::rnorm(n, 0, 0.9), 1)
LBXPLTSI <- round(pmax(20, stats::rnorm(n, 255 - 18 * (!female), 55) - 7.5 * pmax(LUXSMED - 6, 0, na.rm = FALSE) * 1))
LBXPLTSI[is.na(LBXPLTSI)] <- round(pmax(20, stats::rnorm(sum(is.na(LBXPLTSI)), 255, 55)))
LBXWBCSI <- round(exp(stats::rnorm(n, log(7) + 0.1 * infl, 0.25)), 1)
cbc_miss <- !(examined & RIDAGEYR >= 1) | stats::runif(n) < 0.04
for (v in c("LBXHGB", "LBXMCVSI", "LBXRDW", "LBXPLTSI", "LBXWBCSI")) assign(v, ifelse(cbc_miss, NA, get(v)))
bio_miss <- !(examined & RIDAGEYR >= 12) | stats::runif(n) < 0.05
LBXSCR[bio_miss] <- NA; LBXSATSI[bio_miss] <- NA; LBXSASSI[bio_miss] <- NA
LBXSAL <- ifelse(bio_miss, NA, round(stats::rnorm(n, 4.2, 0.3), 1))
LBXSGTSI <- ifelse(bio_miss, NA, round(exp(stats::rnorm(n, log(22), 0.6))))
LBXSAPSI <- ifelse(bio_miss, NA, round(exp(stats::rnorm(n, log(75), 0.3))))
LBXSTB <- ifelse(bio_miss, NA, round(exp(stats::rnorm(n, log(0.5), 0.4)), 1))
URDACT[!(examined & RIDAGEYR >= 6) | stats::runif(n) < 0.06] <- NA
LBXTC <- ifelse(examined & RIDAGEYR >= 6, round(stats::rnorm(n, 188, 38)), NA)
LBDHDD <- ifelse(examined & RIDAGEYR >= 6, round(stats::rnorm(n, 53 - 0.4 * (bmi0 - 28), 14)), NA)

# ---- questionnaire --------------------------------------------------------------------------------
yn <- function(p, elig) ifelse(elig, ifelse(stats::runif(length(p)) < p, 1, 2), NA)
MCQ160B <- yn(0.004 + 0.0007 * pmax(RIDAGEYR - 40, 0), adult)
MCQ160C <- yn(0.004 + 0.001 * pmax(RIDAGEYR - 40, 0), adult)
MCQ160F <- yn(0.003 + 0.0008 * pmax(RIDAGEYR - 40, 0), adult)
MCQ220 <- yn(0.01 + 0.0025 * pmax(RIDAGEYR - 30, 0), adult)
MCQ160L <- yn(0.03, adult)
MCQ053 <- yn(0.015 + 0.03 * menstrual, RIDAGEYR >= 1)
BPQ020 <- yn(0.05 + 0.007 * pmax(RIDAGEYR - 20, 0), RIDAGEYR >= 16)
SMQ020 <- yn(0.42 - 0.12 * female, adult)
SMQ040 <- ifelse(SMQ020 %in% 1, sample(1:3, n, replace = TRUE, prob = c(.30, .07, .63)), NA)
SMQ020[!is.na(SMQ020) & stats::runif(n) < 0.002] <- 7
HIQ011 <- yn(0.9, TRUE)
RHQ031 <- ifelse(female & RIDAGEYR >= 12, ifelse(menstrual & stats::runif(n) < 0.9, 1, 2), NA)
SLD012 <- ifelse(RIDAGEYR >= 16, round(pmin(14, pmax(2, stats::rnorm(n, 7.6, 1.4))) * 2) / 2, NA)

# ---- expansion modules ---------------------------------------------------------------------------
DMDBORN4 <- ifelse(stats::runif(n) < ifelse(RIDRETH3 %in% c(1, 2, 6), 0.45, 0.92), 1, 2)
DMQMILIZ <- ifelse(adult, ifelse(stats::runif(n) < ifelse(female, 0.02, 0.13) * (1 + (RIDAGEYR > 60)), 1, 2), NA)
BMXARMC <- ifelse(bmx_miss, NA, round(14 + 0.55 * bmi0 + 2 * (!female) + stats::rnorm(n, 0, 2), 1))
# blood pressure (3 oscillometric readings) and treatment
sbp_true <- 108 + 0.45 * pmax(RIDAGEYR - 18, 0) + 0.55 * (bmi0 - 28) + 5 * (RIDRETH3 == 4) + 4 * (!female) + stats::rnorm(n, 0, 13)
BPQ040A <- ifelse(BPQ020 %in% 1, ifelse(stats::runif(n) < 0.8, 1, 2), NA)
BPQ050A <- ifelse(BPQ040A %in% 1, ifelse(stats::runif(n) < 0.85, 1, 2), NA)
sbp_true[BPQ050A %in% 1] <- sbp_true[BPQ050A %in% 1] - 8
dbp_true <- 70 + 0.18 * (sbp_true - 120) + stats::rnorm(n, 0, 8)
bp_elig <- examined & RIDAGEYR >= 8 & stats::runif(n) > 0.05
for (i in 1:3) {
  assign(paste0("BPXOSY", i), ifelse(bp_elig, round(sbp_true + stats::rnorm(n, 0, 4)), NA))
  assign(paste0("BPXODI", i), ifelse(bp_elig, round(dbp_true + stats::rnorm(n, 0, 3)), NA))
}
# extra labs
LBDLDL <- ifelse(fasting, round(stats::rnorm(n, 112, 33)), NA)
LBXSUA <- ifelse(is.na(LBXSCR), NA, round(4.2 + 1.3 * (!female) + 0.06 * (bmi0 - 28) + 0.8 * (LBXSCR - 0.9) + stats::rnorm(n, 0, 1.1), 1))
LBXSBU <- ifelse(is.na(LBXSCR), NA, round(9 + 8 * LBXSCR + stats::rnorm(n, 0, 3)))
LBXSTP <- ifelse(is.na(LBXSCR), NA, round(stats::rnorm(n, 7.1, 0.4), 1))
anc_mu <- log(4.1) - 0.42 * (RIDRETH3 == 4) + 0.12 * infl + 0.15 * (SMQ040 %in% c(1, 2))
LBDNENO <- ifelse(cbc_miss, NA, round(exp(stats::rnorm(n, anc_mu, 0.42)), 1))
LBDLYMNO <- ifelse(cbc_miss, NA, round(exp(stats::rnorm(n, log(2.1), 0.32)), 1))
LBDMONO <- ifelse(cbc_miss, NA, round(exp(stats::rnorm(n, log(0.55), 0.3)), 1))
LBDEONO <- ifelse(cbc_miss, NA, round(exp(stats::rnorm(n, log(0.18), 0.6)), 1))
LBXRBCSI <- ifelse(cbc_miss, NA, round(LBXHGB / 2.95 + stats::rnorm(n, 0, 0.15), 2))
LBXHCT <- ifelse(cbc_miss, NA, round(LBXHGB * 2.95 + stats::rnorm(n, 0, 0.8), 1))
LBXMCHSI <- ifelse(cbc_miss, NA, round(LBXMCVSI / 3.0 + stats::rnorm(n, 0, 0.6), 1))
LBXMPSI <- ifelse(cbc_miss, NA, round(stats::rnorm(n, 8.3, 0.9), 1))
smk_now <- SMQ040 %in% c(1, 2)
LBXCOT <- ifelse(examined & RIDAGEYR >= 3 & stats::runif(n) > 0.05, round(ifelse(smk_now, exp(stats::rnorm(n, log(180), 0.8)), exp(stats::rnorm(n, log(0.03), 1.4))), 3), NA)
LBXBPB <- ifelse(examined & RIDAGEYR >= 1 & stats::runif(n) > 0.1, round(exp(stats::rnorm(n, log(0.85) + 0.006 * RIDAGEYR + 0.2 * smk_now - 0.15 * female, 0.55)), 2), NA)
LBXBCD <- ifelse(!is.na(LBXBPB), round(exp(stats::rnorm(n, log(0.25) + 1.0 * smk_now, 0.6)), 2), NA)
LBXTHG <- ifelse(!is.na(LBXBPB), round(exp(stats::rnorm(n, log(0.7) + 0.3 * (RIDRETH3 == 6), 0.9)), 2), NA)
# depression (PHQ-9), sleep, activity, food security
dep_lat <- stats::rnorm(n, 0, 1) + 0.35 * female + 0.25 * (INDFMPIR < 1.3 & !is.na(INDFMPIR)) + 0.2 * infl
phq_resp <- adult & stats::runif(n) > 0.08
for (i in 1:9) assign(sprintf("DPQ0%d0", i), ifelse(phq_resp & stats::runif(n) > 0.004,
                                                   pmin(3, pmax(0, round(0.35 + 0.55 * dep_lat + stats::rnorm(n, 0, 0.55)))), NA))
SLQ050 <- yn(0.2 + 0.1 * (dep_lat > 1), RIDAGEYR >= 16)
ord <- function(p, ok) { v <- sample(seq_along(p) - 1, n, replace = TRUE, prob = p); v[!ok] <- NA; v }
SLQ030 <- ifelse(RIDAGEYR >= 16, pmin(3, ord(c(.30, .25, .25, .20), TRUE) + (bmi0 > 32 & stats::runif(n) < 0.4)), NA)
SLQ040 <- ifelse(RIDAGEYR >= 16, pmin(3, ord(c(.75, .13, .08, .04), TRUE) + (bmi0 > 35 & stats::runif(n) < 0.3)), NA)
SLQ120 <- ifelse(RIDAGEYR >= 16, pmin(4, ord(c(.22, .30, .28, .13, .07), TRUE) + (dep_lat > 1.2)), NA)
frail_lat <- 0.04 * pmax(RIDAGEYR - 40, 0) + 0.04 * pmax(bmi0 - 30, 0) + 0.5 * (dep_lat > 1) + stats::rnorm(n, 0, 1)
pfq <- function(shift) ifelse(adult, ifelse(stats::runif(n) < 0.02, 5, pmin(4, 1 + (frail_lat + shift > 1.6) + (frail_lat + shift > 2.6) + (frail_lat + shift > 3.4))), NA)
PFQ061B <- pfq(0); PFQ061C <- pfq(0.15); PFQ061H <- pfq(-1); PFQ061L <- pfq(-0.8)
DLQ050 <- ifelse(RIDAGEYR >= 5, ifelse(frail_lat + stats::rnorm(n, 0, .3) > 2.3, 1, 2), NA)
DLQ060 <- ifelse(RIDAGEYR >= 5, ifelse(frail_lat + stats::rnorm(n, 0, .3) > 3.0, 1, 2), NA)
DLQ040 <- ifelse(RIDAGEYR >= 5, ifelse(frail_lat + dep_lat + stats::rnorm(n, 0, .5) > 3.2, 1, 2), NA)
DLQ080 <- ifelse(RIDAGEYR >= 15, ifelse(frail_lat + stats::rnorm(n, 0, .3) > 2.9, 1, 2), NA)
PAQ650 <- yn(0.35 - 0.003 * pmax(RIDAGEYR - 20, 0), RIDAGEYR >= 12)
PAQ665 <- yn(0.5, RIDAGEYR >= 12)
PAD680 <- ifelse(RIDAGEYR >= 12, round(pmin(1200, pmax(0, stats::rnorm(n, 330, 160)))), NA)
FSDAD <- sample(1:4, n, replace = TRUE, prob = c(.72, .10, .11, .07))
FSDAD[INDFMPIR %in% NA] <- FSDAD[INDFMPIR %in% NA]
FSDAD[!is.na(INDFMPIR) & INDFMPIR < 1] <- sample(1:4, sum(!is.na(INDFMPIR) & INDFMPIR < 1), replace = TRUE, prob = c(.45, .15, .22, .18))
# other conditions
MCQ010 <- yn(0.14, RIDAGEYR >= 1); MCQ160A <- yn(0.05 + 0.006 * pmax(RIDAGEYR - 30, 0), adult)
MCQ160O <- yn(0.02 + 0.06 * smk_now + 0.0007 * pmax(RIDAGEYR - 40, 0), adult); MCQ160M <- yn(0.06 + 0.1 * female, adult)
KIQ026 <- yn(0.09, adult); DIQ160 <- yn(0.08, RIDAGEYR >= 12)
# dietary day-1 recall (separate dietary weights; ~88% of examinees with a reliable recall)
diet_ok <- examined & stats::runif(n) < 0.88
DR1DRSTZ <- ifelse(examined, ifelse(diet_ok, 1, sample(2:5, n, replace = TRUE)), NA)
DR1TKCAL <- ifelse(diet_ok, round(pmax(400, stats::rnorm(n, ifelse(female, 1800, 2400), 650))), NA)
DR1TPROT <- ifelse(diet_ok, round(DR1TKCAL * stats::rnorm(n, 0.04, 0.008), 1), NA)
DR1TIRON <- ifelse(diet_ok, round(DR1TKCAL * stats::rnorm(n, 0.0068, 0.002), 1), NA)
DR1TFIBE <- ifelse(diet_ok, round(pmax(1, DR1TKCAL * stats::rnorm(n, 0.0085, 0.003)), 1), NA)
DR1TSODI <- ifelse(diet_ok, round(DR1TKCAL * stats::rnorm(n, 1.6, 0.35)), NA)
DR1TSUGR <- ifelse(diet_ok, round(DR1TKCAL * stats::rnorm(n, 0.048, 0.015), 1), NA)
WTDRD1PP <- ifelse(diet_ok, WTMECPRP * 1.13 * exp(stats::rnorm(n, 0, 0.1)), 0)
# sodium -> blood pressure (so association examples behave plausibly)
for (i in 1:3) assign(paste0("BPXOSY", i), get(paste0("BPXOSY", i)) + ifelse(is.na(DR1TSODI), 0, round(0.6 * (DR1TSODI - 3400) / 1000)))

wr <- function(df, name) {
  df <- as.data.frame(df)
  haven::write_xpt(df, file.path(outdir, paste0(name, ".xpt")), version = 5, name = substr(gsub("[^A-Z]", "", name), 1, 8))
}
wr(data.frame(SEQN, RIDSTATR, RIAGENDR, RIDAGEYR, RIDRETH3, DMDEDUC2, INDFMPIR, RIDEXPRG, DMDBORN4, DMQMILIZ, SDMVPSU, SDMVSTRA, WTINTPRP, WTMECPRP), "P_DEMO")
ex <- examined
wr(data.frame(SEQN, LBXHGB, LBXMCVSI, LBXRDW, LBXPLTSI, LBXWBCSI, LBDNENO, LBDLYMNO, LBDMONO, LBDEONO, LBXRBCSI, LBXHCT, LBXMCHSI, LBXMPSI)[ex, ], "P_CBC")
wr(data.frame(SEQN, LBXFER)[ex & RIDAGEYR >= 1, ], "P_FERTIN")
wr(data.frame(SEQN, LBXIRN, LBXUIB, LBDTIB, LBDPCT)[ex & RIDAGEYR >= 6, ], "P_FETIB")
wr(data.frame(SEQN, LBXHSCRP)[ex & RIDAGEYR >= 1, ], "P_HSCRP")
wr(data.frame(SEQN, LBXSCR, LBXSATSI, LBXSASSI, LBXSAPSI, LBXSGTSI, LBXSAL, LBXSTB, LBXSUA, LBXSBU, LBXSTP)[ex & RIDAGEYR >= 12, ], "P_BIOPRO")
wr(data.frame(SEQN, URDACT)[ex & RIDAGEYR >= 6, ], "P_ALB_CR")
wr(data.frame(SEQN, LBXGH)[ex & RIDAGEYR >= 12, ], "P_GHB")
wr(data.frame(SEQN, LBXGLU, WTSAFPRP)[ex & RIDAGEYR >= 12, ], "P_GLU")
wr(data.frame(SEQN, LBXIN)[ex & RIDAGEYR >= 12, ], "P_INS")
wr(data.frame(SEQN, LBXTR, LBDLDL)[ex & RIDAGEYR >= 12, ], "P_TRIGLY")
wr(data.frame(SEQN, LBXTC)[ex & RIDAGEYR >= 6, ], "P_TCHOL")
wr(data.frame(SEQN, LBDHDD)[ex & RIDAGEYR >= 6, ], "P_HDL")
wr(data.frame(SEQN, BMXWT, BMXHT, BMXBMI, BMXWAIST, BMXHIP, BMXARMC)[ex, ], "P_BMX")
wr(data.frame(SEQN, LUAXSTAT, LUXSMED, LUXSIQR, LUXCAPM)[ex & RIDAGEYR >= 12, ], "P_LUX")
wr(data.frame(SEQN, DIQ010, DIQ050, DIQ070, DIQ160)[RIDAGEYR >= 1, ], "P_DIQ")
wr(data.frame(SEQN, MCQ160B, MCQ160C, MCQ160F, MCQ220, MCQ160L, MCQ053, MCQ010, MCQ160A, MCQ160E = yn(0.004 + 0.0009 * pmax(RIDAGEYR - 40, 0), adult), MCQ160O, MCQ160M), "P_MCQ")
wr(data.frame(SEQN, KIQ022, KIQ025, KIQ026)[adult, ], "P_KIQ_U")
wr(data.frame(SEQN, SMQ020, SMQ040)[adult, ], "P_SMQ")
wr(data.frame(SEQN, ALQ121, ALQ130)[adult, ], "P_ALQ")
wr(data.frame(SEQN, BPQ020, BPQ040A, BPQ050A)[RIDAGEYR >= 16, ], "P_BPQ")
wr(data.frame(SEQN, HEQ010, HEQ030)[RIDAGEYR >= 6, ], "P_HEQ")
wr(data.frame(SEQN, RHQ031)[female & RIDAGEYR >= 12, ], "P_RHQ")
wr(data.frame(SEQN, HIQ011), "P_HIQ")
wr(data.frame(SEQN, SLD012, SLQ050, SLQ030, SLQ040, SLQ120)[RIDAGEYR >= 16, ], "P_SLQ")
wr(data.frame(SEQN, PFQ061B, PFQ061C, PFQ061H, PFQ061L)[adult, ], "P_PFQ")
wr(data.frame(SEQN, DLQ040, DLQ050, DLQ060, DLQ080)[RIDAGEYR >= 5, ], "P_DLQ")
wr(data.frame(SEQN, BPXOSY1, BPXOSY2, BPXOSY3, BPXODI1, BPXODI2, BPXODI3)[ex & RIDAGEYR >= 8, ], "P_BPXO")
wr(data.frame(SEQN, LBXBPB, LBXBCD, LBXTHG)[ex & RIDAGEYR >= 1, ], "P_PBCD")
wr(data.frame(SEQN, LBXCOT)[ex & RIDAGEYR >= 3, ], "P_COT")
wr(data.frame(SEQN, DPQ010, DPQ020, DPQ030, DPQ040, DPQ050, DPQ060, DPQ070, DPQ080, DPQ090)[adult, ], "P_DPQ")
wr(data.frame(SEQN, PAQ650, PAQ665, PAD680)[RIDAGEYR >= 12, ], "P_PAQ")
wr(data.frame(SEQN, FSDAD), "P_FSQ")
wr(data.frame(SEQN, DR1DRSTZ, DR1TKCAL, DR1TPROT, DR1TIRON, DR1TFIBE, DR1TSODI, DR1TSUGR, WTDRD1PP)[ex, ], "P_DR1TOT")
writeLines(c("SYNTHETIC NHANES-LIKE DATA - generated by r/synth/make_synthetic_nhanes.R",
             sprintf("n = %d, seed = %d, generated %s", n, seed, format(Sys.time())),
             "Not real survey data. Use only for software demonstration and testing."), file.path(outdir, "README_SYNTHETIC.txt"))
cat(sprintf("Wrote %d synthetic P_* files to %s\n", length(list.files(outdir, pattern = "xpt$")), normalizePath(outdir)))
