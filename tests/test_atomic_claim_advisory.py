"""Independent synthetic review vectors; no historical output or holdout reads."""

import copy
import json

import pytest

from scripts import atomic_claim_adapter as adapter
from scripts import atomic_claim_advisory as advisory
from scripts import atomic_claim_contract as contract
from tests.test_atomic_claim_contract import make_pack


@pytest.fixture(autouse=True)
def no_model_or_dotenv(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr(adapter, "create_sdk", lambda *_args, **_kwargs: pytest.fail("Advisory cannot create an SDK"))
    monkeypatch.setattr(adapter, "invoke_once", lambda *_args, **_kwargs: pytest.fail("Advisory cannot call a model"))


def raw_item(
    pack,
    *,
    claim=None,
    quote=None,
    section=7,
    reason="Local sufficiency remains unconfirmed.",
    proposal="Proposed local review.",
):
    basis = (
        {"kind": "abstention", "reason": reason}
        if claim is None
        else {
            "kind": "claim",
            "text": claim,
            "evidence": {"passage_ref": pack["passages"][0]["passage_ref"], "quote": quote},
        }
    )
    return json.dumps(
        {
            "schema": adapter.WIRE_SCHEMA,
            "evidence_pack_sha256": pack["evidence_pack_sha256"],
            "items": [{"id": "review", "section_id": section, "basis": basis, "local_proposal": proposal}],
        },
        ensure_ascii=False,
    )


def review_claim(texts, claim, quote):
    pack, *_ = make_pack(texts)
    result = advisory.review_selection(raw_item(pack, claim=claim, quote=quote), pack)
    return result, result["items"][0]["claim_review"], pack


def inventory(pack, section, reason="Local sufficiency remains unconfirmed."):
    row = advisory.review_selection(raw_item(pack, section=section, reason=reason), pack)["items"][0]
    return row, {item["cue"]: item for item in row["abstention_review"]["topic_cue_inventory"]}


def test_adjacent_sentence_and_other_passages_do_not_fill_selected_quote_gaps():
    quote = "Inspect generator cables weekly."
    result, review, _ = review_claim(
        [quote + " Store spare batteries in a labelled cabinet.", "A separate site stocks chargers."],
        "Inspect generator cables weekly and store spare batteries in a labelled cabinet.",
        quote,
    )
    assert {"batteries", "cabinet", "labelled"} <= set(review["claim_content_terms_not_in_quote"])
    assert "batteries" in review["context_review"]["after"]["claim_terms_missing_from_quote_found_here"]
    assert review["context_review"]["used_to_resolve_selected_quote_differences"] is False
    assert result["manual_review_required"] and result["semantic_support"] == "unknown"
    _, review, _ = review_claim(
        ["The library offers text alerts.", "The clinic offers sign-language appointments."],
        "The library offers sign-language appointments.",
        "The library offers text alerts.",
    )
    assert {"sign-language", "appointments"} <= set(review["claim_content_terms_not_in_quote"])
    assert review["context_review"]["other_passages_used"] is False


@pytest.mark.parametrize(
    "text,claim,field,value",
    [
        ("batMARKtery", "A battery is required.", "claim_content_terms_not_in_quote", "battery"),
        ("0MARK00", "Call 000.", "numeric_literals_not_in_quote", "000"),
    ],
)
def test_context_fragments_never_join_across_quote(text, claim, field, value):
    _, review, _ = review_claim([text], claim, "MARK")
    assert value in review[field]
    for side in ("before", "after"):
        context = review["context_review"][side]
        assert value not in context["claim_terms_missing_from_quote_found_here"]
        assert value not in context["numeric_literals_missing_from_quote_found_here"]
        assert context["text"] == text[context["span"]["start"] : context["span"]["end"]]


def test_negation_flip_is_a_possible_difference_but_retention_is_not_approval():
    quote = "A green indicator does not confirm that the room is suitable."
    _, changed, _ = review_claim([quote], "A green indicator confirms that the room is suitable.", quote)
    assert changed["marker_difference"]["negation"]["quote_only"] == ["not"]
    assert "possible_negation_marker_difference" in changed["possible_review_clues"]
    result, retained, _ = review_claim([quote], quote, quote)
    assert retained["possible_review_clues"] == []
    assert result["manual_review_required"] and result["semantic_support"] == "unknown"


def test_unrelated_context_negation_does_not_become_quote_conflict():
    quote = "Bottled water remains available."
    _, review, _ = review_claim([quote + " Do not store it in sunlight."], quote, quote)
    assert review["marker_difference"]["negation"] == {"claim_only": [], "quote_only": []}
    assert "possible_negation_marker_difference" not in review["possible_review_clues"]
    assert review["context_review"]["after"]["markers_observed_here"]["negation"] == ["not"]


def test_unless_only_except_and_qualifiers_remain_review_clues():
    quote = "Issue a unit only after inspection, unless a recall is active; except units marked X, which are excluded."
    _, changed, _ = review_claim([quote], "Issue any inspected unit.", quote)
    assert {"only", "after", "unless", "except"} <= set(changed["marker_difference"]["condition"]["quote_only"])
    assert "excluded" in changed["marker_difference"]["qualifier"]["quote_only"]
    result, retained, _ = review_claim([quote], quote, quote)
    assert all(not any(values.values()) for values in retained["marker_difference"].values())
    assert result["semantic_accuracy"] is None and result["manual_review_required"]
    quote = "For trained adult volunteers, rehearsals may last up to 20 minutes in cool conditions."
    _, changed, _ = review_claim([quote], "All volunteers should rehearse for 20 minutes.", quote)
    assert {"trained", "adult", "may", "up to"} <= set(changed["marker_difference"]["qualifier"]["quote_only"])
    assert changed["numeric_literals_not_in_quote"] == []


def test_numeric_literals_include_000_and_never_get_filled_from_context():
    _, review, _ = review_claim(
        ["Call 112 for support. The emergency number is 000."], "Call 000 for support.", "Call 112 for support."
    )
    assert review["numeric_literals_not_in_quote"] == ["000"]
    assert review["context_review"]["after"]["numeric_literals_missing_from_quote_found_here"] == ["000"]
    _, matching, _ = review_claim(
        ["Call 000 for emergencies."], "Call 000 for emergencies.", "Call 000 for emergencies."
    )
    assert matching["numeric_literals_not_in_quote"] == []


def test_same_words_and_numbers_across_populations_never_imply_semantic_support():
    quote = (
        "20% of coordinators completed the exercise. Separately, 20% of participants requested printed instructions."
    )
    result, review, _ = review_claim([quote], "20% of participants completed the exercise.", quote)
    assert review["claim_content_terms_not_in_quote"] == review["numeric_literals_not_in_quote"] == []
    assert result["semantic_support"] == "unknown" and result["manual_review_required"]
    assert any("populations" in note for note in result["limitations"])


@pytest.mark.parametrize(
    "reason", ["Local language needs have not been established.", "No communication evidence is available."]
)
def test_general_communication_cues_do_not_decide_abstention_correctness(reason):
    pack, *_ = make_pack(["The service publishes warning updates and an Easy English guide. Contact support agencies."])
    row, cues = inventory(pack, 11, reason)
    assert cues["warnings_updates"]["observation"] == "observed"
    assert cues["easy_english"]["observation"] == "observed"
    assert cues["support_contacts_agencies"]["observation"] == "observed"
    assert (
        row["abstention_review"]["local_sufficiency"] == row["abstention_review"]["abstention_correctness"] == "unknown"
    )
    assert row["manual_review_required"]


def test_no_cue_never_means_no_evidence_and_general_roof_text_is_not_training():
    pack, *_ = make_pack(["A paper copy in larger type is available on request. Check the roof and evacuation route."])
    for section in (11, 12):
        row, cues = inventory(pack, section)
        assert all(cue["observation"] == "not_observed" for cue in cues.values())
        assert row["abstention_review"]["abstention_correctness"] == "unknown"


def test_cue_word_boundaries_and_negated_mentions_are_not_positive_evidence():
    pack, *_ = make_pack(["Mandrills visit the roof. Labellingdrills is one word. Trainingground is one word."])
    _, cues = inventory(pack, 12)
    assert all(cue["observation"] == "not_observed" for cue in cues.values())
    pack, *_ = make_pack(["Training is not offered. No first aid, CPR, AED, drill or exercise is provided."])
    row, cues = inventory(pack, 12)
    assert all(cue["observation"] == "observed" for cue in cues.values())
    assert "not" in cues["training"]["occurrences"][0]["context"]["markers_observed"]["negation"]
    assert row["semantic_support"] == "unknown"


def test_exact_cue_spans_and_omitted_late_occurrences_are_explicit():
    pack, *_ = make_pack(["training " * (advisory.MAX_CUE_OCCURRENCES + 2), "Training and an AED are mentioned later."])
    row, cues = inventory(pack, 12)
    cue = cues["training"]
    assert cue["occurrences_total"] == advisory.MAX_CUE_OCCURRENCES + 3
    assert cue["occurrences_omitted"] == 3
    assert pack["passages"][1]["passage_ref"] in cue["omitted_occurrence_passage_refs"]
    texts = {passage["passage_ref"]: passage["text"] for passage in pack["passages"]}
    for occurrence in cue["occurrences"]:
        source, span = texts[occurrence["passage_ref"]], occurrence["span"]
        assert source[span["start"] : span["end"]] == occurrence["matched_text"]
        context = occurrence["context"]
        assert source[context["span"]["start"] : context["span"]["end"]] == context["text"]
    assert row["abstention_review"]["processing"]["all_visible_text_scanned"]
    rendered = advisory.render_advisory(raw_item(pack, section=12), pack)
    assert "omitted 3" in rendered and "Omitted occurrence references" in rendered


def test_content_difference_omissions_are_disclosed():
    words = [f"a{chr(97 + index // 26)}{chr(97 + index % 26)}" for index in range(90)]
    _, review, _ = review_claim(["Reference phrase."], " ".join(words), "Reference phrase.")
    assert len(review["claim_content_terms_not_in_quote"]) == advisory.MAX_LISTED_DIFFERENCES
    assert review["processing"]["missing_terms_total"] == 90
    assert review["processing"]["missing_terms_omitted"] == 90 - advisory.MAX_LISTED_DIFFERENCES


def test_acronyms_and_word_forms_are_not_automatically_called_unsupported():
    result, review, _ = review_claim(["Maintain the APZ."], "Maintain the Asset Protection Zone.", "Maintain the APZ.")
    assert {"asset", "protection", "zone"} <= set(review["claim_content_terms_not_in_quote"])
    assert any("abbreviations" in note and "false alarms" in note for note in result["limitations"])
    assert result["semantic_support"] == "unknown" and result["manual_review_required"]


def test_envelope_and_proposal_never_inherit_a_positive_verdict():
    result, _, _ = review_claim(["Inspect cables."], "Inspect cables.", "Inspect cables.")
    assert result["schema"] == "atomic-quote-advisory-v1"
    assert result["additional_model_calls"] == 0 and result["new_transport_capture"] is False
    assert result["input_origin"] == "caller_supplied_revalidated" and result["semantic_accuracy"] is None
    assert result["span_unit"] == "python_unicode_codepoints" and result["full_report_coverage"] == "not_evaluated"
    assert result["production_enabled"] is False and result["release_gate"] == {"active": False}
    proposal = result["items"][0]["local_proposal"]
    assert (
        proposal["review_required"]
        and proposal["semantic_support"] == "unknown"
        and not proposal["basis_evidence_inherited"]
    )

    def keys(value):
        if isinstance(value, dict):
            yield from value
            for child in value.values():
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not {"supported", "pass", "score"}.intersection(keys(result))


def test_renderer_escapes_all_untrusted_nodes_and_revalidates_inputs():
    pack, *_ = make_pack(["Inspect cables."], source_id="source<img>", chunk_prefix="[chunk](https://evil.test)")
    attack = "<img src=x>\n# forged\n[go](https://evil.test)\u202e"
    raw = raw_item(pack, claim=attack, quote="Inspect cables.", proposal=attack)
    preview = advisory.render_advisory(raw, pack)
    assert preview.startswith("# OFFLINE REVIEW\n# NOT REPORT")
    for dangerous in ("<img", "\n# forged", "[go](", "https://", "\u202e"):
        assert dangerous not in preview
    assert "source&lt;img&gt;" in preview
    abstain_preview = advisory.render_advisory(raw_item(pack, section=11, reason=attack, proposal=attack), pack)
    assert "<img" not in abstain_preview and "\n# forged" not in abstain_preview
    with pytest.raises(contract.ContractError):
        advisory.render_advisory(advisory.review_selection(raw, pack), pack)
    wrong = json.loads(raw)
    wrong["items"][0]["basis"]["evidence"]["quote"] = "Invented quotation."
    with pytest.raises(adapter.SelectionError):
        advisory.render_advisory(json.dumps(wrong), pack)
    changed = copy.deepcopy(pack)
    changed["passages"][0]["text"] += " altered"
    with pytest.raises(contract.ContractError):
        advisory.review_selection(raw, changed)
