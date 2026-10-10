# Study protocol and statistical analysis plan

## Association of Abdominal Obesity (Waist Circumference) With Glycemic Control (HbA1c) Among US Adults: NHANES 2017-March 2020 pre-pandemic

_Plan plan_a92f8ef7ad v1 - sha256 `780f3a793976e5b3911be4ffb120ad59f194624e55fa4a64bfe1e441d32607a1` - approved by Investigator on 2026-10-10_

## 1. Research question

- **Clinical observation:** “I have noticed that adults with greater abdominal obesity may have worse blood sugar control even at similar weight.”
- **Refined question:** Among noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years; excluding pregnant at examination), is greater waist circumference (per 10 cm) associated with higher HbA1c, after adjustment for age, sex, race and ethnicity, income-to-poverty ratio, educational attainment, smoking status, and body mass index?
- **Primary hypothesis:** Greater waist circumference is associated with higher HbA1c independent of BMI.
- **Study type:** association - Cross-sectional, nationally representative complex survey

## 2. PICO and eligibility

- **Population:** noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years; excluding pregnant at examination)
- **Exposure:** Waist circumference (per 10 cm)
- **Comparator:** Lower levels of the exposure (per-unit contrast; quartile 1 in sensitivity analysis)
- **Outcome:** HbA1c
- **Covariates:** Age, Sex, Race and ethnicity, Income-to-poverty ratio, Educational attainment, Smoking status, and Body mass index
- **Inclusion criteria:** Age >=18 years
- **Exclusion criteria:** Pregnant at examination
- **Data:** NHANES 2017-March 2020 pre-pandemic (public-use files, CDC)

## 3. Variables: concepts mapped to NHANES

| Role | Concept | NHANES source | Direct or derived | Definition |
|---|---|---|---|---|
| Outcome | HbA1c | LBXGH (P: P_GHB) | Direct | `LBXGH` |
| Exposure | Waist circumference | BMXWAIST (P: P_BMX) | Direct | `BMXWAIST` |
| Covariate | Age | RIDAGEYR (P: P_DEMO) | Direct | `RIDAGEYR` |
| Covariate | Sex | RIAGENDR (P: P_DEMO) | Derived | `cases(female == 0, "Male", female == 1, "Female")` |
| Covariate | Race and ethnicity | RIDRETH1, RIDRETH3 (P: P_DEMO) | Derived | `coalesce(cases(RIDRETH3 == 3, "Non-Hispanic White", RIDRETH3 == 4, "Non-Hispanic Black", RIDRETH3 %in% c(1, 2), "Hispanic", RIDRETH3 == 6, "Non-Hispanic Asian",` |
| Covariate | Income-to-poverty ratio | INDFMPIR (P: P_DEMO) | Derived | `cases(pir < 1.3, "<1.30", pir < 3.5, "1.30-3.49", pir >= 3.5, "3.50+")` |
| Covariate | Educational attainment | DMDEDUC2 (P: P_DEMO) | Derived | `cases(DMDEDUC2 %in% c(1, 2), "Less than high school", DMDEDUC2 == 3, "High school or GED", DMDEDUC2 == 4, "Some college", DMDEDUC2 == 5, "College graduate or ab` |
| Covariate | Smoking status | SMQ020, SMQ040 (P: P_SMQ) | Derived | `cases(SMQ020 == 2, "Never", SMQ040 == 3, "Former", SMQ040 %in% c(1, 2), "Current")` |
| Covariate | Body mass index | BMXBMI (P: P_BMX) | Direct | `BMXBMI` |
| Subgroup | Age group | RIDAGEYR (P: P_DEMO) | Derived | `cases(age < 18, "<18", age < 40, "18-39", age < 65, "40-64", age >= 65, "65+")` |
| Sensitivity | Elevated HbA1c (>=6.5%) | LBXGH (P: P_GHB) | Derived | `hba1c >= 6.5` |
| Sensitivity | Abdominal obesity - waist >102 cm (men) / >88 cm (women) | BMXWAIST, RIAGENDR (P: P_BMX, P_DEMO) | Derived | `ifelse(female == 1, waist > 88, waist > 102)` |
| Sensitivity | Central adiposity - waist-to-height ratio >=0.5 | BMXHT, BMXWAIST (P: P_BMX) | Derived | `waist / height_cm >= 0.5` |

