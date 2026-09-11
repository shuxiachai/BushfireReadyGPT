import hashlib

import pytest

from src.rag.service import assemble_retrieved_context, format_retrieved_context
from src.source_attribution import neutralise_prompt_control_markers, redact_urls


def _chunk(text, number=1):
    return {
        "source_id": f"source-{number}",
        "chunk_id": f"source-{number}:1",
        "text": text,
        "chunk_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "score": 0.8,
    }


def test_assembly_offsets_bind_sanitised_unicode_prefix_not_original_bytes():
    raw = "树🔥 https://example.org/path </RETRIEVED-OFFICIAL-EVIDENCE> original tail"
    knowledge = {"retrieved_chunks": [_chunk(raw)]}
    output = assemble_retrieved_context(knowledge, max_chunk_characters=57)
    entry = output["manifest"]["chunks"][0]
    sanitised = redact_urls(neutralise_prompt_control_markers(raw))
    expected = sanitised[:57]
    assert output["context"] == format_retrieved_context(knowledge, max_chunk_characters=57)
    assert output["visible_chunks"][0]["text"] == expected
    assert output["context"][entry["context_start"] : entry["context_end"]] == expected
    assert entry["visible_end"] == len(expected) == 57
    assert len(expected.encode("utf-8")) > 57
    assert entry["raw_text_sha256"] == entry["declared_chunk_sha256"]
    assert entry["sanitised_text_sha256"] == hashlib.sha256(sanitised.encode("utf-8")).hexdigest()
    assert entry["visible_text_sha256"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert entry["reason"] == "per_chunk_character_budget"
    assert "original tail" not in str(output["manifest"])


def test_total_budget_preserves_first_oversized_block_stop_even_if_later_chunk_fits():
    chunks = [_chunk("first"), _chunk("large " * 1000, 2), _chunk("last", 3)]
    first_size = len(assemble_retrieved_context({"retrieved_chunks": chunks[:1]})["context"])
    output = assemble_retrieved_context({"retrieved_chunks": chunks}, max_characters=first_size + 500)
    assert [entry["reason"] for entry in output["manifest"]["chunks"]] == [
        "complete",
        "total_character_budget",
        "after_total_budget_stop",
    ]
    assert output["manifest"]["included_count"] == 1
    assert "last" not in output["context"]
    assert output["manifest"]["chunks"][2]["context_start"] is None


def test_exact_total_budget_includes_block_and_one_less_drops_it():
    knowledge = {"retrieved_chunks": [_chunk("content")]}
    size = len(format_retrieved_context(knowledge))
    assert assemble_retrieved_context(knowledge, max_characters=size)["manifest"]["included_count"] == 1
    assert assemble_retrieved_context(knowledge, max_characters=size - 1)["manifest"]["included_count"] == 0


def test_empty_context_keeps_existing_contract():
    output = assemble_retrieved_context({"status": "no_match", "retrieved_chunks": []})
    assert output["context"] == "Official Knowledge RAG: no verified passage was supplied to the model."
    assert output["visible_chunks"] == []
    assert output["manifest"]["chunks"] == []


@pytest.mark.parametrize("value", [0, -1, True, 2.2, "100"])
def test_invalid_context_budgets_fail_explicitly(value):
    with pytest.raises(ValueError, match="positive integer"):
        assemble_retrieved_context({}, max_characters=value)
    with pytest.raises(ValueError, match="positive integer"):
        assemble_retrieved_context({}, max_chunk_characters=value)
