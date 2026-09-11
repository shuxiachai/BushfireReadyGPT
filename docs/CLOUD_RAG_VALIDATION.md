# CPU RAG validation for cloud deployment

The CPU embedding implementation has been exercised locally with the existing corpus. The structured retrieval-configuration profile passes its configured thresholds, but those historical runs sent question-set text rather than complete application forms. Free-text retrieval passes the original calibrated question set but misses one of four answerable questions in an additional diagnostic. These are development diagnostics, not a cloud deployment acceptance result or release evidence.

## Model and corpus identity

The runs below were performed on Windows on 2026-09-10. They used local CPU inference; no report-generation API was called.

| Field | Recorded value |
| --- | --- |
| Provider | `fastembed`, `CPUExecutionProvider` |
| Model | `BAAI/bge-small-en-v1.5` |
| Vector dimension | 384 |
| Model repository | `Qdrant/bge-small-en-v1.5-onnx-Q` |
| Pinned repository revision | `52398278842ec682c6f32300af41344b1c0b0bb2` |
| Runtime versions | FastEmbed `0.8.0`; ONNX Runtime `1.29.0` |
| Model identity digest | `c53c5f9494de9802b39f3a6693a1840400178a368117e63e402b047acc1bda51` |
| ONNX file SHA256 | `51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431` |
| Local corpus | 9 source documents, 28 chunks |
| Index schema | `bushfire-rag-index-v3` |
| Index manifest SHA256 | `065abb2b2827aa353016ef803c9297863e624130f08991b49d56e88edcffcb39` |
| Source catalog SHA256 | `49e48740d72b06a672962226496108c26221231a235428e1c6c66795e260c5f1` |
| Corpus SHA256 | `02cba70434724c2829851bd382d57b3ff5c8c8dbd2d0043defdcfa1426083fd8` |
| Document snapshot SHA256 | `1b21fe597f79c86797a5045b5f5098af482cae2d133161ede476fe85d4288bcc` |

The model identity digest covers provider, model, dimension, repository revision, encoding mode, runtime versions, and the size/SHA256 of six inference files: ONNX weights, model configuration, tokenizer, tokenizer configuration, special-token mapping, and vocabulary. It is not just a hash of the model name. The v3 index records this identity and checks it during construction and retrieval. Changed model bytes or an incompatible dimension invalidate the index. The September 11 maintenance adds separate Ollama v4 identity binding; old Ollama v2 bytes remain historical evidence, not a runtime index with a retrospectively proven build digest. See [Ollama migration and form-context diagnostics](AUDIT_FOLLOWUP_2026-09-11.md).

The model is downloaded only by explicit preparation. Runtime construction uses the prepared directory with `local_files_only=True` and reuses one model instance per process. A local smoke check produced two 384-dimensional vectors in approximately 0.842 seconds including initial loading; a subsequent call took approximately 0.046 seconds. These timings are observations on the development machine, not Railway performance estimates.

## Calibration on the existing question set

The original [84-question set](../data_australia/rag/evaluation.json) was unchanged. Its file SHA256 was `7b796a87676f9bb9f17573ae1f1e8d7e1cceec127eba8b70dd6cb0d4c14e6654`.

Reusing the Ollama free-text semantic threshold of 0.45 with BGE produced only 50% abstention on the 16 negative questions. BGE cosine scores have a different distribution. The FastEmbed free-text semantic threshold was therefore calibrated to **0.70** on this existing set. The Ollama default remains 0.45. This calibration set cannot also establish independent generalization.

| Profile | Questions | Returned Top-k | Source / passage Recall@k | MRR | Top-1 accuracy | Negative abstention |
| --- | --- | --- | --- | --- | --- | --- |
| Structured planning | 73: 68 answerable + 5 unanswerable | 8 | 100% / 100% | 0.8946 | 80.88% | 5/5, 100% |
| Free text | 84: 68 answerable + 16 unanswerable | 5 | 94.12% / 94.12% | 0.8358 | 75.00% | 16/16, 100% |

Both profiles passed the existing thresholds: passage Recall@k at least 0.90, MRR at least 0.75, and negative abstention at least 0.80. The free-text configuration trades some recall for rejection of irrelevant questions.

Top-k is the number of passages requested. Top-1 accuracy measures how often the first retrieved passage matches the expected passage; reporting it does not mean the application retrieves only one passage. The two profiles also use different answerability thresholds and negative-question populations, so their percentages are not interchangeable. The historical structured-planning evaluator used the trusted-scope retrieval configuration, including the effective semantic threshold of 0.35, but did not construct its queries from real forms. Its 100% abstention covers five in-scope profile negatives, not all sixteen free-text negatives. Neither historical profile measures relevance after passage/context truncation in the final report prompt.

The calibrated run used warmup. Observed mean / p95 retrieval latency was 83.55 / 95.69 ms for structured planning and 86.05 / 98.97 ms for free text. These include local retrieval processing and are not report-generation latency.

