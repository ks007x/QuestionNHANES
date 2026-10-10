# What stays under human supervision

Q2E automates the mechanical parts of a retrospective study: drafting, mapping, coding, executing, checking and
formatting. It keeps people in charge of the judgments that determine whether a study is valid. Each gate below is
enforced in code, not left to convention.

| Decision | Why a human | How Q2E enforces it |
|---|---|---|
| **Framing the question** | Clinical meaning and relevance | The agents' interpretation is shown as an editable protocol. Ambiguous role assignment ("first concept = exposure") is stated in the roundtable, and a one-click swap is offered. |
| **Case definitions** | Guidelines are written for clinicians, not survey datasets | Each definition shows its source and verification status. **Operational assumptions** (e.g. hsCRP >5 mg/L as the inflammation proxy for ASH 2026; BMI ≥30 as the obesity flag for Baveno VIII) are *major* reviewer items that must be acknowledged before approval. |
| **New / AI-proposed definitions or variables** | LLMs can hallucinate thresholds | They are stored as `proposed` or `ai-proposed`. The compiler refuses to run them, and the reviewer raises a *blocker* until a named person approves. |
| **Confounder selection** | Causal structure is subject-matter knowledge | Agents remove mediators and variables that share components with the outcome or exposure definition, and explain why. The investigator can add or remove any covariate. |
| **Approval to execute** | Prevents "run first, justify later" | Running requires an approval whose recorded hash equals the current plan hash. Any edit invalidates it. |
| **QC failures** | Automated checks can be wrong in both directions | Sign-off is impossible while a check has status `fail` and no written override reason. Overrides are stored in the ledger. |
| **Interpretation** | Cross-sectional data support association only | Causal-language detection runs on the question, the protocol and the generated narrative. LLM narrative is drafted from aggregate results only and softened automatically; the human signs the final text. |
| **Sign-off** | Accountability | Five attestations, a name, and the plan and results hashes go into a tamper-evident ledger. |
| **Data governance** | Institutional responsibility | Restricted mode limits LLM use to approved or local providers; row-level data never leave the R engine. |

## Where autonomy is safe
Parsing and drafting, variable lookup, code generation through the compiler, execution, standard checks, formatting,
literature search, and producing the reproducibility bundle. In all of these, a mistake is visible and reversible
before sign-off.
