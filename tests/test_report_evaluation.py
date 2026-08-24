import copy
import json
import os
import sys

import pytest

from scripts import evaluate_report_generation
from scripts.evaluate_report_generation import (
    _assess_scenario_alignment,
    _rag_behavior_passed,
    _temporary_rag_mode,
    run_scenario_with_artifacts,
)


def _passing_row(scenario_id):
    return {
        "id": scenario_id,
        "kind": "product_scenario",
        "generation_attempts": 1,
        "repair_required": False,
        "governed_gate_passed": True,
        "structural_gate_passed": True,
        "quality_policy_version": evaluate_report_generation.QUALITY_POLICY_VERSION,
        "quality_policy_fingerprint": evaluate_report_generation.QUALITY_POLICY_FINGERPRINT,
        "blocking_failures": [],
        "safety_violation_codes": [],
        "safety_violation_count": 0,
        "retrieved_chunks": 0,
        "knowledge_status": "ready",
        "rag_embedding_model": None,
        "rag_index_manifest_sha256": None,
        "expected_knowledge_status": ["ready"],
        "rag_behavior_passed": True,
        "evidence_bound": True,
        "rag_title_attributed": True,
        "attributed_source_ids": [],
        "unsafe_live_claims": [],
        "scenario_topic_coverage": 1.0,
        "scenario_topics_passed": True,
        "forbidden_term_hits": [],
        "latency_seconds": 0.1,
        "report_characters": 100,
        "report_character_limit": 32000,
        "report_size_passed": True,
        "grounding_status": "review_required",
        "grounding_claims_evaluated": 0,
        "grounding_support_rate": None,
        "citation_coverage_rate": None,
        "citation_precision_rate": None,
        "numeric_consistency_rate": None,
        "jurisdiction_conflicts": 0,
    }


def _release_metadata():
    return {
        "started_at_utc": "2026-08-24T00:00:00+00:00",
        "scenario_file": "scenarios.json",
        "scenario_file_sha256": "a" * 64,
        "scenario_schema_version": 2,
        "git": {"commit": "b" * 40, "working_tree_dirty": False, "collection_status": "collected"},
        "rag_index": {
            "status": "verified",
            "manifest_sha256": "c" * 64,
            "catalog_sha256": "d" * 64,
            "corpus_sha256": "e" * 64,
            "documents_sha256": "f" * 64,
        },
        "model": {
            "provider": "ollama",
            "name": "bushfire-ready-qwen",
            "digest": "1" * 64,
            "digest_status": "resolved",
        },
        "quality_policy": {
            "version": evaluate_report_generation.QUALITY_POLICY_VERSION,
            "fingerprint": evaluate_report_generation.QUALITY_POLICY_FINGERPRINT,
            "manifest": {},
        },
    }


def _complete_scenario_payload():
    return {
        "schema_version": 2,
        "required_product_scenarios": [],
        "thresholds": {},
        "scenarios": [
            {"id": "product", "scenario": "School", "location": "Cairns"},
            {"id": "no-rag", "scenario": "Household", "rag_enabled": False},
            {
                "id": "live-safety",
                "scenario": "Current route",
                "expected_knowledge_status": "out_of_scope",
            },
        ],
    }


def test_scenario_alignment_supports_synonym_groups_and_reports_contamination():
    result = _assess_scenario_alignment(
        "A home plan covers an emergency kit and pets, but it incorrectly mentions teachers.",
        {
            "expected_topic_groups": [["household", "home"], "emergency kit", ["pet", "animal"]],
            "minimum_topic_coverage": 1.0,
            "forbidden_terms": ["teacher", "aged care"],
        },
    )

    assert result["scenario_topics_passed"] is True
    assert result["scenario_topic_coverage"] == 1.0
    assert result["forbidden_term_hits"] == ["teacher"]


def test_rag_behavior_checks_status_and_expected_chunk_presence():
    assert _rag_behavior_passed({}, "ready", 2) is True
    assert _rag_behavior_passed({"expect_retrieved_chunks": False}, "ready", 2) is False
    assert (
        _rag_behavior_passed(
            {"expected_knowledge_status": "out_of_scope", "expect_retrieved_chunks": False},
            "out_of_scope",
            0,
        )
        is True
    )


def test_temporary_rag_mode_restores_environment(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "true")

    with _temporary_rag_mode(False):
        assert os.environ["BUSHFIRE_RAG_ENABLED"] == "false"

    assert os.environ["BUSHFIRE_RAG_ENABLED"] == "true"


