import copy
import json
import subprocess
from pathlib import Path
from urllib.error import URLError

import pytest

from scripts import evaluation_artifacts
from scripts.evaluation_artifacts import (
    ArtifactValidationError,
    ollama_model_identity,
    validate_rag_evaluation_artifact,
    validate_report_evaluation_artifact,
)


def _git():
    return {"commit": "a" * 40, "working_tree_dirty": False, "collection_status": "collected"}


def _timestamps():
    return {
        "started_at_utc": "2026-08-24T00:00:00+00:00",
        "completed_at_utc": "2026-08-24T00:01:00+00:00",
    }


def test_git_provenance_distinguishes_a_clean_tree_from_collection_failure(monkeypatch):
    def clean_run(command, **_kwargs):
        stdout = "a" * 40 + "\n" if command[-2:] == ["rev-parse", "HEAD"] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(evaluation_artifacts.subprocess, "run", clean_run)
    assert evaluation_artifacts.git_provenance(Path(".")) == {
        "commit": "a" * 40,
        "working_tree_dirty": False,
        "collection_status": "collected",
    }

    monkeypatch.setattr(
        evaluation_artifacts.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="failed"),
    )
    assert evaluation_artifacts.git_provenance(Path(".")) == {
        "commit": None,
        "working_tree_dirty": None,
        "collection_status": "unavailable",
    }


def _index():
    return {
        "status": "verified",
        "manifest_sha256": "c" * 64,
        "catalog_sha256": "d" * 64,
        "corpus_sha256": "e" * 64,
        "documents_sha256": "f" * 64,
    }


def _valid_rag_artifact():
    answerable_row = {
        "id": "answerable",
        "jurisdiction": "Queensland",
        "category": "property",
        "answerable": True,
        "status": "ready",
        "source_hit": True,
        "source_rank": 1,
        "passage_hit": True,
        "passage_rank": 1,
        "reciprocal_rank": 1.0,
        "correctly_abstained": None,
        "retrieved_source_ids": ["expected-source"],
    }
    second_answerable_row = {**answerable_row, "id": "answerable-two"}
    unanswerable_row = {
        "id": "unanswerable",
        "jurisdiction": "Australia",
        "category": "hard-negative",
        "answerable": False,
        "status": "no_match",
        "source_hit": None,
        "source_rank": None,
        "passage_hit": None,
        "passage_rank": None,
        "reciprocal_rank": None,
        "correctly_abstained": True,
        "retrieved_source_ids": [],
    }
    return {
        "artifact_schema": "bushfire-rag-evaluation-v3",
        "passed": True,
        "run": {
            **_timestamps(),
            "git": _git(),
            "questions_sha256": "b" * 64,
            "questions_hash_basis": "exact_file_bytes",
            "rag_index": _index(),
            "embedding_model": {
                "name": "embeddinggemma",
                "digest": "1" * 64,
                "digest_status": "resolved",
            },
        },
        "release_gate": {
            "profile": "structured_planning",
            "active": True,
            "passed": True,
            "uses_production_settings": True,
        },
        "profiles": {
            "structured_planning": {
                "passed": True,
                "thresholds": {
                    "passage_recall_at_k": 0.9,
                    "mean_reciprocal_rank": 0.75,
                    "unanswerable_accuracy": 0.8,
                },
                "summary": {
                    "questions": 3,
                    "answerable_questions": 2,
                    "unanswerable_questions": 1,
                    "source_recall_at_k": 1.0,
                    "passage_recall_at_k": 1.0,
                    "mean_reciprocal_rank": 1.0,
                    "top_1_accuracy": 1.0,
                    "unanswerable_accuracy": 1.0,
                    "false_positive_rate": 0.0,
                    "top_k": 8,
                },
                "rows": [answerable_row, second_answerable_row, unanswerable_row],
            }
        },
    }


