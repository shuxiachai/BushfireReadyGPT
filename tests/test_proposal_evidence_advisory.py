"""Synthetic tests for proposal lexical advisory; no network, SDK, or environment access."""

import ast
import difflib
import json
from pathlib import Path

import pytest

from scripts import atomic_claim_contract as contract
from scripts import proposal_evidence_advisory as advisory
from scripts import proposal_evidence_contract as proposals
from src.model_evidence import json_sha256, text_sha256
from tests.test_atomic_claim_contract import make_pack


def _case(texts, drafts=None, selected=None):
    pack, *_ = make_pack(texts)
    refs = [passage["passage_ref"] for passage in pack["passages"]]
    selected = selected or {"7": refs[0], "11": refs[1] if len(refs) > 1 else None, "12": None}
    request = proposals.build_request(pack, selected)
    drafts = drafts or {7: "Inspect equipment only after approval, unless a recall is active.", 11: None, 12: None}
    items = []
    for section in (7, 11, 12):
        text = drafts.get(section)
        if text is None:
            proposal = {"kind": "requires_evidence"}
        else:
            ref = selected[str(section)]
            proposal = {"kind": "draft_for_review", "text": text, "declared_refs": [ref]}
        items.append({"section_id": section, "proposal": proposal})
    return pack, request, json.dumps({"items": items}, ensure_ascii=False)


def _review(*args, **kwargs):
    _, request, raw = _case(*args, **kwargs)
    return advisory.review_proposals(raw, request)


def test_marker_differences_and_exception_scope_are_review_only():
    result = _review(["Issue equipment only after inspection, unless a recall is active.", "Other source."])
    marker = result["items"][0]["declared_dependencies"][0]["marker_review"]
    assert "unless" in marker["source_markers"]["condition"]
    assert marker["exception_scope_review_required"]
    assert marker["semantic_or_condition_verdict"] == "not_provided"
    changed = _review(
        ["Issue equipment only after inspection, unless a recall is active.", "Other source."],
        {7: "Issue equipment only after inspection, except when recalled."},
    )
    assert changed["items"][0]["declared_dependencies"][0]["marker_review"]["exception_scope_review_required"]
    deleted = _review(
        ["Issue equipment only after inspection, unless a recall is active.", "Other source."],
        {7: "Issue equipment after inspection."},
    )
    deleted_marker = deleted["items"][0]["declared_dependencies"][0]["marker_review"]
    assert "unless" in deleted_marker["marker_difference"]["condition"]["source_only"]
    assert deleted_marker["exception_scope_review_required"]


@pytest.mark.parametrize("exception", ["unless", "except"])
def test_unchanged_exception_marker_still_requires_scope_review(exception):
    text = f"Issue equipment after inspection {exception} when a recall is active."
    result = _review([text, "Other source."], {7: text})
    marker = result["items"][0]["declared_dependencies"][0]["marker_review"]
    assert all(
        difference == {"proposal_only": [], "source_only": []} for difference in marker["marker_difference"].values()
    )
    assert marker["exception_scope_review_required"] is True
    assert marker["semantic_or_condition_verdict"] == "not_provided"
    assert result["condition_preservation"] == result["semantic_support"] == "unknown"


def test_same_markers_and_synonyms_do_not_become_approval():
    result = _review(
        ["Do not issue equipment unless inspected.", "Other source."],
        {7: "Do not distribute equipment unless checked."},
    )
    marker = result["items"][0]["declared_dependencies"][0]["marker_review"]
    assert marker["marker_difference"]["negation"] == {"proposal_only": [], "source_only": []}
    assert result["semantic_support"] == result["condition_preservation"] == "unknown"
    assert result["manual_review_required"]
    scope_changed = _review(
        ["Not all operators have completed the inspection.", "Other source."],
        {7: "All operators have not completed the inspection."},
    )
    marker = scope_changed["items"][0]["declared_dependencies"][0]["marker_review"]
    assert all(
        difference == {"proposal_only": [], "source_only": []} for difference in marker["marker_difference"].values()
    )
    assert scope_changed["condition_preservation"] == "unknown"


def test_each_declared_dependency_is_compared_separately():
    pack, request, raw = _case(["Do not issue equipment.", "Issue equipment only after inspection."])
    payload = json.loads(raw)
    payload["items"][0]["proposal"]["declared_refs"] = ["passage-001", "passage-002"]
    result = advisory.review_proposals(json.dumps(payload), request)
    dependencies = result["items"][0]["declared_dependencies"]
    assert len(dependencies) == 2
    assert dependencies[0]["marker_review"]["source_markers"]["negation"] == ["not"]
    assert dependencies[1]["marker_review"]["source_markers"]["condition"] == ["after", "only"]


