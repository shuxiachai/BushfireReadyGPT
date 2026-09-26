"""Pure synthetic proposal-contract tests; no model, historical output or migration."""

import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from scripts import atomic_claim_contract as contract
from scripts import extractive_basis_prototype as prototype
from scripts import proposal_evidence_contract as proposals
from src.model_evidence import json_sha256, text_sha256
from tests.test_atomic_claim_contract import make_pack


def example():
    pack, *_ = make_pack(
        [
            "Issue equipment only after inspection, unless a recall is active. Items marked X are excluded.",
            "Record a named owner for each equipment entry. Do not assume local ownership.",
            "Publish accessible notices and ask participants which formats they require.",
        ]
    )
    refs = [passage["passage_ref"] for passage in pack["passages"]]
    selected = {"7": refs[0], "11": refs[2], "12": None}
    payload = {
        "items": [
            {
                "section_id": 7,
                "proposal": {
                    "kind": "draft_for_review",
                    "text": "Propose a local equipment review, with inspection and recall checks and an owner enquiry.",
                    "declared_refs": refs[:2],
                },
            },
            {"section_id": 11, "proposal": {"kind": "requires_evidence"}},
            {"section_id": 12, "proposal": {"kind": "requires_evidence"}},
        ]
    }
    return pack, selected, proposals.build_request(pack, selected), payload


def validate(payload, request):
    return proposals.validate_proposals(json.dumps(payload, ensure_ascii=False), request)


def rehash_pack(pack):
    pack["evidence_pack_sha256"] = json_sha256({k: v for k, v in pack.items() if k != "evidence_pack_sha256"})


def test_request_freezes_application_context_and_bounded_wire_schema():
    pack, selected, request, _ = example()
    data = request.to_dict()
    assert data["version"] == proposals.REQUEST_VERSION
    assert data["selection_context_origin"] == "application_supplied"
    assert data["selected_ref_by_section"] == selected
    assert data["catalog"] == pack["passages"]
    assert data["request_sha256"] == json_sha256({k: v for k, v in data.items() if k != "request_sha256"})
    assert not {"messages", "model", "temperature", "max_tokens", "transport_capture"}.intersection(data)
    schema = data["output_json_schema"]
    assert schema["required"] == ["items"] and schema["additionalProperties"] is False
    items = schema["properties"]["items"]
    assert items["minItems"] == items["maxItems"] == 3
    assert items["items"]["required"] == ["section_id", "proposal"]
    branches = items["items"]["properties"]["proposal"]["oneOf"]
    assert branches[0]["required"] == ["kind"]
    assert branches[1]["properties"]["declared_refs"]["maxItems"] == 3
    selected["7"] = None
    pack["passages"][0]["text"] = "Changed after request creation."
    data["catalog"].clear()
    assert request.to_dict()["selected_ref_by_section"]["7"] is not None
    assert len(request.to_dict()["catalog"]) == 3


@pytest.mark.parametrize(
    "selected",
    [
        {7: None, 11: None, 12: None},
        {True: None, "11": None, "12": None},
        {"7": None, "11": None},
        {"7": None, "11": None, "12": None, "13": None},
        {"7": True, "11": None, "12": None},
        {"7": "foreign-ref", "11": None, "12": None},
        {"7": "", "11": None, "12": None},
        [],
    ],
)
def test_selection_context_is_exact_string_key_map(selected):
    pack, *_ = make_pack()
    with pytest.raises(contract.ContractError):
        proposals.build_request(pack, selected)


