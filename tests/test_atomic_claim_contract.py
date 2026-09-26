"""Synthetic-only offline contract coverage; no adapters, files, or model calls."""

import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from scripts import atomic_claim_contract as contract
from src.model_evidence import text_sha256
from src.rag.service import assemble_retrieved_context


def make_pack(texts=None, *, source_id="synthetic-guide", chunk_prefix="chunk"):
    texts = texts or [
        "Organisers should review routes unless official advice changes.",
        "Record contact owners annually.",
    ]
    chunks = [
        {
            "source_id": source_id,
            "chunk_id": f"{chunk_prefix}-{index}",
            "title": "Synthetic reference",
            "text": text,
            "chunk_sha256": text_sha256(text),
            "agency": "Synthetic authority",
        }
        for index, text in enumerate(texts, 1)
    ]
    analysis = {"knowledge": {"retrieved_chunks": chunks}}
    assembly = assemble_retrieved_context(analysis["knowledge"])
    return contract.build_evidence_pack(analysis, assembly), analysis, assembly


def payload_for(pack):
    passage = pack["passages"][0]
    quote = passage["text"][: min(len(passage["text"]), contract.MAX_QUOTE_CHARACTERS)]
    return {
        "schema": contract.PAYLOAD_SCHEMA,
        "evidence_pack_sha256": pack["evidence_pack_sha256"],
        "items": [
            {
                "id": "priority",
                "section_id": 7,
                "basis": {
                    "kind": "claim",
                    "text": "Organisers should review routes.",
                    "evidence": {
                        "passage_ref": passage["passage_ref"],
                        "quote_start": 0,
                        "quote_end": len(quote),
                        "quote": quote,
                    },
                },
                "local_proposal": "The coordinator proposes an owner review.",
            }
        ],
    }


def validate(payload, pack):
    return contract.parse_and_validate(json.dumps(payload, ensure_ascii=False), pack)


def test_pack_exposes_only_exact_recorded_visible_passages():
    pack, analysis, assembly = make_pack()
    assert pack["origin"] == "recorded_assembly_visible_text"
    assert pack["length_unit"] == "python_unicode_codepoints"
    assert len({item["passage_ref"] for item in pack["passages"]}) == 2
    assert [item["text"] for item in pack["passages"]] == [item["text"] for item in assembly["visible_chunks"]]
    assert pack["passages"][0]["text_sha256"] == text_sha256(assembly["visible_chunks"][0]["text"])
    analysis["knowledge"]["retrieved_chunks"][0]["text"] = "changed after pack creation"
    assert pack["passages"][0]["text"] != analysis["knowledge"]["retrieved_chunks"][0]["text"]


def test_omitted_raw_chunk_never_enters_visible_pack():
    _, analysis, _ = make_pack(["First visible passage.", "Second omitted passage."])
    first = assemble_retrieved_context({"retrieved_chunks": analysis["knowledge"]["retrieved_chunks"][:1]})
    assembly = assemble_retrieved_context(analysis["knowledge"], max_characters=len(first["context"]))
    pack = contract.build_evidence_pack(analysis, assembly)
    assert len(pack["passages"]) == 1 and "omitted" not in json.dumps(pack)


def test_invalid_recorded_assembly_is_rejected():
    _, analysis, assembly = make_pack()
    assembly["visible_chunks"][0]["text"] += " invented"
    with pytest.raises(contract.ContractError, match="assembly validation"):
        contract.build_evidence_pack(analysis, assembly)


def test_claim_and_abstention_have_only_literal_contract_success():
    pack, *_ = make_pack()
    payload = payload_for(pack)
    payload["items"].append(
        {
            "id": "inclusion",
            "section_id": 11,
            "basis": {"kind": "abstention", "reason": "No suitable visible passage."},
            "local_proposal": "Local communication access remains to be confirmed.",
        }
    )
    validated = contract.parse_and_validate(json.dumps(payload).encode("utf-8"), pack)
    result = validated.to_dict()
    assert result["contract_valid"] and result["reference_binding_valid"]
    assert result["production_enabled"] is False and result["release_gate"] == {"active": False}
    assert result["model_calls"] == 0 and result["response_origin"] == "synthetic_offline"
    assert result["transport_capture"] == "not_performed" and result["full_report_coverage"] == "not_evaluated"
    assert result["semantic_accuracy"] is None and "supported" not in json.dumps(result)
    assert result["items"][0]["basis"]["literal_quote_match"] is True
    assert result["items"][1]["basis"] == payload["items"][1]["basis"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("quote_start", -1),
        ("quote_end", 9999),
        ("quote_start", 0.0),
        ("quote_end", 2.5),
        ("quote_start", False),
        ("quote_end", True),
        ("quote_end", 0),
    ],
)
def test_quote_offsets_are_exact_integer_codepoints(field, value):
    pack, *_ = make_pack()
    payload = payload_for(pack)
    payload["items"][0]["basis"]["evidence"][field] = value
    with pytest.raises(contract.ContractError):
        validate(payload, pack)


