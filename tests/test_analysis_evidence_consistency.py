"""Independent regressions for evidence loss at data and chunk boundaries."""

import hashlib

import pytest

from src.agents.community_vulnerability_agent import CommunityVulnerabilityAgent
from src.rag.corpus import chunk_catalog_sources


def _community_row(**values):
    return {
        "risk_notes": "Synthetic community context.",
        "older_people_pct": "20",
        "no_car_households_pct": "12",
        "language_support_needed": "low",
        **values,
    }


@pytest.mark.parametrize("missing", ["", None, "unknown", "nan", "inf", "-1", "101"])
def test_missing_transport_does_not_suppress_valid_age_evidence(missing):
    notes = CommunityVulnerabilityAgent()._build_notes(_community_row(no_car_households_pct=missing))

    assert any(note.startswith("Older residents should") for note in notes)
    assert not any(note.startswith("Transport support and alternative") for note in notes)
    assert any(note.startswith("Transport vulnerability is not available") for note in notes)


@pytest.mark.parametrize("missing", ["", None, "unknown", "nan", "inf", "-1", "101"])
def test_missing_age_does_not_suppress_valid_transport_evidence(missing):
    notes = CommunityVulnerabilityAgent()._build_notes(_community_row(older_people_pct=missing))

    assert any(note.startswith("Transport support and alternative") for note in notes)
    assert not any(note.startswith("Older residents should") for note in notes)
    assert not any(note.startswith("Transport vulnerability is not available") for note in notes)


def test_zero_indicators_remain_known_not_missing():
    notes = CommunityVulnerabilityAgent()._build_notes(_community_row(older_people_pct="0", no_car_households_pct=0))

    assert notes == ["Synthetic community context."]


def _synthetic_source(tmp_path, paragraphs):
    path = tmp_path / "synthetic.txt"
    path.write_text("\n\n".join(paragraphs), encoding="utf-8")
    return {
        "source_id": "synthetic_test",
        "resolved_path": path,
        "format": "text",
        "title": "Synthetic test text",
        "agency": "Test author",
        "url": "https://example.invalid/synthetic",
        "document_date": "2026-09-10",
        "licence": "Test fixture",
        "licence_url": "https://example.invalid/terms",
        "reuse_status": "test_only",
        "last_verified_date": "2026-09-10",
        "jurisdictions": ["Queensland"],
        "audiences": ["community"],
        "scenarios": ["preparedness"],
    }


@pytest.mark.parametrize("paragraph_sizes", [[130], [20, 50, 30, 100], [50, 50], [49, 1, 51]])
@pytest.mark.parametrize("overlap", [0, 10, 49])
def test_chunk_limits_overlap_and_all_source_words_are_preserved(tmp_path, paragraph_sizes, overlap):
    words = [f"token{number}" for number in range(sum(paragraph_sizes))]
    paragraphs = []
    offset = 0
    for size in paragraph_sizes:
        paragraphs.append(" ".join(words[offset : offset + size]))
        offset += size
    source = _synthetic_source(tmp_path, paragraphs)

    chunks = chunk_catalog_sources([source], max_words=50, overlap_words=overlap)

    assert chunks == chunk_catalog_sources([source], max_words=50, overlap_words=overlap)
    assert all(0 < len(chunk["text"].split()) <= 50 for chunk in chunks)
    reconstructed = chunks[0]["text"].split()
    for previous, chunk in zip(chunks, chunks[1:]):
        chunk_words = chunk["text"].split()
        carried = min(overlap, len(previous["text"].split()))
        if carried:
            assert chunk_words[:carried] == previous["text"].split()[-carried:]
        assert len(chunk_words) > carried, "A chunk must add evidence, not only repeat overlap."
        reconstructed.extend(chunk_words[carried:])
    assert reconstructed == words
    assert [chunk["chunk_number"] for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk["page"] is None for chunk in chunks)
    for chunk in chunks:
        assert chunk["chunk_sha256"] == hashlib.sha256(chunk["text"].encode()).hexdigest()


def test_chunk_overlap_never_crosses_source_boundaries(tmp_path):
    first = _synthetic_source(tmp_path, [" ".join(f"first{number}" for number in range(80))])
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = _synthetic_source(second_dir, [" ".join(f"second{number}" for number in range(80))])
    second["source_id"] = "synthetic_second"

    chunks = chunk_catalog_sources([first, second], max_words=50, overlap_words=10)

    for chunk in chunks:
        prefix = "first" if chunk["source_id"] == "synthetic_test" else "second"
        assert all(word.startswith(prefix) for word in chunk["text"].split())