def test_two_dependencies_are_whole_separate_copies_and_not_support_verdicts():
    pack, _, request, payload = example()
    result = validate(payload, request).to_dict()
    item = result["items"][0]
    dependencies = item["proposal"]["dependencies"]
    for actual, expected in zip(dependencies, pack["passages"][:2], strict=True):
        assert {key: actual[key] for key in expected} == expected
        assert actual["semantic_support"] == "unknown" and actual["review_required"]
    assert "unless a recall is active" in dependencies[0]["text"]
    assert "Items marked X are excluded." in dependencies[0]["text"]
    assert dependencies[0]["text"] != dependencies[1]["text"]
    for field in (
        "proposal_semantics",
        "primary_relevance",
        "declared_dependency_completeness",
        "undeclared_dependencies",
        "local_sufficiency",
    ):
        assert item[field] == "unknown"
    assert item["review_required"]
    assert result["semantic_support"] == "unknown" and result["semantic_accuracy"] is None
    assert result["manual_review_required"] and result["full_report_coverage"] == "not_evaluated"


def test_both_selected_and_null_sections_may_require_evidence_with_fixed_preview_only():
    _, _, request, payload = example()
    for item in payload["items"]:
        item["proposal"] = {"kind": "requires_evidence"}
    typed = validate(payload, request)
    for item in typed.to_dict()["items"]:
        assert item["proposal"] == {
            "kind": "requires_evidence",
            "application_message": proposals.REQUIRES_EVIDENCE_MESSAGE,
        }
    preview = proposals.render_preview(typed)
    assert preview.count(proposals.REQUIRES_EVIDENCE_MESSAGE) == 3
    assert "Proposal draft" not in preview and "Issue equipment" not in preview
    assert "source synthetic" not in preview


@pytest.mark.parametrize("field", ["text", "declared_refs", "selection_note", "local_unknowns"])
def test_requires_evidence_forbids_every_free_field(field):
    _, _, request, payload = example()
    payload["items"][2]["proposal"][field] = "unverified model text"
    with pytest.raises(contract.ContractError):
        validate(payload, request)


def test_null_primary_cannot_use_other_section_reference_to_display_draft():
    _, _, request, payload = example()
    payload["items"][2]["proposal"] = copy.deepcopy(payload["items"][0]["proposal"])
    with pytest.raises(contract.ContractError, match="selected primary"):
        validate(payload, request)


@pytest.mark.parametrize(
    "refs", [[], ["passage-002"], ["passage-001"] * 2, ["missing"], [True], [""], ["passage-001"] * 4, "passage-001"]
)
def test_explicit_primary_and_dependency_limits(refs):
    _, _, request, payload = example()
    payload["items"][0]["proposal"]["declared_refs"] = refs
    with pytest.raises(contract.ContractError):
        validate(payload, request)


def test_one_to_three_refs_allowed_without_insertion_or_reordering():
    _, _, request, payload = example()
    for refs in (["passage-001"], ["passage-003", "passage-001", "passage-002"]):
        payload["items"][0]["proposal"]["declared_refs"] = refs
        result = validate(payload, request).to_dict()["items"][0]["proposal"]
        assert result["declared_refs"] == refs
        assert [item["passage_ref"] for item in result["dependencies"]] == refs


def test_same_ref_may_be_primary_in_two_sections_and_other_pack_only_ref_is_rejected():
    pack, selected, _, payload = example()
    selected["11"] = selected["7"]
    payload["items"][1]["proposal"] = copy.deepcopy(payload["items"][0]["proposal"])
    request = proposals.build_request(pack, selected)
    assert len(validate(payload, request).to_dict()["items"]) == 3
    other, *_ = make_pack(["One.", "Two.", "Three.", "Four."])
    payload["items"][0]["proposal"]["declared_refs"].append(other["passages"][3]["passage_ref"])
    with pytest.raises(contract.ContractError, match="Unknown"):
        validate(payload, request)


