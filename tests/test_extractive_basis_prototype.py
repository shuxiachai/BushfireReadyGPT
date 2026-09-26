"""Reusable synthetic development vectors; no real output, holdout, or SDK access."""

import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from scripts import atomic_claim_contract as contract
from scripts import extractive_basis_prototype as prototype
from src.model_evidence import json_sha256
from tests.test_atomic_claim_contract import make_pack

DEV_VECTORS = (
    {
        "name": "contact_owner",
        "unit": "Keep the equipment contact register current. Record a named owner for each entry.",
        "section": 7,
        "choose": True,
        "proposal": "Ask the responsible organisation to nominate an owner for review.",
        "unknowns": ["Who currently owns each contact entry?"],
    },
    {
        "name": "conditions_and_exception",
        "unit": "Issue equipment only after inspection, unless a recall is active. Items marked X are excluded.",
        "section": 7,
        "choose": True,
        "proposal": "Propose a local inspection and recall-check process for human review.",
        "unknowns": ["Has the relevant equipment been inspected?", "Is any applicable recall active?"],
    },
    {
        "name": "accessible_notices",
        "unit": "Publish notices in accessible formats. Ask participants which formats they require.",
        "section": 11,
        "choose": True,
        "proposal": "Propose asking participants about required formats before planning resources.",
        "unknowns": [
            "Which languages and formats are locally required?",
            "How many participants need each format?",
            "What resources are available?",
        ],
    },
    {
        "name": "no_training_unit",
        "unit": "The archive labels storage boxes by year.",
        "section": 12,
        "choose": False,
        "proposal": "Propose an independent review of first-aid training needs.",
        "unknowns": [
            "What training frequency is locally appropriate?",
            "What first-aid capabilities are currently available?",
        ],
    },
)


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


def development_case(vector):
    """Pure helper usable by parent preview review without historical artifacts."""
    pack, *_ = make_pack([vector["unit"]])
    ref = pack["passages"][0]["passage_ref"]
    payload = {"items": []}
    for section in prototype.SECTIONS:
        target = section == vector["section"]
        chosen = target and vector["choose"]
        payload["items"].append(
            {
                "section_id": section,
                "selected_passage_ref": ref if chosen else None,
                "selection_note": None
                if chosen
                else "No unit selected for this synthetic section; relevance needs review.",
                "proposal": vector["proposal"] if target else "Proposed separate local review.",
                "local_unknowns": list(vector["unknowns"]) if target else [],
            }
        )
    return pack, prototype.build_request(pack), payload


@pytest.mark.parametrize("vector", DEV_VECTORS, ids=[item["name"] for item in DEV_VECTORS])
def test_development_vectors_copy_full_unit_and_preserve_unknowns(vector):
    pack, request, payload = development_case(vector)
    typed = prototype.validate_selection(json.dumps(payload), request)
    result = typed.to_dict()
    item = next(row for row in result["items"] if row["section_id"] == vector["section"])
    if vector["choose"]:
        assert item["basis"]["state"] == "unit_selected"
        assert item["basis"]["text"] == pack["passages"][0]["text"] == vector["unit"]
        assert item["basis"]["text_sha256"] == pack["passages"][0]["text_sha256"]
    else:
        assert item["basis"]["state"] == "no_unit_selected" and "text" not in item["basis"]
        assert item["basis"]["selection_note_status"] == "unverified"
    assert item["local_unknowns"]["items"] == vector["unknowns"]
    assert item["proposal"]["text"] == vector["proposal"] and item["proposal"]["review_required"]
    assert item["condition_preservation"] == item["topic_relevance"] == item["local_sufficiency"] == "unknown"
    assert result["original_document_completeness"] == "unknown" and result["semantic_accuracy"] is None
    assert result["unit_complete_scope"] == "recorded_visible_passage_only"
    assert (
        result["model_calls"] == 0
        and result["origin"] == "synthetic_offline"
        and result["transport_capture"] == "not_performed"
    )
    assert result["production_enabled"] is False and result["release_gate"] == {"active": False}
    preview = prototype.render_preview(typed)
    assert (
        "# NOT REPORT" in preview
        and "Local questions and assumptions" in preview
        and "Independent local proposal" in preview
    )
    assert "20 participants" not in preview and "John" not in preview


