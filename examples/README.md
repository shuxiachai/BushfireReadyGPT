# Example Outputs

This folder contains static example outputs for people reviewing the project without running the Streamlit app.

The examples are intended for demonstration and portfolio review. They are not live emergency advice and must not be used as operational bushfire instructions.

The versioned examples below are frozen evidence for their named releases, not
regenerated examples of the maintained `main` branch. In particular, the
September 10 population-basis correction is not retroactively applied to their
language-ratio text. A current report treats unsupported legacy ratios as
unknown. Preserve the old outputs for comparison; do not reuse their figures as
current validated indicators.

`scripts/build_showcase_sample.py` refuses to overwrite any existing sample
output, before calling the model and again at publication. For a new diagnostic
use a fresh `--output-dir output/showcase-<run-id>`; a completed sample is not a
formal release until its source, model/index identity, evaluations and export
checks are recorded. See the [follow-up status](../docs/AUDIT_FOLLOWUP_2026-09-11.md).

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
