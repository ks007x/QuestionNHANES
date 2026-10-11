# Using Amazon Bedrock with BEDSIDE

BEDSIDE (formerly Q2E; the package and CLI keep the `q2e` name) runs without any AI model: every agent has a rule-based version, and the statistics are always done by the R
engine. Turning on Bedrock adds a language model on top. It never sees row-level data, only the question, the
study plan, variable metadata and aggregate results (estimates, CIs, counts). Identifiers are scrubbed before
every call and each call is logged.

## What changes when Bedrock is on

| Where | Agent | Without AI | With Bedrock |
|---|---|---|---|
| Ask | Recognizer | Abbreviations, variants and typos by rules ("type ii diabetes", "T2DM", "HTN", "diabetis") | Model also maps lay, regional and unusual terms ("sugar diabetes", "renal stones") to catalog terms; only phrases that appear verbatim in the question are relabelled, shown as "Recognized: … · AI" chips |
| Ask | Interviewer | Fixed follow-up questions | Extra follow-up questions written for your idea (every choice checked against the NHANES catalog) |
| Plan | Investigator, Reviewer | Rule-based plan and review | Model refines the question and adds review comments |
| Plan | Statistician (model advisor) | Options scored by rules | Model re-ranks the same options and explains why (it can only pick from the listed, runnable models) |
| Results | Librarian (published evidence) | Regex reads OR/PR/HR/β with CIs from abstracts | Model also reads each abstract; a number is kept only if it appears in the abstract text |
| Plan | Epidemiologist (covariates) | Confounder/mediator roles from the curated library | Model reviews each candidate's role and explains it; it can only comment on listed variables and nothing changes until you click |
| Results | Writer | Template manuscript | "Manuscript + AI narrative": introduction, discussion, limitations, a methods summary and a plain-language summary. Every number still comes from R |

The app header shows which one is active: `AI: bedrock · <model>`, `AI: bedrock not ready` (hover for the reason),
or `AI off · rule-based agents`. The model advisor and evidence cards also say which model produced them.

## Quickest: paste your Bedrock API key into BEDSIDE

1. AWS console → **Amazon Bedrock** → **Model access**: enable an Anthropic Claude model in your region.
2. **Amazon Bedrock → API keys → Generate**. Copy the key.
3. In BEDSIDE, click the **AI chip** in the top bar (it says `AI off · rule-based agents`), or *Connect Amazon Bedrock*
   under *Data and settings* on the Ask page. Paste the key, pick the region, leave the model blank to let BEDSIDE pick a
   Claude model, and press **Test and connect**.

BEDSIDE sends one tiny test request before it keeps the key. The key is never shown again, never written to a
project, log or GitHub, and is saved only in this folder's `.env` file if *Remember on this computer* is ticked
(`.env` is in `.gitignore`). *Turn AI off* in the same dialog disconnects and can also remove the saved key.

**Setup code.** If the browser is not on the computer running BEDSIDE (GitHub Codespaces, a forwarded port, another
machine), the dialog also asks for a setup code. BEDSIDE prints it in its terminal when it starts:

```
  BEDSIDE setup code: 1234-5678
```

Only the person who started BEDSIDE can see it, so a stranger who can reach the web page cannot change the AI login.
After 10 wrong codes the dialog locks until BEDSIDE is restarted (which prints a new code).

From a terminal instead: `python -m q2e bedrock-connect` asks for the key without showing it, tests it and saves it.

**Never put a real key in `.env.example`** - that file is committed. If a key was ever committed, delete it in the
AWS console (Bedrock → API keys) and generate a new one; removing it from the file does not remove it from git history.

## 1. Get credentials (one of two kinds)

* **Bedrock API key** (simplest): AWS console → Amazon Bedrock → API keys → generate. One long value.
* **Access keys**: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`. Hackathon/student accounts also give an
  `AWS_SESSION_TOKEN`; those keys expire after a few hours, so paste fresh ones when calls start failing.

In the console, under **Bedrock → Model access**, make sure a Claude model is enabled in your region.

## 2. Run on your own computer

```bash
cp .env.example .env          # once
```

Fill in `.env`:

```
Q2E_LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
AWS_BEARER_TOKEN_BEDROCK=<your key>          # or the three AWS_* access-key lines
Q2E_BEDROCK_MODEL_ID=                        # leave empty for now
```

Then:

```bash
python -m q2e bedrock-check
```

It lists the models your login can use. Copy a Claude id (inference-profile ids look like `us.anthropic.claude-…`)
into `Q2E_BEDROCK_MODEL_ID`, run `bedrock-check` again until it prints **Bedrock works**, then start the app:

```bash
python -m q2e serve           # http://127.0.0.1:8000
```

You can also switch per study: on the Ask page open **Data and settings → AI agents** and pick `bedrock` or `offline`.

Headless run of a whole study with Bedrock:

```bash
python -m q2e study "Is abdominal obesity linked to worse glycemic control?" --source cdc --provider bedrock --out outputs/bedrock
```

The first line of the log says `AI agents: bedrock (<model>)`; the model advisor and evidence lines say whether AI was used.

## 3. Run in GitHub Codespaces

Codespaces reads secrets as environment variables. On github.com: **Settings → Secrets and variables → Codespaces**,
add `AWS_BEARER_TOKEN_BEDROCK` (or the access keys), `Q2E_BEDROCK_MODEL_ID` and `Q2E_LLM_PROVIDER=bedrock`, then
start (or restart) the codespace. No `.env` file needed.

## 4. Run the real-data GitHub workflow with Bedrock

1. Repository **Settings → Secrets and variables → Actions**:
   * Secrets tab: `AWS_BEARER_TOKEN_BEDROCK` (or `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
   * Variables tab: `Q2E_BEDROCK_MODEL_ID`, and `AWS_REGION` if not `us-east-1`
2. **Actions → Run a study on real NHANES data → Run workflow**, set **AI agents** to `bedrock`.

The workflow first runs `bedrock-check` and stops with a clear message if a secret or the model id is missing.
The run's README on the `results` branch records which AI setting was used. GitHub never prints secret values in logs.

## Data governance

* `Q2E_DATA_POLICY=public` (default, public-use NHANES): any configured provider may be used.
* `Q2E_DATA_POLICY=restricted`: only providers listed in `Q2E_APPROVED_PROVIDERS` (Bedrock is on that list by
  default, for tenants covered by an institutional agreement) and no aggregates are sent.
* `Q2E_SEND_AGGREGATES=false` keeps even aggregate results away from the model.

## Troubleshooting

| Message | Fix |
|---|---|
| `No AWS credentials` | Key not in `.env`/secrets, or the line has a typo |
| `ExpiredToken` / `security token … invalid` | Temporary keys expired: paste fresh ones and restart |
| `AccessDeniedException` | Enable the model under Bedrock → Model access, or pick another id from `bedrock-check` |
| `on-demand throughput isn't supported` | Use the inference-profile id (`us.anthropic.…`), not the bare model id |
| Header says `bedrock not ready` | Hover the chip for the reason; restart the server after editing `.env` |

Answers are cached in `workspace/llm_cache/`, so repeating the same step is instant and costs nothing.
