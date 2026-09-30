import hashlib

import pytest
from streamlit.testing.v1 import AppTest


def test_body_claim_detail_preserves_long_table_claim_and_resolves_only_matching_excerpt():
    long_claim = "Evacuation planning requires local verification " + ("with authorised partners " * 45)
    passage = {
        "source_id": "fire-service-guide",
        "chunk_id": "chunk-7",
        "text": "The submitted official passage says to verify evacuation arrangements with authorised partners.",
    }
    reference = {
        "passage_index": 0,
        "source_id": passage["source_id"],
        "chunk_id": passage["chunk_id"],
        "visible_text_sha256": hashlib.sha256(passage["text"].encode("utf-8")).hexdigest(),
    }
    claim = {
        "claim_id": "long-table-claim",
        "claim": long_claim,
        "section": "Action plan",
        "block_type": "table_cell",
        "span": {"start": 617, "end": 617 + len(long_claim)},
        "table_row": 2,
        "table_column": 3,
        "classification": "external_assertion",
        "citation_required": True,
        "citation_status": "cited",
        "support_status": "lexical_match",
        "reasons": ["human verification required"],
        "source_checks": [
            {
                "source_id": passage["source_id"],
                "source_type": "rag",
                "support_status": "lexical_match",
                "passage_refs": [reference],
            }
        ],
    }
    code = (
        "from src.ui.review_views import _render_body_claim_detail\n"
        f"_render_body_claim_detail({claim!r}, {[passage]!r}, 'captured')"
    )

    app = AppTest.from_string(code).run(timeout=15)

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert long_claim.rstrip() in rendered
    assert "table row 2, column 3" in rendered
    assert "human verification required" in rendered
    assert passage["text"] in "\n".join(item.value for item in app.code)


def test_current_body_claim_review_marks_unavailable_snapshot_unknown_without_mutating_record():
    report = {
        "text": "## Action plan\n\nThe evacuation route reduces fire risk.",
        "analysis": {"knowledge": {"retrieved_chunks": []}, "data": {"sources": []}},
        "grounding_evaluation": {
            "model_visible_rag": {
                "snapshot": {
                    "schema": "model-evidence-v1",
                    "status": "unavailable",
                    "reason": "not_recorded",
                    "attempt_number": None,
                    "request_kind": None,
                }
            }
        },
    }
    app = AppTest.from_string(
        "import copy\nimport streamlit as st\n"
        "from src.ui.review_views import _render_current_body_claim_review\n"
        f"report = {report!r}\n"
        "original = copy.deepcopy(report)\n"
        "_render_current_body_claim_review(report)\n"
        "st.session_state['record_unchanged'] = (report == original)"
    ).run(timeout=15)

    assert not app.exception
    messages = "\n".join(item.value for elements in (app.info, app.caption, app.warning) for item in elements)
    assert "Submitted-passage support is unknown" in messages
    assert "does not reconstruct historical model context" in messages
    assert app.session_state["record_unchanged"] is True
    assert app.checkbox[0].label == "Show claims not requiring citations under this diagnostic"
    assert app.checkbox[0].key == "body_claim_review_show_not_required"


@pytest.mark.parametrize(
    "text,classification",
    [
        ("Unverified proposal for local review: consider additional drinking water.", "uncertain"),
        # Deliberate synthetic counterexample: a prefix does not validate the
        # factual assertion hidden behind it. Preserve the classifier's limits.
        ("Unverified proposal for local review: drinking water prevents heat illness.", "uncertain"),
        ("The user reports having a household emergency kit.", "user_context"),
    ],
)
def test_unverified_claims_still_require_review_without_changing_classification(text, classification):
    app = AppTest.from_string(
        "import copy\nimport streamlit as st\n"
        "from src.report_claim_evidence import evaluate_body_claim_evidence\n"
        "from src.ui.review_views import _render_body_claim_detail\n"
        f"evaluation = evaluate_body_claim_evidence({text!r}, {{}})\n"
        "original = copy.deepcopy(evaluation)\n"
        "claim = evaluation['claims'][0]\n"
        "_render_body_claim_detail(claim, [], 'unavailable')\n"
        "st.session_state['unchanged'] = (evaluation == original)\n"
        "st.session_state['claim'] = claim"
    ).run(timeout=15)

    assert not app.exception
    assert app.session_state["unchanged"] is True
    claim = app.session_state["claim"]
    assert claim["classification"] == classification
    assert claim["citation_status"] == "not_required"
    assert claim["support_status"] == "not_applicable"
    rendered = "\n".join(item.value for item in app.caption)
    assert "does not mean supported, approved, or exempt" in rendered
    if classification == "uncertain":
        assert "factual, medical and safety assertions still need evidence" in app.warning[0].value
        assert "even when this diagnostic marks the citation not_required" in app.warning[0].value
    else:
        assert "User-reported context remains unverified" in rendered