def test_cross_section_duplicate_rules_are_lexical_and_bounded():
    long = "Review emergency equipment records before each exercise and document responsible staff and required maintenance actions"
    near = "review emergency equipment records before each exercise and document responsible staff with required maintenance actions"
    different = "Publish accessible communication formats after consultation with participants and record preferences for each information channel"
    result = _review(["source seven", "source eleven"], {7: long, 11: near, 12: None})
    assert result["cross_section_duplicate_review"][0]["section_ids"] == [7, 11]
    assert not _review(["source seven", "source eleven"], {7: long, 11: different, 12: None})[
        "cross_section_duplicate_review"
    ]
    assert not _review(
        ["source seven", "source eleven"], {7: "Same disclaimer applies.", 11: "Same disclaimer applies.", 12: None}
    )["cross_section_duplicate_review"]
    pack, request, raw = _case(
        ["shared source", "other"], {7: long, 11: long, 12: None}, {"7": "passage-001", "11": "passage-001", "12": None}
    )
    assert advisory.review_proposals(raw, request)["cross_section_duplicate_review"]
    _, request, raw = _case(
        ["shared source", "other"],
        {7: long, 11: different, 12: None},
        {"7": "passage-001", "11": "passage-001", "12": None},
    )
    assert not advisory.review_proposals(raw, request)["cross_section_duplicate_review"]


def test_bytes_and_text_raw_have_identical_advisory_data():
    _, request, raw = _case(["Source text.", "Other source."])
    assert advisory.review_proposals(raw, request) == advisory.review_proposals(raw.encode("utf-8"), request)


def test_threshold_boundary_and_requires_evidence_do_not_participate():
    words = "one two three four five six seven eight nine ten eleven twelve"
    near = "one two three four five six seven eight nine ten eleven changed"
    _, request, raw = _case(["one", "two"], {7: words, 11: near, 12: None})
    assert advisory.review_proposals(raw, request)["cross_section_duplicate_review"]
    below = "one two three four five six seven eight nine ten eleven"
    _, request, raw = _case(["one", "two"], {7: below, 11: below, 12: None})
    assert not advisory.review_proposals(raw, request)["cross_section_duplicate_review"]
    below_ratio = "one two three four five six changed eight nine ten changed changed"
    _, request, raw = _case(["one", "two"], {7: words, 11: below_ratio, 12: None})
    assert not advisory.review_proposals(raw, request)["cross_section_duplicate_review"]


def test_common_long_disclaimer_can_be_a_false_positive_review_clue():
    disclaimer = "subject to local approvals and available resources with independent human review required before any operational action begins with documented local authorization"
    left = "Inspect equipment records " + disclaimer
    right = "Publish community notices " + disclaimer
    expected_ratio = difflib.SequenceMatcher(
        None, left.casefold().split(), right.casefold().split(), autojunk=False
    ).ratio()
    assert expected_ratio >= 0.85
    result = _review(["source one", "source two"], {7: left, 11: right, 12: None})
    assert result["cross_section_duplicate_review"][0]["sequence_ratio"] == pytest.approx(expected_ratio)
    assert any("falsely flag shared disclaimers" in note for note in result["limitations"])
    assert result["semantic_support"] == result["condition_preservation"] == "unknown"


@pytest.mark.parametrize("matching_tokens,expected_ratio,listed", [(16, 0.8, False), (17, 0.85, True), (18, 0.9, True)])
def test_fixed_ratio_threshold_is_inclusive_without_semantic_approval(matching_tokens, expected_ratio, listed):
    left = [f"word{index}" for index in range(20)]
    right = left[:matching_tokens] + [f"changed{index}" for index in range(matching_tokens, 20)]
    assert difflib.SequenceMatcher(None, left, right, autojunk=False).ratio() == expected_ratio
    result = _review(["source one", "source two"], {7: " ".join(left), 11: " ".join(right)})
    findings = result["cross_section_duplicate_review"]
    assert bool(findings) is listed
    assert result["duplicate_diagnostic"]["sequence_ratio_threshold"] == 0.85
    assert result["duplicate_diagnostic"]["minimum_word_tokens"] == 12
    if listed:
        assert findings[0]["word_counts"] == [20, 20]
        assert findings[0]["sequence_ratio"] == expected_ratio
    assert result["semantic_support"] == "unknown" and result["semantic_accuracy"] is None