@pytest.mark.parametrize(
    "text",
    [
        "Issue all equipment without inspection even during recall.",
        "The local operator has 20 certified technicians and guaranteed funding.",
    ],
)
def test_negation_flip_or_undeclared_local_dependency_is_not_a_semantic_verdict(text):
    _, _, request, payload = example()
    payload["items"][0]["proposal"]["text"] = text
    item = validate(payload, request).to_dict()["items"][0]
    assert item["proposal"]["text"] == text
    assert item["proposal_semantics"] == item["undeclared_dependencies"] == "unknown"
    assert all(value["semantic_support"] == "unknown" for value in item["proposal"]["dependencies"])
    assert "supported" not in item and "score" not in item


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_section",
        "bool_section",
        "float_section",
        "string_section",
        "missing_section",
        "extra_section",
        "item_extra",
        "root_extra",
        "unknown_kind",
        "draft_extra",
    ],
)
def test_exact_wire_rejects_invalid_sections_and_old_v1_extra_shapes(mutation):
    _, _, request, payload = example()
    if mutation.endswith("section"):
        if mutation == "duplicate_section":
            payload["items"][1]["section_id"] = 7
        elif mutation == "bool_section":
            payload["items"][0]["section_id"] = True
        elif mutation == "float_section":
            payload["items"][0]["section_id"] = 7.0
        elif mutation == "string_section":
            payload["items"][0]["section_id"] = "7"
        elif mutation == "missing_section":
            payload["items"].pop()
        else:
            payload["items"].append(copy.deepcopy(payload["items"][0]))
    elif mutation == "item_extra":
        payload["items"][0]["selected_passage_ref"] = "passage-001"
    elif mutation == "root_extra":
        payload["schema"] = contract.PAYLOAD_SCHEMA
    elif mutation == "unknown_kind":
        payload["items"][0]["proposal"]["kind"] = "approved"
    else:
        payload["items"][0]["proposal"]["source_id"] = "forged"
    with pytest.raises(contract.ContractError):
        validate(payload, request)


@pytest.mark.parametrize(
    "raw",
    [
        '{"items":[],"items":[]}',
        '{"items":NaN}',
        '{"items":Infinity}',
        '```json\n{"items":[]}\n```',
        '{"items":[]} trailing',
        b"\xff",
        "{" + "0" * 17000,
    ],
)
def test_shared_strict_parser_is_not_relaxed(raw):
    _, _, request, _ = example()
    with pytest.raises(contract.ContractError):
        proposals.validate_proposals(raw, request)


@pytest.mark.parametrize("text", ["", " ", "🙂" * 481, "text\x00", "\ud800"])
def test_proposal_node_boundaries_reject_invalid_text(text):
    _, _, request, payload = example()
    payload["items"][0]["proposal"]["text"] = text
    with pytest.raises(contract.ContractError):
        validate(payload, request)


def test_unicode_480_proposal_and_complete_2200_visible_text_and_byte_limits():
    text = "家🙂" * 1100
    pack, *_ = make_pack([text])
    request = proposals.build_request(pack, {"7": "passage-001", "11": None, "12": None})
    _, _, _, payload = example()
    payload["items"][0]["proposal"].update(text="🙂" * 480, declared_refs=["passage-001"])
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    padded = raw + b" " * (contract.MAX_PAYLOAD_BYTES - len(raw))
    result = proposals.validate_proposals(padded, request).to_dict()
    assert result["items"][0]["proposal"]["dependencies"][0]["text"] == text
    assert result["items"][0]["proposal"]["text"] == "🙂" * 480
    with pytest.raises(contract.ContractError, match="byte limit"):
        proposals.validate_proposals(padded + b" ", request)


def test_pack_tampering_and_valid_rehashed_pack_substitution_are_rejected():
    pack, selected, request, payload = example()
    changed = copy.deepcopy(pack)
    changed["passages"][0]["text"] = "Changed text with its own valid hash."
    with pytest.raises(contract.ContractError):
        proposals.build_request(changed, selected)
    changed["passages"][0]["text_sha256"] = text_sha256(changed["passages"][0]["text"])
    rehash_pack(changed)
    replacement = proposals.build_request(changed, selected)
    object.__setattr__(request, "_pack_json", replacement._pack_json)
    object.__setattr__(request, "_request_json", replacement._request_json)
    with pytest.raises(contract.ContractError, match="Frozen request"):
        validate(payload, request)


