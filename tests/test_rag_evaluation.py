import copy
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import evaluate_rag
from scripts.evaluate_rag import _resolve_mode, build_run_metadata, run_evaluation


class EvaluationService:
    def __init__(self):
        self.settings = SimpleNamespace(top_k=8)
        self.calls = []

    def retrieve(self, query, *, jurisdiction=None, top_k=None, trusted_planning_scope=False):
        profile = "structured_planning" if trusted_planning_scope else "free_text"
        self.calls.append((query, jurisdiction, top_k, trusted_planning_scope))
        effective = {
            "dense_score_threshold": 0.35,
            "lexical_coverage_threshold": 0.35 if trusted_planning_scope else 0.61,
            "semantic_score_threshold": 0.35 if trusted_planning_scope else 0.45,
            "semantic_coverage_threshold": 0.1 if trusted_planning_scope else 0.2,
        }
        configuration = {
            "query_scope": profile,
            "top_k": top_k,
            "candidate_k": top_k * 4,
            "candidate_multiplier": 4,
            "dense_weight": 0.65,
            "lexical_weight": 0.35,
            "max_chunks_per_source": 3,
            "configured_thresholds": {
                "dense_score_threshold": 0.35,
                "lexical_coverage_threshold": 0.61,
                "semantic_score_threshold": 0.45,
                "semantic_coverage_threshold": 0.2,
            },
            "effective_thresholds": effective,
        }
        if query == "unsupported":
            return {
                "status": "no_match",
                "retrieved_chunks": [],
                "retrieval_configuration": configuration,
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
        }


def _payload():
    return {
        "schema_version": 3,
        "thresholds": {
            "passage_recall_at_k": 0.9,
            "mean_reciprocal_rank": 0.75,
            "unanswerable_accuracy": 0.8,
        },
        "questions": [
            {
                "id": "answerable",
                "query": "property preparation",
                "jurisdiction": "Queensland",
                "category": "property",
                "expected_source_ids": ["expected-source"],
                "expected_terms": ["prepare", "property"],
            },
            {
                "id": "unanswerable",
                "query": "unsupported",
                "answerable": False,
                "category": "hard-negative",
            },
        ],
    }


def _release_metadata():
    return {
        "started_at_utc": "2026-08-24T00:00:00+00:00",
        "questions_file": "questions.json",
        "questions_sha256": "a" * 64,
        "questions_hash_basis": "exact_file_bytes",
        "questions_schema_version": 3,
        "git": {"commit": "b" * 40, "working_tree_dirty": False, "collection_status": "collected"},
        "rag_index": {
            "status": "verified",
            "manifest_sha256": "c" * 64,
            "catalog_sha256": "e" * 64,
            "corpus_sha256": "f" * 64,
            "documents_sha256": "1" * 64,
        },
        "embedding_model": {
            "provider": "ollama",
            "name": "embeddinggemma",
            "digest": "d" * 64,
            "digest_status": "resolved",
        },
    }


def test_default_rag_evaluation_gates_production_and_reports_both_profiles():
    service = EvaluationService()

    output = run_evaluation(
        _payload(),
        service,
        mode="both",
        free_text_top_k=5,
    )

    assert output["passed"] is True
    assert output["artifact_schema"] == "bushfire-rag-evaluation-v3"
    assert len(output["run"]["questions_sha256"]) == 64
    assert output["run"]["questions_hash_basis"] == "canonical_json"
    assert output["release_gate"] == {
        "profile": "structured_planning",
        "active": True,
        "passed": True,
        "uses_production_settings": True,
    }
    assert set(output["profiles"]) == {"structured_planning", "free_text"}
    production = output["profiles"]["structured_planning"]
    diagnostic = output["profiles"]["free_text"]
    assert production["retrieval_configuration"]["top_k"] == 8
    assert production["retrieval_configuration"]["effective_thresholds"] == {
        "dense_score_threshold": 0.35,
        "lexical_coverage_threshold": 0.35,
        "semantic_score_threshold": 0.35,
        "semantic_coverage_threshold": 0.1,
    }
    assert diagnostic["retrieval_configuration"]["top_k"] == 5
    assert diagnostic["retrieval_configuration"]["effective_thresholds"]["lexical_coverage_threshold"] == 0.61
    assert output["summary"]["query_scope"] == "structured_planning"
    assert len(production["rows"]) == 2
    assert len(diagnostic["rows"]) == 2
    assert output["rows"] == production["rows"]
    assert [call[2:] for call in service.calls] == [
        (8, True),
        (8, True),
        (5, False),
        (5, False),
    ]


def test_summary_only_rag_evaluation_is_diagnostic_not_a_release_gate():
    output = run_evaluation(
        _payload(),
        EvaluationService(),
        mode="both",
        free_text_top_k=5,
        summary_only=True,
    )

    assert output["passed"] is True
    assert output["release_gate"] == {
        "profile": "structured_planning",
        "active": False,
        "passed": None,
        "uses_production_settings": True,
    }
    assert "rows" not in output
    assert all("rows" not in profile for profile in output["profiles"].values())


def test_nonproduction_structured_override_is_not_a_release_gate():
    output = run_evaluation(
        _payload(),
        EvaluationService(),
        mode="structured_planning",
        free_text_top_k=5,
        structured_top_k=4,
    )

    assert output["passed"] is True
    assert output["release_gate"]["active"] is False
    assert output["release_gate"]["passed"] is None
    assert output["release_gate"]["uses_production_settings"] is False
    assert output["summary"]["top_k"] == 4