## 4. Statistical analysis plan

- **Design:** cross-sectional analysis of the National Health and Nutrition Examination Survey (NHANES), 2017-March 2020 pre-pandemic.
- **Population:** Age >=18 years; excluding pregnant at examination.
- **Outcome:** HbA1c.
- **Exposure:** Waist circumference.
- **Comparator:** per-unit contrast along the exposure (lower vs higher values); quartiles as sensitivity.
- **Covariates:** Age, Sex, Race and ethnicity, Income-to-poverty ratio, Educational attainment, Smoking status, Body mass index.
- **Descriptive:** survey-weighted Table 1 by abdominal obesity - waist >102 cm (men) / >88 cm (women); weighted prevalence with 95% CIs.
- **Model:** mean differences (survey-weighted linear regression); sequential models: Unadjusted, Adjusted for age, sex, and race and ethnicity, Fully adjusted (primary).
- **Effect modification:** interaction tests and stratified estimates by sex, age group.
- **Survey design:** Taylor linearisation with strata and PSUs; weight WTMECPRP (mec weight).
- **Missing data:** complete-case primary analysis; multiple imputation as sensitivity.
- **Why this model:** Continuous outcome: survey-weighted linear regression (design-based Taylor-series SEs) estimates adjusted mean differences. A binary clinical threshold of the outcome is analysed as a sensitivity analysis.
- **Missing-data rationale:** Complete-case primary analysis within the design; multiple imputation by chained equations as sensitivity analysis when covariates are missing.
- **Prespecified sensitivity analyses:**
  - Binary outcome: Elevated HbA1c (>=6.5%) (PR)
  - Exclude participants on glucose-lowering therapy
  - Exclude anemia (HbA1c unreliable)
  - Multiple imputation of missing covariates (m = 10)
  - Exposure in weighted quartiles (Q4 vs Q1, P for trend)
  - Alternative exposure: Abdominal obesity - waist >102 cm (men) / >88 cm (women)
  - Alternative exposure: Central adiposity - waist-to-height ratio >=0.5
  - Unweighted analysis (design ignored)
- **Adjustment sets:**
  - Unadjusted: none
  - Adjusted for age, sex, and race and ethnicity: Age, Sex, Race and ethnicity
  - Fully adjusted (primary): Age, Sex, Race and ethnicity, Income-to-poverty ratio, Educational attainment, Smoking status, Body mass index
- **Covariate decisions:**
  - Body mass index: BMI adjustment isolates the contribution of central adiposity beyond overall weight ('at similar weight'). Expect collinearity with waist (VIF check).
- **Further covariates considered (not in the primary model):**
  - Any vigorous recreational activity (confounder): Physical activity relates to cardiometabolic risk and mood.
  - Has health insurance (confounder): Insurance determines diagnosis and treatment of self-reported or treated conditions.
  - Systemic inflammation (hsCRP >5 mg/L) (mediator): Inflammation alters ferritin, hepcidin and leukocyte counts.
- **Sample size and power:** Alpha 0.05 (two-sided), power 80%, target 0.2 SD, DEFF 1.8: Run the blinded probe to estimate power.
  - Design effect 1.8 (typical for NHANES; the post-run check uses the actual design-based SE).

## 5. Anticipated limitations

- Cross-sectional design: temporality cannot be established and associations must not be interpreted causally.
- Single measurement of laboratory values; within-person variability and chronicity cannot be assessed.
- Residual confounding by unmeasured or imperfectly measured factors (e.g., diet, medications, menstrual blood loss).
- Self-reported comorbidities and behaviours are subject to recall and social-desirability bias.
- NHANES excludes institutionalized and active-duty military populations.
- **Temporality:** Cross-sectional: temporality cannot be established. Results are reported as associations; causal language is blocked in the manuscript.

## 6. Feasibility and novelty

- **Feasibility in NHANES:** 100/100 (High)
- **Novelty (PubMed/MEDLINE):** 18/100 (Low) - 11 PubMed NHANES paper(s) on the full question in 10 years (7 in the last 3). By element - Abdominal obesity (waist circumference) x Glycemic control (HbA1c): 11 NHANES / 352 any data.

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