def test_request_is_neutral_schema_task_without_provider_settings_or_predetermined_choices():
    pack, request, _ = development_case(DEV_VECTORS[0])
    data = request.to_dict()
    assert data["version"] == prototype.REQUEST_VERSION and data["catalog"] == pack["passages"]
    assert data["evidence_pack_sha256"] == pack["evidence_pack_sha256"]
    assert data["request_sha256"] == json_sha256({key: value for key, value in data.items() if key != "request_sha256"})
    assert not {"model", "temperature", "max_tokens", "endpoint", "tools", "messages", "items"}.intersection(data)
    assert [item["section_id"] for item in data["requested_sections"]] == [7, 11, 12]
    schema = data["output_json_schema"]
    assert schema["required"] == ["items"] and schema["additionalProperties"] is False
    assert schema["properties"]["items"]["minItems"] == schema["properties"]["items"]["maxItems"] == 3
    assert set(schema["properties"]["items"]["items"]["required"]) == prototype._ITEM_KEYS
    assert "default" not in json.dumps(schema)


@pytest.mark.parametrize(
    "field", ["basis_text", "quote", "quote_start", "quote_end", "source_id", "schema", "evidence_pack_sha256"]
)
def test_model_cannot_supply_basis_or_application_metadata(field):
    _, request, payload = development_case(DEV_VECTORS[0])
    payload["items"][0][field] = "forged"
    with pytest.raises(contract.ContractError, match="missing or unknown fields"):
        prototype.validate_selection(json.dumps(payload), request)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_ref",
        "duplicate",
        "bool_section",
        "missing_item",
        "extra_item",
        "selected_with_note",
        "empty_selection_without_note",
        "empty_note",
        "bool_ref",
    ],
)
def test_selection_shape_and_null_rules_are_strict(mutation):
    _, request, payload = development_case(DEV_VECTORS[0])
    item = payload["items"][0]
    if mutation == "unknown_ref":
        item["selected_passage_ref"] = "unknown"
    elif mutation == "duplicate":
        payload["items"][1]["section_id"] = 7
    elif mutation == "bool_section":
        item["section_id"] = True
    elif mutation == "missing_item":
        payload["items"].pop()
    elif mutation == "extra_item":
        payload["items"].append(copy.deepcopy(item))
    elif mutation == "selected_with_note":
        item["selection_note"] = "not allowed with a selected ref"
    elif mutation == "empty_selection_without_note":
        item["selected_passage_ref"] = None
    elif mutation == "empty_note":
        payload["items"][1]["selection_note"] = " "
    else:
        item["selected_passage_ref"] = False
    with pytest.raises(contract.ContractError):
        prototype.validate_selection(json.dumps(payload), request)


@pytest.mark.parametrize("field,limit", [("proposal", 480), ("selection_note", 280), ("local_unknowns", 160)])
def test_text_limits_accept_boundary_and_reject_overflow(field, limit):
    _, request, payload = development_case(DEV_VECTORS[3])
    item = payload["items"][0]
    item[field] = ["x" * limit] if field == "local_unknowns" else "x" * limit
    prototype.validate_selection(json.dumps(payload), request)
    item[field] = ["x" * (limit + 1)] if field == "local_unknowns" else "x" * (limit + 1)
    with pytest.raises(contract.ContractError, match="bounded text"):
        prototype.validate_selection(json.dumps(payload), request)


def test_unknown_list_limit_and_empty_list_never_mean_local_sufficiency():
    _, request, payload = development_case(DEV_VECTORS[3])
    payload["items"][0]["local_unknowns"] = ["Unverified question?"] * 3
    result = prototype.validate_selection(json.dumps(payload), request).to_dict()
    assert result["items"][1]["local_unknowns"]["status"] == "not_listed"
    assert result["items"][1]["local_sufficiency"] == "unknown"
    payload["items"][0]["local_unknowns"].append("Fourth question?")
    with pytest.raises(contract.ContractError, match="zero to three"):
        prototype.validate_selection(json.dumps(payload), request)


def test_full_2200_unicode_unit_is_copied_without_cutting_and_ref_reuse_is_allowed():
    full = "家🙂" * 1100
    pack, *_ = make_pack([full])
    request = prototype.build_request(pack)
    _, _, payload = development_case(DEV_VECTORS[0])
    for item in payload["items"]:
        item.update(selected_passage_ref=pack["passages"][0]["passage_ref"], selection_note=None)
    result = prototype.validate_selection(json.dumps(payload), request).to_dict()
    assert len(pack["passages"][0]["text"]) == 2200
    assert all(item["basis"]["text"] == full for item in result["items"])
    assert all(item["topic_relevance"] == "unknown" for item in result["items"])


