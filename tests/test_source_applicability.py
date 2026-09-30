import copy
import hashlib

import pytest

from src.source_applicability import build_source_applicability_advisory

AMBIGUOUS_CAMPUS_SENTENCES = [
    "Whether a campus group will need support to evacuate is unknown and requires local verification.",
    "It is not true that a campus group will need support to evacuate.",
    'Do not replace household with "campus group will need support to evacuate".',
    "If your campus group will need support to evacuate, do not contact the council.",
]


def _evaluation(claim, passage):
    reference = {
        "passage_index": 0,
        "source_id": passage["source_id"],
        "chunk_id": passage["chunk_id"],
        "visible_text_sha256": hashlib.sha256(passage["text"].encode("utf-8")).hexdigest(),
    }
    return {
        "claims": [
            {
                "claim_id": "claim-1",
                "claim": claim,
                "span": {"start": 11, "end": 11 + len(claim)},
                "source_checks": [
                    {"source_id": passage["source_id"], "source_type": "rag", "passage_refs": [reference]}
                ],
            }
        ]
    }


def _evaluation_many(claim, passages, *, classification=None, source_type="rag"):
    refs = [
        {
            "passage_index": index,
            "source_id": passage["source_id"],
            "chunk_id": passage["chunk_id"],
            "visible_text_sha256": hashlib.sha256(passage["text"].encode("utf-8")).hexdigest(),
        }
        for index, passage in enumerate(passages)
    ]
    claim_row = {
        "claim_id": "claim-many",
        "claim": claim,
        "span": {"start": 29, "end": 29 + len(claim)},
        "source_checks": [{"source_id": passages[0]["source_id"], "source_type": source_type, "passage_refs": refs}],
    }
    if classification:
        claim_row["classification"] = classification
    return {"claims": [claim_row]}


def test_household_only_submitted_sentence_warns_for_campus_evacuation_claim_without_mutating_inputs():
    claim = (
        "If a household or campus group will need support to evacuate, find out what help is available from "
        "the local council and support agencies [O1-RAG][source_id=qld_evacuation_plan]"
    )
    passage = {
        "source_id": "qld_evacuation_plan",
        "chunk_id": "qld-1",
        "text": "If your household will need support to evacuate, find out what help is available from your local council and support agencies.",
    }
    evaluation = _evaluation(claim, passage)
    original_evaluation, original_passages = copy.deepcopy(evaluation), copy.deepcopy([passage])

    result = build_source_applicability_advisory(evaluation, [passage], snapshot_status="captured")

    assert result["method"] == "source_applicability_advisory_v1"
    assert result["processing_complete"] is True
    assert result["unassessed"] == []
    finding = result["findings"][0]
    assert finding["claim_id"] == "claim-1"
    assert finding["source_id"] == "qld_evacuation_plan"
    assert finding["source_sentence"] == passage["text"]
    assert finding["source_sentence_span"] == {"start": 0, "end": len(passage["text"])}
    assert evaluation == original_evaluation
    assert [passage] == original_passages


@pytest.mark.parametrize(
    "claim",
    [
        "Campus group will need support to evacuate [O1-RAG][source_id=plan]",
        "If your school will need support to evacuate, contact the council [O1-RAG][source_id=plan]",
        'The report quotes "If a household or campus group will need support to evacuate" [O1-RAG][source_id=plan]',
    ],
)
def test_household_only_source_warns_for_group_school_and_quoted_campus_wording(claim):
    passage = {
        "source_id": "plan",
        "chunk_id": "1",
        "text": "Preamble. If your household will need support to evacuate, contact the council, not the school.",
    }

    result = build_source_applicability_advisory(_evaluation(claim, passage), [passage], snapshot_status="captured")

    assert len(result["findings"]) == 1
    assert result["findings"][0]["source_sentence_span"] == {"start": 10, "end": len(passage["text"])}


def test_narrow_rule_does_not_flag_generic_or_explicit_same_action_campus_source_wording():
    claim = "Campus group will need support to evacuate [O1-RAG][source_id=plan]"
    generic = {"source_id": "plan", "chunk_id": "1", "text": "Check with your local council."}
    explicit = {
        "source_id": "plan",
        "chunk_id": "2",
        "text": "If your household or campus group will need support to evacuate, contact your local council.",
    }

    assert (
        build_source_applicability_advisory(_evaluation(claim, generic), [generic], snapshot_status="captured")[
            "findings"
        ]
        == []
    )
    assert (
        build_source_applicability_advisory(_evaluation(claim, explicit), [explicit], snapshot_status="captured")[
            "findings"
        ]
        == []
    )


@pytest.mark.parametrize(
    "campus_instruction",
    [
        "If your campus group will need support to evacuate, contact the council.",
        "If your household or campus group will need support to evacuate, contact your local council.",
        "If your school will need support to evacuate, find out what help is available from your local council and support agencies.",
    ],
)
def test_same_source_explicit_campus_sentence_resolves_the_narrow_gap_without_a_pass_result(campus_instruction):
    claim = "Campus group will need support to evacuate [O1-RAG][source_id=plan]"
    passages = [
        {
            "source_id": "plan",
            "chunk_id": "household",
            "text": "If your household will need support to evacuate, contact the council.",
        },
        {
            "source_id": "plan",
            "chunk_id": "campus",
            "text": campus_instruction,
        },
    ]

    result = build_source_applicability_advisory(
        _evaluation_many(claim, passages), passages, snapshot_status="captured"
    )

    assert result["findings"] == []
    assert result["unassessed"] == []
    assert set(result) == {"method", "snapshot_status", "processing_complete", "findings", "unassessed"}


