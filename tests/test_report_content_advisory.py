"""Synthetic tests for the detached literal-only content advisory."""

import ast
import copy
from pathlib import Path

import pytest

from scripts import report_content_advisory as advisory
from src.model_evidence import json_sha256, text_sha256
from src.source_attribution import format_rag_citation_token


def _pack(text, source_id="guide"):
    passage = {
        "passage_ref": "passage-001",
        "source_id": source_id,
        "chunk_id": "chunk-1",
        "retrieved_rank": 1,
        "text": text,
        "text_sha256": text_sha256(text),
    }
    pack = {
        "schema": "atomic-claim-evidence-pack-v1",
        "origin": "recorded_assembly_visible_text",
        "length_unit": "python_unicode_codepoints",
        "assembly_sha256": "a" * 64,
        "passages": [passage],
    }
    pack["evidence_pack_sha256"] = json_sha256(pack)
    return pack


def _analysis():
    return {"knowledge": {"retrieved_chunks": [{"source_id": "guide", "title": "Guide"}]}, "data": {"sources": []}}


def _span(text, piece):
    start = text.index(piece)
    return {"start": start, "end": start + len(piece)}


def _case(report=None, source=None):
    source = "Northbank students recorded 27 paper maps." if source is None else source
    report = "Northbank students recorded 27 paper maps. [O1-RAG][source_id=guide] Guide" if report is None else report
    target = {
        "id": "fact1",
        "passage_ref": "passage-001",
        "source_span": _span(source, source),
        "source_text": source,
        "report_span": _span(report, report),
        "report_text": report,
        "probes": ["Northbank", "27", "paper maps"],
    }
    return report, _analysis(), _pack(source), [target], []


def _review(*args):
    report, analysis, pack, facts, actions = _case(*args)
    return advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)


def test_catalogue_fact_and_citation_are_literal_observations_only():
    result = _review()
    fact = result["fact_observations"][0]
    unit = fact["unit_observations"][0]
    assert fact["co_occurrence"] == unit["co_occurrence"] == unit["citation_binding"] == "observed"
    assert fact["units_scanned"] == result["units_scanned"] == 1
    assert fact["expected_citation"] == {"source_type": "rag", "source_id": "guide"}
    assert result["semantics"] == result["conditions"] == "unknown"
    assert result["manual_review"] and not result["production"] and result["additional_model_calls"] == 0
    assert result["semantic_accuracy"] is None


def test_empty_report_retains_predeclared_target_as_not_observed():
    source = "Northbank students recorded 27 paper maps."
    target = {
        "id": "empty",
        "passage_ref": "passage-001",
        "source_span": _span(source, source),
        "source_text": source,
        "report_span": {"start": 0, "end": 0},
        "report_text": "",
        "probes": ["27"],
    }
    result = advisory.review_report_content("", _analysis(), _pack(source), fact_targets=[target], local_actions=[])
    fact = result["fact_observations"][0]
    assert fact["unit_observations"] == [] and fact["co_occurrence"] == "not_observed" and fact["units_scanned"] == 0


def test_probe_token_boundaries_are_exact_unicode_and_case_sensitive():
    report = "Northbank students recorded S27 and 270 paper maps."
    source = "Northbank students recorded 27 paper maps."
    report, analysis, pack, facts, actions = _case(report, source)
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    assert result["fact_observations"][0]["unit_observations"][0]["probe_observations"][1]["positions"] == []


@pytest.mark.parametrize(
    "report,target_text",
    [
        (
            "Northbank students recorded paper maps. [O1-RAG][source_id=guide] Guide",
            "Northbank students recorded paper maps. [O1-RAG][source_id=guide] Guide",
        ),
        (
            "Northbank students recorded 27 digital maps. [O1-RAG][source_id=guide] Guide",
            "Northbank students recorded 27 digital maps. [O1-RAG][source_id=guide] Guide",
        ),
        (
            "Northbank students recorded paper maps.\nOther students recorded 27 paper maps.",
            "Northbank students recorded paper maps.",
        ),
        (
            "Action | Other\n--- | ---\nNorthbank students recorded paper maps. | 27 paper maps.",
            "Northbank students recorded paper maps.",
        ),
    ],
)
def test_deleted_or_moved_literal_probe_is_not_observed(report, target_text):
    source = "Northbank students recorded 27 paper maps."
    report, analysis, pack, facts, actions = _case(report, source)
    facts[0]["report_text"] = target_text
    facts[0]["report_span"] = _span(report, target_text)
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    assert result["fact_observations"][0]["co_occurrence"] == "not_observed"


