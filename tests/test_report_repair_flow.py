import pytest

from src import report_generation_quality as quality
from src.source_attribution import (
    format_official_attribution,
    format_official_citation_token,
    format_rag_attribution,
    format_rag_citation_token,
)


def _analysis_with_source_contract(*, official_count=2, rag_sources=None):
    return {
        "data": {
            "sources": [
                {"id": f"official-{index}", "name": f"Official source {index}"} for index in range(official_count)
            ]
        },
        "knowledge": {"retrieved_chunks": list(rag_sources or [])},
    }


def test_generation_and_repair_share_one_bounded_policy(monkeypatch):
    assessments = iter(
        [
            {"approval_gate": {"passed": False, "blocking_failures": [{"name": "Structure"}]}},
            {"approval_gate": {"passed": True, "blocking_failures": []}},
        ]
    )
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda _text, _analysis: next(assessments))
    monkeypatch.setattr(
        quality,
        "build_report_repair_prompt",
        lambda original, previous, _result, **_kwargs: f"repair::{original}::{previous}",
    )
    calls = []

    def generate(prompt, attempt_number, is_repair):
        calls.append((prompt, attempt_number, is_repair))
        return "first draft" if attempt_number == 1 else "replacement draft"

    narrative, result, attempts = quality.generate_narrative_with_repairs(
        "governed prompt",
        _analysis_with_source_contract(),
        generate,
    )

    assert narrative == "replacement draft"
    assert result["approval_gate"]["passed"] is True
    assert attempts == 2
    assert calls == [
        ("governed prompt", 1, False),
        ("repair::governed prompt::first draft", 2, True),
    ]


def test_generation_repairs_stop_at_configured_limit(monkeypatch):
    failed = {"approval_gate": {"passed": False, "blocking_failures": []}}
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda _text, _analysis: failed)
    monkeypatch.setattr(quality, "build_report_repair_prompt", lambda *_args, **_kwargs: "repair")
    calls = []

    narrative, result, attempts = quality.generate_narrative_with_repairs(
        "prompt",
        _analysis_with_source_contract(),
        lambda prompt, attempt, repair: calls.append((prompt, attempt, repair)) or f"draft-{attempt}",
        max_repair_attempts=2,
    )

    assert narrative == "draft-3"
    assert result is failed
    assert attempts == 3
    assert [call[1] for call in calls] == [1, 2, 3]


@pytest.mark.parametrize("limit", [-1, True, 1.5, "2"])
def test_generation_repair_limit_must_be_a_non_negative_integer(limit):
    with pytest.raises(ValueError, match="non-negative integer"):
        quality.generate_narrative_with_repairs("prompt", {}, lambda *_args: "draft", max_repair_attempts=limit)


def test_generation_callback_must_be_callable():
    with pytest.raises(TypeError, match="must be callable"):
        quality.generate_narrative_with_repairs("prompt", {}, None)


@pytest.mark.parametrize("official_count", [0, 1])
def test_generation_fails_closed_before_model_access_without_two_official_sources(official_count):
    calls = []

    with pytest.raises(quality.ReportGenerationPreconditionError, match="At least two complete"):
        quality.generate_narrative_with_repairs(
            "governed prompt",
            _analysis_with_source_contract(official_count=official_count),
            lambda *_args: calls.append(True) or "draft",
        )

    assert calls == []


def test_generation_rejects_canonical_identifier_collision_before_model_access():
    analysis = {
        "data": {
            "sources": [
                {"id": "source one", "name": "First official source"},
                {"id": "source@one", "name": "Different official source"},
            ]
        }
    }
    calls = []

    with pytest.raises(quality.ReportGenerationPreconditionError, match="Canonical source identifier collision"):
        quality.generate_narrative_with_repairs(
            "governed prompt",
            analysis,
            lambda *_args: calls.append(True) or "draft",
        )

    assert calls == []


def test_generation_expands_recognised_opaque_tokens_after_model_response(monkeypatch):
    rag = {
        "source_id": "rag-guide",
        "title": "Official bushfire preparation guide",
    }
    analysis = _analysis_with_source_contract(rag_sources=[rag])
    first_official = analysis["data"]["sources"][0]
    model_response = (
        f"{format_official_citation_token(first_official)}\n"
        f"Households should document and review preparedness arrangements. {format_rag_citation_token(rag)}"
    )
    assessed = []
    monkeypatch.setattr(
        quality,
        "assess_generated_narrative",
        lambda narrative, _analysis: (
            assessed.append(narrative) or {"approval_gate": {"passed": True, "blocking_failures": []}}
        ),
    )

    narrative, _result, attempts = quality.generate_narrative_with_repairs(
        "governed prompt",
        analysis,
        lambda *_args: model_response,
    )

    assert attempts == 1
    assert assessed == [narrative]
    assert format_official_attribution(first_official) in narrative
    assert format_rag_attribution(rag) in narrative
    assert format_official_citation_token(first_official) not in narrative
    assert format_rag_citation_token(rag) not in narrative
