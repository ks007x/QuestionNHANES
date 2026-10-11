# Study protocol and statistical analysis plan

## Association of Liver Stiffness With Thrombocytopenia Among US Adults: NHANES 2017-March 2020 pre-pandemic

_Plan plan_b2cc741679 v1 - sha256 `0f5ba7ba4cf71b92984ebfca05f23e5bbba3345662805a16e978b5c3d21f0680` - approved by Karan on 2026-10-11_

## 1. Research question

- **Clinical observation:** “Is higher liver stiffness associated with thrombocytopenia in US adults?”
- **Refined question:** Among noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years), is greater liver stiffness (VCTE median) (per 5 kPa) associated with a higher prevalence of thrombocytopenia - platelets <150 x10^9/L, after adjustment for age, sex, race and ethnicity, income-to-poverty ratio, body mass index, diabetes (self-report, medication, or HbA1c >=6.5%), and smoking status?
- **Primary hypothesis:** Greater liver stiffness (VCTE median) is associated with a higher prevalence of thrombocytopenia - platelets <150 x10^9/L.
- **Study type:** association - Cross-sectional, nationally representative complex survey

## 2. PICO and eligibility

- **Population:** noninstitutionalized US participants in NHANES 2017-March 2020 pre-pandemic (Age >=18 years)
- **Exposure:** Liver stiffness (VCTE median) (per 5 kPa)
- **Comparator:** Lower levels of the exposure (per-unit contrast; quartile 1 in sensitivity analysis)
- **Outcome:** Thrombocytopenia - platelets <150 x10^9/L
- **Covariates:** Age, Sex, Race and ethnicity, Income-to-poverty ratio, Body mass index, Diabetes (self-report, medication, or HbA1c >=6.5%), and Smoking status
- **Inclusion criteria:** Age >=18 years
- **Exclusion criteria:** -
- **Data:** NHANES 2017-March 2020 pre-pandemic (public-use files, CDC)

## 3. Variables: concepts mapped to NHANES

| Role | Concept | NHANES source | Direct or derived | Definition |
|---|---|---|---|---|
| Outcome | Thrombocytopenia - platelets <150 x10^9/L | LBXPLTSI (P: P_CBC) | Derived | `plt < 150` |
| Exposure | Liver stiffness (VCTE median) | LUXSMED (P: P_LUX) | Direct | `LUXSMED` |
| Covariate | Age | RIDAGEYR (P: P_DEMO) | Direct | `RIDAGEYR` |
| Covariate | Sex | RIAGENDR (P: P_DEMO) | Derived | `cases(female == 0, "Male", female == 1, "Female")` |
| Covariate | Race and ethnicity | RIDRETH1, RIDRETH3 (P: P_DEMO) | Derived | `coalesce(cases(RIDRETH3 == 3, "Non-Hispanic White", RIDRETH3 == 4, "Non-Hispanic Black", RIDRETH3 %in% c(1, 2), "Hispanic", RIDRETH3 == 6, "Non-Hispanic Asian",` |
| Covariate | Income-to-poverty ratio | INDFMPIR (P: P_DEMO) | Derived | `cases(pir < 1.3, "<1.30", pir < 3.5, "1.30-3.49", pir >= 3.5, "3.50+")` |
| Covariate | Body mass index | BMXBMI (P: P_BMX) | Direct | `BMXBMI` |
| Covariate | Diabetes (self-report, medication, or HbA1c >=6.5%) | DIQ010, DIQ050, DIQ070, LBXGH (P: P_DIQ, P_GHB) | Derived | `any_of(dm_selfreport, insulin_use, dm_pills, hba1c >= 6.5)` |
| Covariate | Smoking status | SMQ020, SMQ040 (P: P_SMQ) | Derived | `cases(SMQ020 == 2, "Never", SMQ040 == 3, "Former", SMQ040 %in% c(1, 2), "Current")` |
| Subgroup | Age group | RIDAGEYR (P: P_DEMO) | Derived | `cases(age < 18, "<18", age < 40, "18-39", age < 65, "40-64", age >= 65, "65+")` |

## 4. Statistical analysis plan

