# Q2E accuracy against published NHANES estimates

Run 2026-10-11 on CDC public-use files. Published crude prevalence estimates from NCHS reports and JAMA Network Open; each question asked once in plain language; Q2E auto-approved with no per-item tuning; crude weighted prevalence compared with the published figure (overall, men, women).

## Original questions

* Questions answered as a prevalence: 14/14 (100%); questions the public files cannot answer as published, correctly flagged or declined: 1/1 (100%)
* Questions where Q2E picked the published case definition: 14/14 (100%) (0 published definitions are not in Q2E's library)

**When Q2E used the published definition** (38 estimates):

* Inside the published 95% CI: 38/38 (100%)
* 95% CIs overlap: 38/38 (100%)
* Within 1 percentage point: 37/38 (97%); within 2 points: 38/38 (100%)
* Mean absolute difference 0.18 points (median 0.06, max 1.21)

**All estimates Q2E produced** (38 estimates):

* Inside the published 95% CI: 38/38 (100%)
* 95% CIs overlap: 38/38 (100%)
* Within 1 percentage point: 37/38 (97%); within 2 points: 38/38 (100%)
* Mean absolute difference 0.18 points (median 0.06, max 1.21)

## Hold-out set 1 (added after the first fixes; its three failures were then fixed, so no longer unseen)

* Questions answered as a prevalence: 12/12 (100%); questions the public files cannot answer as published, correctly flagged or declined: 1/1 (100%)
* Questions where Q2E picked the published case definition: 10/12 (83%) (2 published definitions are not in Q2E's library)

**When Q2E used the published definition** (28 estimates):

* Inside the published 95% CI: 28/28 (100%)
* 95% CIs overlap: 28/28 (100%)
* Within 1 percentage point: 27/28 (96%); within 2 points: 28/28 (100%)
* Mean absolute difference 0.19 points (median 0.07, max 1.04)

**All estimates Q2E produced** (34 estimates):

* Inside the published 95% CI: 34/34 (100%)
* 95% CIs overlap: 34/34 (100%)
* Within 1 percentage point: 32/34 (94%); within 2 points: 34/34 (100%)
* Mean absolute difference 0.22 points (median 0.07, max 1.11)

## Hold-out set 2 (added last; never used to tune Q2E)

* Questions answered as a prevalence: 8/8 (100%)
* Questions where Q2E picked the published case definition: 8/8 (100%) (0 published definitions are not in Q2E's library)

**When Q2E used the published definition** (20 estimates):

* Inside the published 95% CI: 20/20 (100%)
* 95% CIs overlap: 20/20 (100%)
* Within 1 percentage point: 20/20 (100%); within 2 points: 20/20 (100%)
* Mean absolute difference 0.21 points (median 0.17, max 0.78)

**All estimates Q2E produced** (20 estimates):

* Inside the published 95% CI: 20/20 (100%)
* 95% CIs overlap: 20/20 (100%)
* Within 1 percentage point: 20/20 (100%); within 2 points: 20/20 (100%)
* Mean absolute difference 0.21 points (median 0.17, max 0.78)

## All questions

* Questions answered as a prevalence: 34/34 (100%); questions the public files cannot answer as published, correctly flagged or declined: 2/2 (100%)
* Questions where Q2E picked the published case definition: 32/34 (94%) (2 published definitions are not in Q2E's library)

**When Q2E used the published definition** (86 estimates):

* Inside the published 95% CI: 86/86 (100%)
* 95% CIs overlap: 86/86 (100%)
* Within 1 percentage point: 84/86 (98%); within 2 points: 86/86 (100%)
* Mean absolute difference 0.19 points (median 0.07, max 1.21)

**All estimates Q2E produced** (92 estimates):

* Inside the published 95% CI: 92/92 (100%)
* 95% CIs overlap: 92/92 (100%)
* Within 1 percentage point: 89/92 (97%); within 2 points: 92/92 (100%)
* Mean absolute difference 0.2 points (median 0.07, max 1.21)

## Item by item

| Item | Group | Published % (95% CI) | Q2E % (95% CI) | Diff (pts) | In CI | Q2E definition |
|---|---|---|---|---|---|---|
| obesity_P | overall | 41.9 (39.4-44.3) | 41.9 (39.4-44.4) | -0.0 | yes | Obesity - BMI >=30 kg/m2 |
| obesity_P | Male | 41.6 (37.4-45.8) | 41.6 (37.4-45.8) | -0.0 | yes |  |
| obesity_P | Female | 42.1 (39.6-44.8) | 42.1 (39.6-44.8) | +0.0 | yes |  |
| severe_obesity_P | overall | 9.0 (7.8-10.3) | 9.0 (7.8-10.3) | -0.0 | yes | Severe obesity - BMI >=40 kg/m2 (adults); BMI >=120% of the 95th percentile (2-19 y) |
| severe_obesity_P | Male | 6.4 (5.1-8.0) | 6.4 (5.1-8.0) | +0.0 | yes |  |
| severe_obesity_P | Female | 11.4 (9.7-13.3) | 11.4 (9.7-13.3) | -0.0 | yes |  |
| hypertension_P | overall | 48.1 (45.4-50.8) | 49.0 (46.4-51.6) | +0.9 | yes | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| hypertension_P | Male | 50.5 (46.9-54.2) | 51.2 (47.7-54.7) | +0.7 | yes |  |
| hypertension_P | Female | 45.7 (42.8-48.6) | 46.9 (44.1-49.8) | +1.2 | yes |  |
| diabetes_P | overall | 16.2 (14.2-18.3) | 16.2 (14.2-18.3) | -0.0 | yes | Total diabetes (NCHS) - diagnosed, or fasting plasma glucose >=126 mg/dL, or HbA1c >=6.5% |
| diabetes_P | Male | 17.7 (15.5-20.2) | 17.7 (15.4-20.1) | -0.0 | yes |  |
| diabetes_P | Female | 14.8 (12.2-17.7) | 14.7 (12.1-17.6) | -0.1 | yes |  |
| child_obesity_P | overall | 19.7 (17.9-21.6) | 19.8 (18.1-21.6) | +0.1 | yes | Obesity - BMI >=30 kg/m2 (adults); BMI >=95th percentile of the CDC growth charts (2-19 y) |
| child_obesity_P | Male | 20.9 (18.9-22.9) | 21.1 (19.2-23.1) | +0.2 | yes |  |
| child_obesity_P | Female | 18.5 (16.3-21.0) | 18.6 (16.4-20.8) | +0.1 | yes |  |
| absolute_iron_deficiency_P | overall | 14.0 (13.0-15.0) | 13.8 (12.8-14.8) | -0.2 | yes | Absolute iron deficiency - ferritin <30 ng/mL |
| functional_iron_deficiency_P | overall | 15.0 (14.0-17.0) | 15.4 (14.4-16.5) | +0.4 | yes | Functional iron deficiency - ferritin >=30 ng/mL with TSAT <20% |
| obesity_L | overall | 40.3 (36.8-43.8) | 40.3 (36.3-44.3) | -0.0 | yes | Obesity - BMI >=30 kg/m2 |
| obesity_L | Male | 39.2 (35.5-42.9) | 39.2 (35.1-43.5) | +0.0 | yes |  |
| obesity_L | Female | 41.3 (37.0-45.6) | 41.3 (36.6-46.1) | -0.0 | yes |  |
| severe_obesity_L | overall | 9.4 (8.0-10.8) | 9.4 (8.1-10.9) | +0.0 | yes | Severe obesity - BMI >=40 kg/m2 (adults); BMI >=120% of the 95th percentile (2-19 y) |
| severe_obesity_L | Male | 6.7 (5.3-8.1) | 6.7 (5.2-8.3) | -0.1 | yes |  |
| severe_obesity_L | Female | 12.1 (10.3-13.9) | 12.1 (10.3-14.1) | -0.0 | yes |  |
| hypertension_L | overall | 47.7 (45.4-49.9) | 48.0 (45.8-50.2) | +0.3 | yes | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| hypertension_L | Male | 50.8 (48.4-53.2) | 51.1 (48.6-53.5) | +0.3 | yes |  |
| hypertension_L | Female | 44.6 (41.4-47.8) | 45.1 (42.0-48.2) | +0.5 | yes |  |
| diabetes_L | overall | 15.8 (13.6-18.2) | 15.8 (13.6-18.2) | -0.0 | yes | Total diabetes (NCHS) - diagnosed, or fasting plasma glucose >=126 mg/dL, or HbA1c >=6.5% |
| diabetes_L | Male | 18.0 (15.7-20.4) | 17.9 (15.7-20.4) | -0.1 | yes |  |
| diabetes_L | Female | 13.7 (11.0-16.7) | 13.7 (11.0-16.7) | -0.0 | yes |  |
| high_cholesterol_L | overall | 11.3 (9.8-12.9) | 11.2 (9.7-12.8) | -0.1 | yes | High total cholesterol - serum total cholesterol >=240 mg/dL |
| high_cholesterol_L | Male | 10.6 (8.6-12.9) | 10.6 (8.6-12.9) | +0.0 | yes |  |
| high_cholesterol_L | Female | 11.9 (10.3-13.6) | 11.7 (10.1-13.5) | -0.2 | yes |  |
| low_hdl_L | overall | 13.8 (12.1-15.7) | 14.0 (12.2-15.9) | +0.2 | yes | Low HDL cholesterol - HDL-C <40 mg/dL |
| low_hdl_L | Male | 21.5 (18.6-24.6) | 21.5 (18.6-24.6) | -0.0 | yes |  |
| low_hdl_L | Female | 6.6 (5.4-8.0) | 6.8 (5.5-8.2) | +0.2 | yes |  |
| anemia_L | overall | 9.3 (8.3-10.3) | 9.1 (8.1-10.3) | -0.2 | yes | Anemia - WHO hemoglobin thresholds |
| anemia_L | Male | 5.5 (4.5-6.5) | 5.4 (4.3-6.7) | -0.1 | yes |  |
| anemia_L | Female | 13.0 (11.8-14.2) | 12.8 (11.5-14.1) | -0.2 | yes |  |
| depression_L | - | 13.1 | **flagged_limit**: warning: Ages 12-17 are not in the public files | | | Depression - PHQ-9 score >=10 |
| holdout_obesity_20_39_L (hold-out 1) | overall | 35.5 (29.6-41.4) | 35.5 (29.2-42.2) | +0.0 | yes | Obesity - BMI >=30 kg/m2 |
| holdout_obesity_20_39_L (hold-out 1) | Male | 34.3 (28.8-39.8) | 34.3 (28.4-40.6) | -0.0 | yes |  |
| holdout_obesity_20_39_L (hold-out 1) | Female | 36.8 (29.7-43.9) | 36.8 (29.2-44.9) | +0.0 | yes |  |
| holdout_obesity_60plus_L (hold-out 1) | overall | 38.9 (36.0-41.8) | 38.9 (35.6-42.3) | -0.0 | yes | Obesity - BMI >=30 kg/m2 |
| holdout_obesity_60plus_L (hold-out 1) | Male | 38.0 (33.5-42.5) | 38.0 (33.2-43.0) | +0.0 | yes |  |
| holdout_obesity_60plus_L (hold-out 1) | Female | 39.6 (35.9-43.3) | 39.6 (35.5-43.9) | +0.0 | yes |  |
| holdout_severe_obesity_60plus_P (hold-out 1) | overall | 6.1 (5.2-7.2) | 6.1 (5.2-7.2) | +0.0 | yes | Severe obesity - BMI >=40 kg/m2 (adults); BMI >=120% of the 95th percentile (2-19 y) |
| holdout_severe_obesity_60plus_P (hold-out 1) | Male | 3.5 (2.6-4.5) | 3.5 (2.7-4.5) | -0.0 | yes |  |
| holdout_severe_obesity_60plus_P (hold-out 1) | Female | 8.3 (6.8-10.0) | 8.3 (6.8-10.0) | +0.0 | yes |  |
| holdout_hypertension_18_39_L (hold-out 1) | overall | 23.4 (20.2-26.9) | 23.6 (20.4-27.2) | +0.2 | yes | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| holdout_hypertension_18_39_L (hold-out 1) | Male | 30.0 (26.2-34.1) | 30.0 (26.2-34.1) | +0.0 | yes |  |
| holdout_hypertension_18_39_L (hold-out 1) | Female | 16.4 (12.6-21.0) | 16.9 (13.0-21.5) | +0.5 | yes |  |
| holdout_hypertension_60plus_P (hold-out 1) | overall | 74.1 (71.4-76.7) | 75.0 (72.2-77.5) | +0.8 | yes | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| holdout_hypertension_60plus_P (hold-out 1) | Male | 73.1 (68.5-77.3) | 73.7 (69.2-77.8) | +0.6 | yes |  |
| holdout_hypertension_60plus_P (hold-out 1) | Female | 75.0 (72.1-77.7) | 76.0 (73.3-78.6) | +1.0 | yes |  |
| holdout_diabetes_60plus_P (hold-out 1) | overall | 30.0 (27.2-32.9) | 29.9 (27.1-32.9) | -0.1 | yes | Total diabetes (NCHS) - diagnosed, or fasting plasma glucose >=126 mg/dL, or HbA1c >=6.5% |
| holdout_diabetes_60plus_P (hold-out 1) | Male | 36.3 (30.8-42.1) | 36.3 (30.8-42.1) | +0.0 | yes |  |
| holdout_diabetes_60plus_P (hold-out 1) | Female | 24.4 (19.4-30.1) | 24.4 (19.3-30.0) | -0.0 | yes |  |
| holdout_diagnosed_diabetes_L (hold-out 1) | overall | 11.3 (9.3-13.5) | 11.2 (9.8-12.7) | -0.1 | yes | Diagnosed diabetes - ever told by a doctor (other than during pregnancy) - **no matching definition** |
| holdout_diagnosed_diabetes_L (hold-out 1) | Male | 12.9 (11.0-15.0) | 11.8 (10.6-13.1) | -1.1 | yes |  |
| holdout_diagnosed_diabetes_L (hold-out 1) | Female | 9.7 (7.3-12.7) | 10.7 (8.7-12.9) | +1.0 | yes |  |
| holdout_undiagnosed_diabetes_L (hold-out 1) | overall | 4.5 (3.3-5.9) | 4.5 (3.3-5.9) | -0.0 | yes | Undiagnosed diabetes - no diagnosis, but fasting plasma glucose >=126 mg/dL or HbA1c >=6.5% - **no matching definition** |
| holdout_undiagnosed_diabetes_L (hold-out 1) | Male | 5.1 (3.6-6.9) | 5.1 (3.6-6.9) | -0.0 | yes |  |
| holdout_undiagnosed_diabetes_L (hold-out 1) | Female | 3.9 (2.8-5.3) | 3.9 (2.8-5.3) | +0.0 | yes |  |
| holdout_child_obesity_12_19_P (hold-out 1) | overall | 22.2 (19.7-24.8) | 22.1 (19.8-24.6) | -0.1 | yes | Obesity - BMI >=30 kg/m2 (adults); BMI >=95th percentile of the CDC growth charts (2-19 y) |
| holdout_child_obesity_12_19_P (hold-out 1) | Male | 22.6 (19.7-25.7) | 22.3 (19.2-25.8) | -0.3 | yes |  |
| holdout_child_obesity_12_19_P (hold-out 1) | Female | 21.7 (18.1-25.7) | 21.9 (18.4-25.8) | +0.2 | yes |  |
| holdout_child_obesity_2_5_P (hold-out 1) | overall | 12.7 (10.8-14.8) | 12.7 (10.8-14.7) | -0.0 | yes | Obesity - BMI >=30 kg/m2 (adults); BMI >=95th percentile of the CDC growth charts (2-19 y) |
| holdout_child_obesity_2_5_P (hold-out 1) | Male | 13.6 (10.8-16.8) | 14.0 (10.8-17.7) | +0.4 | yes |  |
| holdout_child_obesity_2_5_P (hold-out 1) | Female | 11.8 (9.3-14.8) | 11.4 (9.3-13.8) | -0.4 | yes |  |
| holdout_depression_12_19_L (hold-out 1) | - | 19.2 | **flagged_limit**: blocker: Public NHANES files have no data for ages 12-17 | | | Depression - PHQ-9 score >=10 |
| holdout_depression_60plus_L (hold-out 1) | overall | 8.7 (7.1-10.3) | 8.6 (7.0-10.4) | -0.1 | yes | Depression - PHQ-9 score >=10 |
| holdout_depression_60plus_L (hold-out 1) | Male | 6.5 (4.0-9.1) | 6.3 (4.0-9.6) | -0.2 | yes |  |
| holdout_depression_60plus_L (hold-out 1) | Female | 10.6 (8.4-12.8) | 10.5 (8.3-13.1) | -0.1 | yes |  |
| holdout_anemia_women_20_59_L (hold-out 1) | overall | 14.0 (12.6-15.4) | 13.9 (12.3-15.6) | -0.1 | yes | Anemia - WHO hemoglobin thresholds |
| h2_hypertension_40_59_L (hold-out 2) | overall | 52.5 (49.5-55.4) | 52.6 (49.8-55.4) | +0.1 | yes | Hypertension - ACC/AHA 2017 (BP >=130/80 mm Hg or antihypertensive use) |
| h2_hypertension_40_59_L (hold-out 2) | Male | 55.9 (50.6-61.1) | 56.2 (50.8-61.5) | +0.3 | yes |  |
| h2_hypertension_40_59_L (hold-out 2) | Female | 49.0 (45.8-52.3) | 49.1 (45.9-52.3) | +0.1 | yes |  |
| h2_diabetes_40_59_L (hold-out 2) | overall | 17.7 (14.7-21.0) | 17.7 (14.7-21.0) | +0.0 | yes | Total diabetes (NCHS) - diagnosed, or fasting plasma glucose >=126 mg/dL, or HbA1c >=6.5% |
| h2_diabetes_20_39_L (hold-out 2) | overall | 3.6 (2.0-5.9) | 3.6 (1.9-5.9) | -0.0 | yes | Total diabetes (NCHS) - diagnosed, or fasting plasma glucose >=126 mg/dL, or HbA1c >=6.5% |
| h2_severe_obesity_40_59_L (hold-out 2) | overall | 12.0 (10.0-14.0) | 12.0 (9.8-14.4) | -0.0 | yes | Severe obesity - BMI >=40 kg/m2 (adults); BMI >=120% of the 95th percentile (2-19 y) |
| h2_severe_obesity_40_59_L (hold-out 2) | Male | 9.2 (6.7-11.8) | 9.2 (6.6-12.3) | -0.0 | yes |  |
| h2_severe_obesity_40_59_L (hold-out 2) | Female | 14.7 (12.0-17.4) | 14.7 (11.8-17.9) | -0.0 | yes |  |
| h2_severe_obesity_20_39_P (hold-out 2) | overall | 9.7 (7.7-12.0) | 9.7 (7.7-12.0) | -0.0 | yes | Severe obesity - BMI >=40 kg/m2 (adults); BMI >=120% of the 95th percentile (2-19 y) |
| h2_severe_obesity_20_39_P (hold-out 2) | Male | 7.0 (4.7-10.1) | 7.0 (4.7-10.1) | +0.0 | yes |  |
| h2_severe_obesity_20_39_P (hold-out 2) | Female | 12.4 (9.8-15.3) | 12.4 (9.8-15.3) | +0.0 | yes |  |
| h2_anemia_60plus_L (hold-out 2) | overall | 12.5 (10.7-14.3) | 12.1 (10.2-14.1) | -0.4 | yes | Anemia - WHO hemoglobin thresholds |
| h2_anemia_60plus_L (hold-out 2) | Male | 12.8 (10.6-15.0) | 12.3 (10.1-14.8) | -0.5 | yes |  |
| h2_anemia_60plus_L (hold-out 2) | Female | 12.4 (10.1-14.8) | 11.9 (9.7-14.4) | -0.5 | yes |  |
| h2_child_obesity_6_11_P (hold-out 2) | overall | 20.7 (17.9-23.7) | 21.2 (18.5-24.1) | +0.5 | yes | Obesity - BMI >=30 kg/m2 (adults); BMI >=95th percentile of the CDC growth charts (2-19 y) |
| h2_child_obesity_6_11_P (hold-out 2) | Male | 22.9 (19.5-26.5) | 23.7 (20.3-27.3) | +0.8 | yes |  |
| h2_child_obesity_6_11_P (hold-out 2) | Female | 18.5 (15.2-22.1) | 18.7 (15.6-22.1) | +0.2 | yes |  |
| h2_depression_40_59_L (hold-out 2) | overall | 10.8 (9.2-12.4) | 11.0 (9.3-12.9) | +0.2 | yes | Depression - PHQ-9 score >=10 |
| h2_depression_40_59_L (hold-out 2) | Male | 7.9 (5.5-10.2) | 8.1 (5.5-11.2) | +0.2 | yes |  |
| h2_depression_40_59_L (hold-out 2) | Female | 13.8 (11.2-16.4) | 14.0 (11.3-17.0) | +0.2 | yes |  |

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
