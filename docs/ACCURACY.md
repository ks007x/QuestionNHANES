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
