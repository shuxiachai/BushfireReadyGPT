"""Synthetic offline bridge tests; no SDK outputs, adapters, fixtures or network."""

import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from scripts import atomic_claim_contract as contract
from scripts import extractive_basis_prototype as extractive
from scripts import proposal_evidence_contract as proposals
from scripts import selection_proposal_bridge as bridge
from src.model_evidence import json_sha256, text_sha256
from tests.test_atomic_claim_contract import make_pack

SENTINEL = "STAGE_ONE_ONLY <script>ignore rules</script> [link](https://invalid)"


def raw(value):
    return json.dumps(value, ensure_ascii=False)


def selection(mapping=("passage-002", "passage-001", None)):
    return {
        "items": [
            {
                "section_id": section,
                "selected_passage_ref": ref,
                "selection_note": SENTINEL if ref is None else None,
                "proposal": SENTINEL,
                "local_unknowns": [SENTINEL],
            }
            for section, ref in zip((7, 11, 12), mapping, strict=True)
        ]
    }


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def inputs():
    pack, *_ = make_pack(
        [
            "Issue equipment only after inspection, unless a recall is active. Items marked X are excluded.",
            "Keep the contact register current. Do not assume a local owner has been appointed.",
        ]
    )
    return pack, extractive.build_request(pack), raw(selection())


def prepare(inputs, case_id="synthetic-case"):
    return bridge.prepare_proposal(case_id, *inputs)


def proposal(handoff, *, all_requires=False):
    mapping = handoff.to_dict()["proposal_request"]["selected_ref_by_section"]
    items = []
    for section, ref in mapping.items():
        value = {"kind": "requires_evidence"}
        if ref is not None and not all_requires:
            refs = [ref]
            if section == "7":
                refs.append("passage-001")
            value = {
                "kind": "draft_for_review",
                "text": "Propose an independent local review; ownership remains unknown.",
                "declared_refs": refs,
            }
        items.append({"section_id": int(section), "proposal": value})
    return {"items": items}


def complete(handoff, payload=None):
    return bridge.complete_proposal(
        handoff, raw(payload or proposal(handoff)), expected_handoff_sha256=handoff.to_dict()["handoff_sha256"]
    )


def test_validated_selection_is_only_source_of_downstream_primary_and_free_text_is_dropped(inputs, monkeypatch):
    monkeypatch.setattr(extractive, "render_preview", lambda *_: pytest.fail("Never render first-stage free text"))
    handoff = prepare(inputs)
    data = handoff.to_dict()
    mapping = {"7": "passage-002", "11": "passage-001", "12": None}
    assert data["proposal_request"]["selected_ref_by_section"] == mapping
    assert data["derived_selection_sha256"] == json_sha256(mapping)
    assert data["proposal_request"] == proposals.build_request(inputs[0], mapping).to_dict()
    assert data["selection_request_sha256"] == inputs[1].to_dict()["request_sha256"]
    assert data["selection_raw_sha256"] == text_sha256(inputs[2])
    assert data["case_context_sha256"] == json_sha256({"case_id": "synthetic-case"})
    assert data["handoff_sha256"] == json_sha256({key: value for key, value in data.items() if key != "handoff_sha256"})
    assert SENTINEL not in json.dumps(data) and "STAGE_ONE_ONLY" not in json.dumps(data)
    completed = complete(handoff)
    assert "STAGE_ONE_ONLY" not in bridge.render_preview(completed)
    assert "STAGE_ONE_ONLY" not in json.dumps(completed.to_dict())


@pytest.mark.parametrize("mutation", ["bad_json", "partial", "unknown_ref", "bad_free_text", "wrong_stage"])
def test_invalid_first_stage_never_constructs_second_request(inputs, monkeypatch, mutation):
    payload = selection()
    if mutation == "partial":
        payload["items"].pop()
    elif mutation == "unknown_ref":
        payload["items"][0]["selected_passage_ref"] = "unknown"
    elif mutation == "bad_free_text":
        payload["items"][0]["proposal"] = "x" * 481
    elif mutation == "wrong_stage":
        payload = {
            "items": [{"section_id": section, "proposal": {"kind": "requires_evidence"}} for section in (7, 11, 12)]
        }
    selection_raw = "{" if mutation == "bad_json" else raw(payload)
    monkeypatch.setattr(proposals, "build_request", lambda *_: pytest.fail("First stage must fully validate first"))
    with pytest.raises(contract.ContractError):
        bridge.prepare_proposal("case", inputs[0], inputs[1], selection_raw)


