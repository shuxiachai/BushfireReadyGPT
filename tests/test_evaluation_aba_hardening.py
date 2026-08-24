import copy
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import evaluate_rag, evaluate_report_generation

BASELINE_INDEX = "a" * 64
DRIFTED_INDEX = "9" * 64


def _rag_metadata():
    return {
        "started_at_utc": "2026-08-24T00:00:00+00:00",
        "questions_file": "questions.json",
        "questions_sha256": "1" * 64,
        "questions_hash_basis": "exact_file_bytes",
        "questions_schema_version": 3,
        "git": {"commit": "2" * 40, "working_tree_dirty": False, "collection_status": "collected"},
        "rag_index": {
            "status": "verified",
            "manifest_sha256": BASELINE_INDEX,
            "catalog_sha256": "3" * 64,
            "corpus_sha256": "4" * 64,
            "documents_sha256": "5" * 64,
        },
        "embedding_model": {
            "provider": "ollama",
            "name": "embeddinggemma",
            "digest": "6" * 64,
            "digest_status": "resolved",
        },
    }


def _rag_questions():
    return {
        "schema_version": 3,
        "thresholds": {
            "passage_recall_at_k": 0.0,
            "mean_reciprocal_rank": 0.0,
            "unanswerable_accuracy": 0.0,
        },
        "questions": [
            {
                "id": "answerable",
                "query": "property preparation",
                "expected_source_ids": ["expected-source"],
                "expected_terms": ["prepare", "property"],
            },
            {"id": "negative", "query": "unsupported", "answerable": False},
        ],
    }


class RagEvaluationService:
    observed_manifest = BASELINE_INDEX

    def __init__(self):
        self.settings = SimpleNamespace(top_k=8)

    def retrieve(self, query, *, jurisdiction=None, top_k=None, trusted_planning_scope=False):
        del jurisdiction
        profile = "structured_planning" if trusted_planning_scope else "free_text"
        configuration = {
            "query_scope": profile,
            "top_k": top_k,
            "candidate_k": top_k * 4,
        }
        if query == "unsupported":
            return {
                "status": "no_match",
                "retrieved_chunks": [],
                "retrieval_configuration": configuration,
                "index_manifest_sha256": self.observed_manifest,
            }
        return {
            "status": "ready",
            "retrieved_chunks": [
                {
                    "source_id": "expected-source",
                    "text": "prepare the property",
                }
            ],
            "retrieval_configuration": configuration,
            "index_manifest_sha256": self.observed_manifest,
        }


def _report_metadata():
    return {
        "started_at_utc": "2026-08-24T00:00:00+00:00",
        "scenario_file": "scenarios.json",
        "scenario_file_sha256": "1" * 64,
        "scenario_schema_version": 2,
        "git": {"commit": "2" * 40, "working_tree_dirty": False, "collection_status": "collected"},
        "rag_index": {
            "status": "verified",
            "manifest_sha256": BASELINE_INDEX,
            "catalog_sha256": "3" * 64,
            "corpus_sha256": "4" * 64,
            "documents_sha256": "5" * 64,
        },
        "model": {
            "provider": "ollama",
            "name": "bushfire-ready-qwen",
            "digest": "6" * 64,
            "digest_status": "resolved",
        },
        "quality_policy": {
            "version": evaluate_report_generation.QUALITY_POLICY_VERSION,
            "fingerprint": evaluate_report_generation.QUALITY_POLICY_FINGERPRINT,
            "manifest": {},
        },
    }


def _report_scenarios():
    return {
        "schema_version": 2,
        "required_product_scenarios": [],
        "thresholds": {},
        "scenarios": [
            {"id": "product", "scenario": "School"},
            {"id": "no-rag", "scenario": "Household", "rag_enabled": False},
            {
                "id": "live-safety",
                "scenario": "Current route",
                "expected_knowledge_status": "out_of_scope",
            },
        ],
    }


def test_rag_release_rejects_index_used_by_question_after_files_restore_to_baseline(tmp_path, monkeypatch):
    questions_path = tmp_path / "questions.json"
    output_path = tmp_path / "rag-result.json"
    questions_path.write_text(json.dumps(_rag_questions()), encoding="utf-8")
    RagEvaluationService.observed_manifest = DRIFTED_INDEX
    monkeypatch.setattr(evaluate_rag, "RagService", RagEvaluationService)
    monkeypatch.setattr(evaluate_rag, "build_run_metadata", lambda *_args: copy.deepcopy(_rag_metadata()))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_rag.py",
            "--questions",
            str(questions_path),
            "--mode",
            "structured_planning",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="rag_index"):
        evaluate_rag.main()

    assert not output_path.exists()


