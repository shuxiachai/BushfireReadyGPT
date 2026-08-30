# Example Outputs

This folder contains static example outputs for people reviewing the project without running the Streamlit app.

The examples are intended for demonstration and portfolio review. They are not live emergency advice and must not be used as operational bushfire instructions.

Available examples:

- `v0.6.0/` - the current Cairns Council Markdown, PDF and DOCX reports plus the verified `pilot-export-v4` package.
- `v0.5.0/` - the historical v0.5.0 governed package retained for release comparison.
- `v0.3.0/` - the historical governed Cairns Council package retained for release comparison.
- `cairns_campus_bushfire_report.md` - an earlier lightweight historical campus draft.

The v0.6.0 verifier first checks the three tracked release artifacts, their clean
source-commit ancestry and shared model/index/policy identities. It then checks
package CRC, duplicate/case-colliding and unsafe paths, complete hashes, audit
lineage, prompt-marker leakage and sensitive audit payloads. Sample metadata
binds Ollama as the provider, `bushfire-ready-qwen` as the model name, the
local-loopback boundary, `governed-report-v6` and the same RAG manifest as the
release benchmarks. It does not claim or store a sample-generation model digest.
