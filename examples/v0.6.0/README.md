# BushfireReadyGPT v0.6.0 Governed Sample

This is the current Cairns Council portfolio sample. It is a preparedness-
planning draft for controlled review, not live emergency advice, an evacuation
order or an operational plan.

## Included Files

| File | Size | SHA-256 / verification detail |
| --- | ---: | --- |
| `cairns-council-report.md` | 23,274 bytes | `713f1fbfc0ff81157e6ad01fd4a03aa400e1e1ce4564372be05268dddb816237` |
| `cairns-council-report.pdf` | 42,849 bytes | `94e29779485569a5205c5c4d2cb9e2e0841ae59676c3c622778fe7a2d0632665`; 15 pages |
| `cairns-council-report.docx` | 49,337 bytes | `872fcb71b7e11ef4af8b38bfeb12d3393a87106eb73386345e9b7c2bf883b52f`; 166 paragraphs |
| `cairns-council-pilot-package.zip` | 111,376 bytes | `4647d71a1471ff89756d55cb8f3a17b7657dfbfaaa8cf310524af18e2cb4bc51` |

The report passed the current governed gate on its first generation attempt.

## Provenance Boundary

- Release-benchmark source commit: [`44d0c3f`](https://github.com/shuxiachai/BushfireReadyGPT/commit/44d0c3f1f8c78af4291f79b090eb3fc53da95ea7)
- Quality policy: `governed-report-v6`
- Quality fingerprint: `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`
- Model provider and name: `ollama` / `bushfire-ready-qwen`
- Model endpoint boundary: `local_loopback`
- RAG manifest: `aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`

The package audit binds the provider, configured model name, local-loopback
boundary, current policy and the same RAG manifest as the v0.6.0 benchmarks. It
does not claim or store a sample-generation model digest; the separate benchmark
records its own resolved model identity.

## Associated Evidence

- [RAG benchmark](../../docs/benchmarks/rag-retrieval-v0.6.0.json): 73-question
  production Top-8 release gate with 1.0000 recall, 0.9216 MRR, 0.8529 Top-1 and
  1.0000 abstention; the 84-question Top-5 profile remains diagnostic.
- [Product benchmark](../../docs/benchmarks/report-generation-v0.6.0.json): all
  eight governed scenarios pass with zero safety violations and zero repair
  exhaustion.
- [Prompt-injection red team](../../docs/benchmarks/report-red-team-v0.6.0.json):
  all six attacks pass the independent diagnostic gate with 1.0000 resistance.

Application-bound RAG attribution is retrieval provenance, not claim-level
citation accuracy. Grounding remains diagnostic and requires human review.
Local validation passed 884 non-E2E tests at 86.95% coverage plus one Chromium
E2E test. No external participant or real-user outcome is claimed.
