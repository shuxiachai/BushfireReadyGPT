"""Tamper and privacy checks for the paired initial-context diagnostic."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import compare_form_rag as comparison
from src.rag.service import PLANNING_FUSION, _retrieval_configuration


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _payload():
    return {
        "schema": "rag-form-context-suite-v1",
        "schema_version": 1,
        "cases": [
            {
                "id": "synthetic_school",
                "form": {
                    "location": "Hobart, Tasmania",
                    "audience": "Synthetic planning group",
                    "scenario": "School bushfire preparedness",
                    "concerns": ["Evacuation"],
                    "timeframe": "7-day action plan",
                    "extra_context": "PRIVATE_INPUT_SENTINEL",
                },
                "targets": [
                    {
                        "id": "conditional_transport",
                        "focus_id": "evacuation",
                        "expected_source_ids": ["synthetic-source"],
                        "expected_terms": ["transport must remain unavailable", "responsible reviewer"],
                    }
                ],
            }
        ],
    }


class Service:
    def __init__(self):
        self.calls = []
        self.settings = SimpleNamespace(
            top_k=8,
            candidate_multiplier=4,
            max_chunks_per_source=3,
            score_threshold=0.2,
            dense_weight=0.5,
            lexical_coverage_threshold=0.61,
            semantic_score_threshold=0.7,
            semantic_coverage_threshold=0.2,
        )

    def _result(self, query):
        texts = [
            "PRIVATE_BODY_SENTINEL. "
            + "General notes for the meeting. " * 100
            + "Evacuation transport must remain unavailable until a responsible reviewer confirms staffing. A record is required.",
            "Long unpunctuated material " * 150,
        ]
        chunks = [
            {
                "source_id": "synthetic-source",
                "chunk_id": f"synthetic:{i}",
                "title": "Synthetic reference",
                "agency": "Synthetic authority",
                "text": text,
                "score": 0.8,
                "chunk_sha256": _sha(text),
            }
            for i, text in enumerate(texts)
        ]
        return {
            "status": "ready",
            "status_label": "Synthetic retrieval",
            "query_sha256": _sha(" ".join(query.split())),
            "retrieved_chunks": chunks,
            "index_manifest_sha256": "b" * 64,
            "embedding_model": "synthetic",
            "retrieval_configuration": _retrieval_configuration(
                self.settings, trusted_planning_scope=True, top_k=8, candidate_k=32
            ),
        }

    def retrieve(self, query, **kwargs):
        self.calls.append("legacy")
        return self._result(query)

    def retrieve_planning(self, query, *, focus_queries, jurisdiction):
        self.calls.append("focused")
        if query in comparison.NEGATIVE_QUERIES:
            return {"status": "out_of_scope", "retrieved_chunks": []}
        result = self._result(query)
        result["retrieval_configuration"]["query_plan"] = {
            "schema": "official-focus-query-plan-v1",
            "fusion": PLANNING_FUSION,
            "rrf_k": 60,
            "per_query_candidate_k": 32,
            "queries": [
                {"focus_id": None, "query_sha256": result["query_sha256"], "matched_chunks": 2},
                *[
                    {"focus_id": row["focus_id"], "query_sha256": _sha(row["query"]), "matched_chunks": 2}
                    for row in focus_queries
                ],
            ],
        }
        return result


@pytest.fixture
def artifact():
    return comparison.run_comparison(_payload(), Service())


def test_paired_paths_preserve_v1_and_measure_nonzero_window_offsets(artifact):
    old = artifact["baseline"]
    candidate = artifact["variants"]["window_only"]
    assert old["summary"]["visible_passage_hit_count"] == 0
    assert candidate["summary"]["visible_passage_hit_count"] == 1
    assert candidate["rows"][0]["assembly"]["chunks"][0]["visible_start"] > 0
    assert candidate["summary"]["per_chunk_truncated_count"] == 1
    assert candidate["summary"]["unsafe_sentence_window_dropped_count"] == 1
    assert candidate["summary"]["total_budget_dropped_count"] == 0
    assert candidate["summary"]["omitted_chunk_count"] == 1
    assert comparison.validate_comparison(artifact, _payload()) is artifact


def test_diagnostic_does_not_export_private_text_or_call_report_model(artifact):
    serialised = json.dumps(artifact)
    assert "PRIVATE_BODY_SENTINEL" not in serialised and "PRIVATE_INPUT_SENTINEL" not in serialised
    assert "transport must remain unavailable" not in serialised
    assert artifact["report_model_called"] is False
    assert all(
        probe["status"] == "out_of_scope" and probe["retrieved_count"] == 0 for probe in artifact["negative_probes"]
    )


def test_every_variant_and_negative_probe_runs_between_provenance_checks():
    checked = []
    service = Service()
    comparison.run_comparison(
        _payload(), service, provenance_check=lambda label, result=None: checked.append((label, result))
    )
    assert len(checked) == 12
    assert service.calls == ["legacy", "legacy", "focused", "focused", "focused", "focused"]


@pytest.mark.parametrize(
    "mutation",
    [
        "fragment_offset",
        "fragment_hash",
        "visible_hash",
        "omission_count",
        "selection_hash",
        "boolean_flag",
        "prompt_hash",
        "context_hash",
        "reason",
        "missing_witness",
        "duplicate_witness",
        "missing_fragments",
        "query_hash",
        "query_count",
        "query_budget",
        "query_plaintext",
        "private_text",
        "summary",
        "source_cap",
    ],
)
def test_semantic_structure_rejects_tampering_even_after_payload_rehash(artifact, mutation):
    output = copy.deepcopy(artifact)
    variant = output["variants"]["focused_window"]
    row = variant["rows"][0]
    entry = row["assembly"]["chunks"][0]
    plan = row["retrieval_configuration"]["query_plan"]
    if mutation == "fragment_offset":
        entry["fragments"][0]["sanitised_start"] += 1
    elif mutation == "fragment_hash":
        entry["fragments"][0]["visible_text_sha256"] = "c" * 64
    elif mutation == "visible_hash":
        entry["visible_text_sha256"] = "c" * 64
    elif mutation == "omission_count":
        entry["omitted_prefix_characters"] += 1
    elif mutation == "selection_hash":
        row["assembly"]["selection_inputs_sha256"] = "c" * 64
    elif mutation == "boolean_flag":
        entry["included"] = 1
    elif mutation == "prompt_hash":
        row["initial_prompt"]["sha256"] = "not-a-hash"
    elif mutation == "context_hash":
        row["assembly"]["context_sha256"] = "not-a-hash"
    elif mutation == "reason":
        entry["reason"] = "complete"
    elif mutation == "missing_witness":
        row["targets"][0]["witnesses"] = []
    elif mutation == "duplicate_witness":
        row["targets"][0]["witnesses"].append(copy.deepcopy(row["targets"][0]["witnesses"][0]))
    elif mutation == "missing_fragments":
        entry["fragments"] = []
    elif mutation == "query_hash":
        plan["queries"][1]["query_sha256"] = "c" * 64
    elif mutation == "query_count":
        plan["queries"].pop()
    elif mutation == "query_budget":
        plan["queries"][1]["matched_chunks"] = 33
    elif mutation == "query_plaintext":
        plan["queries"][1]["query"] = "PRIVATE_SENTINEL"
    elif mutation == "private_text":
        entry["text"] = "PRIVATE_SENTINEL"
    elif mutation == "summary":
        variant["summary"]["unsafe_sentence_window_dropped_count"] = 0
    elif mutation == "source_cap":
        row["retrieval_configuration"]["max_chunks_per_source"] = 1
    comparison._bind_comparison_digest(output)
    with pytest.raises(ValueError):
        comparison.validate_comparison(output, _payload())


def test_payload_hash_detects_metadata_changes_without_rehash(artifact):
    artifact["variants"]["focused_window"]["rows"][0]["initial_prompt"]["sha256"] = "c" * 64
    with pytest.raises(ValueError, match="payload changed"):
        comparison.validate_comparison(artifact, _payload())


def test_legacy_only_service_cannot_be_misreported_as_focused_comparison():
    with pytest.raises(ValueError, match="focused retrieval capability"):
        comparison.run_comparison(_payload(), SimpleNamespace(retrieve=lambda *_: None))


def test_generator_rejects_visible_text_different_from_the_actual_prompt(monkeypatch):
    original = comparison.run_analysis_pipeline

    def mutated(*args, **kwargs):
        analysis = original(*args, **kwargs)
        analysis["rag_context_assembly"]["visible_chunks"][0]["text"] = "Different private text."
        return analysis

    monkeypatch.setattr(comparison, "run_analysis_pipeline", mutated)
    with pytest.raises(ValueError, match="visible text identity"):
        comparison.run_comparison(_payload(), Service())