def test_irrelevant_unit_and_unverified_note_do_not_produce_semantic_findings():
    pack, request, payload = development_case(DEV_VECTORS[3])
    payload["items"][2].update(selected_passage_ref=pack["passages"][0]["passage_ref"], selection_note=None)
    result = prototype.validate_selection(json.dumps(payload), request).to_dict()
    assert result["items"][2]["basis"]["text"] == DEV_VECTORS[3]["unit"]
    assert result["items"][2]["topic_relevance"] == "unknown"
    payload["items"][2].update(
        selected_passage_ref=None, selection_note="No source anywhere contains useful training evidence."
    )
    row = prototype.validate_selection(json.dumps(payload), request).to_dict()["items"][2]
    assert row["basis"]["state"] == "no_unit_selected" and row["basis"]["selection_note_status"] == "unverified"
    assert row["local_sufficiency"] == "unknown"


@pytest.mark.parametrize(
    "raw",
    [
        '{"items":[],"items":[]}',
        '{"items":NaN}',
        "```json\n{}\n```",
        '{"schema":"atomic-claim-selection-v1","evidence_pack_sha256":"x","items":[]}',
        '{"schema":"atomic-claim-contract-v1","items":[]}',
        'prefix {"items":[]}',
    ],
)
def test_old_wire_and_non_strict_json_are_rejected(raw):
    _, request, _ = development_case(DEV_VECTORS[0])
    with pytest.raises(contract.ContractError):
        prototype.validate_selection(raw, request)


def test_oversized_raw_payload_is_rejected():
    _, request, payload = development_case(DEV_VECTORS[0])
    with pytest.raises(contract.ContractError, match="byte limit"):
        prototype.validate_selection(" " * 16384 + json.dumps(payload), request)


def test_request_pack_drift_and_forged_dict_are_rejected():
    pack, request, payload = development_case(DEV_VECTORS[0])
    changed_pack = copy.deepcopy(pack)
    changed_pack["passages"][0]["text"] += " changed"
    with pytest.raises(contract.ContractError):
        prototype.build_request(changed_pack)
    with pytest.raises(TypeError, match="build_request"):
        prototype.validate_selection(json.dumps(payload), request.to_dict())
    changed_request = request.to_dict()
    changed_request["request_sha256"] = "0" * 64
    object.__setattr__(request, "_request_json", json.dumps(changed_request))
    with pytest.raises(contract.ContractError, match="Request hash or catalog"):
        prototype.validate_selection(json.dumps(payload), request)
    request = prototype.build_request(pack)
    object.__setattr__(request, "_pack_json", json.dumps(changed_pack))
    with pytest.raises(contract.ContractError):
        prototype.validate_selection(json.dumps(payload), request)


def test_immutable_copies_do_not_allow_unvalidated_rendering_or_mutate_full_basis():
    pack, request, payload = development_case(DEV_VECTORS[0])
    data = request.to_dict()
    data["catalog"][0]["text"] = "external copy edit"
    result = prototype.validate_selection(json.dumps(payload), request)
    copy_result = result.to_dict()
    copy_result["items"][0]["basis"]["text"] = "invented replacement"
    assert result.to_dict()["items"][0]["basis"]["text"] == pack["passages"][0]["text"]
    assert "invented replacement" not in prototype.render_preview(result)
    with pytest.raises(TypeError, match="validate_selection"):
        prototype.render_preview(copy_result)
    with pytest.raises(TypeError):
        prototype._Selection(copy_result)
    with pytest.raises(TypeError):
        prototype._Request(pack, data)
    with pytest.raises(FrozenInstanceError):
        result._json = "{}"
    with pytest.raises(FrozenInstanceError):
        request._request_json = "{}"


def test_renderer_escapes_unit_metadata_notes_proposals_unknowns_and_controls():
    attack = "<img src=x>\n# forged\n[link](https://evil.test) `code`\u202e"
    pack, *_ = make_pack([attack], source_id="source<img>", chunk_prefix="[chunk](https://evil.test)")
    request = prototype.build_request(pack)
    _, _, payload = development_case(DEV_VECTORS[0])
    for item in payload["items"]:
        item["proposal"] = attack
        item["local_unknowns"] = [attack]
        if item["selected_passage_ref"] is None:
            item["selection_note"] = attack
    preview = prototype.render_preview(prototype.validate_selection(json.dumps(payload), request))
    for unsafe in ("<img", "\n# forged", "[link](", "https://", "`code`", "\u202e"):
        assert unsafe not in preview
    assert "source&lt;img&gt;" in preview and "Unverified selection explanation" in preview
    proposal = preview.split("### Independent local proposal", 1)[1].split("## Section", 1)[0]
    assert "Reference " not in proposal
