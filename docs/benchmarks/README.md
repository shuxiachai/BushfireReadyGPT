# Benchmark Evidence

This folder contains machine-readable engineering regression results. It does
not contain stakeholder validation, production accuracy claims or emergency-use
evidence.

## v0.6.0 Release Evidence

The current release evidence consists of three complete machine-readable artifacts:

- [`rag-retrieval-v0.6.0.json`](rag-retrieval-v0.6.0.json), schema
  `bushfire-rag-evaluation-v3`;
- [`report-generation-v0.6.0.json`](report-generation-v0.6.0.json), schema
  `bushfire-report-generation-evaluation-v4`;
- [`report-red-team-v0.6.0.json`](report-red-team-v0.6.0.json), schema
  `bushfire-report-generation-evaluation-v4`.

All three runs were collected from clean source commit
`44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`. Their call-boundary and completion
snapshots were stable, and all bind the same verified RAG manifest
`aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`.
The retrieval run records embedding model digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
Both report runs record model digest
`21aa9b63ebd65652bfda214b8012ba0d61375855a448d7396ed57a7d7fa0f8ac`
and governed quality policy `governed-report-v6` with fingerprint
`b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`.

Local source validation completed with `884` passing non-E2E tests, `1`
separately selected E2E test and `86.95%` non-E2E `src` coverage. These are
engineering results, not a substitute for external user validation.

### RAG retrieval

| Profile | Questions | Passage Recall@K | MRR | Top-1 | Abstention | Average | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Structured planning Top-8 | 73 (68 answerable + 5 unanswerable) | 1.0000 | 0.9216 | 0.8529 | 1.0000 | 86.05 ms | 124.15 ms |
| Free text Top-5 | 84 (68 answerable + 16 unanswerable) | 0.9706 | 0.8922 | 0.8235 | 1.0000 | 94.00 ms | 113.10 ms |

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
live-route request and explicit no-RAG degradation. Its active release gate
passed all `8/8` cases; enforced rates were:

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
| Repair rate | 0.1250 |
| Repair success rate | 1.0000 |
| Repair exhaustion rate | 0.0000 |

Average model-run latency was `26.99 seconds` on the release machine. All eight
reports remained `review_required` under the diagnostic grounding heuristic.
Average grounding support was `0.9612`, citation coverage `0.0000`, citation
precision `0.0000`, numeric consistency `0.9792`, and jurisdiction conflicts
were `0`. The attribution metric represents application-bound retrieval
provenance, not claim-level model citation accuracy. Grounding remains a lexical
diagnostic, is not included in the release `passed` decision, and requires human
source review.

Repeat the complete report run with:

```powershell
poetry run python scripts\evaluate_report_generation.py --output output\report-generation-next.json
```

### Prompt-injection red team

The six-case red-team suite covers U0 location, audience and additional-context
overrides; governance removal; forged tool Markdown; and delimiter/live-route
prompt leakage. Its active diagnostic gate passed all six cases:

| Diagnostic | Result |
| --- | ---: |
| Governed report | 1.0000 |
| Prompt-injection resistance | 1.0000 |
| Safety violations | 0.0000 |
| Repair success | 1.0000 |
| Repair exhaustion | 0.0000 |

Average model-run latency was `30.45 seconds`. The red-team artifact's release
gate is inactive by design and its diagnostic gate is active and passing; it
cannot replace the eight-case product release suite.

Repeat the red-team diagnostic with:

```powershell
poetry run python scripts\evaluate_report_generation.py --scenario-file data_australia\rag\report_red_team-v0.6.0.json --output output\report-red-team-next.json
```

After all three reviewed artifacts and the current showcase package are in their
versioned repository paths, verify the complete release evidence offline:

```powershell
poetry run python scripts\verify_release.py
```

The verifier does not call Ollama or the network. It validates artifact schemas
and active passing gates, exact current source-dataset hashes, shared Git and RAG
index provenance, the current quality-policy binding, and the governed
`examples/v0.6.0` showcase package.

These artifacts are engineering regression evidence, not operational-safety or
stakeholder-validation evidence. No real external pilot has been completed.

## Historical: v0.5.0 Release Evidence

The immutable `rag-retrieval-v0.5.0.json` and
`report-generation-v0.5.0.json` artifacts remain available as the previous
release baseline. They retain their original source-commit, model, policy and
latency metadata and are not rewritten under the v0.6.0 contract.

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
