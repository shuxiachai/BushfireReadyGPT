# Local Official-Knowledge RAG

## Why it exists

The RAG subsystem demonstrates a conventional, explainable retrieval pipeline
without weakening the project's safety boundary. It retrieves small passages
from static Australian government preparedness material before report
generation. It does not read live incidents, warnings, fire bans, evacuation
orders or confirmed safe routes.

## Runtime flow

```text
sources.yml -> HTTPS download -> document validation -> focused multi-region extraction
            -> deterministic chunks -> Ollama embeddinggemma -> Qdrant + document snapshot

report form -> jurisdiction-aware query -> dense candidates + BM25 candidates
            -> weighted reciprocal-rank fusion -> bounded metadata rerank
            -> per-source diversity cap -> top-k passages
            -> Official Knowledge Agent -> evidence table + bounded prompt context
            -> report generation -> Evidence Trail + privacy-minimised audit metadata
```

The report form's free-text additional context is deliberately not copied into
the retrieval query. The query uses only state, locality, setting, scenario,
focus areas and timeframe. This reduces accidental disclosure and makes the
retrieval input reproducible.

## Build and evaluate

From the project root:

```powershell
ollama pull embeddinggemma
poetry run python scripts\build_rag_index.py --download
poetry run python scripts\evaluate_rag.py --warmup --output output\rag-retrieval-next.json
```

The default command evaluates two explicit profiles. `structured_planning`
matches report generation by enabling the trusted planning scope and using the
runtime `BUSHFIRE_RAG_TOP_K` value (8 by default); this profile controls the
process exit code and release gate. `free_text` keeps the stricter answerability
thresholds and runs at Top-5 as a diagnostic. The JSON records each profile's
query scope, Top-K, candidate limit, configured thresholds and effective
thresholds. This makes any structured-planning threshold relaxation visible.
An active release artifact also includes every per-question result row for every
profile. The offline validator rejects missing or duplicate IDs and recomputes
question counts, source and passage recall, MRR, Top-1, abstention and
false-positive rate directly from those rows instead of trusting the summary.
The production profile runs all 68 answerable questions and the five
live-operation/life-safety negatives that the retrieval boundary must always
withhold. The remaining 11 arbitrary out-of-domain negatives are scoped to
`free_text`: the trusted planning profile is only reachable through a bounded,
form-built, in-domain query in the application, so treating arbitrary user text
as trusted would not represent production behavior.

For a backward-compatible free-text-only run, use:

```powershell
poetry run python scripts\evaluate_rag.py --mode free_text --top-k 5 --warmup --summary-only
```

`--mode structured_planning` without `--top-k` uses the production Top-K and is
eligible for the release gate only when full per-question rows are retained.
Supplying `--top-k` in that mode is allowed for investigation; the JSON marks
the release gate inactive whenever that value differs from the runtime
production setting. `--summary-only` also always marks the gate inactive, even
when the production Top-K is used, so a compact diagnostic cannot be mistaken
for auditable release evidence.

Use `--refresh` to re-download every declared source. The build creates local
files under `data_australia/rag/raw/` and `data_australia/rag/index/`; both are
ignored by Git. `BUSHFIRE_RAG_ENABLED=false` disables retrieval without
disabling the rest of the report pipeline.

The catalog currently covers nine official preparedness pages across all eight
Australian states and territories. Every page declares a licence URL, a reuse
classification and the date its metadata was last verified. Restricted or
ambiguous pages remain useful as local references but require permission review
before redistribution.

The committed evaluation set contains 68 answerable questions plus 16 hard
negatives. It measures source-level and passage-level Recall@K, mean reciprocal
rank, Top-1 accuracy, unanswerable accuracy, false-positive rate and latency. On
the 2026-08-22 `v0.3.0` free-text baseline, Top-5 passage recall was 0.9706, MRR
0.8922, Top-1 accuracy 0.8235, unanswerable accuracy 1.0000, average latency
133.48 ms and p95 latency 163.44 ms. These are reproducible project-benchmark
results, not evidence of production accuracy. Unit tests use a deterministic test
embedder and temporary Qdrant database, keeping CI offline and repeatable.

