"""Evaluate production and free-text retrieval against the committed RAG question set."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation_artifacts import (  # noqa: E402
    RAG_EVALUATION_ARTIFACT_SCHEMA,
    canonical_sha256,
    git_provenance,
    ollama_model_identity,
    project_relative,
    rag_index_provenance,
    require_stable_release_provenance,
    sha256_file,
    validate_rag_evaluation_artifact,
)
from src.rag.service import RagService  # noqa: E402

PRODUCTION_PROFILE = "structured_planning"
FREE_TEXT_PROFILE = "free_text"
DEFAULT_FREE_TEXT_TOP_K = 5
_RELEASE_STABILITY_FIELDS = (
    "questions_sha256",
    "git",
    "rag_index",
    "embedding_model",
)


def build_run_metadata(payload, questions_path, service, embedding_identity=None):
    """Collect exact question, index, embedding and Git provenance for one run."""

    index = rag_index_provenance(service.settings)
    settings = service.settings
    embedding = (
        dict(embedding_identity)
        if isinstance(embedding_identity, dict)
        else ollama_model_identity(
            getattr(settings, "embedding_base_url", ""),
            getattr(settings, "embedding_model", ""),
        )
    )
    embedding.update(
        {
            "provider": "ollama",
            "dimension": index.get("embedding_dimension"),
        }
    )
    return {
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions_file": project_relative(questions_path, PROJECT_ROOT),
        "questions_sha256": sha256_file(questions_path),
        "questions_hash_basis": "exact_file_bytes",
        "questions_schema_version": payload.get("schema_version"),
        "git": git_provenance(PROJECT_ROOT),
        "rag_index": index,
        "embedding_model": embedding,
        "model_identity_observation": (
            "ollama_tag_checked_at_retrieval_call_boundaries; "
            "an in-flight tag swap entirely inside one embedding HTTP call is not observable"
        ),
    }


def _finalize_provenance(run, completion_metadata, *, release_gate_active):
    """Record an end snapshot and fail a release run if its identity drifted."""

    drift_fields = [field for field in _RELEASE_STABILITY_FIELDS if run.get(field) != completion_metadata.get(field)]
    completed_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if release_gate_active and drift_fields:
        raise SystemExit("RAG release provenance changed during evaluation: " + ", ".join(drift_fields))
    run["provenance_stability"] = {
        "checked": True,
        "stable": not drift_fields,
        "drift_fields": drift_fields,
    }
    run["completed_at_utc"] = completed_at_utc


class _RagReleaseBoundaryGuard:
    def __init__(self, payload, questions_path, service, baseline):
        self.payload = payload
        self.questions_path = questions_path
        self.service = service
        self.baseline = baseline

    def check(self, label, result=None):
        current = build_run_metadata(
            self.payload,
            self.questions_path,
            self.service,
            None,
        )
        require_stable_release_provenance(
            self.baseline,
            current,
            _RELEASE_STABILITY_FIELDS,
            label=label,
            artifact_name="RAG",
        )
        if not isinstance(result, dict):
            return
        expected_manifest = self.baseline.get("rag_index", {}).get("manifest_sha256")
        observed_manifest = result.get("index_manifest_sha256")
        status = result.get("status")
        if status in {"ready", "no_match"} and (not expected_manifest or observed_manifest != expected_manifest):
            raise SystemExit(f"RAG release provenance changed at {label}: rag_index")
        if (
            status == "out_of_scope"
            and expected_manifest
            and observed_manifest
            and observed_manifest != expected_manifest
        ):
            raise SystemExit(f"RAG release provenance changed at {label}: rag_index")


def _in_memory_run_metadata(payload, service):
    settings = getattr(service, "settings", None)
    return {
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions_file": "<in-memory>",
        "questions_sha256": canonical_sha256(payload),
        "questions_hash_basis": "canonical_json",
        "questions_schema_version": payload.get("schema_version"),
        "git": {"commit": None, "working_tree_dirty": None, "collection_status": "not_collected"},
        "rag_index": {"status": "not_collected"},
        "embedding_model": {
            "provider": "ollama",
            "name": getattr(settings, "embedding_model", ""),
            "digest": None,
            "digest_status": "not_collected",
        },
    }


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


def _pass_thresholds(payload, profile):
    configured = dict(payload.get("thresholds", {}))
    configured.update(payload.get("profile_thresholds", {}).get(profile, {}))
    thresholds = {
        "passage_recall_at_k": float(configured.get("passage_recall_at_k", 0.9)),
        "mean_reciprocal_rank": float(configured.get("mean_reciprocal_rank", 0.75)),
        "unanswerable_accuracy": float(configured.get("unanswerable_accuracy", 0.8)),
    }
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in thresholds.values()):
        raise SystemExit(f"RAG evaluation thresholds for {profile} must be between 0 and 1.")
    return thresholds


def _validate_questions(payload):
    if payload.get("schema_version") != 3:
        raise SystemExit("RAG evaluation schema_version must be 3.")
    questions = payload.get("questions", [])
    if not questions:
        raise SystemExit("No RAG evaluation questions were found.")
    if not any(question.get("answerable", True) is False for question in questions):
        raise SystemExit("RAG evaluation must include at least one unanswerable question.")
    allowed_profiles = {PRODUCTION_PROFILE, FREE_TEXT_PROFILE}
    for question in questions:
        profiles = question.get("evaluation_profiles", list(allowed_profiles))
        if (
            not isinstance(profiles, list)
            or not profiles
            or any(profile not in allowed_profiles for profile in profiles)
        ):
            raise SystemExit("RAG evaluation question profiles are invalid.")
    return questions


def _questions_for_profile(questions, profile):
    selected = [
        question
        for question in questions
        if profile in question.get("evaluation_profiles", [PRODUCTION_PROFILE, FREE_TEXT_PROFILE])
    ]
    if not any(question.get("answerable", True) is not False for question in selected):
        raise SystemExit(f"RAG evaluation profile {profile} has no answerable questions.")
    if not any(question.get("answerable", True) is False for question in selected):
        raise SystemExit(f"RAG evaluation profile {profile} has no unanswerable questions.")
    return selected


def _percentile_95(values):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(0.95 * len(ordered) + 0.5) - 1))
    return ordered[index]


def _evaluate_profile(
    service,
    questions,
    *,
    profile,
    top_k,
    thresholds,
    warmup=False,
    summary_only=False,
    provenance_check=None,
):
    trusted_planning_scope = profile == PRODUCTION_PROFILE
    if warmup:
        first = questions[0]
        if provenance_check:
            provenance_check(f"before {profile} warmup")
        warmup_result = service.retrieve(
            first["query"],
            jurisdiction=first.get("jurisdiction"),
            top_k=top_k,
            trusted_planning_scope=trusted_planning_scope,
        )
        if provenance_check:
            provenance_check(f"after {profile} warmup", warmup_result)

    rows = []
    reciprocal_ranks = []
    latencies = []
    retrieval_configurations = {}
    for question in questions:
        if provenance_check:
            provenance_check(f"before {profile} question {question['id']}")
        started = time.perf_counter()
        result = service.retrieve(
            question["query"],
            jurisdiction=question.get("jurisdiction"),
            top_k=top_k,
            trusted_planning_scope=trusted_planning_scope,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        if provenance_check:
            provenance_check(f"after {profile} question {question['id']}", result)
        result_configuration = result.get("retrieval_configuration")
        if not isinstance(result_configuration, dict):
            raise SystemExit("RAG result did not disclose its effective retrieval configuration.")
        if result.get("status") not in {"ready", "no_match", "out_of_scope"}:
            error_code = str(result.get("error_code") or result.get("status") or "unknown")
            raise SystemExit(f"RAG evaluation cannot run because retrieval is unavailable ({error_code}).")
        configuration_key = json.dumps(result_configuration, sort_keys=True)
        retrieval_configurations[configuration_key] = result_configuration

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

    if len(retrieval_configurations) != 1:
        raise SystemExit(f"RAG evaluation observed inconsistent retrieval settings for {profile}.")
    retrieval_configuration = next(iter(retrieval_configurations.values()))
    if retrieval_configuration.get("query_scope") != profile or retrieval_configuration.get("top_k") != top_k:
        raise SystemExit(f"RAG evaluation did not apply the requested {profile} retrieval profile.")

    answerable_rows = [row for row in rows if row["answerable"]]
    unanswerable_rows = [row for row in rows if not row["answerable"]]
    passage_recall = sum(row["passage_hit"] for row in answerable_rows) / len(answerable_rows)
    source_recall = sum(row["source_hit"] for row in answerable_rows) / len(answerable_rows)
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
    top_1_accuracy = sum(row["passage_rank"] == 1 for row in answerable_rows) / len(answerable_rows)
    unanswerable_accuracy = sum(row["correctly_abstained"] for row in unanswerable_rows) / len(unanswerable_rows)
    passed = (
        passage_recall >= thresholds["passage_recall_at_k"]
        and mean_reciprocal_rank >= thresholds["mean_reciprocal_rank"]
        and unanswerable_accuracy >= thresholds["unanswerable_accuracy"]
    )
    output = {
        "passed": passed,
        "profile": profile,
        "thresholds": thresholds,
        "retrieval_configuration": retrieval_configuration,
        "summary": {
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
            "p95_latency_ms": round(_percentile_95(latencies), 2),
            "top_k": top_k,
            "query_scope": profile,
            "retrieval_mode": "dense_bm25_rrf_v1",
        },
        "by_jurisdiction": _aggregate(answerable_rows, "jurisdiction"),
        "by_category": _aggregate(answerable_rows, "category"),
    }
    if not summary_only:
        output["rows"] = rows
    if provenance_check:
        provenance_check(f"after {profile} profile")
    return output


def _selected_profiles(mode):
    if mode == "both":
        return (PRODUCTION_PROFILE, FREE_TEXT_PROFILE)
    return (mode,)


def run_evaluation(
    payload,
    service,
    *,
    mode,
    free_text_top_k,
    structured_top_k=None,
    warmup=False,
    summary_only=False,
    run_metadata=None,
    provenance_check=None,
):
    questions = _validate_questions(payload)
    production_top_k = structured_top_k or service.settings.top_k
    profiles = {}
    for profile in _selected_profiles(mode):
        top_k = production_top_k if profile == PRODUCTION_PROFILE else free_text_top_k
        profiles[profile] = _evaluate_profile(
            service,
            _questions_for_profile(questions, profile),
            profile=profile,
            top_k=top_k,
            thresholds=_pass_thresholds(payload, profile),
            warmup=warmup,
            summary_only=summary_only,
            provenance_check=provenance_check,
        )

    primary_profile = PRODUCTION_PROFILE if PRODUCTION_PROFILE in profiles else FREE_TEXT_PROFILE
    primary = profiles[primary_profile]
    uses_production_settings = (
        PRODUCTION_PROFILE in profiles
        and profiles[PRODUCTION_PROFILE]["retrieval_configuration"]["top_k"] == service.settings.top_k
    )
    release_gate_active = PRODUCTION_PROFILE in profiles and uses_production_settings and not summary_only
    metadata = dict(run_metadata or _in_memory_run_metadata(payload, service))
    metadata["completed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output = {
        "artifact_schema": RAG_EVALUATION_ARTIFACT_SCHEMA,
        "evaluation_schema_version": 3,
        "run": metadata,
        "passed": primary["passed"],
        "release_gate": {
            "profile": PRODUCTION_PROFILE,
            "active": release_gate_active,
            "passed": profiles[PRODUCTION_PROFILE]["passed"] if release_gate_active else None,
            "uses_production_settings": uses_production_settings,
        },
        "profiles": profiles,
        # Backward-compatible aliases point at the selected release profile.
        "thresholds": primary["thresholds"],
        "summary": primary["summary"],
        "by_jurisdiction": primary["by_jurisdiction"],
        "by_category": primary["by_category"],
    }
    if not summary_only:
        output["rows"] = primary["rows"]
    return output


def _positive_top_k(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("top-k must be a positive integer")
    return parsed


def _resolve_mode(mode, top_k):
    # Before dual-profile evaluation existed, --top-k selected a free-text run.
    # Preserve that exact CLI while making a no-option invocation the release gate.
    return mode or (FREE_TEXT_PROFILE if top_k is not None else "both")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_ROOT / "data_australia" / "rag" / "evaluation.json",
    )
    parser.add_argument(
        "--mode",
        choices=("both", PRODUCTION_PROFILE, FREE_TEXT_PROFILE),
        default=None,
        help="Evaluate both profiles by default; only structured_planning is the release gate.",
    )
    parser.add_argument(
        "--top-k",
        type=_positive_top_k,
        default=None,
        help="Free-text top-k. In structured_planning-only mode this is an explicit non-production override.",
    )
    parser.add_argument("--warmup", action="store_true", help="Run one unmeasured query before each profile.")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-question rows and produce a diagnostic artifact that cannot activate the release gate.",
    )
    parser.add_argument("--output", type=Path, help="Optionally write the exact JSON result to this path.")
    args = parser.parse_args()
    payload = json.loads(args.questions.read_text(encoding="utf-8"))
    service = RagService()
    mode = _resolve_mode(args.mode, args.top_k)
    free_text_top_k = args.top_k or DEFAULT_FREE_TEXT_TOP_K
    structured_top_k = args.top_k if mode == PRODUCTION_PROFILE and args.top_k is not None else None
    run_metadata = build_run_metadata(payload, args.questions, service)
    production_top_k = structured_top_k or service.settings.top_k
    release_boundary_checks_active = (
        PRODUCTION_PROFILE in _selected_profiles(mode)
        and production_top_k == service.settings.top_k
        and not args.summary_only
    )
    provenance_guard = (
        _RagReleaseBoundaryGuard(payload, args.questions, service, run_metadata)
        if release_boundary_checks_active
        else None
    )
    output = run_evaluation(
        payload,
        service,
        mode=mode,
        free_text_top_k=free_text_top_k,
        structured_top_k=structured_top_k,
        warmup=args.warmup,
        summary_only=args.summary_only,
        run_metadata=run_metadata,
        provenance_check=provenance_guard.check if provenance_guard else None,
    )
    completion_metadata = build_run_metadata(payload, args.questions, service)
    _finalize_provenance(
        output["run"],
        completion_metadata,
        release_gate_active=output["release_gate"]["active"],
    )
    validate_rag_evaluation_artifact(output)
    rendered = json.dumps(output, indent=2)
    if args.output:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