@pytest.mark.parametrize(
    "report",
    [
        "Northbank students recorded <!-- 27 --> paper maps.",
        "Northbank students recorded <span hidden>27</span> paper maps.",
        "Northbank students recorded paper maps.\n# 27 title",
        "Northbank students recorded paper maps.\n```\n27\n```",
        "Northbank students recorded paper maps.\n## Evidence Tables\n27",
    ],
)
def test_hidden_metadata_titles_fences_and_appendices_never_supply_probe(report):
    result = _review(report)
    assert result["fact_observations"][0]["co_occurrence"] == "not_observed"


def test_local_action_prefix_is_own_unit_and_short_group_is_compared():
    first = "Unverified proposal for local review: Do not act unless approved."
    second = "Unverified proposal for local review: Act."
    report = first + "\n" + second
    actions = [
        {"id": "a", "unit_span": _span(report, first), "unit_text": first, "group_id": "g"},
        {"id": "b", "unit_span": _span(report, second), "unit_text": second, "group_id": "g"},
    ]
    result = advisory.review_report_content(
        report, _analysis(), _pack("source"), fact_targets=[], local_actions=actions
    )
    assert all(item["prefix_observation"] == "observed" for item in result["local_action_observations"])
    review = result["same_group_marker_reviews"][0]["marker_reviews"][0]
    assert "unless" in review["marker_difference"]["condition"]["proposal_only"]


def test_fact_and_task_in_one_cited_unit_only_create_a_review_clue():
    source = "Unverified proposal for local review: Northbank students recorded 27 paper maps."
    report = source + " [O1-RAG][source_id=guide] Guide"
    report, analysis, pack, facts, _ = _case(report, source)
    actions = [{"id": "action", "unit_span": _span(report, report), "unit_text": report, "group_id": None}]
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    assert result["mixed_unit_review_clues"] == [
        {
            "fact_target_id": "fact1",
            "local_action_id": "action",
            "unit_span": _span(report, report),
            "citation_binding": "observed",
            "citation_visibility": "observed",
            "finding": "possible_mixed_fact_action_unit",
            "semantics": "unknown",
            "review_required": True,
        }
    ]


def test_action_does_not_borrow_prefix_from_neighbouring_unit():
    first = "Unverified proposal for local review: Prepare supplies."
    second = "Prepare water."
    report = first + "\n" + second
    actions = [{"id": "a", "unit_span": _span(report, second), "unit_text": second, "group_id": None}]
    result = advisory.review_report_content(
        report, _analysis(), _pack("source"), fact_targets=[], local_actions=actions
    )
    assert result["local_action_observations"][0]["prefix_observation"] == "not_observed"


@pytest.mark.parametrize(
    "report",
    [
        "Prepare water and review local contacts.",
        "# Northbank students recorded 27 paper maps.",
        "<!-- Northbank students recorded 27 paper maps. -->",
        "```\nNorthbank students recorded 27 paper maps.\n```",
        "## Evidence Tables\nNorthbank students recorded 27 paper maps.",
    ],
)
def test_nonempty_report_keeps_entirely_deleted_fact_target(report):
    result = _review(report)
    assert len(result["fact_observations"]) == 1
    assert result["fact_observations"][0]["co_occurrence"] == "not_observed"
    assert result["semantics"] == "unknown"


def test_whole_report_search_over_480_characters_preserves_each_unit():
    report = "Review local contacts.\n" * 30 + "Northbank students recorded 27 paper maps."
    assert len(report) > 480
    result = _review(report)
    fact = result["fact_observations"][0]
    assert fact["co_occurrence"] == "observed"
    assert fact["units_scanned"] == 31
    assert [item["co_occurrence"] for item in fact["unit_observations"]] == ["not_observed"] * 30 + ["observed"]


