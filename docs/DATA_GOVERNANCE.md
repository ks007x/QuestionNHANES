# Data governance & intellectual property

* **Row-level data never reach a language model.** The R engine reads the data. LLM payloads are built from the question (scrubbed for identifiers), the study plan and data-dictionary metadata. Aggregate results go to an LLM only when `Q2E_DATA_POLICY=public` and `Q2E_SEND_AGGREGATES=true`.
* **Restricted mode** (`Q2E_DATA_POLICY=restricted`): only providers listed in `Q2E_APPROVED_PROVIDERS` can be used, for example a local Ollama model or an enterprise Azure OpenAI or Bedrock deployment covered by your BAA/DUA. No aggregate results are sent.
* **Identifier scrubbing**: emails, phone numbers, SSNs, MRNs, dates, long numbers and titled names are redacted from free text before any LLM call or speech-to-text post-processing.
* **Audit**: every LLM call records the provider, model, agent, payload SHA-256, latency and success in the provenance ledger. You can see what kind of data went out without storing the payload itself.
* **Unpublished ideas**: running in offline mode, or with a local model, keeps the research question on your infrastructure.
* **Public NHANES** files are downloaded from CDC over HTTPS and identified by MD5 in every run's metadata.
