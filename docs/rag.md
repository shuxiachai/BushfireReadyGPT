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
poetry run python scripts\evaluate_rag.py --top-k 5 --warmup --summary-only
```

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
the 2026-08-22 `v0.2.1` local baseline, Top-5 passage recall was 0.9706, MRR
0.8922, Top-1 accuracy 0.8235, unanswerable accuracy 1.0000, average latency
104.70 ms and p95 latency 126.57 ms. These are reproducible project-benchmark
results, not evidence of production accuracy. Unit tests use a deterministic test
embedder and temporary Qdrant database, keeping CI offline and repeatable.

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
- A staged index is published atomically under a lock with interrupted-build recovery.
- The manifest binds catalog bytes, source bytes, canonical document snapshot, chunk corpus, embedding model and vector dimension.
- Retrieval revalidates source bytes, the complete document snapshot, manifest, collection count, point ID and returned text hash before embedding the query.
- The Python 3.13 embedded-Qdrant path derives SQLite thread safety without leaking the temporary probe connection used by the upstream client.
- Passages are delimited as untrusted quoted evidence; the model is told never to follow passage instructions.
- Prompt payloads cap total retrieved context at 8,000 characters and each passage at 2,200 characters.
- The audit stores query/source/chunk hashes and scores, but not retrieved passage text by default.
- Live-warning and life-safety queries are deterministically withheld from the static corpus, while free-text retrieval must pass lexical or combined semantic/lexical answerability thresholds.

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