@pytest.mark.parametrize(
    "report",
    [
        "Northbank students recorded paper maps. Other students recorded 27 paper maps.",
        "First | Second\n--- | ---\nNorthbank students recorded paper maps. | Students recorded 27 paper maps.",
    ],
)
def test_full_report_never_combines_probes_across_sentences_or_cells(report):
    fact = _review(report)["fact_observations"][0]
    assert fact["units_scanned"] == 2
    assert fact["co_occurrence"] == "not_observed"
    assert all(unit["co_occurrence"] == "not_observed" for unit in fact["unit_observations"])


@pytest.mark.parametrize("piece", ["Northbank students", "", "students recorded 27 paper maps."])
def test_fact_range_rejects_partial_unit_and_empty_window_in_nonempty_report(piece):
    report, analysis, pack, facts, actions = _case("Northbank students recorded 27 paper maps.")
    facts[0]["report_text"] = piece
    facts[0]["report_span"] = _span(report, piece)
    with pytest.raises(advisory.ContentAdvisoryError):
        advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)


@pytest.mark.parametrize(
    "report",
    [
        '<span data-count="27">Northbank students recorded paper maps</span>.',
        '<span data-count=">27">Northbank students recorded paper maps</span>.',
        '<span title="notes. 27">Northbank students recorded paper maps</span>.',
        "Northbank students recorded paper maps [details](https://example.test/27).",
        'Northbank students recorded paper maps [details](https://example.test/path "27").',
        "Northbank students recorded paper maps [details](https://example.test/path_(27)).",
        "Northbank students recorded paper maps [details][27].",
    ],
)
def test_html_attributes_and_link_metadata_cannot_supply_fact_probe(report):
    fact = _review(report)["fact_observations"][0]
    assert fact["co_occurrence"] == "not_observed"
    assert all(item["probe_observations"][1]["positions"] == [] for item in fact["unit_observations"])


def test_link_label_is_visible_and_positions_retain_original_offsets():
    report = "Northbank students recorded [27 paper maps](https://example.test/details)."
    observation = _review(report)["fact_observations"][0]["unit_observations"][0]
    assert observation["co_occurrence"] == "observed"
    assert observation["probe_observations"][1]["positions"] == [report.index("27")]


@pytest.mark.parametrize(
    "title",
    ['"notes) 27"', "'notes) 27'", '"notes( 27"', '"notes. 27"', r'"notes\") 27"'],
)
def test_quoted_link_title_delimiters_cannot_supply_fact_probe(title):
    report = f"Northbank students recorded paper maps [details](https://example.test/a {title})."
    fact = _review(report)["fact_observations"][0]
    assert fact["co_occurrence"] == "not_observed"
    assert all(unit["probe_observations"][1]["positions"] == [] for unit in fact["unit_observations"])


@pytest.mark.parametrize("quote", ['"', "'"])
def test_quoted_link_title_preserves_label_and_following_body_offsets(quote):
    report = f"Northbank students recorded [27 paper maps](https://example.test/a {quote}notes) 80{quote}) today."
    observation = _review(report)["fact_observations"][0]["unit_observations"][0]
    assert observation["co_occurrence"] == "observed"
    assert observation["probe_observations"][1]["positions"] == [report.index("27")]
    shadow, unsupported = advisory._metadata_shadow(report)
    assert unsupported == [] and len(shadow) == len(report)
    assert shadow[report.index("today") :] == "today."


@pytest.mark.parametrize("quote", ['"', "'"])
def test_citation_and_action_markers_inside_quoted_link_title_remain_metadata(quote):
    citation = format_rag_citation_token(_analysis()["knowledge"]["retrieved_chunks"][0])
    title = f"{quote}notes) {citation} only adults unless approved{quote}"
    first = (
        "Unverified proposal for local review: Northbank students recorded 27 paper maps "
        f"[details](https://example.test/a {title})."
    )
    second = "Unverified proposal for local review: Prepare water."
    report, analysis, pack, facts, _ = _case(first + "\n" + second)
    actions = [
        {"id": "a", "unit_span": _span(report, first), "unit_text": first, "group_id": "g"},
        {"id": "b", "unit_span": _span(report, second), "unit_text": second, "group_id": "g"},
    ]
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    observation = result["fact_observations"][0]["unit_observations"][0]
    assert observation["co_occurrence"] == "observed"
    assert observation["citation_binding"] == observation["citation_visibility"] == "not_observed"
    assert all(item["prefix_observation"] == "observed" for item in result["local_action_observations"])
    for item in result["local_action_observations"]:
        assert all(not markers for markers in item["marker_review"]["proposal_markers"].values())
    for review in result["same_group_marker_reviews"][0]["marker_reviews"]:
        assert all(
            not values["proposal_only"] and not values["source_only"] for values in review["marker_difference"].values()
        )


