# Concept coverage and "Can NHANES answer this?"

## 1. How a question is understood (four layers)

| Layer | Size | What it gives | Trust level |
|---|---|---|---|
| **Curated concept ontology** (`knowledge/concepts.yaml`) | ~90 clinical concepts, several hundred synonyms | Concept → guideline definition or building block, with domain defaults (covariates, exclusions, sensitivity analyses) | Curated |
| **Curated variable dictionary** (`knowledge/nhanes/dictionary.csv`) | ~135 variables with ranges, non-response codes, cycles and weight level | Exact NHANES variables, plausibility checks | Curated |
| **Full NHANES variable catalog** (`knowledge/nhanes/catalog.csv`, built by `scripts/build_nhanes_catalog.py`) | All variables in the chosen cycles (thousands) | Fallback mapping for any phrase not in the ontology | Uncurated: needs investigator confirmation |
| **Component catalog** (`knowledge/nhanes/tables.csv`) + component synonyms | ~340 NHANES tables (1999-2023) | "NHANES measures hearing in Audiometry (AUX)" even without variables | Pointer only |

Plus `not_in_nhanes`: phrases NHANES cannot answer (mortality, incidence, dementia diagnosis, sepsis/ICU, transplant, cancer stage, imaging, genetics, trials). Each has a reason and a suggested reframing.

### Parsing algorithm
1. Lower-case the question and claim **population phrases** first, longest first. "with X" is not treated as a population when it follows "associated/linked/related".
2. Claim **out-of-scope phrases** and **component synonyms**.
3. Claim **concept synonyms**, longest first, so "functional iron deficiency" beats "iron deficiency".
4. Take what remains and remove stop words plus research filler ("study", "associated", "risk", "lead to", …). The leftover content-word chunks are the **residual phrases**.
5. Search each residual phrase against the **full dictionary** (curated + catalog) with BM25. A match only counts if *every* content token appears in the variable's name, label or tags. If the whole phrase fails, try its longest sub-phrases.
6. Each match becomes a pseudo-concept `dict:VAR` and takes part in ordering like any concept:
   - yes/no questions are coded `VAR == 1`, anything else is used as-is;
   - it is flagged for **explicit confirmation** against the CDC codebook.
7. Anything still unexplained is reported as an **unmapped term**.

### Growing the ontology
* **Fastest:** build the full catalog once. On a machine with CDC access, run
  `python scripts/build_nhanes_catalog.py --cdc`. With local files, run
  `Rscript scripts/verify_nhanes_dictionary.R data/nhanes labels.csv` then `python scripts/build_nhanes_catalog.py --from-labels labels.csv`.
  Every NHANES variable then becomes reachable through step 5.
* **Curate high-value concepts:** add a building block (one line of YAML), a concept with synonyms, and a guideline definition if needed. Tests check that every concept target and every expression resolves.
* **LLM-assisted:** when a model is configured, the Investigator agent proposes expressions for unmapped concepts, and the guideline curator imports definitions from pasted text. Both stay `ai-proposed`/`proposed` until a human approves them.

## 2. Answerability engine

### Static checks (instant, no data)
| Dimension | Rule |
|---|---|
| Design fit | `not_in_nhanes` phrases → **fail** (mortality, incidence, …) or caution (trends) |
| Coverage | Component-only matches and dictionary-matched or unmapped terms → caution. An association asked with fewer than two mapped concepts → fail |
| Co-measurement | Cycles in which the outcome, the exposure and every criterion can **all** be computed. The algorithm treats `coalesce()` arguments as alternative protocols (union of cycles), e.g. oscillometric vs auscultatory BP, and every other input as required (intersection). Selected cycles outside this set → fail, with the cycles that would work |
| Subsample | Fasting (fasting weights), dietary recall (dietary weights), elastography; environmental subsamples flagged |
| Data structure | Multi-record files (medications, individual foods) need aggregation → fail |
| Eligibility | Components collected only above a minimum age (e.g. PHQ-9 ≥18, education ≥20) vs. the population's minimum age |
| Measurement | Interview-based outcome → caution |

### Blinded feasibility probe (seconds, real data, allowed before approval)
The R engine loads the files, derives variables, applies the criteria and returns **counts only**:
- eligible participants per cycle, with outcome and exposure measured, analytic n and complete-case n
- design df (PSUs − strata) and subgroup sizes
- exposure SD or level counts, and the number of model parameters
- the **outcome rate rounded to a 5-point band**

It produces no effect estimates and no exact prevalence, so the protocol cannot be shaped by the answer. Every probe is logged in the provenance ledger.

### Precision formulas (design effect DEFF = 1.8 assumed and stated)
* Prevalence 95% CI half-width = 1.96·√(DEFF·p(1−p)/n), with p at the midpoint of the band. Each subgroup is checked against the NCHS standards using n_eff = n/DEFF.
* Binary outcome and continuous exposure (log-linear model): SE(log PR per SD) ≈ √(DEFF/E), where E = expected events. **Minimum detectable PR** (80% power, α = .05) = exp(2.80·SE/SD) per reporting unit.
* Binary or categorical exposure: SE(log PR) ≈ √(DEFF·((1−p)/(n₁p) + (1−p)/(n₀p))).
* Continuous outcome: detectable standardized slope = 2.80·√(DEFF/n), converted to outcome units per exposure unit.
* Events per parameter, and parameters vs design df.

These are unadjusted approximations; adjustment for correlated covariates widens them (stated in the output).

### Verdict
Any fail → **Not answerable as stated** (with suggestions); any caution → **Answerable with caveats**; otherwise **Answerable**.
A "not answerable" verdict becomes a major reviewer item. The investigator must acknowledge it, which accepts the
reframed cross-sectional question, before approving.
