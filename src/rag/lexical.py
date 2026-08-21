from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "about",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "for",
    "from",
    "guidance",
    "how",
    "in",
    "is",
    "it",
    "of",
    "official",
    "on",
    "or",
    "planning",
    "preparedness",
    "scenario",
    "setting",
    "should",
    "static",
    "the",
    "their",
    "to",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
    "your",
}


def tokenize(value):
    return [
        token
        for token in _TOKEN_PATTERN.findall(str(value or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


def bm25_rank(query, documents, *, k1=1.5, b=0.75):
    """Return deterministic BM25 scores for a small verified document corpus."""

    query_terms = tokenize(query)
    if not query_terms or not documents:
        return []
    tokenised = [tokenize(document.get("text")) for document in documents]
    average_length = sum(len(tokens) for tokens in tokenised) / len(tokenised)
    if average_length <= 0:
        return []
    document_frequency = Counter()
    for tokens in tokenised:
        document_frequency.update(set(tokens))
    query_frequency = Counter(query_terms)
    total = len(documents)
    scored = []
    for document, tokens in zip(documents, tokenised):
        frequencies = Counter(tokens)
        score = 0.0
        for term, query_count in query_frequency.items():
            term_frequency = frequencies.get(term, 0)
            if not term_frequency:
                continue
            frequency = document_frequency[term]
            inverse_frequency = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            denominator = term_frequency + k1 * (1 - b + b * len(tokens) / average_length)
            score += query_count * inverse_frequency * (term_frequency * (k1 + 1) / denominator)
        if score > 0:
            scored.append(
                {
                    "chunk_id": document["chunk_id"],
                    "lexical_score": score,
                }
            )
    scored.sort(key=lambda row: (-row["lexical_score"], row["chunk_id"]))
    for rank, row in enumerate(scored, start=1):
        row["lexical_rank"] = rank
        row["lexical_score"] = round(row["lexical_score"], 6)
    return scored


def hybrid_rank(
    query,
    documents,
    dense_results,
    *,
    jurisdiction,
    top_k,
    candidate_k,
    dense_score_threshold,
    dense_weight,
    rrf_k,
    max_chunks_per_source,
    lexical_coverage_threshold=0.61,
    semantic_score_threshold=0.45,
    semantic_coverage_threshold=0.2,
):
    """Fuse dense and BM25 ranks, then apply bounded metadata-aware reranking."""

    by_id = {document["chunk_id"]: document for document in documents}
    dense_rows = dense_results[:candidate_k]
    dense_by_id = {
        row["chunk_id"]: {
            "dense_rank": rank,
            "dense_score": float(row["score"]),
        }
        for rank, row in enumerate(dense_rows, start=1)
    }
    lexical_rows = bm25_rank(query, documents)[:candidate_k]
    lexical_by_id = {row["chunk_id"]: row for row in lexical_rows}
    candidate_ids = set(dense_by_id) | set(lexical_by_id)
    lexical_weight = 1 - dense_weight
    normaliser = 1 / (rrf_k + 1)
    query_tokens = set(tokenize(query))
    ranked = []
    for chunk_id in candidate_ids:
        document = by_id.get(chunk_id)
        if document is None:
            continue
        dense = dense_by_id.get(chunk_id, {})
        lexical = lexical_by_id.get(chunk_id, {})
        dense_score = dense.get("dense_score")
        document_tokens = set(tokenize(f"{document.get('title', '')} {document.get('text', '')}"))
        query_term_coverage = len(query_tokens & document_tokens) / len(query_tokens) if query_tokens else 0.0
        lexical_evidence = lexical.get("lexical_score", 0) > 0 and query_term_coverage >= lexical_coverage_threshold
        semantic_evidence = (
            dense_score is not None
            and dense_score >= max(dense_score_threshold, semantic_score_threshold)
            and query_term_coverage >= semantic_coverage_threshold
        )
        if not (lexical_evidence or semantic_evidence):
            continue
        fusion = 0.0
        if dense.get("dense_rank"):
            fusion += dense_weight / (rrf_k + dense["dense_rank"])
        if lexical.get("lexical_rank"):
            fusion += lexical_weight / (rrf_k + lexical["lexical_rank"])
        fusion /= normaliser
        reasons = []
        bonus = 0.0
        jurisdictions = document.get("jurisdictions", [])
        if jurisdiction and jurisdiction != "Australia" and jurisdiction in jurisdictions:
            bonus += 0.025
            reasons.append("exact_jurisdiction")
        title_tokens = set(tokenize(document.get("title")))
        if title_tokens:
            title_coverage = len(query_tokens & title_tokens) / len(title_tokens)
            title_bonus = min(0.025, 0.025 * title_coverage)
            if title_bonus:
                bonus += title_bonus
                reasons.append("title_overlap")
        ranked.append(
            {
                **document,
                "score": round(min(1.0, fusion + bonus), 6),
                "fusion_score": round(fusion, 6),
                "dense_score": round(dense_score, 6) if dense_score is not None else None,
                "lexical_score": lexical.get("lexical_score", 0.0),
                "dense_rank": dense.get("dense_rank"),
                "lexical_rank": lexical.get("lexical_rank"),
                "query_term_coverage": round(query_term_coverage, 6),
                "answerability_evidence": (
                    "lexical_and_semantic"
                    if lexical_evidence and semantic_evidence
                    else "lexical"
                    if lexical_evidence
                    else "semantic"
                ),
                "rerank_reasons": reasons,
                "retrieval_mode": "dense_bm25_rrf_v1",
            }
        )
    ranked.sort(
        key=lambda row: (
            -row["score"],
            row.get("dense_rank") or candidate_k + 1,
            row.get("lexical_rank") or candidate_k + 1,
            row["chunk_id"],
        )
    )
    selected = []
    source_counts = Counter()
    for row in ranked:
        source_id = row["source_id"]
        if source_counts[source_id] >= max_chunks_per_source:
            continue
        selected.append(row)
        source_counts[source_id] += 1
        if len(selected) >= top_k:
            break
    return selected
