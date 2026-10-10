# Study protocol and statistical analysis plan

## Association of Hypertension With Chronic Kidney Disease Among US Adults: NHANES 2017-March 2020 pre-pandemic

_Plan plan_c5cf21efc8 v1 - sha256 `f3021200b0f1d8ada3c078c21d2d683f21a609e317ad0925c324ce03d1ca26ab` - approved by Investigator on 2026-10-10_

## 1. Research question

- **Clinical observation:** “Is hypertension associated with chronic kidney disease in US adults?”
- **Refined question:** Among noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years; excluding pregnant at examination), is hypertension - ACC/AHA 2017 (BP >=130/80 mm hg or antihypertensive use) associated with a higher prevalence of CKD - eGFR <60 or UACR >=30 mg/g (single measurement), after adjustment for age, sex, race and ethnicity, income-to-poverty ratio, diabetes (self-report, medication, or HbA1c >=6.5%), educational attainment, smoking status, and body mass index?
- **Primary hypothesis:** Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) is associated with a higher prevalence of CKD - eGFR <60 or UACR >=30 mg/g (single measurement).
- **Study type:** association - Cross-sectional, nationally representative complex survey

## 2. PICO and eligibility

- **Population:** noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years; excluding pregnant at examination)
- **Exposure:** Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use)
- **Comparator:** Participants without the exposure
- **Outcome:** CKD - eGFR <60 or UACR >=30 mg/g (single measurement)
- **Covariates:** Age, Sex, Race and ethnicity, Income-to-poverty ratio, Diabetes (self-report, medication, or HbA1c >=6.5%), Educational attainment, Smoking status, and Body mass index
- **Inclusion criteria:** Age >=18 years
- **Exclusion criteria:** Pregnant at examination
- **Data:** NHANES 2017-March 2020 pre-pandemic (public-use files, CDC)

## 3. Variables: concepts mapped to NHANES

| Role | Concept | NHANES source | Direct or derived | Definition |
|---|---|---|---|---|
| Outcome | CKD - eGFR <60 or UACR >=30 mg/g (single measurement) | LBXSCR, RIAGENDR, RIDAGEYR, URDACT (P: P_ALB_CR, P_BIOPRO, P_DEMO) | Derived | `any_of(egfr < 60, uacr >= 30)` |
| Exposure | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) | BPQ050A, BPXDI1, BPXDI2, BPXDI3, BPXODI1, BPXODI2, BPXODI3, BPXOSY1, BPXOSY2, BPXOSY3, BPXSY1, BPXSY2, BPXSY3 (P: P_BPQ, P_BPX, P_BPXO) | Derived | `any_of(sbp >= 130, dbp >= 80, bp_meds)` |
| Covariate | Age | RIDAGEYR (P: P_DEMO) | Direct | `RIDAGEYR` |
| Covariate | Sex | RIAGENDR (P: P_DEMO) | Derived | `cases(female == 0, "Male", female == 1, "Female")` |
| Covariate | Race and ethnicity | RIDRETH1, RIDRETH3 (P: P_DEMO) | Derived | `coalesce(cases(RIDRETH3 == 3, "Non-Hispanic White", RIDRETH3 == 4, "Non-Hispanic Black", RIDRETH3 %in% c(1, 2), "Hispanic", RIDRETH3 == 6, "Non-Hispanic Asian",` |
| Covariate | Income-to-poverty ratio | INDFMPIR (P: P_DEMO) | Derived | `cases(pir < 1.3, "<1.30", pir < 3.5, "1.30-3.49", pir >= 3.5, "3.50+")` |
| Covariate | Diabetes (self-report, medication, or HbA1c >=6.5%) | DIQ010, DIQ050, DIQ070, LBXGH (P: P_DIQ, P_GHB) | Derived | `any_of(dm_selfreport, insulin_use, dm_pills, hba1c >= 6.5)` |
| Covariate | Educational attainment | DMDEDUC2 (P: P_DEMO) | Derived | `cases(DMDEDUC2 %in% c(1, 2), "Less than high school", DMDEDUC2 == 3, "High school or GED", DMDEDUC2 == 4, "Some college", DMDEDUC2 == 5, "College graduate or ab` |
| Covariate | Smoking status | SMQ020, SMQ040 (P: P_SMQ) | Derived | `cases(SMQ020 == 2, "Never", SMQ040 == 3, "Former", SMQ040 %in% c(1, 2), "Current")` |
| Covariate | Body mass index | BMXBMI (P: P_BMX) | Direct | `BMXBMI` |
| Subgroup | Age group | RIDAGEYR (P: P_DEMO) | Derived | `cases(age < 18, "<18", age < 40, "18-39", age < 65, "40-64", age >= 65, "65+")` |
| Sensitivity | Hypertension - JNC7 (BP >=140/90 mm Hg or antihypertensive use) | BPQ050A, BPXDI1, BPXDI2, BPXDI3, BPXODI1, BPXODI2, BPXODI3, BPXOSY1, BPXOSY2, BPXOSY3, BPXSY1, BPXSY2, BPXSY3 (P: P_BPQ, P_BPX, P_BPXO) | Derived | `any_of(sbp >= 140, dbp >= 90, bp_meds)` |

## 4. Statistical analysis plan