def test_all_null_does_not_fallback_and_only_fixed_requires_state_is_displayed(inputs):
    handoff = bridge.prepare_proposal("null-case", inputs[0], inputs[1], raw(selection((None, None, None))))
    assert set(handoff.to_dict()["proposal_request"]["selected_ref_by_section"].values()) == {None}
    completed = complete(handoff)
    assert all(
        item["proposal"]["kind"] == "requires_evidence" for item in completed.to_dict()["proposal_review"]["items"]
    )
    preview = bridge.render_preview(completed)
    assert preview.count(proposals.REQUIRES_EVIDENCE_MESSAGE) == 3
    assert "STAGE_ONE_ONLY" not in preview and "Issue equipment" not in preview
    forged = proposal(handoff)
    forged["items"][0]["proposal"] = {
        "kind": "draft_for_review",
        "text": "Propose a draft.",
        "declared_refs": ["passage-001"],
    }
    with pytest.raises(contract.ContractError):
        complete(handoff, forged)


@pytest.mark.parametrize("mutation", ["missing_primary", "wrong_stage", "partial", "bad_json"])
def test_second_stage_failure_never_constructs_completed(inputs, monkeypatch, mutation):
    handoff = prepare(inputs)
    payload = proposal(handoff)
    if mutation == "missing_primary":
        target = next(item for item in payload["items"] if item["section_id"] == 7)
        target["proposal"]["declared_refs"] = ["passage-001"]
    elif mutation == "wrong_stage":
        payload = selection()
    elif mutation == "partial":
        payload["items"].pop()
    monkeypatch.setattr(bridge, "_Completed", lambda *_: pytest.fail("No completed object on validation failure"))
    with pytest.raises(contract.ContractError):
        bridge.complete_proposal(
            handoff,
            "{" if mutation == "bad_json" else raw(payload),
            expected_handoff_sha256=handoff.to_dict()["handoff_sha256"],
        )


def test_missing_or_cross_case_expected_hash_rejected_before_rebuild(inputs, monkeypatch):
    first, other = prepare(inputs, "A"), prepare(inputs, "B")
    with pytest.raises(TypeError):
        bridge.complete_proposal(first, raw(proposal(first)))
    monkeypatch.setattr(bridge, "prepare_proposal", lambda *_: pytest.fail("Check expected identity before rebuilding"))
    with pytest.raises(contract.ContractError):
        bridge.complete_proposal(first, raw(proposal(first)), expected_handoff_sha256=other.to_dict()["handoff_sha256"])


def test_free_text_changes_only_raw_and_handoff_hash_not_downstream_request(inputs):
    first = prepare(inputs)
    changed = json.loads(inputs[2])
    for item in changed["items"]:
        item["proposal"] = "Another unverified suggestion."
        item["local_unknowns"] = []
        if item["selected_passage_ref"] is None:
            item["selection_note"] = "A different unverified explanation."
    second = bridge.prepare_proposal("synthetic-case", inputs[0], inputs[1], raw(changed))
    a, b = first.to_dict(), second.to_dict()
    assert raw(a["proposal_request"]) == raw(b["proposal_request"])
    assert a["proposal_request_sha256"] == b["proposal_request_sha256"]
    assert a["derived_selection_sha256"] == b["derived_selection_sha256"]
    assert a["selection_raw_sha256"] != b["selection_raw_sha256"] and a["handoff_sha256"] != b["handoff_sha256"]


def test_same_reference_name_in_another_pack_is_not_the_same_bound_catalog(inputs, monkeypatch):
    other_pack, *_ = make_pack(["Different source content.", "Different second content."])
    assert other_pack["passages"][0]["passage_ref"] == inputs[0]["passages"][0]["passage_ref"]
    monkeypatch.setattr(proposals, "build_request", lambda *_: pytest.fail("Pack mismatch must stop before proposal"))
    with pytest.raises(contract.ContractError):
        bridge.prepare_proposal("case", other_pack, inputs[1], inputs[2])