def _valid_report_artifact():
    row = {
        "id": "one",
        "kind": "product_scenario",
        "generation_attempts": 1,
        "repair_required": False,
        "repair_succeeded": False,
        "repair_exhausted": False,
        "governed_gate_passed": True,
        "structural_gate_passed": True,
        "blocking_failures": [],
        "safety_violation_codes": [],
        "safety_violation_count": 0,
        "safety_findings": [],
        "quality_policy_version": "governed-report-v2",
        "quality_policy_fingerprint": "c" * 64,
        "retrieved_chunks": 1,
        "evidence_bound": True,
        "rag_title_attributed": True,
        "rag_behavior_passed": True,
        "unsafe_live_claims": [],
        "scenario_topics_passed": True,
        "forbidden_term_hits": [],
        "latency_seconds": 0.25,
        "report_characters": 100,
        "report_character_limit": 32000,
        "report_size_passed": True,
        "grounding_status": "not_applicable",
        "grounding_claims_evaluated": 0,
        "grounding_support_rate": None,
        "citation_coverage_rate": None,
        "citation_precision_rate": None,
        "numeric_consistency_rate": None,
        "jurisdiction_conflicts": 0,
        "grounding_review_claim_count": 0,
        "grounding_review_claim_unique_count": 0,
        "grounding_review_claim_ids": [],
        "grounding_review_claim_ids_truncated": False,
    }
    return {
        "artifact_schema": "bushfire-report-generation-evaluation-v4",
        "evaluation_schema_version": 4,
        "passed": True,
        "run": {
            **_timestamps(),
            "git": _git(),
            "scenario_file": "data_australia/rag/report_evaluation-v0.6.0.json",
            "scenario_file_sha256": "b" * 64,
            "scenario_hash_basis": "exact_file_bytes",
            "scenario_schema_version": 3,
            "scenario_suite_kind": "product_regression",
            "scenario_suite_version": "0.6.0",
            "quality_policy": {
                "version": "governed-report-v2",
                "fingerprint": "c" * 64,
            },
            "rag_index": _index(),
            "model": {
                "name": "bushfire-ready-qwen",
                "digest": "d" * 64,
                "digest_status": "resolved",
                "parameters": {"max_report_repair_attempts": 2},
            },
        },
        "selection": {
            "declared_scenario_ids": ["one"],
            "selected_scenario_ids": ["one"],
            "declared_scenarios": 1,
            "selected_scenarios": 1,
            "complete": True,
            "declared_scenario_kinds": [{"id": "one", "kind": "product_scenario", "attack_surface": None}],
        },
        "release_gate": {"active": True, "passed": True},
        "thresholds": {
            "governed_gate_rate": 1.0,
            "evidence_binding_rate": 1.0,
            "rag_title_attribution_rate": 1.0,
            "rag_behavior_rate": 1.0,
            "safety_violation_rate": 0.0,
            "unsafe_live_claim_rate": 0.0,
            "scenario_topic_rate": 1.0,
            "scenario_contamination_rate": 0.0,
            "repair_rate": 0.75,
            "oversized_report_rate": 0.0,
        },
        "summary": {
            "scenarios": 1,
            "governed_gate_rate": 1.0,
            "structural_gate_rate": 1.0,
            "evidence_binding_rate": 1.0,
            "rag_title_attribution_rate": 1.0,
            "rag_behavior_rate": 1.0,
            "safety_violation_rate": 0.0,
            "unsafe_live_claim_rate": 0.0,
            "scenario_topic_rate": 1.0,
            "scenario_contamination_rate": 0.0,
            "repair_rate": 0.0,
            "repair_success_rate": 1.0,
            "repair_exhaustion_rate": 0.0,
            "oversized_report_rate": 0.0,
            "average_latency_seconds": 0.25,
            "p95_latency_seconds": 0.25,
            "maximum_latency_seconds": 0.25,
            "grounding_review_rate": 0.0,
            "average_grounding_support_rate": None,
            "average_citation_coverage_rate": None,
            "average_citation_precision_rate": None,
            "average_numeric_consistency_rate": None,
            "jurisdiction_conflicts": 0,
        },
        "rows": [row],
    }


def _valid_legacy_report_artifact():
    artifact = _valid_report_artifact()
    artifact["artifact_schema"] = "bushfire-report-generation-evaluation-v3"
    artifact["evaluation_schema_version"] = 3
    for field in (
        "scenario_file",
        "scenario_hash_basis",
        "scenario_schema_version",
        "scenario_suite_kind",
        "scenario_suite_version",
    ):
        artifact["run"].pop(field, None)
    artifact["selection"].pop("declared_scenario_kinds")
    for field in (
        "repair_succeeded",
        "repair_exhausted",
        "safety_findings",
        "grounding_review_claim_unique_count",
        "grounding_review_claim_ids_truncated",
    ):
        artifact["rows"][0].pop(field)
    for field in (
        "repair_success_rate",
        "repair_exhaustion_rate",
        "average_latency_seconds",
        "p95_latency_seconds",
        "maximum_latency_seconds",
        "grounding_review_rate",
        "average_grounding_support_rate",
        "average_citation_coverage_rate",
        "average_citation_precision_rate",
        "average_numeric_consistency_rate",
        "jurisdiction_conflicts",
    ):
        artifact["summary"].pop(field)
    return artifact