def test_requires_evidence_has_no_dependencies_or_duplicate_and_no_origin_attestation():
    result = _review(["Source text."], {7: None, 11: None, 12: None})
    assert all(item["proposal"]["kind"] == "requires_evidence" for item in result["items"])
    assert all(item["declared_dependencies"] == [] for item in result["items"])
    assert result["cross_section_duplicate_review"] == []
    assert result["additional_model_calls"] == 0 and result["new_transport_capture"] is False
    assert result["input_origin"] == "caller_supplied_revalidated"
    assert result["request_origin_attestation"] == "not_performed"
    assert result["semantic_support"] == result["declared_dependency_completeness"] == "unknown"


def test_empty_selection_cannot_be_used_to_show_a_draft():
    _, request, raw = _case(
        ["Source text.", "Other source."], {7: "Draft text", 11: None, 12: None}, {"7": None, "11": None, "12": None}
    )
    with pytest.raises(contract.ContractError):
        advisory.review_proposals(raw, request)


def test_tampered_typed_request_binding_is_rejected():
    _, request, raw = _case(["Source text.", "Other source."])
    object.__setattr__(request, "_binding_sha256", "0" * 64)
    with pytest.raises(contract.ContractError):
        advisory.review_proposals(raw, request)


def test_hashes_detachment_and_strict_input_types():
    pack, request, raw = _case(["Source text.", "Other source."])
    original_render = advisory.render_advisory(raw, request)
    result = advisory.review_proposals(raw, request)
    assert result["schema"] == advisory.SCHEMA
    assert result["request_sha256"] == request.to_dict()["request_sha256"]
    assert result["evidence_pack_sha256"] == pack["evidence_pack_sha256"]
    assert result["raw_proposals_sha256"] == text_sha256(raw)
    result["items"][0]["proposal"]["text"] = "tampered"
    result["items"][0]["declared_dependencies"][0]["dependency"]["text"] = "tampered source"
    result["semantic_support"] = "forged approval"
    result["cross_section_duplicate_review"].append({"forged": True})
    assert advisory.review_proposals(raw, request)["items"][0]["proposal"]["text"] != "tampered"
    assert advisory.render_advisory(raw, request) == original_render
    with pytest.raises((TypeError, contract.ContractError)):
        advisory.review_proposals(result, request)
    with pytest.raises(TypeError):
        advisory.review_proposals(raw, request.to_dict())
    with pytest.raises(contract.ContractError):
        advisory.review_proposals("{bad", request)


def test_renderer_escapes_untrusted_nodes_and_revalidates_raw():
    attack = "<img src=x>\n# forged [link](https://evil.test)\u202e"
    pack, request, raw = _case([attack, "Other source."], {7: attack, 11: None, 12: None})
    payload = json.loads(raw)
    payload["items"][0]["proposal"]["declared_refs"] = [pack["passages"][0]["passage_ref"]]
    rendered = advisory.render_advisory(json.dumps(payload), request)
    for dangerous in ("<img", "\n# forged", "[link](", "https://", "\u202e"):
        assert dangerous not in rendered
    assert contract._safe(attack) in rendered
    with pytest.raises((TypeError, contract.ContractError)):
        advisory.render_advisory(advisory.review_proposals(raw, request), request)


def test_renderer_escapes_dependency_identifiers():
    attack = "<img src=x>\n# forged [link](https://evil.test)\u202e"
    pack, *_ = make_pack(["Visible source text.", "Other source."], source_id=attack, chunk_prefix=attack)
    passage = pack["passages"][0]
    passage["passage_ref"] = attack
    passage["text_sha256"] = text_sha256(passage["text"])
    pack["evidence_pack_sha256"] = json_sha256(
        {key: value for key, value in pack.items() if key != "evidence_pack_sha256"}
    )
    request = proposals.build_request(pack, {"7": attack, "11": None, "12": None})
    raw = json.dumps(
        {
            "items": [
                {
                    "section_id": 7,
                    "proposal": {"kind": "draft_for_review", "text": "Draft text", "declared_refs": [attack]},
                },
                {"section_id": 11, "proposal": {"kind": "requires_evidence"}},
                {"section_id": 12, "proposal": {"kind": "requires_evidence"}},
            ]
        }
    )
    rendered = advisory.render_advisory(raw, request)
    for dangerous in ("<img", "\n# forged", "[link](", "https://", "\u202e"):
        assert dangerous not in rendered
    assert contract._safe(attack) in rendered


def test_module_has_no_sdk_environment_or_network_imports_or_calls():
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
    calls = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    calls.update(
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    )
    assert not imported & forbidden
    assert not {"getenv", "load_dotenv", "get", "post", "request", "connect", "open", "read_text", "read_bytes"} & calls