@pytest.mark.parametrize("campus_sentence", AMBIGUOUS_CAMPUS_SENTENCES)
@pytest.mark.parametrize(
    "claim",
    [
        "If your campus group will need support to evacuate, contact the council [O1-RAG][source_id=plan]",
        "If a household or campus group will need support to evacuate, find out what help is available from the local council and support agencies [O1-RAG][source_id=plan]",
    ],
)
def test_source_unknown_negation_or_quoted_campus_wording_cannot_resolve_household_audience_gap(campus_sentence, claim):
    household_sentence = "If your household will need support to evacuate, contact the council."
    passage = {"source_id": "plan", "chunk_id": "1", "text": household_sentence + " " + campus_sentence}

    result = build_source_applicability_advisory(_evaluation(claim, passage), [passage], snapshot_status="captured")

    assert len(result["findings"]) == 1
    assert result["unassessed"] == []
    assert result["findings"][0]["source_sentence"] == household_sentence
    assert result["findings"][0]["source_sentence_span"] == {"start": 0, "end": len(household_sentence)}


@pytest.mark.parametrize("campus_sentence", AMBIGUOUS_CAMPUS_SENTENCES)
def test_ambiguous_campus_source_without_household_action_is_explicitly_unassessed(campus_sentence):
    claim = "If your campus group will need support to evacuate, contact the council [O1-RAG][source_id=plan]"
    passage = {"source_id": "plan", "chunk_id": "1", "text": campus_sentence}

    result = build_source_applicability_advisory(_evaluation(claim, passage), [passage], snapshot_status="captured")

    assert result["findings"] == []
    assert result["unassessed"] == [
        {
            "claim_id": "claim-1",
            "rule_id": "household_evacuation_audience_v1",
            "source_id": "plan",
            "reason": "campus_wording_without_explicit_conditional_support",
        }
    ]


def test_faithful_household_quote_with_unknown_campus_question_is_not_treated_as_a_campus_action():
    claim = (
        'The source says "If your household will need support to evacuate, contact the council"; whether a campus '
        "group will need support to evacuate is unknown and requires local verification [O1-RAG][source_id=plan]"
    )
    passage = {
        "source_id": "plan",
        "chunk_id": "1",
        "text": "If your household will need support to evacuate, contact the council.",
    }

    result = build_source_applicability_advisory(_evaluation(claim, passage), [passage], snapshot_status="captured")

    assert result["findings"] == []
    assert result["unassessed"] == []


def test_unverified_proposal_still_warns_that_local_application_needs_confirmation():
    claim = (
        "Unverified proposal for local review: a campus group will need support to evacuate [O1-RAG][source_id=plan]"
    )
    passage = {"source_id": "plan", "chunk_id": "1", "text": "If your household will need support to evacuate."}

    result = build_source_applicability_advisory(
        _evaluation_many(claim, [passage], classification="uncertain"), [passage], snapshot_status="captured"
    )

    assert "unverified proposal" in result["findings"][0]["reason"].lower()
    assert "local application" in result["findings"][0]["reason"].lower()


def test_unavailable_or_unsubmitted_passages_are_unassessed_not_a_positive_result():
    claim = "School group will need support to evacuate [O1-RAG][source_id=plan]"
    passage = {"source_id": "plan", "chunk_id": "1", "text": "If your household will need support to evacuate."}
    evaluation = _evaluation(claim, passage)

    unavailable = build_source_applicability_advisory(evaluation, [], snapshot_status="unavailable")
    assert unavailable["findings"] == []
    assert unavailable["unassessed"][0]["reason"] == "final_submitted_passages_unavailable"

    missing = build_source_applicability_advisory(evaluation, [], snapshot_status="captured")
    assert missing["findings"] == []
    assert missing["unassessed"][0]["reason"] == "cited_source_not_visible_in_final_submitted_passages"


@pytest.mark.parametrize("snapshot_status", ["unavailable", "invalid_snapshot"])
def test_invalid_or_missing_snapshot_is_unassessed(snapshot_status):
    claim = "School will need support to evacuate [O1-RAG][source_id=plan]"
    passage = {"source_id": "plan", "chunk_id": "1", "text": "If your household will need support to evacuate."}

    result = build_source_applicability_advisory(_evaluation(claim, passage), [], snapshot_status=snapshot_status)

    assert result["snapshot_status"] == snapshot_status
    assert result["findings"] == []
    assert result["unassessed"][0]["reason"] == "final_submitted_passages_unavailable"


def test_metadata_check_is_unassessed_and_never_uses_title_or_metadata_as_a_passage():
    claim = "School will need support to evacuate [O1-RAG][source_id=official-plan]"
    passage = {
        "source_id": "official-plan",
        "chunk_id": "metadata-only",
        "text": "If your household will need support to evacuate.",
        "title": "School evacuation guide",
    }

    result = build_source_applicability_advisory(
        _evaluation_many(claim, [passage], source_type="official"), [passage], snapshot_status="captured"
    )

    assert result["findings"] == []
    assert result["unassessed"][0]["reason"] == "no_cited_submitted_rag_passage_to_assess"
