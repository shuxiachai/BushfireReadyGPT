# Benchmark Evidence

This folder contains machine-readable engineering regression results. It does
not contain stakeholder validation, production accuracy claims or emergency-use
evidence.

## v0.5.0 Release Evidence

The current release evidence consists of two complete machine-readable artifacts:

- [`rag-retrieval-v0.5.0.json`](rag-retrieval-v0.5.0.json), schema
  `bushfire-rag-evaluation-v3`;
- [`report-generation-v0.5.0.json`](report-generation-v0.5.0.json), schema
  `bushfire-report-generation-evaluation-v3`.

Both runs were collected from clean source commit
`e02f07687ee2e2329fc59afb5fe1c8ea4f532646`. Their start and completion
snapshots were stable, and both bind the same verified RAG manifest
`aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`.
The retrieval run records embedding model digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
The report run records model digest
`21aa9b63ebd65652bfda214b8012ba0d61375855a448d7396ed57a7d7fa0f8ac`
and governed quality policy `governed-report-v2` with fingerprint
`7c20b6fa049dc1028cc367955eb28b5434318b2d4050995cc9cf58b53a5da9d1`.

### RAG retrieval

| Profile | Questions | Passage Recall@K | MRR | Top-1 | Abstention | Average | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Structured planning Top-8 | 73 (68 answerable + 5 unanswerable) | 1.0000 | 0.9216 | 0.8529 | 1.0000 | 130.36 ms | 157.49 ms |
| Free text Top-5 | 84 (68 answerable + 16 unanswerable) | 0.9706 | 0.8922 | 0.8235 | 1.0000 | 131.59 ms | 159.00 ms |

An active release artifact must retain every per-question row for every included
profile. Offline validation rejects missing or duplicate question IDs and
re-aggregates question counts, answerable/unanswerable counts, source and
passage recall, MRR, Top-1, abstention and false-positive rate from those rows.
`--summary-only` remains available for smaller diagnostic output, but it always
marks the release gate inactive and cannot become release evidence.

Repeat the complete evaluation with:

```powershell
poetry run python scripts\evaluate_rag.py --warmup --output output\rag-retrieval-next.json
```

### Governed report generation

The eight-case run covers all six product scenarios, deterministic refusal of a
live-route request and explicit no-RAG degradation. Its enforced rates were:

| Gate | Result |
| --- | ---: |
| Governed report | 1.0000 |
| Structural | 1.0000 |
| Evidence binding | 1.0000 |
| RAG title attribution | 1.0000 |
| RAG behaviour | 1.0000 |
| Scenario topic | 1.0000 |
| Safety violations | 0.0000 |
| Unsafe live claims | 0.0000 |
| Scenario contamination | 0.0000 |
| Oversized reports | 0.0000 |
| Repair rate | 0.6250 |

Average model-run latency was `46.77 seconds` on the release machine. All eight
reports remained `review_required` under the diagnostic grounding heuristic.
Average grounding support was `0.9280`, citation coverage `0.2687`, citation
precision `0.8571`, numeric consistency `0.9167`, and jurisdiction conflicts
were `0`. These grounding metrics remain advisory and are not included in the
release `passed` decision.

Repeat the complete report run with:

```powershell
poetry run python scripts\evaluate_report_generation.py --output output\report-generation-next.json
```

After both reviewed artifacts and the current showcase package are in their
versioned repository paths, verify the complete release evidence offline:

```powershell
poetry run python scripts\verify_release.py
```

The verifier does not call Ollama or the network. It validates artifact schemas
and active passing gates, exact current source-dataset hashes, shared Git and RAG
index provenance, the current quality-policy binding, and the governed
`examples/v0.5.0` showcase package.

## Historical: Report Generation v0.4.0

`report-generation-v0.4.0.json` repeats the same eight declared product, safety
and degradation cases with the `v0.4.0` evaluator. The 2026-08-22 local run:

- passed every configured structural, evidence-binding, RAG-behaviour, topic,
  contamination, unsafe-live-claim and size gate;
- averaged `27.74 seconds` on the release machine;
- required one structural repair (`0.125` repair rate);
- measured average lexical evidence support `0.9540`;
- measured sentence-level citation coverage `0.2311` and cited-source precision
  `1.0000`;
- measured numeric consistency `0.9583` and zero jurisdiction conflicts;
- marked all eight reports `review_required` under the new grounding heuristic.

Grounding metrics in this release are deliberately diagnostic and are not part
of the aggregate `passed` decision. The JSON records
`grounding_release_gate_enforced: false`. Low citation coverage is a measured
report-authoring gap, not evidence that the reports are factually correct or
incorrect. Every claim still requires human checking against the current
official page before formal use.

Repeat the current run with:

```powershell
poetry run python scripts\evaluate_report_generation.py --output output\report-generation-next.json
```

The committed `v0.4.0` result is historical release evidence. Do not overwrite
it with a later evaluator or quality policy; review a new output and commit it
under the next release/version name.

## Historical: RAG Retrieval Summary 2026-08-24

`rag-retrieval-2026-08-24.json` records an earlier summary-only local
dual-profile invocation:

- the production-aligned `structured_planning` Top-8 profile covered 68
  answerable questions plus five reachable live/life-safety negatives;
- the separate `free_text` Top-5 profile covers the full 84-question diagnostic,
  including 16 hard negatives;
- both configured and actually effective thresholds are recorded, so the
  trusted-planning relaxation is visible rather than hidden.

The historical file predates the v0.5.0 full-row artifact contract. Under the
current evaluator, repeat a comparable summary diagnostic with:

```powershell
poetry run python scripts\evaluate_rag.py --warmup --summary-only
```

The resulting release gate is intentionally inactive. Latency is
machine-specific. Retrieval metrics are regression evidence, not factual
correctness or production accuracy.

## Historical: Report Generation v0.3.0

`report-generation-v0.3.0.json` records one real local-Ollama run against eight
declared cases:

- six product scenarios: school, council, community, household, aged care and farm;
- one live-route request that must remain outside the product safety boundary;
- one no-RAG case that must degrade explicitly rather than invent retrieval evidence.

The run used `bushfire-ready-qwen` with temperature `0.2`, seed `42` and a 2,300
token output limit. It passed all configured gates. The average latency of
`27.97 seconds` describes only the release machine and should not be compared
across hardware as a product performance claim.

The benchmark checks report structure, deterministic evidence binding, RAG
source-title attribution, expected RAG behavior, unsafe live claims, scenario
topic coverage, cross-scenario contamination, repair frequency and report size.
It does not establish that factual statements, legal wording or preparedness
actions are correct for a real organisation.

To repeat the run after Ollama, the report model and the verified RAG index are
available:

```powershell
poetry run python scripts\evaluate_report_generation.py --output docs\benchmarks\report-generation-v0.3.0.json
```

Hardware, model and corpus changes may legitimately change latency and model
wording. Review the complete JSON result and do not copy only the aggregate
`passed` field into external claims.