@pytest.mark.parametrize(
    "opener",
    [
        '<span title="notes. ',
        "<span title='notes. ",
        '<span title="notes>.\n',
        '[details](https://example.test/a "notes. ',
        "[details](https://example.test/a 'notes. ",
        '[details](https://example.test/a "notes)" trailing. ',
    ],
)
def test_uncertain_metadata_boundary_propagates_across_units_for_all_observations(opener):
    before = "Review local contacts."
    affected = (
        "Unverified proposal for local review: Northbank students recorded 27 paper maps. "
        "[O1-RAG][source_id=guide] Guide"
    )
    report = before + "\nNorthbank students recorded paper maps " + opener + affected
    report, analysis, pack, facts, _ = _case(report)
    actions = [
        {"id": "before", "unit_span": _span(report, before), "unit_text": before, "group_id": "g"},
        {"id": "affected", "unit_span": _span(report, affected), "unit_text": affected, "group_id": "g"},
    ]
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    fact = result["fact_observations"][0]
    assert fact["co_occurrence"] == "unassessed" and fact["units_scanned"] == 3
    assert fact["unit_observations"][0]["co_occurrence"] == "not_observed"
    for unit in fact["unit_observations"][1:]:
        assert unit["co_occurrence"] == unit["citation_binding"] == unit["citation_visibility"] == "unassessed"
        assert unit["unassessed_reason"] == "unsupported_static_markup"
        assert all(probe["positions"] is None for probe in unit["probe_observations"])
    assert result["local_action_observations"][0]["prefix_observation"] == "not_observed"
    action = result["local_action_observations"][1]
    assert action["prefix_observation"] == "unassessed" and action["marker_review"] is None
    group = result["same_group_marker_reviews"][0]
    assert group["marker_reviews"] is None and group["unassessed_reason"] == "unsupported_unit_visibility"
    assert result["mixed_unit_review_clues"] == []


def test_unclosed_html_attribute_keeps_original_two_sentence_regression_unassessed():
    report = 'Northbank students recorded paper maps <span title="notes. Northbank students recorded 27 paper maps'
    fact = _review(report)["fact_observations"][0]
    assert fact["units_scanned"] == 2 and fact["co_occurrence"] == "unassessed"
    assert all(unit["co_occurrence"] == "unassessed" for unit in fact["unit_observations"])
    assert all(probe["positions"] is None for unit in fact["unit_observations"] for probe in unit["probe_observations"])


@pytest.mark.parametrize("carrier", ["html", "link", "hidden"])
def test_citation_in_invisible_metadata_never_establishes_binding(carrier):
    citation = format_rag_citation_token(_analysis()["knowledge"]["retrieved_chunks"][0])
    if carrier == "html":
        report = f'<span data-cite="{citation}">Northbank students recorded 27 paper maps</span>.'
    elif carrier == "link":
        report = f"Northbank students recorded 27 paper maps [details](https://example.test/{citation})."
    else:
        report = f"Northbank students recorded <!-- {citation} --> 27 paper maps."
    observation = _review(report)["fact_observations"][0]["unit_observations"][0]
    assert observation["co_occurrence"] == "observed"
    assert observation["citation_binding"] == observation["citation_visibility"] == "not_observed"


@pytest.mark.parametrize(
    "extra",
    [
        "[O1-RAG][ref=27]",
        "[O1-RAG] [ref=27]",
        "[O1-UNKNOWN][ref=27]",
        "[O1-RAG][source_id=missing] 27 Only adults",
        '<span data-count="27"',
        "[details](https://example.test/27",
        "&#27;",
    ],
)
def test_unsupported_markup_and_unknown_citations_are_unassessed(extra):
    report = "Northbank students recorded paper maps " + extra
    fact = _review(report)["fact_observations"][0]
    assert fact["co_occurrence"] == "unassessed"
    assert all(item["citation_binding"] == "unassessed" for item in fact["unit_observations"])
    assert all(probe["positions"] is None for item in fact["unit_observations"] for probe in item["probe_observations"])