def test_offline_rag_artifact_validation_rejects_missing_question_hash():
    artifact = _valid_rag_artifact()
    assert validate_rag_evaluation_artifact(artifact) is artifact
    invalid = copy.deepcopy(artifact)
    invalid["run"]["questions_sha256"] = None

    with pytest.raises(ArtifactValidationError, match="questions SHA"):
        validate_rag_evaluation_artifact(invalid)


def test_offline_report_artifact_validation_requires_policy_and_safety_bindings():
    artifact = _valid_report_artifact()
    assert validate_report_evaluation_artifact(artifact) is artifact
    invalid = copy.deepcopy(artifact)
    invalid["run"]["quality_policy"]["fingerprint"] = "not-a-sha"

    with pytest.raises(ArtifactValidationError, match="fingerprint"):
        validate_report_evaluation_artifact(invalid)


def test_report_artifact_validation_accepts_v4_and_historical_v3_contracts():
    current = _valid_report_artifact()
    legacy = _valid_legacy_report_artifact()

    assert validate_report_evaluation_artifact(current) is current
    assert validate_report_evaluation_artifact(legacy) is legacy


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({}, "explicit repair-attempt limit"),
        ({"max_report_repair_attempts": -1}, "maximum report repair attempts is invalid"),
    ],
)
def test_report_artifact_validation_requires_a_valid_explicit_repair_attempt_limit(parameters, message):
    artifact = _valid_report_artifact()
    artifact["run"]["model"]["parameters"] = parameters

    with pytest.raises(ArtifactValidationError, match=message):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize(
    ("artifact_schema", "evaluation_schema_version"),
    [
        ("bushfire-report-generation-evaluation-v4", 3),
        ("bushfire-report-generation-evaluation-v3", 4),
    ],
)
def test_report_artifact_validation_rejects_schema_version_cross_binding(
    artifact_schema,
    evaluation_schema_version,
):
    artifact = _valid_report_artifact() if artifact_schema.endswith("v4") else _valid_legacy_report_artifact()
    artifact["evaluation_schema_version"] = evaluation_schema_version

    with pytest.raises(ArtifactValidationError, match="schema version does not match"):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize("latency", [-0.01, float("nan")])
def test_report_artifact_validation_rejects_negative_or_non_finite_latency(latency):
    artifact = _valid_report_artifact()
    artifact["rows"][0]["latency_seconds"] = latency

    with pytest.raises(ArtifactValidationError, match="latency is invalid"):
        validate_report_evaluation_artifact(artifact)


def test_report_artifact_validation_rejects_governed_pass_without_structural_pass():
    artifact = _valid_report_artifact()
    artifact["rows"][0]["structural_gate_passed"] = False

    with pytest.raises(ArtifactValidationError, match="failed the structural gate"):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize(
    ("row_updates", "message"),
    [
        ({"generation_attempts": 2}, "repair-required result is inconsistent"),
        ({"generation_attempts": 4, "repair_required": True}, "attempt count is invalid"),
        (
            {"generation_attempts": 2, "repair_required": True, "repair_succeeded": False},
            "repair success result is inconsistent",
        ),
        (
            {
                "generation_attempts": 3,
                "repair_required": True,
                "repair_exhausted": False,
                "governed_gate_passed": False,
                "structural_gate_passed": False,
                "blocking_failures": [{"name": "Model generation", "detail": "failed"}],
            },
            "repair exhaustion result is inconsistent",
        ),
    ],
)
def test_report_artifact_validation_rejects_inconsistent_attempt_and_repair_relations(row_updates, message):
    artifact = _valid_report_artifact()
    artifact["rows"][0].update(row_updates)

    with pytest.raises(ArtifactValidationError, match=message):
        validate_report_evaluation_artifact(artifact)


def _make_failing_safety_row(artifact, *, count, finding_count, claim_hash):
    artifact["rows"][0].update(
        {
            "governed_gate_passed": False,
            "structural_gate_passed": False,
            "blocking_failures": [{"name": "Safety", "detail": "blocked"}],
            "safety_violation_codes": ["road_status_assertion"],
            "safety_violation_count": count,
            "safety_findings": [
                {
                    "code": "road_status_assertion",
                    "count": finding_count,
                    "claim_hash": claim_hash,
                }
            ],
        }
    )


def test_report_artifact_validation_binds_safety_count_to_privacy_minimised_findings():
    artifact = _valid_report_artifact()
    _make_failing_safety_row(artifact, count=2, finding_count=1, claim_hash="e" * 64)

    with pytest.raises(ArtifactValidationError, match="findings do not match violation count"):
        validate_report_evaluation_artifact(artifact)