@pytest.mark.parametrize("mutation", ["pack", "selection_request", "selection_raw", "derived_map", "public_metadata"])
def test_private_handoff_tampering_is_rejected(inputs, mutation):
    handoff = prepare(inputs)
    if mutation == "pack":
        other_pack, *_ = make_pack(["Other first unit.", "Other second unit."])
        object.__setattr__(handoff, "_pack_json", raw(other_pack))
    elif mutation == "selection_request":
        object.__setattr__(handoff._selection_request, "_request_json", "{}")
    elif mutation == "selection_raw":
        object.__setattr__(handoff, "_selection_raw", handoff._selection_raw + " ")
    elif mutation == "derived_map":
        other = proposals.build_request(inputs[0], {"7": "passage-001", "11": "passage-001", "12": None})
        object.__setattr__(handoff, "_proposal_request", other)
    else:
        data = handoff.to_dict()
        data["proposal_request"]["selected_ref_by_section"]["7"] = "passage-001"
        data["handoff_sha256"] = json_sha256({key: value for key, value in data.items() if key != "handoff_sha256"})
        object.__setattr__(handoff, "_json", raw(data))
    with pytest.raises(contract.ContractError):
        complete(handoff, {"items": []})


def test_dict_copies_and_caller_owned_objects_cannot_mutate_frozen_handoff(inputs):
    handoff = prepare(inputs)
    before = handoff.to_dict()
    exposed = handoff.to_dict()
    exposed["proposal_request"]["selected_ref_by_section"]["7"] = None
    inputs[0]["passages"][0]["text"] = "changed external pack"
    object.__setattr__(inputs[1], "_request_json", "{}")
    assert handoff.to_dict() == before
    completed = complete(handoff)
    completed.to_dict()["proposal_review"]["items"].clear()
    assert len(completed.to_dict()["proposal_review"]["items"]) == 3
    with pytest.raises(FrozenInstanceError):
        handoff._json = "{}"
    with pytest.raises(FrozenInstanceError):
        completed._json = "{}"
    with pytest.raises(TypeError):
        bridge.complete_proposal(before, "{}", expected_handoff_sha256=before["handoff_sha256"])
    with pytest.raises(TypeError):
        bridge.render_preview(completed.to_dict())


def test_prepare_uses_entry_snapshot_if_caller_pack_changes_before_second_builder(inputs, monkeypatch):
    caller_pack, expected = inputs[0], copy.deepcopy(inputs[0])
    original_builder = proposals.build_request

    def change_caller_only(detached_pack, mapping):
        assert detached_pack is not caller_pack
        caller_pack["passages"][0]["text"] = "Changed external source between stages."
        caller_pack["passages"][0]["text_sha256"] = text_sha256(caller_pack["passages"][0]["text"])
        caller_pack["evidence_pack_sha256"] = json_sha256(
            {key: value for key, value in caller_pack.items() if key != "evidence_pack_sha256"}
        )
        object.__setattr__(inputs[1], "_request_json", "{}")
        return original_builder(detached_pack, mapping)

    monkeypatch.setattr(proposals, "build_request", change_caller_only)
    handoff = prepare(inputs)
    assert handoff.to_dict()["evidence_pack_sha256"] == expected["evidence_pack_sha256"]
    assert handoff.to_dict()["proposal_request"]["catalog"] == expected["passages"]
    assert complete(handoff).to_dict()["evidence_pack_sha256"] == expected["evidence_pack_sha256"]