@pytest.mark.parametrize("suffix_only", [False, True])
def test_unknown_citation_boundary_propagates_beyond_its_unit_and_search_range(suffix_only):
    suffix = "Northbank students recorded 27 paper maps"
    report = "Northbank students recorded paper maps [O1-RAG][source_id=missing] Notes. " + suffix
    report, analysis, pack, facts, actions = _case(report)
    if suffix_only:
        facts[0]["report_text"] = suffix
        facts[0]["report_span"] = _span(report, suffix)
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    fact = result["fact_observations"][0]
    assert fact["units_scanned"] == (1 if suffix_only else 2)
    assert fact["co_occurrence"] == "unassessed"
    for unit in fact["unit_observations"]:
        assert unit["co_occurrence"] == unit["citation_binding"] == unit["citation_visibility"] == "unassessed"
        assert unit["unassessed_reason"] == "unknown_citation_boundary"
        assert all(probe["positions"] is None for probe in unit["probe_observations"])


def test_unknown_citation_suffix_cannot_supply_later_binding_prefix_markers_or_mixed_clue():
    before = "Unverified proposal for local review: Prepare supplies."
    affected = (
        "Unverified proposal for local review: Northbank students recorded 27 paper maps unless approved. "
        "[O1-RAG][source_id=guide] Guide"
    )
    report = before + "\nNorthbank students recorded paper maps [O1-RAG][source_id=missing] Notes. " + affected
    report, analysis, pack, facts, _ = _case(report)
    actions = [
        {"id": "before", "unit_span": _span(report, before), "unit_text": before, "group_id": "g"},
        {"id": "affected", "unit_span": _span(report, affected), "unit_text": affected, "group_id": "g"},
    ]
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    observations = result["fact_observations"][0]["unit_observations"]
    assert len(observations) == 3 and observations[0]["co_occurrence"] == "not_observed"
    assert all(unit["co_occurrence"] == unit["citation_binding"] == "unassessed" for unit in observations[1:])
    assert all(unit["unassessed_reason"] == "unknown_citation_boundary" for unit in observations[1:])
    assert result["local_action_observations"][0]["prefix_observation"] == "observed"
    action = result["local_action_observations"][1]
    assert action["prefix_observation"] == "unassessed" and action["marker_review"] is None
    group = result["same_group_marker_reviews"][0]
    assert group["marker_reviews"] is None and group["unassessed_reason"] == "unsupported_unit_visibility"
    assert result["mixed_unit_review_clues"] == []


def test_known_complete_title_masks_probes_before_table_unit_projection():
    title_suffix = "Unverified proposal for local review: Northbank students recorded 27 paper maps only for adults unless approved"
    title = "Notes. | " + title_suffix
    analysis = _analysis()
    analysis["knowledge"]["retrieved_chunks"][0]["title"] = title
    first = "Northbank students recorded paper maps [O1-RAG][source_id=guide] Notes."
    report, _, pack, facts, _ = _case("First | Second\n--- | ---\n" + first + " | " + title_suffix)
    actions = [
        {"id": "a", "unit_span": _span(report, first), "unit_text": first, "group_id": "g"},
        {"id": "b", "unit_span": _span(report, title_suffix), "unit_text": title_suffix, "group_id": "g"},
    ]
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    fact = result["fact_observations"][0]
    assert fact["co_occurrence"] == "not_observed" and fact["units_scanned"] == 2
    first_unit, title_unit = fact["unit_observations"]
    assert first_unit["citation_binding"] == first_unit["citation_visibility"] == "observed"
    assert title_unit["citation_binding"] == title_unit["citation_visibility"] == "not_observed"
    assert all(probe["positions"] == [] for probe in title_unit["probe_observations"])
    assert all(item["prefix_observation"] == "not_observed" for item in result["local_action_observations"])
    for item in result["local_action_observations"]:
        assert all(not markers for markers in item["marker_review"]["proposal_markers"].values())
    for review in result["same_group_marker_reviews"][0]["marker_reviews"]:
        assert all(
            not values["proposal_only"] and not values["source_only"] for values in review["marker_difference"].values()
        )
    assert result["mixed_unit_review_clues"] == []


