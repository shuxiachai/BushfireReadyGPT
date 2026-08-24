# BushfireReadyGPT v0.5.0 Governed Sample

This is the current release sample for the Cairns Council pilot scenario. It is a
preparedness-planning draft for portfolio and controlled-review use. It is not
live emergency advice, an evacuation order or an operational plan.

## Included Files

| File | Size | Verification detail |
| --- | ---: | --- |
| `cairns-council-report.md` | 24,213 bytes | Exact governed Markdown bound to the audit record |
| `cairns-council-report.pdf` | 44,300 bytes | 16 readable pages |
| `cairns-council-report.docx` | 49,611 bytes | 203 paragraphs with a dedicated human-sign-off page |
| `cairns-council-pilot-package.zip` | 111,776 bytes | Current `pilot-export-v4` governance package |

The report passed the canonical governed gate on its first generation attempt.

## Provenance Boundary

- Release-benchmark source commit: [`e02f076`](https://github.com/shuxiachai/BushfireReadyGPT/commit/e02f07687ee2e2329fc59afb5fe1c8ea4f532646)
- Quality policy: `governed-report-v2`
- Quality fingerprint: `7c20b6fa049dc1028cc367955eb28b5434318b2d4050995cc9cf58b53a5da9d1`
- Model provider and name: `ollama` / `bushfire-ready-qwen`
- Model endpoint boundary: `local_loopback`
- RAG manifest: `aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`

The sample audit binds the provider, configured model name, local-loopback
boundary and the same RAG manifest used by the v0.5.0 benchmarks. It does **not**
bind or claim a sample-generation model digest. The separate report benchmark
records its own resolved model identity and digest.

## Verification

The current verifier checks:

- ZIP CRC integrity, duplicate entries, case collisions and unsafe paths;
- exact manifest contents and complete non-manifest SHA-256 coverage;
- the current audit head, complete audit chain and recursive parent lineage;
- governed quality-policy, analysis and reviewer-sign-off bindings;
- Markdown, PDF and DOCX readability and required report markers;
- internal prompt/retrieval-boundary leakage across reports and governance files;
- absence of `sensitive_payload` from committed audit chains; and
- byte-for-byte equality between standalone reports and their packaged copies.

## Associated v0.5.0 Evidence

The [RAG artifact](../../docs/benchmarks/rag-retrieval-v0.5.0.json) records:

- structured Top-8: 73 questions (68 answerable + 5 safety negatives), recall
  1.0000, MRR 0.9216, Top-1 0.8529, abstention 1.0000, average 130.36 ms and p95
  157.49 ms;
- free-text Top-5: 84 questions (68 answerable + 16 negatives), recall 0.9706,
  MRR 0.8922, Top-1 0.8235, abstention 1.0000, average 131.59 ms and p95 159.00 ms.

The [report artifact](../../docs/benchmarks/report-generation-v0.5.0.json)
records eight scenarios. Governed, structural, evidence-binding, RAG attribution,
RAG behaviour and topic gates are all 1.0000; safety-violation and unsafe-live
rates are 0.0000; repair rate is 0.6250; and average latency is 46.77 seconds.
Diagnostic grounding is 0.9280 support, 0.2687 citation coverage, 0.8571
precision, 0.9167 numeric consistency and zero jurisdiction conflicts. All eight
cases remain `review_required` for human grounding review.

Release validation passed 429 tests: 428 non-E2E tests at 86.08% coverage plus
one Chromium E2E test. These are engineering regression results, not real-user,
operational or government validation.

The `examples/v0.3.0/` package remains available only as a historical release
sample.
