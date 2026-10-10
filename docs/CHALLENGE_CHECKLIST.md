# Challenge 4 checklist: instructions vs Q2E

Checked against *Ops Unleashed Challenge 4, AI Research Copilot (Research Services)* using the challenge's own
example question on **real NHANES data** (GitHub Actions run 26, `results` branch, `runs/2026-10-10-run26/`):

> "I have noticed that adults with greater abdominal obesity may have worse blood sugar control even at similar weight."

Result: survey-weighted linear regression, NHANES 2017-March 2020 (MEC weight `WTMECPRP`, 24 strata / 49 PSUs, design
df 25), adults, pregnant excluded, n = 6,610 complete cases representing 226 million US adults. Each 10 cm of waist
circumference was associated with **0.15 percentage points higher HbA1c (95% CI 0.10-0.21)** after adjustment for age,
sex, race and ethnicity, income, education, smoking **and BMI** ("at similar weight").

## Core stages

| Stage | Required | Where in Q2E | Evidence from run 26 |
|---|---|---|---|
| 1 Refine the question | Population, exposure, comparator, outcome, covariates, inclusion/exclusion, hypothesis | Protocol page; follow-up questions before drafting | `protocol_and_sap.md` section 1-2: all seven elements; "at similar weight" became BMI adjustment |
| 2 Protocol | Population, variables, design, planned analyses, limitations (confounding, missing data, measurement error, causal interpretation) | Protocol page; **Protocol & analysis plan** document (Approve step, Outputs, bundle) | `protocol_and_sap.md/.html`, hash-stamped and approved before data access; section 5 lists limitations |
| 3 Concept -> NHANES variables | Datasets, cycles, variable names, derived variables; direct vs derived | Data map page | 13 analysis variables: 4 direct, 9 derived, 12 raw variables in P_BMX, P_DEMO, P_GHB, P_SMQ; per-cycle availability |
| 4 Statistical analysis plan | Descriptives, weighting, model choice, adjustment, missing data, interactions/subgroups, sensitivity, **why** | Analysis plan page; SAP section 4 | Linear model chosen for a continuous outcome with stated reason; 3 adjustment sets; complete case + MICE; sex and age interactions; 8 prespecified sensitivity analyses |
| 5 Execute | Import, combine cycles, criteria, derive, design/weights, descriptives, models, sensitivity | R engine (`survey`), runs locally or on GitHub Actions from CDC | Files downloaded from CDC with md5; flow 15,560 -> 6,610; Table 1, prevalences, 3 models, 8 sensitivity analyses |
| 6 Validate | Sample size, missingness, ranges, weights, implausible estimates, convergence/coding errors, alternative specifications | Run & validate page (18 automatic checks); single-valued terms no longer crash a run | 13 pass, 4 warn (complete-case loss 17%, 2 out-of-range values, VIF 8.5 with BMI, 1 divergent sensitivity analysis), 0 fail |
| 7 Results | Cohort description, Table 1, regression, CIs, figures, plain language, limitations | Results page; JAMA-style manuscript | Manuscript with Key Points, Table 1-3, forest plot, plain-language summary, detected-limitations list, GRADE-informed certainty |

## Deliverables

| # | Deliverable | Provided |
|---|---|---|
| 1 | Working prototype | Web app (`python -m q2e serve`), CLI, MCP/REST tools; GitHub Actions runs real-data studies without installing anything |
| 2 | Protocol & analysis plan | `protocol_and_sap.html/.md` (new), plus the machine-readable `study_plan.json` |
| 3 | Executable, reproducible code | Reproducibility bundle: compiled plan, R engine, `reproduce.R` that re-runs and asserts the primary estimate |
| 4 | Results from NHANES | `manuscript.html/.md`, `results.json`, figures (run 26 on the `results` branch) |
| 5 | Validation / QC documentation | QC checks in the app, manuscript supplement and `results.json`; design audit; protocol section 7 |
| 6 | What stays under human supervision | Protocol section 8, Sign-off page, README "Human oversight"; approval and sign-off cannot be done by an AI tool |

## Innovation items from the brief

Interactive investigator-AI dialogue (follow-up questions) - multiple agents (investigator, data steward,
epidemiologist, statistician, reviewer, design auditor) - automated critique before analysis - feasibility score and
blinded probe - causal-language guard - comparison of alternative specifications - hash-chained provenance -
versioned, hash-locked plans - reviewer mode - automatic sensitivity analyses - literature benchmark and PubMed
novelty score.

## Evaluation criteria: items an assessor may raise

- **Scientific rigor**: BMI and waist are collinear (VIF 8.5); this is intended by the question and flagged. Excluding
  people on glucose-lowering drugs shrinks the estimate from 0.15 to 0.05 (still above zero) - worth a sentence in
  the discussion. The certainty rating comes out Moderate because of the quartile gradient (P-trend); a stricter
  reviewer could rate down for the treated-exclusion difference.
- **Safety**: row-level data never go to an LLM; the data-policy chip in the top bar shows which model is allowed.
- **Usability**: one page per section with foldable steps; only items needing a decision open themselves.