def test_rag_release_stops_on_intermediate_mutable_drift_before_aba_restore(tmp_path, monkeypatch):
    questions_path = tmp_path / "questions.json"
    output_path = tmp_path / "rag-result.json"
    questions_path.write_text(json.dumps(_rag_questions()), encoding="utf-8")
    baseline = _rag_metadata()
    drifted = copy.deepcopy(baseline)
    drifted["questions_sha256"] = "8" * 64
    snapshots = iter((baseline, drifted, baseline))
    RagEvaluationService.observed_manifest = BASELINE_INDEX
    monkeypatch.setattr(evaluate_rag, "RagService", RagEvaluationService)
    monkeypatch.setattr(evaluate_rag, "build_run_metadata", lambda *_args: copy.deepcopy(next(snapshots)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_rag.py",
            "--questions",
            str(questions_path),
            "--mode",
            "structured_planning",
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="questions_sha256"):
        evaluate_rag.main()

    assert not output_path.exists()


def test_rag_question_boundaries_refresh_model_identity_every_time(monkeypatch):
    baseline = _rag_metadata()
    supplied_model_identities = []

    def observed_metadata(_payload, _questions_path, _service, embedding_identity=None):
        supplied_model_identities.append(embedding_identity)
        return copy.deepcopy(baseline)

    monkeypatch.setattr(evaluate_rag, "build_run_metadata", observed_metadata)
    guard = evaluate_rag._RagReleaseBoundaryGuard(
        _rag_questions(),
        "questions.json",
        RagEvaluationService(),
        baseline,
    )
    result = {"index_manifest_sha256": BASELINE_INDEX}

    guard.check("question one", result)
    guard.check("question two", result)
    guard.check("profile boundary")

    with pytest.raises(SystemExit, match="rag_index"):
        guard.check("missing manifest", {"status": "ready", "retrieved_chunks": []})

    assert supplied_model_identities == [None, None, None, None]


def test_rag_question_boundaries_detect_model_a_to_b_to_a_drift(monkeypatch):
    baseline = _rag_metadata()
    drifted = copy.deepcopy(baseline)
    drifted["embedding_model"]["digest"] = "8" * 64
    snapshots = iter((baseline, drifted, baseline))

    def observed_metadata(_payload, _questions_path, _service, embedding_identity=None):
        assert embedding_identity is None
        return copy.deepcopy(next(snapshots))

    monkeypatch.setattr(evaluate_rag, "build_run_metadata", observed_metadata)
    guard = evaluate_rag._RagReleaseBoundaryGuard(
        _rag_questions(),
        "questions.json",
        RagEvaluationService(),
        baseline,
    )

    guard.check("before question one")
    with pytest.raises(SystemExit, match="embedding_model"):
        guard.check("after question one")
    guard.check("before question two")


def test_report_release_rejects_index_used_by_scenario_after_files_restore_to_baseline(tmp_path, monkeypatch):
    scenarios_path = tmp_path / "scenarios.json"
    output_path = tmp_path / "report-result.json"
    scenarios_path.write_text(json.dumps(_report_scenarios()), encoding="utf-8")
    monkeypatch.setattr(
        evaluate_report_generation,
        "_report_run_metadata",
        lambda *_args, **_kwargs: copy.deepcopy(_report_metadata()),
    )
    monkeypatch.setattr(
        evaluate_report_generation,
        "_run_scenario",
        lambda scenario: {
            "id": scenario["id"],
            "retrieved_chunks": 1,
            "rag_index_manifest_sha256": DRIFTED_INDEX,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_report_generation.py",
            "--scenarios",
            str(scenarios_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="rag_index"):
        evaluate_report_generation.main()

    assert not output_path.exists()


def test_report_release_stops_on_intermediate_model_drift_before_aba_restore(tmp_path, monkeypatch):
    scenarios_path = tmp_path / "scenarios.json"
    output_path = tmp_path / "report-result.json"
    scenarios_path.write_text(json.dumps(_report_scenarios()), encoding="utf-8")
    baseline = _report_metadata()
    drifted = copy.deepcopy(baseline)
    drifted["model"]["digest"] = "8" * 64
    snapshots = iter((baseline, baseline, drifted, baseline))
    monkeypatch.setattr(
        evaluate_report_generation,
        "_report_run_metadata",
        lambda *_args, **_kwargs: copy.deepcopy(next(snapshots)),
    )
    monkeypatch.setattr(
        evaluate_report_generation,
        "_run_scenario",
        lambda scenario: {
            "id": scenario["id"],
            "retrieved_chunks": 0,
            "rag_index_manifest_sha256": None,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_report_generation.py",
            "--scenarios",
            str(scenarios_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit, match="model"):
        evaluate_report_generation.main()

    assert not output_path.exists()


def test_report_scenario_boundaries_detect_model_a_to_b_to_a_drift(monkeypatch):
    baseline = _report_metadata()
    drifted = copy.deepcopy(baseline)
    drifted["model"]["digest"] = "8" * 64
    snapshots = iter((baseline, drifted, baseline))

    def observed_metadata(*_args, model_identity=None, **_kwargs):
        assert model_identity is None
        return copy.deepcopy(next(snapshots))

    monkeypatch.setattr(evaluate_report_generation, "_report_run_metadata", observed_metadata)
    guard = evaluate_report_generation._ReportReleaseBoundaryGuard(
        _report_scenarios(),
        "scenarios.json",
        baseline,
        started_at_utc=baseline["started_at_utc"],
    )

    guard.check("before scenario one")
    with pytest.raises(SystemExit, match="model"):
        guard.check("after scenario one")
    guard.check("before scenario two")
