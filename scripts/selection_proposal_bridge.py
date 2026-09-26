"""Pure offline contract bridge; hashes associate records, not model requests.

Compatible raw JSON carries no request identity. This module cannot establish its
origin or detect every cross-case copy. Frozen wrappers guard misuse/drift, not
arbitrary local Python control. No SDK, scheduler, migration or report is provided.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

from scripts import atomic_claim_contract as contract
from scripts import extractive_basis_prototype as extractive
from scripts import proposal_evidence_contract as proposals
from src.model_evidence import json_sha256

HANDOFF_VERSION = "selection-proposal-handoff-v1"
COMPLETED_VERSION = "selection-proposal-completed-v1"
MAX_CASE_ID_CHARACTERS = 128
_SEAL = object()
_CHAIN_FIELDS = (
    "case_id",
    "case_context_sha256",
    "evidence_pack_sha256",
    "selection_request_sha256",
    "selection_raw_sha256",
    "derived_selection_sha256",
    "proposal_request_sha256",
    "handoff_sha256",
)
_REVIEW_FIELDS = (
    "items",
    "unit_complete_scope",
    "original_document_completeness",
    "semantic_support",
    "condition_preservation",
    "topic_relevance",
    "manual_review_required",
    "semantic_accuracy",
    "full_report_coverage",
)


def _flags():
    return {
        "evaluation_origin": "offline_application_supplied",
        "request_origin_attestation": "not_performed",
        "model_calls": 0,
        "transport_capture": "not_performed",
        "production_enabled": False,
        "release_gate": {"active": False},
        "semantic_support": "unknown",
        "semantic_accuracy": None,
        "manual_review_required": True,
        "full_report_coverage": "not_evaluated",
    }


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _raw_hash(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, init=False)
class _Handoff:
    _case_id: str
    _pack_json: str
    _selection_request: extractive._Request
    _selection_raw: str | bytes
    _proposal_request: proposals._Request
    _json: str

    def __init__(self, case_id, pack, selection_request, selection_raw, proposal_request, data, seal=None):
        if seal is not _SEAL:
            raise TypeError("Use prepare_proposal to create a handoff.")
        object.__setattr__(self, "_case_id", case_id)
        object.__setattr__(self, "_pack_json", _json(pack))
        object.__setattr__(self, "_selection_request", copy.deepcopy(selection_request))
        object.__setattr__(self, "_selection_raw", selection_raw)
        object.__setattr__(self, "_proposal_request", copy.deepcopy(proposal_request))
        object.__setattr__(self, "_json", _json(data))

    def to_dict(self):
        """Detached chain metadata and proposal request, never stage-one free text."""
        return json.loads(self._json)


def prepare_proposal(case_id, pack, selection_request, selection_raw):
    """Consume a fully validated selection before constructing the second request."""
    case_id = contract._node(case_id, MAX_CASE_ID_CHARACTERS)
    pack, selection_request = copy.deepcopy(pack), copy.deepcopy(selection_request)
    selected = extractive.validate_selection(selection_raw, selection_request).to_dict()
    expected = extractive.build_request(pack).to_dict()
    if selection_request.to_dict() != expected:
        raise contract.ContractError("Selection request differs from the supplied pack/catalog.")
    mapping = {
        str(item["section_id"]): item["basis"]["passage_ref"] if item["basis"]["state"] == "unit_selected" else None
        for item in selected["items"]
    }
    proposal_request = proposals.build_request(pack, mapping)
    task = proposal_request.to_dict()
    data = {
        "version": HANDOFF_VERSION,
        **_flags(),
        "case_id": case_id,
        # Only this application label is bound, not an absent full user scenario.
        "case_context_sha256": json_sha256({"case_id": case_id}),
        "evidence_pack_sha256": pack["evidence_pack_sha256"],
        "selection_request_sha256": expected["request_sha256"],
        "selection_raw_sha256": _raw_hash(selection_raw),
        "derived_selection_sha256": json_sha256(mapping),
        "proposal_request_sha256": task["request_sha256"],
        "proposal_request": task,
    }
    data["handoff_sha256"] = json_sha256(data)
    return _Handoff(case_id, pack, selection_request, selection_raw, proposal_request, data, _SEAL)


def _revalidate_handoff(handoff, expected_handoff_sha256):
    if type(handoff) is not _Handoff:
        raise TypeError("A handoff from prepare_proposal is required.")
    try:
        recorded = handoff.to_dict()
        if not contract._hash(expected_handoff_sha256) or expected_handoff_sha256 != recorded["handoff_sha256"]:
            raise contract.ContractError("Expected handoff identity differs.")
        rebuilt = prepare_proposal(
            handoff._case_id,
            json.loads(handoff._pack_json),
            handoff._selection_request,
            handoff._selection_raw,
        )
        request, _ = proposals._revalidate_request(handoff._proposal_request)
        if handoff._json != rebuilt._json or request != rebuilt.to_dict()["proposal_request"]:
            raise contract.ContractError("Frozen handoff or derived proposal request changed.")
        return rebuilt
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise contract.ContractError("Handoff binding validation failed.") from error


@dataclass(frozen=True, init=False)
class _Completed:
    _handoff: _Handoff
    _expected_handoff_sha256: str
    _proposal_raw: str | bytes
    _proposal_result: proposals._ValidatedProposals
    _json: str

    def __init__(self, handoff, expected, raw, result, data, seal=None):
        if seal is not _SEAL:
            raise TypeError("Use complete_proposal to create a completed fragment.")
        object.__setattr__(self, "_handoff", copy.deepcopy(handoff))
        object.__setattr__(self, "_expected_handoff_sha256", expected)
        object.__setattr__(self, "_proposal_raw", raw)
        object.__setattr__(self, "_proposal_result", copy.deepcopy(result))
        object.__setattr__(self, "_json", _json(data))

    def to_dict(self):
        return json.loads(self._json)


def complete_proposal(handoff, proposal_raw, *, expected_handoff_sha256):
    """Rebuild the bound first stage, then validate second-stage structure only."""
    handoff = _revalidate_handoff(handoff, expected_handoff_sha256)
    validated = proposals.validate_proposals(proposal_raw, handoff._proposal_request)
    review, chain = validated.to_dict(), handoff.to_dict()
    data = {
        "version": COMPLETED_VERSION,
        **_flags(),
        **{key: chain[key] for key in _CHAIN_FIELDS},
        "proposal_raw_sha256": _raw_hash(proposal_raw),
        "proposal_result_sha256": json_sha256(review),
        "proposal_review": {key: review[key] for key in _REVIEW_FIELDS},
    }
    data["completed_sha256"] = json_sha256(data)
    return _Completed(handoff, expected_handoff_sha256, proposal_raw, validated, data, _SEAL)


def render_preview(completed):
    """Recheck the entire frozen chain and use the existing escaped proposal renderer."""
    if type(completed) is not _Completed:
        raise TypeError("render_preview requires a result from complete_proposal.")
    try:
        rebuilt = complete_proposal(
            completed._handoff,
            completed._proposal_raw,
            expected_handoff_sha256=completed._expected_handoff_sha256,
        )
        if (
            completed._json != rebuilt._json
            or completed._proposal_result.to_dict() != rebuilt._proposal_result.to_dict()
        ):
            raise contract.ContractError("Completed result differs from its frozen chain.")
        # Also checks the stored proposal result's private raw/request, not merely its dictionary.
        preview = proposals.render_preview(completed._proposal_result)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise contract.ContractError("Completed chain validation failed.") from error
    data, safe = rebuilt.to_dict(), contract._safe
    lines = [
        "# SYNTHETIC OFFLINE CHAIN FRAGMENT",
        "# NOT REPORT",
        "",
        "Offline application-supplied inputs: no model calls, transport capture or request-origin attestation.",
        "Case identifiers and hashes associate supplied records only; they do not certify a full user scenario or a model request.",
        "Compatible raw JSON has no request identity: cross-case copying cannot always be detected. Input origin is not automatically authenticated as synthetic.",
        "No real two-call sequence, historical-response migration or semantic support is established.",
        "",
    ]
    lines.extend(
        f"{key}: {safe(data[key])}"
        for key in (*_CHAIN_FIELDS, "proposal_raw_sha256", "proposal_result_sha256", "completed_sha256")
    )
    return "\n".join([*lines, "", preview])