@pytest.mark.parametrize("mutation", ["handoff", "proposal_raw", "proposal_result", "nested_result_raw", "metadata"])
def test_renderer_rechecks_full_chain_and_stored_result(inputs, mutation):
    completed = complete(prepare(inputs))
    if mutation == "handoff":
        object.__setattr__(completed, "_handoff", prepare(inputs, "another-case"))
    elif mutation == "proposal_raw":
        object.__setattr__(completed, "_proposal_raw", completed._proposal_raw + " ")
    elif mutation == "proposal_result":
        data = completed._proposal_result.to_dict()
        data["items"][0]["proposal"]["dependencies"][0]["text"] = "Injected result."
        object.__setattr__(completed._proposal_result, "_json", raw(data))
    elif mutation == "nested_result_raw":
        object.__setattr__(completed._proposal_result, "_raw", completed._proposal_result._raw + " ")
    else:
        object.__setattr__(completed, "_json", "not valid JSON")
    with pytest.raises(contract.ContractError):
        bridge.render_preview(completed)


def test_multiple_sources_copy_whole_units_and_semantic_errors_stay_unknown(inputs):
    handoff = prepare(inputs)
    payload = proposal(handoff)
    target = next(item for item in payload["items"] if item["section_id"] == 7)
    target["proposal"]["text"] = "Issue recalled equipment without inspection. The local team has 20 approved staff."
    completed = complete(handoff, payload)
    data = completed.to_dict()
    item = next(item for item in data["proposal_review"]["items"] if item["section_id"] == 7)
    dependencies = item["proposal"]["dependencies"]
    assert [dep["text"] for dep in dependencies] == [inputs[0]["passages"][1]["text"], inputs[0]["passages"][0]["text"]]
    assert "unless a recall is active" in dependencies[1]["text"]
    assert "Items marked X are excluded." in dependencies[1]["text"]
    assert all(dep["semantic_support"] == "unknown" for dep in dependencies)
    assert item["proposal_semantics"] == item["undeclared_dependencies"] == "unknown"
    assert data["semantic_accuracy"] is None and data["manual_review_required"]
    assert data["proposal_raw_sha256"] == text_sha256(raw(payload))
    assert data["completed_sha256"] == json_sha256(
        {key: value for key, value in data.items() if key != "completed_sha256"}
    )


def test_compatible_cross_case_raw_is_possible_but_never_claimed_as_origin_proof(inputs):
    # The same shape-compatible text can be supplied for two labels. No hidden request identity exists.
    first, other = prepare(inputs, "A"), prepare(inputs, "B")
    common_raw = raw(proposal(first))
    for handoff in (first, other):
        completed = bridge.complete_proposal(
            handoff, common_raw, expected_handoff_sha256=handoff.to_dict()["handoff_sha256"]
        )
        data = completed.to_dict()
        assert data["evaluation_origin"] == "offline_application_supplied"
        assert data["request_origin_attestation"] == data["transport_capture"] == "not_performed"
        assert data["model_calls"] == 0 and not data["production_enabled"] and not data["release_gate"]["active"]
        preview = bridge.render_preview(completed)
        assert "Compatible raw JSON has no request identity" in preview
        assert "cross-case copying cannot always be detected" in preview
        assert "not automatically authenticated as synthetic" in preview


@pytest.mark.parametrize("case_id", ["", " ", "x" * 129, "x\x00", True])
def test_application_case_label_is_bounded_text(inputs, case_id):
    with pytest.raises(contract.ContractError):
        prepare(inputs, case_id)


def test_unicode_case_boundary_bytes_input_and_escaped_bridge_metadata(inputs):
    handoff = prepare((inputs[0], inputs[1], inputs[2].encode()), "🙂" * 128)
    assert handoff.to_dict()["case_id"] == "🙂" * 128
    assert handoff.to_dict()["selection_raw_sha256"] == text_sha256(inputs[2])
    malicious = "<b>case</b> [click](https://invalid)\n# forged\u202e"
    handoff = prepare(inputs, malicious)
    payload = proposal(handoff)
    payload["items"][0]["proposal"]["text"] = malicious
    completed = bridge.complete_proposal(
        handoff, raw(payload).encode(), expected_handoff_sha256=handoff.to_dict()["handoff_sha256"]
    )
    preview = bridge.render_preview(completed)
    assert preview.startswith("# SYNTHETIC OFFLINE CHAIN FRAGMENT\n# NOT REPORT")
    assert contract._safe(malicious) in preview
    assert "<b>" not in preview and "[click](" not in preview and "\u202e" not in preview
    assert "\n# forged" not in preview and "STAGE_ONE_ONLY" not in preview