The current `v0.5.0` run was collected from clean commit
`e02f07687ee2e2329fc59afb5fe1c8ea4f532646`. The production-aligned
`structured_planning` profile ran at Top-8 over 73 questions: 68 answerable
questions plus five reachable live/life-safety negatives. It recorded passage
recall `1.0000`, MRR `0.9216`, Top-1 accuracy `0.8529`, abstention `1.0000`,
average latency `130.36 ms` and p95 latency `157.49 ms`. The same complete run
evaluated the 84-question free-text Top-5 profile and recorded passage recall
`0.9706`, MRR `0.8922`, Top-1 `0.8235`, abstention `1.0000`, average latency
`131.59 ms` and p95 latency `159.00 ms`.

The machine-readable result is committed as
[`rag-retrieval-v0.5.0.json`](benchmarks/rag-retrieval-v0.5.0.json), schema
`bushfire-rag-evaluation-v3`. It binds embedding model digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`
and verified RAG manifest
`aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2`.
Its start/end provenance check was stable. The older
[`rag-retrieval-2026-08-24.json`](benchmarks/rag-retrieval-2026-08-24.json) is
retained as historical summary evidence; it does not satisfy the current
full-row release contract.

Retrieval uses weighted reciprocal-rank fusion (0.65 dense / 0.35 BM25 by
default), then small exact-jurisdiction and title-overlap boosts. A deterministic
per-source cap prevents one long page from occupying every returned slot. The
Evidence Trail records the dense score/rank, BM25 score/rank, fused score and
rerank reasons so the result can be explained in an interview or review.

## Integrity and prompt-injection controls

- Catalog entries require unique IDs, HTTPS URLs, bounded local paths and source metadata.
- Downloads are size-limited, retried only for transient failures and validated before atomic writes.
- HTML sources can declare one or more focused ID selectors; every selector must still exist and known WAF pages are rejected.
- Each chunk has deterministic content and identity SHA-256 values.
- Build and retrieval access to the same resolved embedded-Qdrant path is serialised inside one process; the cross-process lock has a unique owner token, reclaims an old lock only after its process is confirmed absent, and removes the lock only when the token still matches. Staged publication retains this lock, and a leftover backup is restored before any partial replacement is trusted.
- A build copies the catalog and every declared source into a private immutable snapshot, verifies the captured hashes before and after embedding, and leaves the previous index untouched if live inputs drift.
- The manifest binds catalog bytes, source bytes, canonical document snapshot, chunk corpus, embedding model and vector dimension.
- Retrieval validates the index generation at entry and exit and revalidates source bytes, the complete document snapshot, manifest, collection count, point ID and returned text hash before returning passages.
- The Python 3.13 embedded-Qdrant path derives SQLite thread safety without leaking the temporary probe connection used by the upstream client.
- Passages are delimited as untrusted quoted evidence; the model is told never to follow passage instructions.
- Prompt payloads cap total retrieved context at 8,000 characters and each passage at 2,200 characters.
- The audit stores query/source/chunk hashes and scores, but not retrieved passage text by default.
- Live-warning and life-safety queries are deterministically withheld from the static corpus, while free-text retrieval must pass lexical or combined semantic/lexical answerability thresholds.
- Release evaluation checks question bytes, Git state, RAG index and embedding-model identity before and after every warm-up and question call, and binds the manifest identity actually used by retrieval. Drift visible at those boundaries aborts an active release before an artifact is written, including A-to-B-to-A file/index/model changes across calls that a final snapshot could otherwise hide. A model-tag swap wholly inside one embedding HTTP call is not observable and is disclosed as such in new run metadata.
- Active release artifacts retain full profile rows and are re-aggregated offline; summary-only output remains diagnostic and release-inactive.

These controls make accidental corruption and common prompt-injection paths
visible. They do not make a local operator-proof or cryptographically signed
knowledge base. A person with filesystem access can replace the whole project,
sources and audit history.

## Interview discussion points

- Why local Ollama embeddings match the project's privacy and offline-demo goal.
- Why jurisdiction filtering happens before dense/BM25 fusion.
- Why reciprocal-rank fusion avoids comparing incomparable raw score scales.
- Why source diversity and component ranks are part of retrieval explainability.
- Why deterministic evidence tables are rebuilt outside the LLM response.
- Why retrieval similarity is not factual correctness or source currency.
- Why the optional subsystem fails closed but does not block the core planner.
- How to extend the evaluation set with hard negatives, add learned reranking, incremental indexing and authenticated remote vector storage.
