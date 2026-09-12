"""Optional model-visible metadata is strict without rewriting old eval schema."""

import copy

import pytest

from scripts.evaluation_artifacts import ArtifactValidationError, validate_report_evaluation_artifact
from tests.test_evaluation_artifacts import _valid_report_artifact


def _summary(*, captured=True):
    return {
        "schema": "model-visible-rag-summary-v1",
        "status": "not_applicable" if captured else "unavailable",
        "capture_status": "captured" if captured else "unavailable",
        "snapshot_sha256": "a" * 64,
        "request_kind": "initial" if captured else None,
        "attempt_number": 1 if captured else None,
        "sdk_messages_sha256": "b" * 64 if captured else None,
        "normalized_narrative_sha256": "c" * 64 if captured else None,
        "context_sha256": "d" * 64 if captured else None,
        "included_passages": 1 if captured else None,
        "retrieved_passages": 1 if captured else None,
        "metrics": {"rag_cited_claims": 0, "claims_with_visible_lexical_support": 0, "support_rate": None},
        "release_gate_enforced": False,
    }


@pytest.mark.parametrize("captured", [True, False])
def test_optional_versioned_summary_can_be_validated_without_changing_original_gate(captured):
    artifact = _valid_report_artifact()
    original = copy.deepcopy(artifact)
    artifact["rows"][0]["model_visible_rag"] = _summary(captured=captured)
    validate_report_evaluation_artifact(artifact)
    assert artifact["summary"] == original["summary"] and artifact["release_gate"] == original["release_gate"]


def test_historical_artifact_without_summary_is_unchanged():
    artifact = _valid_report_artifact()
    original = copy.deepcopy(artifact)
    validate_report_evaluation_artifact(artifact)
    assert artifact == original


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "unknown"},
        {"private_prompt": "secret"},
        {"capture_status": True},
        {"capture_status": []},
        {"status": []},
        {"request_kind": []},
        {"status": "unavailable"},
        {"snapshot_sha256": "secret"},
        {"attempt_number": True},
        {"attempt_number": 2},
        {"request_kind": "revision"},
        {"sdk_messages_sha256": None},
        {"included_passages": True},
        {"included_passages": 2},
        {"retrieved_passages": 2},
        {"release_gate_enforced": True},
        {"status": "pass"},
    ],
)
def test_rejects_unknown_private_fields_and_mismatched_capture_metadata(change):
    artifact = _valid_report_artifact()
    artifact["rows"][0]["model_visible_rag"] = {**_summary(), **change}
    with pytest.raises(ArtifactValidationError, match="model-visible"):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize(
    "metrics",
    [
        {"rag_cited_claims": True, "claims_with_visible_lexical_support": 0, "support_rate": None},
        {
            "rag_cited_claims": 0,
            "claims_with_visible_lexical_support": 0,
            "support_rate": None,
            "private_text": "secret",
        },
        {"rag_cited_claims": 1, "claims_with_visible_lexical_support": 1, "support_rate": None},
    ],
)
def test_rejects_bad_or_private_nested_metrics(metrics):
    artifact = _valid_report_artifact()
    artifact["rows"][0]["model_visible_rag"] = {**_summary(), "metrics": metrics}
    with pytest.raises(ArtifactValidationError, match="model-visible"):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize("change", [{"attempt_number": 1}, {"included_passages": 0}, {"status": "pass"}])
def test_unavailable_capture_cannot_claim_zero_passages_or_a_successful_request(change):
    artifact = _valid_report_artifact()
    artifact["rows"][0]["model_visible_rag"] = {**_summary(captured=False), **change}
    with pytest.raises(ArtifactValidationError, match="model-visible"):
        validate_report_evaluation_artifact(artifact)


@pytest.mark.parametrize(
    "status,supported,rate,valid",
    [
        ("pass", 2, 1.0, True),
        ("review_required", 1, 0.5, True),
        ("pass", 1, 0.5, False),
        ("review_required", 2, 1.0, False),
        ("review_required", 1, 0.6, False),
        ("pass", 2, True, False),
    ],
)
def test_rate_and_status_are_derived_from_the_visible_claim_counts(status, supported, rate, valid):
    artifact = _valid_report_artifact()
    artifact["rows"][0]["model_visible_rag"] = {
        **_summary(),
        "status": status,
        "metrics": {"rag_cited_claims": 2, "claims_with_visible_lexical_support": supported, "support_rate": rate},
    }
    if valid:
        validate_report_evaluation_artifact(artifact)
    else:
        with pytest.raises(ArtifactValidationError, match="model-visible"):
            validate_report_evaluation_artifact(artifact)
