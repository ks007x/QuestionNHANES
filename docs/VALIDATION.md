# Validation and quality control

## Automated checks (every run)
| ID | Area | Fails / warns when |
|---|---|---|
| variable_availability | Data | a requested variable is absent from a source file |
| synthetic_data | Data | synthetic files were used (always flagged) |
| cycle_overlap | Design | 2017-2018 (J) is combined with 2017-March 2020 (P) |
| weight_choice | Design | the weight does not match the most restrictive component (interview < MEC < fasting) |
| weight_values | Design | analytic records have missing or zero weights; reports the weighted population represented |
| design_df | Design | analytic df (#PSU − #strata) < 8 |
| sample_size | Sample | analytic n < 300 (warn) or < 100 (fail) |
| events_per_parameter | Model | fewer than 10 events per parameter |
| missing_outcome | Missing data | outcome missing in > 10% (warn) or > 25% (fail) of the eligible population |
| missing_covariates | Missing data | complete-case loss > 10% (MI recommended) |
| value_ranges | Data | raw values fall outside dictionary plausibility ranges (non-response codes 7/9/77/99… are recoded first) |
| nchs_standards | Reporting | proportions fail NCHS presentation standards (effective n < 30, CI width ≥ 30 points, relative CI width > 130%, df < 8) |
| model_convergence | Model | non-convergence, errors or warnings |
| implausible_estimates | Model | a ratio estimate falls outside 0.1–10 or SE(log) > 2.5 |
| design_df_params | Model | more model parameters than design df |
| collinearity | Model | VIF ≥ 5 |
| robustness | Robustness | a sensitivity analysis disagrees in direction (associations) or in magnitude (prevalence) |
| benchmark_* | External validity | the estimate's CI does not overlap the published estimate |
| derivations | Data | a derived variable is entirely missing |
| age_topcode | Data | info: NHANES age top-coding at 80 years |

## Pre-execution review (Reviewer agent)
Overlapping cycles, variables unavailable in the selected cycles, causal language, odds ratios for common outcomes,
unverified or secondary-source definitions, unacknowledged operational assumptions, over-adjustment (mediators and
definitional overlap), ferritin without handling of inflammation, unhandled pregnancy, a missing MI sensitivity
analysis, multiplicity, HbA1c with anemia, small subpopulations, unapproved AI-proposed variables, and unmapped
building blocks in uploaded datasets.

## Software tests
* `r/tests/testthat`: the expression whitelist blocks `system()`, assignment and `get()`; `cases()` semantics; `any_of()` missing-data logic; a CKD-EPI 2021 worked example (50-year-old man, creatinine 1.0 → 92); the functional iron deficiency definition.
* `tests/`: knowledge-base integrity (every measure maps to the dictionary, every definition cites a source), planner behaviour on all example questions, reviewer fixes, compiler topological order and weight selection, privacy scrubbing, the causal-language guard, tamper detection in the ledger, end-to-end R runs (prevalence and association) with QC assertions, manuscript and bundle generation, and the bring-your-own-dataset path.
* Reproducibility: running `reproduce.R` from a bundle re-ran the analysis and matched the primary estimate exactly.

## Replication target
`fid_tawfik2024` and `aid_tawfik2024` carry the published NHANES 2017–March 2020 estimates (15% [14–17] functional
and 14% [13–15] absolute iron deficiency among 8,021 adults). Running the FID example on the official P-cycle files
gives a direct replication test of Tawfik et al. With synthetic data the comparison only demonstrates the mechanism.

## Borderline-question stress test (sleep and functional status)

16 questions where NHANES only partly measures what a clinician means. `tests/test_borderline.py` locks in the behaviour.

| Question | What Q2E does |
|---|---|
| Short sleep vs obesity | SLD012 <7 h vs BMI >=30 (binary definitions, not continuous BMI) |
| "Obstructive sleep apnea" vs hypertension | Frequent snoring / witnessed apneas proxy (SLQ030/040); major review item: no PSG/AHI |
| Insomnia vs depression | SLQ050 vs PHQ-9 >=10; flags PHQ-9 item-3 circularity and adds PHQ-8 sensitivity analysis (either direction) |
| Daytime sleepiness vs diabetes | SLQ120 "often/almost always" |
| Functional limitation (older adults with diabetes) | PFQ061B/C mobility limitation |
| Disability in CKD | Washington-Group-style DLQ items |
| Poor sleep -> weight *gain* over time | Not answerable: weight change is longitudinal |
| Restless legs syndrome | Not answerable: not measured |
| Frailty | Not answerable as stated: frailty index not encoded; suggests functional limitation/disability |
| Shift work, muscle mass, grip strength, falls, cognition | "Measured but not curated" with the NHANES component (OCQ, DXX, MGX, BAQ, CFQ) and cycle limits |
| Physical activity -> mortality | Hard stop (linked mortality file, not NHANES exam data) |