## Additional diagnostic after calibration

The [additional 16-question fixture](../tests/fixtures/rag_cpu_holdout.json) was authored after fixing the threshold at 0.70. It contains four answerable paraphrases and twelve medical, legal, financial, or unrelated questions. It was not used to select that threshold, and the threshold was not retuned after this result. Its file SHA256 was `9cf0877a5ab4c893f8a12a67e00c671d80e4701faf027271d8ed7d0166369ceb`.

| Free-text Top-5 result | Observation |
| --- | --- |
| Answerable passage recall | 3/4, 75% |
| MRR / Top-1 accuracy | 0.75 / 75% |
| Negative abstention | 12/12, 100% |
| Overall configured diagnostic outcome | **Failed**, because recall was below 0.90 |

The missed question was `cpu_holdout_council`:

> Which local authority can explain the warning systems and nominated evacuation routes in Queensland?

The expected source was `qld_evacuation_plan`, with the terms `local council` and `nominated evacuation routes`. Retrieval returned `no_match`. This is an answerable paraphrase rejected by the conservative free-text configuration. The failed result is retained; it is not relabelled as unanswerable or excluded from the score.

The additional diagnostic was small and author-written, with all four positive examples from Queensland. It supplies evidence about these questions only; it is not external user validation or broad geographic/generalization evidence. Its latency included a cold model load and is not directly comparable with the warmed calibration run.

## Evidence status and interpretation

The local output files are `output/rag-cpu-predeployment-diagnostic.json` (before calibration), `output/rag-cpu-calibrated-diagnostic.json`, and `output/rag-cpu-holdout-diagnostic.json`. They are local generated artifacts, excluded from Git by the existing `output/` rule. Their recorded Git base was `0df58d76a6a6795a1c3be5b8f1be7608dbd659ea`, with `working_tree_dirty=true`; that base commit alone does not identify the uncommitted CPU implementation used during the runs.

All three outputs have an inactive release gate. The calibration output used `--summary-only`; the additional diagnostic used free-text mode and retains per-question rows. No result here replaces the versioned Ollama release artifacts or supports a claim that Ollama has regressed. This work evaluated a different embedding configuration; it did not perform a controlled rerun of the prior model against the same current environment.

The corpus above used the existing locally downloaded official documents. A Docker image that downloads those public pages again can receive changed page content or a different extracted corpus even when the source catalog URL is unchanged. Model revision pinning does not pin third-party preparedness webpages. Compare the new source-artifact hashes, corpus hash, chunk count, and index identity, then rerun both question sets inside the actual image. Windows timing and these local scores do not establish Railway startup, memory, Linux inference, or online report-generation behavior.

## Reproduction

From the repository root in PowerShell, install the optional cloud dependencies and explicitly prepare the model:

```powershell
poetry install --with cloud
$env:BUSHFIRE_RAG_ENABLED = 'true'
$env:BUSHFIRE_RAG_EMBED_PROVIDER = 'fastembed'
$env:BUSHFIRE_RAG_EMBED_MODEL = 'BAAI/bge-small-en-v1.5'
$env:BUSHFIRE_RAG_EMBED_CACHE_DIR = 'output/cpu-embedding-models'
$env:BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY = 'false'
poetry run python scripts/build_rag_index.py --prepare-embedding-only
```

Build a separate CPU index from the existing local sources, then evaluate with the calibrated threshold:

```powershell
$env:BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY = 'true'
$env:BUSHFIRE_RAG_INDEX_DIR = 'data_australia/rag/cpu-index-validation'
$env:BUSHFIRE_RAG_SEMANTIC_SCORE_THRESHOLD = '0.70'
poetry run python scripts/build_rag_index.py
poetry run python scripts/evaluate_rag.py --warmup --summary-only --output output/rag-cpu-calibrated-diagnostic.json
poetry run python scripts/evaluate_rag.py --mode free_text --questions tests/fixtures/rag_cpu_holdout.json --output output/rag-cpu-holdout-diagnostic.json
```

The final command exits with a nonzero status when the additional diagnostic fails. Preserve that failure and its rows. If the declared source files are absent, `scripts/build_rag_index.py --download` obtains them, but this creates a newly fetched corpus whose scores and hashes must be recorded separately.

Inside the built container, use the same evaluation script with the container's prepared model and mounted RAG paths. Save results to a writable directory, for example `/data/output/`, and keep the new Linux/container results distinct from these Windows development diagnostics. The original question set can be evaluated with `--warmup --summary-only`. The production image need not include the test suite: make the additional fixture available through a read-only mount or copy it into a writable diagnostic directory, then pass its container path with `--mode free_text --questions <container-fixture-path>`. A formal release evaluation additionally requires the project's clean-source provenance and release-verification workflow.
