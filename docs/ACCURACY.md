# Accuracy against published NHANES estimates

Q2E is checked against official prevalence figures that NCHS publishes from the same NHANES files
(National Health Statistics Report 158; Data Briefs 508, 511, 515, 516, 519, 527) and against Tawfik et al.,
*JAMA Network Open* 2024. Each question is typed in plain language, Q2E designs and runs the study on CDC
public-use files with no per-question tuning, and its crude weighted prevalence (overall, men, women) is
compared with the published crude estimate.

* Questions and published numbers: [`benchmarks/published_estimates.yaml`](../benchmarks/published_estimates.yaml)
* Runner: `python scripts/benchmark.py` (or GitHub **Actions -> Accuracy benchmark**); reports are saved on the
  `results` branch under `benchmark/`.

## What happened

| Run | What changed | Estimates inside the published 95% CI | Mean absolute difference |
|---|---|---|---|
| 1 | Q2E as it was | 18/23 with the published definition (78%); 18/27 overall (67%); 4 of 15 questions not answered as a prevalence | 3.6 points |
| 2 | Fixes learned from run 1 (below); 13 hold-out questions added | Original 41/41 (100%); hold-out 1 25/28 with the right definition | 0.19 points (original) |
| 3 | Hold-out-1 failures fixed; 8 untouched hold-out-2 questions added | Hold-out 2 (never used for tuning): **20/20 (100%)**, all within 1 point | 0.21 points (hold-out 2) |

| 5 | New estimands: age-adjusted prevalence (36 estimates), trends 1999-2018 by cycle (60), NCHS age groups, a mean with percentiles | New-estimand items 104/104 (100%); all items 220/220 | 0.13 points (new) |
| 6 | Group comparisons (difference and ratio, crude and age-adjusted) | Comparison items 16/16; a published non-significant sex difference reproduced (P = 0.24) | 0.12 points (comparisons) |
| 7 | Hypertension care cascade; fixes from a 65-question stress test | 58 questions, 245/245 estimates (100%), 241 within 1 point | 0.17 points |
| 8 | Regression caught on real data (elastography quality rule dropped by run-7 change) fixed; Q2E's earlier association results added as regression anchors | **245/245 (100%)**; both anchors unchanged (PR 1.1848, n = 6,425; beta 0.1506) | **0.17 points** |

Women's mean height 2015-2018: 161.26 cm vs published 161.3 cm, same sample size (5,510), 5th/50th/95th percentiles
149.9/161.3/172.5 vs 149.8/161.3/172.5.

Two published figures (depression at ages 12-17) come from restricted data that the public files do not contain.
Q2E now says so: it restricts to 18+ with a warning, or declines when most of the requested ages are missing. The
benchmark counts those as correct only when Q2E flags them.

## What Q2E learned from the published studies

| Failure in run 1 | Cause | Fix |
|---|---|---|
| Hypertension 2021-2023 10 points low | A lab-based Table 1 column (HbA1c) switched the whole study to the phlebotomy weight; the BP-medication question was renamed (BPQ050A -> BPQ150) | The weight is set only by the outcome, exposure, model covariates and eligibility; both medication items are read; BP is the mean of up to three readings, as NCHS does |
| Anemia returned no participants | The iron-panel requirement of the iron domain was applied to anemia | Domain requirements apply only when the definition uses them; WHO 2024 cutoffs by age (2+), smoking-adjusted hemoglobin, pregnancy excluded (NCHS Data Brief 519) |
| Diabetes 1-2 points low | Definition without fasting glucose, full-sample weights | National prevalence uses the NCHS definition (diagnosed, FPG >=126 or HbA1c >=6.5%) with fasting weights; diagnosed and undiagnosed diabetes added |
| Absolute iron deficiency +9.5 points | "ferritin below 30" was ignored and the ASH 2026 thresholds used | Cut-points written in the question select the published definition with the same cut-point, or become a yes/no variable |
| Severe obesity, high cholesterol, low HDL answered as means | Thresholds ignored | Same, plus NCHS definitions added to the library |
| Childhood obesity 11 points low | Adult BMI >=30 applied to children | CDC 2000 growth-chart BMI-for-age percentiles (LMS method); adult cut-points are never used under 18 |
| "What percentage of ..." matched an unrelated survey item | Survey wording read as a topic | Wording such as percentage, share and proportion is ignored when matching variables |

Each NCHS definition now carries its published estimate, so every matching study run in the app shows
"Replication of published estimate" in its quality checks.

## Limits

* Prevalence only. Associations (prevalence ratios, odds ratios) are not yet benchmarked against papers with
  identical models; the published-evidence check compares direction and CI overlap from abstracts.
* Q2E reports crude prevalence; age-adjusted figures are not produced yet.
* Reports that give only standard errors are compared with estimate +/- 1.96 SE.

## Estimands Q2E answers

| Estimand | Example question | What runs |
|---|---|---|
| Prevalence (crude and age-adjusted) | "age-adjusted prevalence of obesity in adults 20+" | Korn-Graubard CIs; direct standardization to the 2000 U.S. population (NCHS age groups); subgroup estimates age-adjusted, age-group rows not |
| Trend across cycles | "how has obesity changed from 1999 to 2018?", "did it differ between 2017-2018 and 2021-2023?" | per-cycle crude and age-adjusted estimates, change first to last with CI, test for linear trend |
| Group comparison | "is hypertension more common in men than women?", "racial disparity in ...", "older vs younger adults" | difference and ratio vs the reference group, crude and age-adjusted, design-based test of any difference |
| Mean, median, percentile | "average total cholesterol", "median ferritin", "95th percentile of blood lead" | survey-weighted mean, svyquantile percentiles with CIs, age-adjusted means |
| Count | "how many Americans have diabetes?" | weighted total in millions with CI |
| Association | "is X associated with Y?" | survey GLMs (PR/OR/mean difference), adjustment sets, effect modification, sensitivity analyses |

## Failures anticipated before they happen

Before a protocol is approved, a methods auditor checks known NHANES traps (`knowledge/pitfalls.yaml`): the 2017
switch from auscultatory to oscillometric blood pressure, laboratory method changes, serum creatinine recalibration
(1999-2000, 2005-2006), the 2007 physical-activity questionnaire change, 4-year weights for 1999-2002, race
categories before 2011, age top-coded at 80 (ages above 80 are blocked), and pandemic-era files. The review also
blocks circular questions (an outcome defined from the exposure), adult definitions applied to children, and
questions about ages the public files do not contain; and it flags association questions whose exposure could not
be found instead of quietly answering a different question.

A 65-question stress test of phrasings (tests/test_estimands.py) found and fixed: race words read as blood cells,
"women ... than men" read as two contradictory populations, "non-diabetic" read as diabetic, ages read as
thresholds, cycles named in the question ignored, "hepatitis C antibody" mapped to a self-report item, and others.
