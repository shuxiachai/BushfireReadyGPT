import os

from scripts.evaluate_report_generation import (
    _assess_scenario_alignment,
    _rag_behavior_passed,
    _temporary_rag_mode,
)


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