def test_single_scenario_uses_canonical_gate_and_returns_private_artifacts_separately(monkeypatch):
    analysis = {
        "knowledge": {
            "status": "ready",
            "embedding_model": "embeddinggemma",
            "index_manifest_sha256": "a" * 64,
            "retrieved_chunks": [],
        }
    }
    scenario = {
        "id": "one",
        "location": "Cairns",
        "audience": "school",
        "scenario": "School Preparedness",
        "concerns": ["students"],
        "timeframe": "7 days",
        "expect_retrieved_chunks": False,
    }
    monkeypatch.setattr(evaluate_report_generation, "run_analysis_pipeline", lambda *_args: analysis)
    monkeypatch.setattr(evaluate_report_generation, "build_report_prompt", lambda *_args, **_kwargs: "prompt")

    class Model:
        def generate(self, _prompt):
            return "model narrative"

    monkeypatch.setattr(evaluate_report_generation, "GovernedModelClient", Model)
    monkeypatch.setattr(evaluate_report_generation, "normalize_generated_narrative", lambda value: value)
    monkeypatch.setattr(
        evaluate_report_generation,
        "assess_generated_narrative",
        lambda *_args: {"approval_gate": {"passed": True}},
    )
    monkeypatch.setattr(evaluate_report_generation, "apply_governance_notice", lambda value: value + "\nnotice")
    monkeypatch.setattr(
        evaluate_report_generation,
        "append_evidence_tables",
        lambda value, _analysis: value + "\nevidence",
    )
    monkeypatch.setattr(
        evaluate_report_generation,
        "append_human_signoff",
        lambda value, _review: value + "\nsignoff",
    )
    canonical_calls = []

    def canonical_gate(report, received_analysis):
        canonical_calls.append((report, received_analysis))
        return {
            "approval_gate": {"passed": False, "blocking_failures": [{"name": "Safety", "detail": "blocked"}]},
            "quality_policy_version": "governed-report-v2",
            "quality_policy_fingerprint": "f" * 64,
        }

    monkeypatch.setattr(evaluate_report_generation, "evaluate_governed_report", canonical_gate)
    monkeypatch.setattr(
        evaluate_report_generation,
        "evaluate_safety_boundaries",
        lambda _text: {
            "violations": [{"code": "road_status_assertion"}, {"code": "road_status_assertion"}],
            "summary": {"total": 2},
        },
    )
    monkeypatch.setattr(evaluate_report_generation, "attributed_rag_source_ids", lambda *_args: set())
    monkeypatch.setattr(
        evaluate_report_generation,
        "evaluate_report_grounding",
        lambda *_args: {"status": "review_required", "metrics": {}},
    )

    result = run_scenario_with_artifacts(scenario)

    assert canonical_calls == [(result["report"], analysis)]
    assert result["analysis"] is analysis
    assert result["row"]["governed_gate_passed"] is False
    assert result["row"]["quality_policy_fingerprint"] == "f" * 64
    assert result["row"]["safety_violation_codes"] == ["road_status_assertion"]
    assert "report" not in result["row"]
    assert "analysis" not in result["row"]