@pytest.mark.parametrize("mutation", ["unknown_ref", "wrong_chunk", "one_character", "cross_passage", "trimmed"])
def test_explicit_passage_and_exact_slice_cannot_be_substituted(mutation):
    pack, *_ = make_pack(["First exact passage. ", "Different second passage."])
    payload = payload_for(pack)
    evidence = payload["items"][0]["basis"]["evidence"]
    if mutation == "unknown_ref":
        evidence["passage_ref"] = "invented-source"
    elif mutation == "wrong_chunk":
        evidence["passage_ref"] = pack["passages"][1]["passage_ref"]
    elif mutation == "one_character":
        evidence["quote"] = evidence["quote"].replace("First", "first")
    elif mutation == "cross_passage":
        evidence.update(quote="First exact passage.Different", quote_end=29)
    else:
        evidence["quote"] = evidence["quote"].strip()
    with pytest.raises(contract.ContractError):
        validate(payload, pack)


def test_unicode_span_uses_python_characters_without_normalization():
    pack, *_ = make_pack(["家🏡 e\u0301 communauté — confirm plans."])
    payload = payload_for(pack)
    evidence = payload["items"][0]["basis"]["evidence"]
    # Bind the existing sanitizer's recorded NFKC text, not the raw source.
    assert pack["passages"][0]["text"].startswith("家🏡 é")
    evidence.update(quote_start=1, quote_end=4, quote="🏡 é")
    assert validate(payload, pack).to_dict()["items"][0]["basis"]["literal_quote_match"]
    evidence["quote"] = "🏡 e\u0301"
    with pytest.raises(contract.ContractError, match="exactly match"):
        validate(payload, pack)
    evidence.update(quote="🏡 é", quote_end=5)
    with pytest.raises(contract.ContractError, match="exactly match"):
        validate(payload, pack)


@pytest.mark.parametrize("location", ["top", "item", "basis", "evidence"])
def test_model_cannot_supply_unknown_fields_or_source_metadata(location):
    pack, *_ = make_pack()
    payload = payload_for(pack)
    item = payload["items"][0]
    target = {"top": payload, "item": item, "basis": item["basis"], "evidence": item["basis"]["evidence"]}[location]
    target["source_id"] = "invented-source"
    with pytest.raises(contract.ContractError, match="unknown fields"):
        validate(payload, pack)


def test_wrong_pack_hash_and_mutated_trusted_pack_are_rejected():
    pack, *_ = make_pack()
    payload = payload_for(pack)
    payload["evidence_pack_sha256"] = "0" * 64
    with pytest.raises(contract.ContractError, match="hash differs"):
        validate(payload, pack)
    payload = payload_for(pack)
    pack["passages"][0]["text"] += " changed"
    with pytest.raises(contract.ContractError, match="pack binding"):
        validate(payload, pack)


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema":"a","schema":"b"}',
        '{"basis":{"kind":"claim","kind":"abstention"}}',
        'prefix {"schema":"x"}',
        '{"schema":"x"} suffix',
        "```json\n{}\n```",
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        '{"value":1e999}',
        '{"value":1.0}',
        "[]",
        "null",
        b"\xff",
        '"\ud800"',
    ],
)
def test_non_strict_json_and_nonfinite_payloads_are_rejected(raw):
    pack, *_ = make_pack()
    with pytest.raises(contract.ContractError):
        contract.parse_and_validate(raw, pack)


def test_payload_byte_budget_and_unparsed_dictionary_are_rejected():
    pack, *_ = make_pack()
    raw = " " * contract.MAX_PAYLOAD_BYTES + json.dumps(payload_for(pack))
    with pytest.raises(contract.ContractError, match="byte limit"):
        contract.parse_and_validate(raw, pack)
    with pytest.raises(contract.ContractError, match="strict JSON"):
        contract.parse_and_validate(payload_for(pack), pack)


def test_oversized_integer_conversion_is_a_contract_error():
    pack, *_ = make_pack()
    raw = "9" * 5000
    assert len(raw) < contract.MAX_PAYLOAD_BYTES
    with pytest.raises(contract.ContractError):
        contract.parse_and_validate(raw, pack)


