"""Evaluate deterministic source retrieval against the committed RAG question set."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.service import RagService  # noqa: E402


def _matches_passage(chunk, question):
    expected_sources = set(question.get("expected_source_ids", []))
    if chunk.get("source_id") not in expected_sources:
        return False
    text = str(chunk.get("text") or "").lower()
    return all(str(term).lower() in text for term in question.get("expected_terms", []))


def _aggregate(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(key, "unspecified")].append(row)
    return {
        label: {
            "questions": len(values),
            "passage_recall_at_k": round(
                sum(value["passage_hit"] for value in values) / len(values),
                4,
            ),
            "mean_reciprocal_rank": round(
                sum(value["reciprocal_rank"] for value in values) / len(values),
                4,
            ),
        }
        for label, values in sorted(grouped.items())
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_ROOT / "data_australia" / "rag" / "evaluation.json",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--warmup", action="store_true", help="Run one unmeasured query before evaluation.")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-question rows from the JSON output.",
    )
    args = parser.parse_args()
    payload = json.loads(args.questions.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 3:
        raise SystemExit("RAG evaluation schema_version must be 3.")
    questions = payload.get("questions", [])
    if not questions:
        raise SystemExit("No RAG evaluation questions were found.")
    if not any(question.get("answerable", True) is False for question in questions):
        raise SystemExit("RAG evaluation must include at least one unanswerable question.")

    service = RagService()
    if args.warmup:
        first = questions[0]
        service.retrieve(
            first["query"],
            jurisdiction=first.get("jurisdiction"),
            top_k=args.top_k,
        )
    rows = []
    reciprocal_ranks = []
    latencies = []
    for question in questions:
        started = time.perf_counter()
        result = service.retrieve(
            question["query"],
            jurisdiction=question.get("jurisdiction"),
            top_k=args.top_k,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        chunks = result.get("retrieved_chunks", [])
        source_ids = [item.get("source_id") for item in chunks]
        answerable = question.get("answerable", True) is not False
        expected = set(question.get("expected_source_ids", []))
        source_rank = (
            next(
                (index for index, source_id in enumerate(source_ids, start=1) if source_id in expected),
                None,
            )
            if answerable
            else None
        )
        passage_rank = (
            next(
                (index for index, chunk in enumerate(chunks, start=1) if _matches_passage(chunk, question)),
                None,
            )
            if answerable
            else None
        )
        reciprocal_rank = 1 / passage_rank if passage_rank else 0
        if answerable:
            reciprocal_ranks.append(reciprocal_rank)
        correctly_abstained = not answerable and not chunks and result["status"] in {"no_match", "out_of_scope"}
        rows.append(
            {
                "id": question["id"],
                "jurisdiction": question.get("jurisdiction", "Australia"),
                "category": question.get("category", "unspecified"),
                "answerable": answerable,
                "status": result["status"],
                "source_hit": source_rank is not None if answerable else None,
                "source_rank": source_rank,
                "passage_hit": passage_rank is not None if answerable else None,
                "passage_rank": passage_rank,
                "reciprocal_rank": reciprocal_rank if answerable else None,
                "correctly_abstained": correctly_abstained if not answerable else None,
                "retrieved_source_ids": source_ids,
            }
        )
    answerable_rows = [row for row in rows if row["answerable"]]
    unanswerable_rows = [row for row in rows if not row["answerable"]]
    sorted_latency = sorted(latencies)
    p95_index = max(0, min(len(sorted_latency) - 1, round(0.95 * len(sorted_latency) + 0.5) - 1))
    passage_recall = sum(row["passage_hit"] for row in answerable_rows) / len(answerable_rows)
    source_recall = sum(row["source_hit"] for row in answerable_rows) / len(answerable_rows)
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
    top_1_accuracy = sum(row["passage_rank"] == 1 for row in answerable_rows) / len(answerable_rows)
    unanswerable_accuracy = sum(row["correctly_abstained"] for row in unanswerable_rows) / len(unanswerable_rows)
    summary = {
        "questions": len(questions),
        "answerable_questions": len(answerable_rows),
        "unanswerable_questions": len(unanswerable_rows),
        "source_recall_at_k": round(source_recall, 4),
        "passage_recall_at_k": round(passage_recall, 4),
        "mean_reciprocal_rank": round(mean_reciprocal_rank, 4),
        "top_1_accuracy": round(top_1_accuracy, 4),
        "unanswerable_accuracy": round(unanswerable_accuracy, 4),
        "false_positive_rate": round(1 - unanswerable_accuracy, 4),
        "average_latency_ms": round(sum(latencies) / len(latencies), 2),
        "p95_latency_ms": round(sorted_latency[p95_index], 2),
        "top_k": args.top_k,
        "retrieval_mode": "dense_bm25_rrf_v1",
    }
    thresholds = payload.get("thresholds", {})
    minimum_recall = float(thresholds.get("passage_recall_at_k", 0.9))
    minimum_mrr = float(thresholds.get("mean_reciprocal_rank", 0.75))
    minimum_unanswerable_accuracy = float(thresholds.get("unanswerable_accuracy", 0.8))
    passed = (
        math.isfinite(minimum_recall)
        and math.isfinite(minimum_mrr)
        and math.isfinite(minimum_unanswerable_accuracy)
        and passage_recall >= minimum_recall
        and mean_reciprocal_rank >= minimum_mrr
        and unanswerable_accuracy >= minimum_unanswerable_accuracy
    )
    output = {
        "passed": passed,
        "thresholds": {
            "passage_recall_at_k": minimum_recall,
            "mean_reciprocal_rank": minimum_mrr,
            "unanswerable_accuracy": minimum_unanswerable_accuracy,
        },
        "summary": summary,
        "by_jurisdiction": _aggregate(answerable_rows, "jurisdiction"),
        "by_category": _aggregate(answerable_rows, "category"),
    }
    if not args.summary_only:
        output["rows"] = rows
    print(json.dumps(output, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