def test_returned_dicts_are_detached_and_frozen_wrappers_require_validators():
    _, _, request, payload = example()
    typed = validate(payload, request)
    data = typed.to_dict()
    data["items"][0]["proposal"]["dependencies"][0]["text"] = "tampered"
    request.to_dict()["selected_ref_by_section"]["7"] = None
    assert "tampered" not in proposals.render_preview(typed)
    with pytest.raises(FrozenInstanceError):
        typed._json = "{}"
    with pytest.raises(FrozenInstanceError):
        request._request_json = "{}"
    with pytest.raises(TypeError):
        proposals._Request({}, {})
    with pytest.raises(TypeError):
        proposals._ValidatedProposals("{}", request, {})


@pytest.mark.parametrize("mutation", ["source_text", "origin", "raw", "request", "malformed_output"])
def test_renderer_revalidates_private_result_and_original_input_bindings(mutation):
    pack, selected, request, payload = example()
    typed = validate(payload, request)
    if mutation in {"source_text", "origin"}:
        data = typed.to_dict()
        if mutation == "source_text":
            data["items"][0]["proposal"]["dependencies"][0]["text"] = "Injected text"
        else:
            data["origin"] = "remote_model"
        object.__setattr__(typed, "_json", json.dumps(data, ensure_ascii=False, sort_keys=True))
    elif mutation == "raw":
        object.__setattr__(typed, "_raw", typed._raw + " ")
    elif mutation == "request":
        selected["11"] = None
        object.__setattr__(typed, "_request", proposals.build_request(pack, selected))
    else:
        object.__setattr__(typed, "_json", "not JSON")
    with pytest.raises(contract.ContractError):
        proposals.render_preview(typed)


def test_only_new_typed_results_render_and_offline_cannot_attest_remote_response():
    pack, _, request, payload = example()
    typed = validate(payload, request)
    data = typed.to_dict()
    assert data["origin"] == "synthetic_offline" and data["model_calls"] == 0
    assert data["transport_capture"] == "not_performed"
    assert data["production_enabled"] is False and data["release_gate"] == {"active": False}
    assert data["selection_context_origin"] == "application_supplied"
    with pytest.raises(TypeError):
        proposals.render_preview(data)
    with pytest.raises(TypeError):
        proposals.validate_proposals(json.dumps(payload), request.to_dict())
    with pytest.raises(TypeError):
        proposals.validate_proposals(json.dumps(payload), prototype.build_request(pack))
    preview = proposals.render_preview(typed)
    assert "# OFFLINE PROPOSAL REVIEW" in preview and "# NOT REPORT" in preview
    assert "does not attest a historical or remote response" in preview


def test_every_untrusted_preview_field_is_escaped_without_changing_copied_text():
    pack, _, _, payload = example()
    malicious = "<script>x</script> [link](https://example.invalid)\n# Heading\u202e"
    passage = pack["passages"][0]
    passage.update(passage_ref="[ref](evil)", source_id="<source>\u202e", chunk_id="`chunk`", text=malicious)
    passage["text_sha256"] = text_sha256(malicious)
    rehash_pack(pack)
    request = proposals.build_request(pack, {"7": passage["passage_ref"], "11": None, "12": None})
    payload["items"][0]["proposal"].update(text=malicious, declared_refs=[passage["passage_ref"]])
    typed = validate(payload, request)
    assert typed.to_dict()["items"][0]["proposal"]["dependencies"][0]["text"] == malicious
    preview = proposals.render_preview(typed)
    for value in (malicious, passage["passage_ref"], passage["source_id"], passage["chunk_id"]):
        assert contract._safe(value) in preview
    assert "<script>" not in preview and "[link](" not in preview and "\u202e" not in preview
    assert "\n# Heading" not in preview