def test_register_metadata_is_not_displayed_as_submitted_claim_evidence():
    # A synthetic register entry exercises display semantics; no actual official
    # source or current fact is asserted by this fixture.
    app = AppTest.from_string(
        "import copy\nimport streamlit as st\n"
        "from src.report_claim_evidence import evaluate_body_claim_evidence\n"
        "from src.source_attribution import format_official_citation_token\n"
        "from src.ui.review_views import _render_body_claim_detail\n"
        "source = {'id': 'synthetic-register', 'name': 'Synthetic register fixture'}\n"
        "text = 'Preparedness actions reduce risk. ' + format_official_citation_token(source)\n"
        "evaluation = evaluate_body_claim_evidence(text, {'data': {'sources': [source]}})\n"
        "original = copy.deepcopy(evaluation)\n"
        "_render_body_claim_detail(evaluation['claims'][0], [], 'unavailable')\n"
        "st.session_state['unchanged'] = (evaluation == original)\n"
        "st.session_state['support'] = evaluation['claims'][0]['support_status']"
    ).run(timeout=15)

    assert not app.exception
    assert app.session_state["unchanged"] is True
    assert app.session_state["support"] == "unknown"
    captions = "\n".join(item.value for item in app.caption)
    assert "register metadata, not a submitted evidence passage" in captions
    assert "citation token does not establish support for this claim" in captions
    assert not app.code


def test_source_applicability_advisory_is_visible_before_the_not_required_checkbox():
    app = AppTest.from_string(
        "from src.ui.review_views import _render_current_body_claim_review\n"
        "report = {'text': 'Unverified proposal for local review: campus group will need support to evacuate.', "
        "'analysis': {'knowledge': {'retrieved_chunks': []}, 'data': {'sources': []}}, "
        "'grounding_evaluation': {'model_visible_rag': {'snapshot': {'schema': 'model-evidence-v1', "
        "'status': 'unavailable', 'reason': 'not_recorded', 'attempt_number': None, 'request_kind': None}}}}\n"
        "_render_current_body_claim_review(report)"
    ).run(timeout=15)

    assert not app.exception
    headings = [item.value for item in app.markdown]
    assert "#### Source applicability advisory" in headings
    assert app.checkbox[0].key == "body_claim_review_show_not_required"
    assert any("local applicability is unassessed and unknown" in item.value for item in app.info)


def test_source_unknown_campus_wording_keeps_the_household_applicability_warning_visible():
    passage = {
        "source_id": "plan",
        "chunk_id": "1",
        "text": (
            "If your household will need support to evacuate, contact the council. "
            "Whether a campus group will need support to evacuate is unknown and requires local verification."
        ),
    }
    claim = {
        "claim_id": "claim-campus",
        "claim": "If your campus group will need support to evacuate, contact the council [O1-RAG][source_id=plan]",
        "source_checks": [
            {
                "source_id": "plan",
                "source_type": "rag",
                "passage_refs": [
                    {
                        "passage_index": 0,
                        "source_id": "plan",
                        "chunk_id": "1",
                        "visible_text_sha256": hashlib.sha256(passage["text"].encode("utf-8")).hexdigest(),
                    }
                ],
            }
        ],
    }
    evaluation = {"claims": [claim]}
    app = AppTest.from_string(
        "from src.ui.review_views import _render_source_applicability_advisory\n"
        f"_render_source_applicability_advisory({evaluation!r}, {[passage]!r}, 'captured')"
    ).run(timeout=15)

    assert not app.exception
    assert any("Confirm local applicability" in item.value for item in app.warning)
    assert any(claim["claim"] in item.value for item in app.markdown)
    assert passage["text"] in "\n".join(item.value for item in app.code)
