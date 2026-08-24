# Benchmark Evidence

This folder contains machine-readable engineering regression results. It does
not contain stakeholder validation, production accuracy claims or emergency-use
evidence.

## Report Generation v0.4.0

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

## RAG Retrieval 2026-08-24

`rag-retrieval-2026-08-24.json` records one local dual-profile invocation:

- the production-aligned `structured_planning` Top-8 profile is the active
  release gate and covers 68 answerable questions plus five reachable
  live/life-safety negatives;
- the separate `free_text` Top-5 profile covers the full 84-question diagnostic,
  including 16 hard negatives;
- both configured and actually effective thresholds are recorded, so the
  trusted-planning relaxation is visible rather than hidden.

Repeat it with:

```powershell
poetry run python scripts\evaluate_rag.py --warmup --summary-only
```

Latency is machine-specific. Retrieval metrics are regression evidence, not
factual correctness or production accuracy.

## Report Generation v0.3.0

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