- **Design:** cross-sectional analysis of the National Health and Nutrition Examination Survey (NHANES), 2017-March 2020 pre-pandemic.
- **Population:** Age >=18 years.
- **Outcome:** Thrombocytopenia - platelets <150 x10^9/L.
- **Exposure:** Liver stiffness (VCTE median).
- **Comparator:** per-unit contrast along the exposure (lower vs higher values); quartiles as sensitivity.
- **Covariates:** Age, Sex, Race and ethnicity, Income-to-poverty ratio, Body mass index, Diabetes (self-report, medication, or HbA1c >=6.5%), Smoking status.
- **Descriptive:** survey-weighted Table 1 by thrombocytopenia - platelets <150 x10^9/l; weighted prevalence with 95% CIs.
- **Model:** prevalence ratios (survey-weighted Poisson regression); sequential models: Unadjusted, Adjusted for age, sex, and race and ethnicity, Fully adjusted (primary).
- **Effect modification:** interaction tests and stratified estimates by sex, age group.
- **Survey design:** Taylor linearisation with strata and PSUs; weight WTMECPRP (mec weight).
- **Missing data:** complete-case primary analysis; multiple imputation as sensitivity.
- **Why this model:** Binary outcome: survey-weighted quasi-Poisson regression with log link estimates prevalence ratios (PRs). PRs are preferred to odds ratios for cross-sectional data because ORs exaggerate associations when the outcome is common (>10%); the quasi-Poisson variance is robust under the design-based (Taylor linearization) estimator. Logistic regression is run as a sensitivity analysis.
- **Missing-data rationale:** Complete-case primary analysis within the design; multiple imputation by chained equations as sensitivity analysis when covariates are missing.
- **Prespecified sensitivity analyses:**
  - Exclude heavy alcohol (>2 drinks/day men, >1 women)
  - Exclude self-reported hepatitis B or C
  - Logistic regression (odds ratio)
  - Multiple imputation of missing covariates (m = 10)
  - Exposure in weighted quartiles (Q4 vs Q1, P for trend)
  - Unweighted analysis (design ignored)
- **Adjustment sets:**
  - Unadjusted: none
  - Adjusted for age, sex, and race and ethnicity: Age, Sex, Race and ethnicity
  - Fully adjusted (primary): Age, Sex, Race and ethnicity, Income-to-poverty ratio, Body mass index, Diabetes (self-report, medication, or HbA1c >=6.5%), Smoking status
- **Further covariates considered (not in the primary model):**
  - Educational attainment (confounder): Education captures socioeconomic position beyond income (adults 20+).
  - Alcoholic drinks per drinking day (confounder): Alcohol affects liver, blood pressure and mood.
  - Asthma (ever told) (confounder): Atopy and asthma raise eosinophil counts; parasites (e.g., Toxocara) may also cause wheeze, so asthma can be a mediator.
  - Hay fever in the past 12 months (confounder): Allergic rhinitis raises eosinophil counts.
  - Systemic inflammation (hsCRP >5 mg/L) (confounder): Inflammation alters ferritin, hepcidin and leukocyte counts.
  - Chronic kidney disease (eGFR <60 or UACR >=30 mg/g) (confounder): Kidney disease affects anemia, iron handling and cardiovascular risk.
- **Sample size and power:** Alpha 0.05 (two-sided), power 80%, target PR 1.5, DEFF 1.8: Run the blinded probe to estimate power.
  - Outcome prevalence assumed 10% (run the blinded probe for the real rate band).
  - Design effect 1.8 (typical for NHANES; the post-run check uses the actual design-based SE).

## 5. Anticipated limitations

- Cross-sectional design: temporality cannot be established and associations must not be interpreted causally.
- Single measurement of laboratory values; within-person variability and chronicity cannot be assessed.
- Residual confounding by unmeasured or imperfectly measured factors (e.g., diet, medications, menstrual blood loss).
- Self-reported comorbidities and behaviours are subject to recall and social-desirability bias.
- NHANES excludes institutionalized and active-duty military populations.
- **Temporality:** Cross-sectional: temporality cannot be established. Results are reported as associations; causal language is blocked in the manuscript.

## 6. Feasibility and novelty

- **Feasibility in NHANES:** 98/100 (High)
- **Novelty (PubMed/MEDLINE):** 90/100 (High) - 0 PubMed NHANES paper(s) on the full question in 10 years (0 in the last 3). By element - Liver stiffness x Thrombocytopenia: 0 NHANES / 29 any data.

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