def test_partial_cli_run_cannot_claim_the_release_gate(tmp_path, monkeypatch):
    scenarios_path = tmp_path / "scenarios.json"
    output_path = tmp_path / "partial.json"
    scenarios_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "required_product_scenarios": [],
                "thresholds": {},
                "scenarios": [
                    {"id": "selected", "scenario": "School", "location": "Cairns"},
                    {"id": "no-rag", "scenario": "Household", "rag_enabled": False},
                    {
                        "id": "live-safety",
                        "scenario": "Current route",
                        "expected_knowledge_status": "out_of_scope",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    row = {
        "id": "selected",
        "kind": "product_scenario",
        "generation_attempts": 1,
        "repair_required": False,
        "governed_gate_passed": True,
        "structural_gate_passed": True,
        "quality_policy_version": evaluate_report_generation.QUALITY_POLICY_VERSION,
        "quality_policy_fingerprint": evaluate_report_generation.QUALITY_POLICY_FINGERPRINT,
        "blocking_failures": [],
        "safety_violation_codes": [],
        "safety_violation_count": 0,
        "retrieved_chunks": 0,
        "knowledge_status": "ready",
        "rag_embedding_model": None,
        "rag_index_manifest_sha256": None,
        "expected_knowledge_status": ["ready"],
        "rag_behavior_passed": True,
        "evidence_bound": True,
        "rag_title_attributed": True,
        "attributed_source_ids": [],
        "unsafe_live_claims": [],
        "scenario_topic_coverage": 1.0,
        "scenario_topics_passed": True,
        "forbidden_term_hits": [],
        "latency_seconds": 0.1,
        "report_characters": 100,
        "report_character_limit": 32000,
        "report_size_passed": True,
        "grounding_status": "review_required",
        "grounding_claims_evaluated": 0,
        "grounding_support_rate": None,
        "citation_coverage_rate": None,
        "citation_precision_rate": None,
        "numeric_consistency_rate": None,
        "jurisdiction_conflicts": 0,
    }
    monkeypatch.setattr(evaluate_report_generation, "_run_scenario", lambda _scenario: dict(row))
    monkeypatch.setattr(
        evaluate_report_generation,
        "_report_run_metadata",
        lambda *_args, **_kwargs: {
            "started_at_utc": "2026-08-24T00:00:00+00:00",
            "scenario_file_sha256": "a" * 64,
            "git": {"commit": None, "working_tree_dirty": True, "collection_status": "unavailable"},
            "model": {"name": "test", "digest": None, "digest_status": "unavailable"},
            "quality_policy": {
                "version": evaluate_report_generation.QUALITY_POLICY_VERSION,
                "fingerprint": evaluate_report_generation.QUALITY_POLICY_FINGERPRINT,
            },
            "rag_index": {"status": "unavailable"},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_report_generation.py",
            "--scenarios",
            str(scenarios_path),
            "--limit",
            "1",
            "--output",
            str(output_path),
        ],
    )

    assert evaluate_report_generation.main() == 0
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["passed"] is True
    assert artifact["selection"]["complete"] is False
    assert artifact["release_gate"] == {"active": False, "passed": None}
    assert artifact["run"]["provenance_stability"]["stable"] is True


def test_complete_report_cli_records_stable_completion_provenance(tmp_path, monkeypatch):
    scenarios_path = tmp_path / "scenarios.json"
    output_path = tmp_path / "complete.json"
    scenarios_path.write_text(json.dumps(_complete_scenario_payload()), encoding="utf-8")
    monkeypatch.setattr(
        evaluate_report_generation,
        "_run_scenario",
        lambda scenario: _passing_row(scenario["id"]),
    )
    monkeypatch.setattr(
        evaluate_report_generation,
        "_report_run_metadata",
        lambda *_args, **_kwargs: _release_metadata(),
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

    assert evaluate_report_generation.main() == 0
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["release_gate"] == {"active": True, "passed": True}
    assert artifact["run"]["provenance_stability"] == {
        "checked": True,
        "stable": True,
        "drift_fields": [],
    }
    assert artifact["run"]["completed_at_utc"] >= artifact["run"]["started_at_utc"]


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("scenario_file_sha256", lambda metadata: metadata.update(scenario_file_sha256="9" * 64)),
        ("git", lambda metadata: metadata["git"].update(commit="9" * 40)),
        ("rag_index", lambda metadata: metadata["rag_index"].update(manifest_sha256="9" * 64)),
        ("model", lambda metadata: metadata["model"].update(digest="9" * 64)),
        ("quality_policy", lambda metadata: metadata["quality_policy"].update(fingerprint="9" * 64)),
    ],
)
def test_complete_report_cli_aborts_before_writing_when_release_identity_drifts(
    tmp_path,
    monkeypatch,
    field,
    mutate,
):
    scenarios_path = tmp_path / "scenarios.json"
    output_path = tmp_path / "complete.json"
    scenarios_path.write_text(json.dumps(_complete_scenario_payload()), encoding="utf-8")
    start = _release_metadata()
    completion = copy.deepcopy(start)
    mutate(completion)
    snapshots = iter((start, completion))
    monkeypatch.setattr(
        evaluate_report_generation,
        "_run_scenario",
        lambda scenario: _passing_row(scenario["id"]),
    )
    monkeypatch.setattr(
        evaluate_report_generation,
        "_report_run_metadata",
        lambda *_args, **_kwargs: next(snapshots),
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

    with pytest.raises(SystemExit, match=field):
        evaluate_report_generation.main()

    assert not output_path.exists()
