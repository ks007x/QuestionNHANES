# Q2E accuracy against published NHANES estimates

Run 2026-10-11 on CDC public-use files. 15 published prevalence questions from NCHS reports and JAMA Network Open; each asked once in plain language; Q2E unchanged and auto-approved; crude weighted prevalence compared with the published crude estimate (overall, men, women).

## Summary

* Questions answered as a prevalence: 11/15 (73%)
* Questions where Q2E picked the published case definition: 9/15 (60%) (5 published definitions are not in Q2E's library)

**When Q2E used the published definition** (23 estimates):

* Inside the published 95% CI: 18/23 (78%)
* 95% CIs overlap: 20/23 (87%)
* Within 1 percentage point: 14/23 (61%); within 2 points: 18/23 (78%)
* Mean absolute difference 2.33 points (median 0.86, max 10.39)

**All estimates Q2E produced** (27 estimates):

* Inside the published 95% CI: 18/27 (67%)
* 95% CIs overlap: 20/27 (74%)
* Within 1 percentage point: 14/27 (52%); within 2 points: 18/27 (67%)
* Mean absolute difference 3.57 points (median 0.97, max 12.92)

## Item by item

| Item | Group | Published % (95% CI) | Q2E % (95% CI) | Diff (pts) | In CI | Q2E definition |
|---|---|---|---|---|---|---|
| obesity_P | overall | 41.9 (39.4-44.3) | 41.9 (39.4-44.4) | -0.0 | yes | Obesity - BMI >=30 kg/m2 |
| obesity_P | Male | 41.6 (37.4-45.8) | 41.6 (37.4-45.8) | -0.0 | yes |  |
| obesity_P | Female | 42.1 (39.6-44.8) | 42.1 (39.6-44.8) | +0.0 | yes |  |
| severe_obesity_P | - |  | **wrong_measure**: Q2E reported Mean difference of Obesity - BMI >=30 kg/m2 = 11.2308834492, not a prevalence | | | Body mass index - **no matching definition** |
| hypertension_P | overall | 48.1 (45.4-50.8) | 49.1 (46.4-51.7) | +1.0 | yes | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| hypertension_P | Male | 50.5 (46.9-54.2) | 51.3 (47.8-54.8) | +0.8 | yes |  |
| hypertension_P | Female | 45.7 (42.8-48.6) | 46.9 (44.1-49.8) | +1.2 | yes |  |
| diabetes_P | overall | 16.2 (14.2-18.3) | 14.6 (13.8-15.5) | -1.6 | yes | Diabetes - self-report, medication, or HbA1c >=6.5% |
| diabetes_P | Male | 17.7 (15.5-20.2) | 15.7 (14.3-17.2) | -2.0 | yes |  |
| diabetes_P | Female | 14.8 (12.2-17.7) | 13.6 (12.1-15.1) | -1.2 | yes |  |
| child_obesity_P | overall | 19.7 (17.9-21.6) | 8.6 (7.3-10.2) | -11.1 | no | Obesity - BMI >=30 kg/m2 - **no matching definition** |
| child_obesity_P | Male | 20.9 (18.9-22.9) | 8.0 (6.4-9.7) | -12.9 | no |  |
| child_obesity_P | Female | 18.5 (16.3-21.0) | 9.3 (7.6-11.3) | -9.2 | no |  |
| absolute_iron_deficiency_P | overall | 14.0 (13.0-15.0) | 23.5 (22.2-24.9) | +9.5 | no | Iron deficiency - ASH 2026 ferritin thresholds - **differs** |
| functional_iron_deficiency_P | overall | 15.0 (14.0-17.0) | 15.4 (14.4-16.5) | +0.4 | yes | Functional iron deficiency - ferritin >=30 ng/mL with TSAT <20% |
| obesity_L | overall | 40.3 (36.8-43.8) | 40.3 (36.3-44.3) | -0.0 | yes | Obesity - BMI >=30 kg/m2 |
| obesity_L | Male | 39.2 (35.5-42.9) | 39.2 (35.1-43.5) | +0.0 | yes |  |
| obesity_L | Female | 41.3 (37.0-45.6) | 41.3 (36.6-46.1) | -0.0 | yes |  |
| severe_obesity_L | - |  | **wrong_measure**: Q2E reported Mean difference of Obesity - BMI >=30 kg/m2 = 11.4657265059, not a prevalence | | | Body mass index - **no matching definition** |
| hypertension_L | overall | 47.7 (45.4-49.9) | 37.4 (35.4-39.5) | -10.3 | no | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| hypertension_L | Male | 50.8 (48.4-53.2) | 40.7 (38.6-42.8) | -10.1 | no |  |
| hypertension_L | Female | 44.6 (41.4-47.8) | 34.2 (31.0-37.6) | -10.4 | no |  |
| diabetes_L | overall | 15.8 (13.6-18.2) | 14.8 (13.2-16.5) | -1.0 | yes | Diabetes - self-report, medication, or HbA1c >=6.5% |
| diabetes_L | Male | 18.0 (15.7-20.4) | 15.7 (14.1-17.3) | -2.4 | no |  |
| diabetes_L | Female | 13.7 (11.0-16.7) | 14.1 (11.7-16.7) | +0.3 | yes |  |
| high_cholesterol_L | - |  | **wrong_measure**: Q2E reported Weighted mean of Total cholesterol = 188.0093190521, not a prevalence | | | Total cholesterol - **no matching definition** |
| low_hdl_L | - |  | **wrong_measure**: Q2E reported Weighted mean of HDL cholesterol = 53.609486941, not a prevalence | | | HDL cholesterol - **no matching definition** |
| anemia_L | overall | 9.3 (8.3-10.3) | 0.0 (0.0-97.5) | -9.3 | no | Anemia - WHO hemoglobin thresholds |
| anemia_L | Male | 5.5 (4.5-6.5) | - |  |  |  |
| anemia_L | Female | 13.0 (11.8-14.2) | - |  |  |  |
| depression_L | overall | 13.1 (11.7-14.5) | 12.6 (11.0-14.4) | -0.5 | yes | Depression - PHQ-9 score >=10 |
| depression_L | Male | 10.1 (8.3-11.9) | 10.1 (8.1-12.3) | -0.1 | yes |  |
| depression_L | Female | 16.0 (14.2-17.8) | 15.1 (13.2-17.2) | -0.9 | yes |  |

## Sources

* Stierman B, Afful J, Carroll MD, et al. National Health and Nutrition Examination Survey 2017-March 2020 prepandemic data files: development of files and prevalence estimates for selected health outcomes. National Health Statistics Reports no. 158. NCHS; 2021. https://stacks.cdc.gov/view/cdc/106273
* NCHS. Obesity and severe obesity prevalence in adults: United States, August 2021-August 2023. NCHS Data Brief no. 508. 2024. https://www.cdc.gov/nchs/products/databriefs/db508.htm
* NCHS. Hypertension in adults: United States, August 2021-August 2023. NCHS Data Brief no. 511. 2024. https://www.cdc.gov/nchs/products/databriefs/db511.htm
* NCHS. Total and high-density lipoprotein cholesterol in adults: United States, August 2021-August 2023. NCHS Data Brief no. 515. 2024. https://www.cdc.gov/nchs/products/databriefs/db515.htm
* NCHS. Prevalence of total, diagnosed, and undiagnosed diabetes in adults: United States, August 2021-August 2023. NCHS Data Brief no. 516. 2024. https://www.cdc.gov/nchs/products/databriefs/db516.htm
* NCHS. Anemia prevalence: United States, August 2021-August 2023. NCHS Data Brief no. 519. 2024. https://www.cdc.gov/nchs/products/databriefs/db519.htm
* NCHS. Depression prevalence in adolescents and adults: United States, August 2021-August 2023. NCHS Data Brief no. 527. 2025. https://www.cdc.gov/nchs/products/databriefs/db527.htm
* Tawfik YMK, Billingsley H, Bhatt AS, et al. Absolute and functional iron deficiency in the US, 2017-2020. JAMA Netw Open. 2024;7(9):e2433126. https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2823909

_CIs from reports that give only standard errors are estimate +/- 1.96 SE. Q2E reports crude (not age-adjusted) prevalence, so crude published figures are used throughout._