def test_profile_specific_pass_thresholds_override_shared_defaults():
    payload = _payload()
    payload["profile_thresholds"] = {
        "structured_planning": {"passage_recall_at_k": 1.0},
        "free_text": {"mean_reciprocal_rank": 1.0},
    }

    output = run_evaluation(
        payload,
        EvaluationService(),
        mode="both",
        free_text_top_k=5,
        summary_only=True,
    )

    assert output["profiles"]["structured_planning"]["thresholds"]["passage_recall_at_k"] == 1.0
    assert output["profiles"]["free_text"]["thresholds"]["mean_reciprocal_rank"] == 1.0


def test_legacy_top_k_cli_selects_the_original_free_text_profile():
    assert _resolve_mode(None, 5) == "free_text"
    assert _resolve_mode(None, None) == "both"
    assert _resolve_mode("structured_planning", None) == "structured_planning"


def test_out_of_domain_negatives_can_be_scoped_to_free_text():
    payload = _payload()
    payload["questions"].append(
        {
            "id": "free-text-only-negative",
            "query": "unsupported",
            "answerable": False,
            "category": "out_of_domain",
            "evaluation_profiles": ["free_text"],
        }
    )

    output = run_evaluation(
        payload,
        EvaluationService(),
        mode="both",
        free_text_top_k=5,
        summary_only=True,
    )

    assert output["profiles"]["structured_planning"]["summary"]["questions"] == 2
    assert output["profiles"]["free_text"]["summary"]["questions"] == 3


def test_run_metadata_binds_exact_questions_index_embedding_and_git(tmp_path, monkeypatch):
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps(_payload()), encoding="utf-8")
    service = EvaluationService()
    service.settings.embedding_base_url = "http://127.0.0.1:11434"
    service.settings.embedding_model = "embeddinggemma"
    monkeypatch.setattr(
        evaluate_rag,
        "rag_index_provenance",
        lambda _settings: {
            "status": "verified",
            "manifest_sha256": "a" * 64,
            "corpus_sha256": "b" * 64,
            "embedding_dimension": 768,
        },
    )
    monkeypatch.setattr(
        evaluate_rag,
        "ollama_model_identity",
        lambda *_args, **_kwargs: {
            "name": "embeddinggemma",
            "digest": "c" * 64,
            "digest_status": "resolved",
        },
    )
    monkeypatch.setattr(
        evaluate_rag,
        "git_provenance",
        lambda _root: {"commit": "d" * 40, "working_tree_dirty": False, "collection_status": "collected"},
    )

    metadata = build_run_metadata(_payload(), questions_path, service)

    assert metadata["questions_hash_basis"] == "exact_file_bytes"
    assert len(metadata["questions_sha256"]) == 64
    assert metadata["rag_index"]["corpus_sha256"] == "b" * 64
    assert metadata["embedding_model"]["digest"] == "c" * 64
    assert metadata["embedding_model"]["dimension"] == 768
    assert metadata["git"]["commit"] == "d" * 40


def test_rag_cli_output_file_and_stdout_are_the_same_json(tmp_path, monkeypatch, capsys):
    questions_path = tmp_path / "questions.json"
    output_path = tmp_path / "result.json"
    questions_path.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(evaluate_rag, "RagService", EvaluationService)
    monkeypatch.setattr(evaluate_rag, "build_run_metadata", lambda *_args: _release_metadata())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_rag.py",
            "--questions",
            str(questions_path),
            "--mode",
            "structured_planning",
            "--summary-only",
            "--output",
            str(output_path),
        ],
    )

    assert evaluate_rag.main() == 0
    stdout_payload = json.loads(capsys.readouterr().out)

    assert json.loads(output_path.read_text(encoding="utf-8")) == stdout_payload
    assert stdout_payload["run"]["provenance_stability"] == {
        "checked": True,
        "stable": True,
        "drift_fields": [],
    }
    assert stdout_payload["release_gate"]["active"] is False
    assert stdout_payload["release_gate"]["passed"] is None


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("questions_sha256", lambda metadata: metadata.update(questions_sha256="9" * 64)),
        ("git", lambda metadata: metadata["git"].update(commit="9" * 40)),
        ("rag_index", lambda metadata: metadata["rag_index"].update(manifest_sha256="9" * 64)),
        ("embedding_model", lambda metadata: metadata["embedding_model"].update(digest="9" * 64)),
    ],
)
def test_active_rag_cli_aborts_before_writing_when_release_identity_drifts(
    tmp_path,
    monkeypatch,
    field,
    mutate,
):
    questions_path = tmp_path / "questions.json"
    output_path = tmp_path / "result.json"
    questions_path.write_text(json.dumps(_payload()), encoding="utf-8")
    start = _release_metadata()
    completion = copy.deepcopy(start)
    mutate(completion)
    snapshots = iter((start, completion))
    monkeypatch.setattr(evaluate_rag, "RagService", EvaluationService)
    monkeypatch.setattr(evaluate_rag, "build_run_metadata", lambda *_args: next(snapshots))
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

    with pytest.raises(SystemExit, match=field):
        evaluate_rag.main()

    assert not output_path.exists()
