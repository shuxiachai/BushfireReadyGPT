import hashlib

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
