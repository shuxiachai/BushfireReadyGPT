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
        "governed_gate_passed": True,
        "structural_gate_passed": True,
        "blocking_failures": [],
        "safety_violation_codes": [],
        "quality_policy_version": "governed-report-v2",
        "quality_policy_fingerprint": "c" * 64,
        "retrieved_chunks": 1,
        "evidence_bound": True,
        "rag_title_attributed": True,
        "rag_behavior_passed": True,
        "unsafe_live_claims": [],
        "scenario_topics_passed": True,
        "forbidden_term_hits": [],
        "repair_required": False,
        "report_size_passed": True,
    }
    return {
        "artifact_schema": "bushfire-report-generation-evaluation-v3",
        "passed": True,
        "run": {
            **_timestamps(),
            "git": _git(),
            "scenario_file_sha256": "b" * 64,
            "quality_policy": {
                "version": "governed-report-v2",
                "fingerprint": "c" * 64,
            },
            "rag_index": _index(),
            "model": {
                "name": "bushfire-ready-qwen",
                "digest": "d" * 64,
                "digest_status": "resolved",
            },
        },
        "selection": {
            "declared_scenario_ids": ["one"],
            "selected_scenario_ids": ["one"],
            "declared_scenarios": 1,
            "selected_scenarios": 1,
            "complete": True,
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
            "oversized_report_rate": 0.0,
        },
        "rows": [row],
    }


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
