import pytest

from src import report_generation_quality as quality
from src.agents.report_quality_agent import ReportQualityAgent
from src.source_attribution import (
    canonicalise_model_source_section,
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
    first_official, second_official = analysis["data"]["sources"]
    model_response = (
        "## 5. Data Sources and Limitations\n"
        f"- {format_official_citation_token(first_official)} (registered official verification source)\n"
        "- [O1][ref=unknown-ref] Unregistered source\n"
        f"- {format_rag_citation_token(rag)}\n"
        "The report remains subject to human review.\n\n"
        "## 6. Local Risk Context\n"
        "Households should document and review preparedness arrangements."
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
    assert f"- {format_official_attribution(first_official)}" in narrative
    assert f"- {format_official_attribution(second_official)}" in narrative
    assert (
        f"- {format_official_attribution(second_official)}\n\n"
        "The application retrieved this static official passage as preparedness-planning evidence for human "
        f"review. {format_rag_attribution(rag)}"
    ) in narrative
    assert "registered official verification source" not in narrative
    assert "unknown-ref" not in narrative
    assert "Unregistered source" not in narrative
    assert format_official_citation_token(first_official) not in narrative
    assert format_rag_citation_token(rag) not in narrative


def test_source_section_canonicalisation_does_not_synthesise_a_missing_heading():
    analysis = _analysis_with_source_contract(
        rag_sources=[{"source_id": "rag-guide", "title": "Official preparation guide"}]
    )
    response = "## 1. Title\nDraft report without the required source section."

    assert (
        canonicalise_model_source_section(
            response,
            official_sources=analysis["data"]["sources"],
            rag_sources=analysis["knowledge"]["retrieved_chunks"],
        )
        == response
    )


@pytest.mark.parametrize(
    "duplicate_heading",
    [
        "## 5. Data Sources and Limitations",
        "## Data  Sources and Limitations",
        "## Data Sources and Limitations ##",
    ],
)
def test_source_section_canonicalisation_leaves_duplicate_headings_for_structural_review(duplicate_heading):
    analysis = _analysis_with_source_contract()
    response = f"## 5. Data Sources and Limitations\nFirst section.\n\n{duplicate_heading}\nDuplicate section."

    assert (
        canonicalise_model_source_section(
            response,
            official_sources=analysis["data"]["sources"],
        )
        == response
    )

    complete_sections = []
    for heading in ReportQualityAgent.REQUIRED_SECTION_HEADINGS:
        complete_sections.extend(
            [
                f"## {heading}",
                "This section contains enough distinct words for governed structural validation and review.",
            ]
        )
        if heading == "Data Sources and Limitations":
            complete_sections.extend(
                [
                    f"## {heading}",
                    "This duplicate section also contains enough distinct words for structural validation.",
                ]
            )

    result = ReportQualityAgent()._check_sections("\n".join(complete_sections))

    assert result["status"] == "fail"
    assert "duplicated: Data Sources and Limitations" in result["detail"]


@pytest.mark.parametrize(
    "html_payload",
    [
        "<div hidden>[O1][ref=unknown]</div>",
        "&lt;div hidden&gt;[O1][ref=unknown]&lt;/div&gt;",
        "<!-- [O1][ref=unknown] -->",
        "<![CDATA[\n[O1][ref=unknown]\n]]>",
        "&lt;![CDATA[\n[O1][ref=unknown]\n]]&gt;",
    ],
)
def test_source_section_canonicalisation_keeps_raw_html_fail_closed(html_payload):
    analysis = _analysis_with_source_contract()
    response = f"## 5. Data Sources and Limitations\n{html_payload}"

    assert (
        canonicalise_model_source_section(
            response,
            official_sources=analysis["data"]["sources"],
        )
        == response
    )


def test_source_section_canonicalisation_ignores_a_fenced_heading():
    analysis = _analysis_with_source_contract()
    response = (
        "```markdown\n## 5. Data Sources and Limitations\n[O1][ref=fenced]\n```\n\n"
        "## 5. Data Sources and Limitations\nVisible limitations remain."
    )

    canonicalised = canonicalise_model_source_section(
        response,
        official_sources=analysis["data"]["sources"],
    )

    assert "[O1][ref=fenced]" in canonicalised
    assert canonicalised.count(format_official_citation_token(analysis["data"]["sources"][0])) == 1
    assert "Visible limitations remain." in canonicalised
    assert ReportQualityAgent()._required_heading_counts(response)["data sources and limitations"] == 1


def test_source_section_canonicalisation_preserves_unsafe_or_url_prose_for_quality_gates():
    analysis = _analysis_with_source_contract()
    response = (
        "## 5. Data Sources and Limitations\n"
        f"Smith Road is open. {format_official_citation_token(analysis['data']['sources'][0])} "
        "https://attacker.example/source"
    )

    canonicalised = canonicalise_model_source_section(
        response,
        official_sources=analysis["data"]["sources"],
    )

    assert "Smith Road is open." in canonicalised
    assert "https://attacker.example/source" in canonicalised

    _narrative, assessment, attempts = quality.generate_narrative_with_repairs(
        "governed prompt",
        analysis,
        lambda *_args: response,
        max_repair_attempts=0,
    )
    blocking_names = {item["name"] for item in assessment["approval_gate"]["blocking_failures"]}

    assert attempts == 1
    assert "Safety boundary assertions" in blocking_names
    assert "Model-authored URLs" in blocking_names


def test_source_section_canonicalisation_is_idempotent_before_token_expansion():
    rag = {"source_id": "rag-guide", "title": "Official preparation guide"}
    analysis = _analysis_with_source_contract(rag_sources=[rag])
    response = "## 5. Data Sources and Limitations\nModel-authored limitations remain."

    first = canonicalise_model_source_section(
        response,
        official_sources=analysis["data"]["sources"],
        rag_sources=analysis["knowledge"]["retrieved_chunks"],
    )
    second = canonicalise_model_source_section(
        first,
        official_sources=analysis["data"]["sources"],
        rag_sources=analysis["knowledge"]["retrieved_chunks"],
    )

    assert second == first


@pytest.mark.parametrize(
    "unbound_marker",
    [
        "[\u039f1][ref=evil]",
        "[O1\u2011RAG][ref=evil]",
        "[O1][source\u2011id=evil]",
    ],
)
def test_visually_confusable_unbound_attribution_markers_fail_closed(unbound_marker):
    analysis = _analysis_with_source_contract()
    response = f"## 5. Data Sources and Limitations\n{unbound_marker}"

    narrative, assessment, attempts = quality.generate_narrative_with_repairs(
        "governed prompt",
        analysis,
        lambda *_args: response,
        max_repair_attempts=0,
    )
    marker_check = next(item for item in assessment["checks"] if item["name"] == "Unverified attribution markers")

    assert attempts == 1
    assert unbound_marker in narrative
    assert marker_check["status"] == "fail"
    assert assessment["approval_gate"]["passed"] is False


def test_application_source_bindings_do_not_make_an_empty_model_section_substantive():
    rag = {"source_id": "rag-guide", "title": "Official preparation guide"}
    analysis = _analysis_with_source_contract(rag_sources=[rag])
    model_lines = ["# 1. Title", "Governed preparedness planning report."]
    for heading in ReportQualityAgent.REQUIRED_SECTION_HEADINGS:
        model_lines.append(f"## {heading}")
        if heading != "Data Sources and Limitations":
            model_lines.append(
                "This model-authored section contains distinct substantive planning words for responsible human review."
            )
    model_response = "\n".join(model_lines)

    _narrative, assessment, attempts = quality.generate_narrative_with_repairs(
        "governed prompt",
        analysis,
        lambda *_args: model_response,
        max_repair_attempts=0,
    )
    checks = {item["name"]: item for item in assessment["checks"]}

    assert attempts == 1
    assert checks["Official sources"]["status"] == "pass"
    assert checks["RAG source attribution"]["status"] == "pass"
    assert checks["Required sections"]["status"] == "fail"
    assert "Data Sources and Limitations" in checks["Required sections"]["detail"]