def test_report_artifact_validation_rejects_unverifiable_safety_finding_hash():
    artifact = _valid_report_artifact()
    _make_failing_safety_row(artifact, count=1, finding_count=1, claim_hash="not-a-sha")

    with pytest.raises(ArtifactValidationError, match="claim hash is invalid"):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize(
    ("row_updates", "message"),
    [
        ({"grounding_review_claim_count": 1}, "review claim count is invalid"),
        ({"grounding_review_claim_unique_count": 1}, "unique review claim count is invalid"),
        ({"grounding_status": "review_required"}, "has no review claims"),
        ({"grounding_claims_evaluated": 1}, "non-evaluated grounding status contains claims"),
        ({"grounding_review_claim_ids": ["a" * 16]}, "IDs do not match the unique count"),
        ({"grounding_review_claim_ids_truncated": True}, "truncation flag is inconsistent"),
    ],
)
def test_report_artifact_validation_rejects_inconsistent_grounding_review_evidence(row_updates, message):
    artifact = _valid_report_artifact()
    artifact["rows"][0].update(row_updates)

    with pytest.raises(ArtifactValidationError, match=message):
        validate_report_evaluation_artifact(artifact)


def test_report_artifact_validation_recomputes_p95_latency():
    artifact = _valid_report_artifact()
    artifact["summary"]["p95_latency_seconds"] = 0.24

    with pytest.raises(ArtifactValidationError, match="p95 latency is inconsistent"):
        validate_report_evaluation_artifact(artifact)


def test_release_artifact_validation_rejects_dirty_git_or_tampered_summary():
    dirty = _valid_rag_artifact()
    dirty["run"]["git"]["working_tree_dirty"] = True
    with pytest.raises(ArtifactValidationError, match="dirty Git"):
        validate_rag_evaluation_artifact(dirty)

    tampered = _valid_report_artifact()
    tampered["summary"]["safety_violation_rate"] = 1.0
    with pytest.raises(ArtifactValidationError, match="safety_violation_rate"):
        validate_report_evaluation_artifact(tampered)


def test_active_rag_release_requires_complete_per_profile_rows():
    missing_rows = _valid_rag_artifact()
    del missing_rows["profiles"]["structured_planning"]["rows"]
    with pytest.raises(ArtifactValidationError, match="missing per-question rows"):
        validate_rag_evaluation_artifact(missing_rows)

    missing_question = _valid_rag_artifact()
    missing_question["profiles"]["structured_planning"]["rows"].pop(0)
    with pytest.raises(ArtifactValidationError, match="summary questions"):
        validate_rag_evaluation_artifact(missing_question)


def test_active_rag_release_rejects_duplicate_question_rows():
    artifact = _valid_rag_artifact()
    rows = artifact["profiles"]["structured_planning"]["rows"]
    rows.append(copy.deepcopy(rows[0]))

    with pytest.raises(ArtifactValidationError, match="duplicate question IDs"):
        validate_rag_evaluation_artifact(artifact)


def test_active_rag_release_recomputes_metrics_from_rows():
    artifact = _valid_rag_artifact()
    row = artifact["profiles"]["structured_planning"]["rows"][0]
    row["passage_rank"] = 2
    row["reciprocal_rank"] = 0.5

    with pytest.raises(ArtifactValidationError, match="mean_reciprocal_rank"):
        validate_rag_evaluation_artifact(artifact)


def test_inactive_summary_only_rag_diagnostic_remains_valid_without_rows():
    artifact = _valid_rag_artifact()
    artifact["release_gate"]["active"] = False
    artifact["release_gate"]["passed"] = None
    del artifact["profiles"]["structured_planning"]["rows"]

    assert validate_rag_evaluation_artifact(artifact) is artifact


def test_ollama_digest_metadata_degrades_cleanly_when_service_is_unavailable(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(evaluation_artifacts, "urlopen", unavailable)

    result = ollama_model_identity("http://127.0.0.1:11434/v1", "local-model")

    assert result == {"name": "local-model", "digest": None, "digest_status": "unavailable"}


def test_ollama_digest_metadata_resolves_latest_alias(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "local-model:latest", "digest": "sha256:" + "f" * 64}]}).encode()

    monkeypatch.setattr(evaluation_artifacts, "urlopen", lambda *_args, **_kwargs: Response())

    result = ollama_model_identity("http://127.0.0.1:11434/v1", "local-model")

    assert result == {"name": "local-model", "digest": "f" * 64, "digest_status": "resolved"}