- **Design:** cross-sectional analysis of the National Health and Nutrition Examination Survey (NHANES), 2017-March 2020 pre-pandemic.
- **Population:** Age >=18 years; excluding pregnant at examination.
- **Outcome:** CKD - eGFR <60 or UACR >=30 mg/g (single measurement).
- **Exposure:** Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use).
- **Comparator:** participants without the exposure, from the same survey population.
- **Covariates:** Age, Sex, Race and ethnicity, Income-to-poverty ratio, Diabetes (self-report, medication, or HbA1c >=6.5%), Educational attainment, Smoking status, Body mass index.
- **Descriptive:** survey-weighted Table 1 by ckd - egfr <60 or uacr >=30 mg/g (single measurement); weighted prevalence with 95% CIs.
- **Model:** prevalence ratios (survey-weighted Poisson regression); sequential models: Unadjusted, Adjusted for age, sex, and race and ethnicity, Fully adjusted (primary).
- **Effect modification:** interaction tests and stratified estimates by sex, age group.
- **Survey design:** Taylor linearisation with strata and PSUs; weight WTMECPRP (mec weight).
- **Missing data:** complete-case primary analysis; multiple imputation as sensitivity.
- **Why this model:** Binary outcome: survey-weighted quasi-Poisson regression with log link estimates prevalence ratios (PRs). PRs are preferred to odds ratios for cross-sectional data because ORs exaggerate associations when the outcome is common (>10%); the quasi-Poisson variance is robust under the design-based (Taylor linearization) estimator. Logistic regression is run as a sensitivity analysis.
- **Missing-data rationale:** Complete-case primary analysis within the design; multiple imputation by chained equations as sensitivity analysis when covariates are missing.
- **Prespecified sensitivity analyses:**
  - Exclude self-reported cardiovascular disease
  - Logistic regression (odds ratio)
  - Multiple imputation of missing covariates (m = 10)
  - Alternative exposure: Hypertension - JNC7 (BP >=140/90 mm Hg or antihypertensive use)
  - Unweighted analysis (design ignored)
- **Adjustment sets:**
  - Unadjusted: none
  - Adjusted for age, sex, and race and ethnicity: Age, Sex, Race and ethnicity
  - Fully adjusted (primary): Age, Sex, Race and ethnicity, Income-to-poverty ratio, Diabetes (self-report, medication, or HbA1c >=6.5%), Educational attainment, Smoking status, Body mass index
- **Further covariates considered (not in the primary model):**
  - Alcoholic drinks per drinking day (confounder): Alcohol affects liver, blood pressure and mood.
  - Any vigorous recreational activity (confounder): Physical activity relates to cardiometabolic risk and mood.
  - Has health insurance (confounder): Insurance determines diagnosis and treatment of self-reported or treated conditions.
- **Sample size and power:** Alpha 0.05 (two-sided), power 80%, target PR 1.5, DEFF 1.8: Run the blinded probe to estimate power.
  - Outcome prevalence assumed 10% (run the blinded probe for the real rate band).
  - Design effect 1.8 (typical for NHANES; the post-run check uses the actual design-based SE).
  - Group sizes unknown before the probe - showing the total sample needed for equal groups.

## 5. Anticipated limitations

- Cross-sectional design: temporality cannot be established and associations must not be interpreted causally.
- Single measurement of laboratory values; within-person variability and chronicity cannot be assessed.
- Residual confounding by unmeasured or imperfectly measured factors (e.g., diet, medications, menstrual blood loss).
- Self-reported comorbidities and behaviours are subject to recall and social-desirability bias.
- NHANES excludes institutionalized and active-duty military populations.
- Operational definition (KDIGO CKD): Chronicity (>3 months) cannot be confirmed from one NHANES visit.
- Operational definition (ACC/AHA 2017): BP is the mean of up to 3 readings at a single visit (oscillometric in 2017-2020/2021-2023; auscultatory in earlier cycles - mode differs across cycles).
- **Temporality:** Cross-sectional: temporality cannot be established. Results are reported as associations; causal language is blocked in the manuscript.

## 6. Feasibility and novelty

- **Feasibility in NHANES:** 100/100 (High)
- **Novelty (PubMed/MEDLINE):** 5/100 (Low) - 225 PubMed NHANES paper(s) on the full question in 10 years (158 in the last 3), 1 with a title naming the whole question. By element - Hypertension x Chronic kidney disease: 225 NHANES / 7,616 any data.

## 7. Quality-control checks run automatically

- Analytic sample size and the participant flow at each criterion
- Missingness of every variable; complete-case loss with multiple imputation as sensitivity
- Raw variable ranges against plausible limits; NHANES non-response codes removed
- Correct survey weight for the most restrictive component (interview, MEC, fasting, laboratory subsample); cycle-length rescaling
- Design degrees of freedom and NCHS presentation standards for proportions
- Model convergence, implausible or non-estimable estimates, single-valued terms, collinearity (VIF)
- Agreement across sensitivity analyses and alternative model specifications; unweighted comparison
- Benchmark against published estimates where available; E-value for unmeasured confounding

## 8. Human oversight

- Question framing and clinical meaningfulness - the AI proposes, the investigator decides.
- Case definitions and every operational assumption - explicit acknowledgement; AI-proposed definitions cannot run until approved.
- Confounder selection and causal structure - agents flag mediators and definitional overlap; the investigator decides.
- Approval gate - nothing runs until a named human approves this exact plan hash; any edit voids approval.
- Statistical sign-off - recorded separately by a statistician/epidemiologist.
- QC failures - cannot be silently ignored; each needs a documented override.
- Interpretation and publication - narrative drafted from aggregate results only, causal language filtered, human signs off.
- Data governance - restricted data only with approved/local models; row-level data never reach an LLM.

## 9. Reporting

- STROBE (cross-sectional); estimates are associations, not causal effects.
- Results, code (R `survey` package) and a hash-chained provenance ledger are exported as a reproducibility bundle.