def test_known_title_with_sentence_punctuation_does_not_supply_fact_probes():
    title = "Notes. Northbank students recorded 27 paper maps"
    analysis = _analysis()
    analysis["knowledge"]["retrieved_chunks"][0]["title"] = title
    report, _, pack, facts, actions = _case("Northbank students recorded paper maps [O1-RAG][source_id=guide] " + title)
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    fact = result["fact_observations"][0]
    assert fact["co_occurrence"] == "not_observed" and fact["units_scanned"] == 1
    assert fact["unit_observations"][0]["citation_binding"] == "observed"
    assert fact["unit_observations"][0]["probe_observations"][1]["positions"] == []


def test_known_citation_boundary_keeps_following_real_body_observable():
    before = "Northbank students recorded paper maps. [O1-RAG][source_id=guide] Guide"
    after = "Northbank students recorded 27 paper maps."
    fact = _review(before + "\n" + after)["fact_observations"][0]
    assert fact["co_occurrence"] == "observed" and fact["units_scanned"] == 2
    assert fact["unit_observations"][0]["citation_binding"] == "observed"
    assert fact["unit_observations"][1]["co_occurrence"] == "observed"
    assert fact["unit_observations"][1]["citation_binding"] == "not_observed"


@pytest.mark.parametrize(
    "prefix,expected",
    [
        ("Unverified proposal for local review:", "observed"),
        ("**Unverified proposal for local review:**", "observed"),
        ("Unverified **proposal** for local review:", "observed"),
        ("Ｕnverified proposal for local review:", "not_observed"),
        ("Un\u200bverified proposal for local review:", "not_observed"),
        ("unverified proposal for local review:", "not_observed"),
    ],
)
def test_action_prefix_preserves_literal_characters_with_paired_emphasis(prefix, expected):
    report = prefix + " Prepare supplies."
    actions = [{"id": "a", "unit_span": _span(report, report), "unit_text": report, "group_id": None}]
    result = advisory.review_report_content(
        report, _analysis(), _pack("source"), fact_targets=[], local_actions=actions
    )
    assert result["local_action_observations"][0]["prefix_observation"] == expected


def test_every_group_member_owns_prefix_and_condition_in_its_table_cell():
    first = "Unverified proposal for local review: Do not act unless approved."
    second = "Act on the plan."
    report = f"First | Second\n--- | ---\n{first} | {second}"
    actions = [
        {"id": "a", "unit_span": _span(report, first), "unit_text": first, "group_id": "g"},
        {"id": "b", "unit_span": _span(report, second), "unit_text": second, "group_id": "g"},
    ]
    result = advisory.review_report_content(
        report, _analysis(), _pack("source"), fact_targets=[], local_actions=actions
    )
    assert [item["prefix_observation"] for item in result["local_action_observations"]] == ["observed", "not_observed"]
    marker = result["same_group_marker_reviews"][0]["marker_reviews"][0]
    assert marker["marker_difference"]["condition"]["proposal_only"] == ["unless"]
    assert marker["semantic_or_condition_verdict"] == "not_provided"


def test_citation_titles_never_supply_action_markers_and_agreement_is_not_approval():
    analysis = _analysis()
    analysis["knowledge"]["retrieved_chunks"][0]["title"] = "Approved Only adults"
    first = "Unverified proposal for local review: Prepare supplies. [O1-RAG][source_id=guide] Approved Only adults"
    second = "Unverified proposal for local review: Prepare water."
    report = first + "\n" + second
    actions = [
        {"id": "a", "unit_span": _span(report, first), "unit_text": first, "group_id": "g"},
        {"id": "b", "unit_span": _span(report, second), "unit_text": second, "group_id": "g"},
    ]
    result = advisory.review_report_content(report, analysis, _pack("source"), fact_targets=[], local_actions=actions)
    for review in result["same_group_marker_reviews"][0]["marker_reviews"]:
        assert all(
            not values["proposal_only"] and not values["source_only"] for values in review["marker_difference"].values()
        )
        assert review["semantic_or_condition_verdict"] == "not_provided"
    assert result["semantics"] == result["conditions"] == "unknown"