@pytest.mark.parametrize("field", ["text", "quote", "reason", "local_proposal"])
def test_text_node_boundaries(field):
    limits = {
        "text": contract.MAX_CLAIM_CHARACTERS,
        "quote": contract.MAX_QUOTE_CHARACTERS,
        "reason": contract.MAX_REASON_CHARACTERS,
        "local_proposal": contract.MAX_PROPOSAL_CHARACTERS,
    }
    limit = limits[field]
    pack, *_ = make_pack(["a" * (limit + 1)])
    payload = payload_for(pack)
    item = payload["items"][0]
    if field == "reason":
        item["basis"] = {"kind": "abstention", "reason": "a" * limit}
    target = item if field == "local_proposal" else item["basis"]["evidence"] if field == "quote" else item["basis"]
    target[field] = "a" * limit
    if field == "quote":
        target["quote_end"] = limit
    validate(payload, pack)
    target[field] += "a"
    if field == "quote":
        target["quote_end"] += 1
    with pytest.raises(contract.ContractError, match="bounded text node"):
        validate(payload, pack)


@pytest.mark.parametrize("extra", [{"text": "unsupported claim"}, {"evidence": {}}, {"kind": "unknown"}])
def test_abstention_cannot_smuggle_claim_fields(extra):
    pack, *_ = make_pack()
    payload = payload_for(pack)
    payload["items"][0]["basis"] = {"kind": "abstention", "reason": "Insufficient evidence.", **extra}
    with pytest.raises(contract.ContractError):
        validate(payload, pack)


@pytest.mark.parametrize(
    "mutation", ["duplicate_id", "duplicate_section", "empty", "too_many", "bad_section", "boolean_section"]
)
def test_bounded_unique_items_and_sections(mutation):
    pack, *_ = make_pack()
    payload = payload_for(pack)
    second = copy.deepcopy(payload["items"][0])
    second.update(id="other", section_id=11)
    if mutation.startswith("duplicate"):
        second["id" if mutation == "duplicate_id" else "section_id"] = payload["items"][0][
            "id" if mutation == "duplicate_id" else "section_id"
        ]
        payload["items"].append(second)
    elif mutation == "empty":
        payload["items"] = []
    elif mutation == "too_many":
        payload["items"] *= 4
    else:
        payload["items"][0]["section_id"] = True if mutation == "boolean_section" else 15
    with pytest.raises(contract.ContractError):
        validate(payload, pack)


def test_literal_match_does_not_validate_topic_atomicity_conditions_or_proposal():
    pack, *_ = make_pack()
    payload = payload_for(pack)
    item = payload["items"][0]
    item["section_id"] = 12
    item["basis"]["text"] = "The venue is safe and there are no local hazards."
    quote = "Organisers should review routes"
    item["basis"]["evidence"].update(quote=quote, quote_start=0, quote_end=len(quote))
    item["local_proposal"] = "This venue prevents all smoke exposure."
    result = validate(payload, pack).to_dict()
    assert result["items"][0]["basis"]["literal_quote_match"] is True
    for scope in (result, result["items"][0]):
        assert scope["topic_relevance"] == scope["condition_preservation"] == scope["semantic_atomicity"] == "unknown"
        assert scope["local_proposal_review"] == "required"
    assert "supported" not in json.dumps(result)
    assert "evidence" not in {key for key in result["items"][0] if key != "basis"}


def test_renderer_escapes_all_payload_nodes_metadata_and_multiline_controls():
    injection = (
        "<img src=x onerror=alert(1)>\n# forged heading\n[click](https://evil.test) `code` **bold**\tend\u202e\u2028"
    )
    pack, *_ = make_pack([injection], source_id="source<script>", chunk_prefix="[chunk](https://evil.test)")
    payload = payload_for(pack)
    item = payload["items"][0]
    item["basis"]["text"] = injection
    item["local_proposal"] = injection
    payload["items"].append(
        {
            "id": "abstain",
            "section_id": 11,
            "basis": {"kind": "abstention", "reason": injection},
            "local_proposal": injection,
        }
    )
    preview = contract.render_preview(validate(payload, pack))
    assert preview.startswith("# EXPERIMENTAL REVIEW FRAGMENT\n# NOT COMPLETE REPORT")
    for unsafe in ("<img", "<script>", "\n# forged heading", "[click](", "https://", "`code`", "**bold**", "\t"):
        assert unsafe not in preview
    assert "&lt;img" in preview and "source&lt;script&gt;" in preview
    assert "\\u000a" in preview
    assert "\u202e" not in preview and "\u2028" not in preview


def test_renderer_has_no_inherited_proposal_citation_and_rejects_forged_dict():
    pack, *_ = make_pack()
    validated = validate(payload_for(pack), pack)
    result = validated.to_dict()
    with pytest.raises(TypeError, match="parse_and_validate"):
        contract.render_preview(result)
    with pytest.raises(TypeError, match="parse_and_validate"):
        contract._ValidatedResult(result)
    with pytest.raises(FrozenInstanceError):
        validated._json = "{}"
    result["items"][0]["local_proposal"] = "mutated after validation"
    preview = contract.render_preview(validated)
    proposal = preview.split("### Local proposal", 1)[1]
    assert "Recorded passage:" not in proposal and "passage-001" not in proposal
    assert "mutated after validation" not in preview