def test_local_action_must_remain_one_complete_unit():
    report = "Unverified proposal for local review: Prepare supplies."
    piece = "Prepare supplies."
    actions = [{"id": "a", "unit_span": _span(report, piece), "unit_text": piece, "group_id": None}]
    with pytest.raises(advisory.ContentAdvisoryError, match="complete extracted"):
        advisory.review_report_content(report, _analysis(), _pack("source"), fact_targets=[], local_actions=actions)


@pytest.mark.parametrize(
    "action_text,expected_mixed",
    [
        ("Unverified proposal for local review: Prepare local supplies.", False),
        ("Unverified proposal for local review: Northbank students recorded 27 paper maps.", True),
        (
            'Unverified proposal for local review: <span data-count="27">Northbank students recorded paper maps</span>.',
            False,
        ),
    ],
)
def test_mixed_unit_clue_needs_same_unit_probes_but_does_not_require_citation(action_text, expected_mixed):
    report = "Review local contacts.\n" + action_text
    report, analysis, pack, facts, _ = _case(report)
    actions = [{"id": "a", "unit_span": _span(report, action_text), "unit_text": action_text, "group_id": None}]
    result = advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    assert bool(result["mixed_unit_review_clues"]) is expected_mixed
    if expected_mixed:
        clue = result["mixed_unit_review_clues"][0]
        assert clue["citation_binding"] == "not_observed"
        assert clue["finding"] == "possible_mixed_fact_action_unit" and clue["semantics"] == "unknown"


def test_resource_caps_reject_excess_without_silently_truncating(monkeypatch):
    assert advisory.MAX_TARGET_UNIT_REVIEWS == 8192 and advisory.MAX_PROBE_MATCHES == 16384
    monkeypatch.setattr(advisory, "MAX_TARGET_UNIT_REVIEWS", 2)
    report = "Review local contacts.\nReview local supplies."
    result = _review(report)
    assert result["units_scanned"] == 2
    with pytest.raises(advisory.ContentAdvisoryError, match="target-unit review limit"):
        _review(report + "\nReview local plans.")
    monkeypatch.setattr(advisory, "MAX_PROBE_MATCHES", 3)
    assert _review("Northbank students recorded 27 paper maps.")["probe_matches"] == 3
    with pytest.raises(advisory.ContentAdvisoryError, match="probe match limit"):
        _review("Northbank students recorded 27 and 27 paper maps.")


@pytest.mark.parametrize("mutation", ["bad_hash", "unknown_ref", "wrong_span", "duplicate", "bool", "probe", "limit"])
def test_contract_rejects_tampering_and_limits(mutation):
    report, analysis, pack, facts, actions = _case()
    if mutation == "bad_hash":
        pack["evidence_pack_sha256"] = "0" * 64
    elif mutation == "unknown_ref":
        facts[0]["passage_ref"] = "missing"
    elif mutation == "wrong_span":
        facts[0]["report_text"] = "forged"
    elif mutation == "duplicate":
        facts.append(copy.deepcopy(facts[0]))
    elif mutation == "bool":
        facts[0]["report_span"]["start"] = True
    elif mutation == "probe":
        facts[0]["probes"] = ["absent"]
    else:
        facts *= advisory.MAX_FACT_TARGETS + 1
    with pytest.raises((advisory.ContentAdvisoryError, ValueError)):
        advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)


def test_inputs_are_not_mutated_and_module_has_no_environment_network_or_file_access():
    report, analysis, pack, facts, actions = _case()
    before = copy.deepcopy((report, analysis, pack, facts, actions))
    advisory.review_report_content(report, analysis, pack, fact_targets=facts, local_actions=actions)
    assert (report, analysis, pack, facts, actions) == before
    tree = ast.parse(Path(advisory.__file__).read_text(encoding="utf-8"))
    forbidden = {"dotenv", "requests", "httpx", "urllib", "socket", "openai", "os"}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    imported.update(
        node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported & forbidden
