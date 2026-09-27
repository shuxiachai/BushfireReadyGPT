"""Lexical proposal/dependency review clues for the offline proposal contract.

This module deliberately revalidates caller-supplied raw proposal JSON.  Its
marker and duplicate findings are prompts for a human review, never semantic
support, condition preservation, or evidence-completeness verdicts.
"""

from __future__ import annotations

import copy
import difflib
import re

from scripts import atomic_claim_contract as contract
from scripts import proposal_evidence_contract as proposals

SCHEMA = "proposal-evidence-advisory-v1"
MIN_DUPLICATE_WORDS = 12
DUPLICATE_RATIO = 0.85
_WORDS = re.compile(r"\w+", re.UNICODE)
_EXCEPTION_MARKERS = {"unless", "except"}
_MARKER_PATTERNS = {
    "negation": re.compile(r"\b(?:not|never|without|cannot|no|neither|nor)\b|n['’]t\b", re.I),
    "condition": re.compile(r"\b(?:if|unless|only|except|when|until|before|after|provided|subject\s+to)\b", re.I),
    "qualifier": re.compile(
        r"\b(?:may|might|could|some|all|any|up\s+to|at\s+least|at\s+most|trained|adult|adults|eligible|approved|excluded|excluding|usually|generally)\b",
        re.I,
    ),
}


def _word_tokens(text):
    """Case-folded lexical tokens only; punctuation and whitespace are ignored."""
    return _WORDS.findall(text.casefold())


def _markers(text):
    """Small local marker vocabulary; no SDK-adjacent imports."""
    return {
        name: sorted({match[0].casefold() for match in pattern.finditer(text)})
        for name, pattern in _MARKER_PATTERNS.items()
    }


def _marker_review(proposal_text, dependency_text):
    proposal_markers = _markers(proposal_text)
    source_markers = _markers(dependency_text)
    differences = {
        kind: {
            "proposal_only": sorted(set(proposal_markers[kind]) - set(source_markers[kind])),
            "source_only": sorted(set(source_markers[kind]) - set(proposal_markers[kind])),
        }
        for kind in proposal_markers
    }
    exception_scope_review_required = bool(
        _EXCEPTION_MARKERS & (set(proposal_markers["condition"]) | set(source_markers["condition"]))
    )
    return {
        "proposal_markers": proposal_markers,
        "source_markers": source_markers,
        "marker_difference": differences,
        "exception_scope_review_required": exception_scope_review_required,
        "semantic_or_condition_verdict": "not_provided",
    }


def _dependency_review(dependency, proposal_text):
    copied = copy.deepcopy(dependency)
    return {
        "dependency": copied,
        "marker_review": _marker_review(proposal_text, copied["text"]),
        "semantic_support": "unknown",
        "manual_review_required": True,
    }


def _duplicates(items):
    """Return lexical similarities for every cross-section draft pair.

    Source identity neither establishes nor suppresses a duplicate finding:
    the proposal text is always compared.  A common source can still produce
    unrelated drafts, and common source text can produce a review clue.
    """
    drafts = []
    for item in items:
        proposal = item["proposal"]
        if proposal["kind"] != "draft_for_review":
            continue
        drafts.append((item["section_id"], proposal["text"]))
    findings = []
    for index, (left_section, left_text) in enumerate(drafts):
        left_words = _word_tokens(left_text)
        if len(left_words) < MIN_DUPLICATE_WORDS:
            continue
        for right_section, right_text in drafts[index + 1 :]:
            right_words = _word_tokens(right_text)
            if len(right_words) < MIN_DUPLICATE_WORDS:
                continue
            ratio = difflib.SequenceMatcher(None, left_words, right_words, autojunk=False).ratio()
            if ratio >= DUPLICATE_RATIO:
                findings.append(
                    {
                        "section_ids": [left_section, right_section],
                        "word_counts": [len(left_words), len(right_words)],
                        "sequence_ratio": ratio,
                        "review_required": True,
                        "finding": "possible_cross_section_lexical_duplicate",
                    }
                )
    return findings


def review_proposals(raw, typed_request):
    """Revalidate raw proposals and return detached lexical advisory data.

    ``typed_request`` must be the opaque request made by ``build_request``;
    dictionaries and already-reviewed results are intentionally not accepted.
    """
    validated = proposals.validate_proposals(raw, typed_request).to_dict()
    items = []
    for validated_item in validated["items"]:
        proposal = validated_item["proposal"]
        item = {
            "section_id": validated_item["section_id"],
            "primary_selected_ref": validated_item["primary_selected_ref"],
            "proposal": copy.deepcopy(proposal),
            "proposal_semantics": "unknown",
            "condition_preservation": "unknown",
            "manual_review_required": True,
        }
        if proposal["kind"] == "draft_for_review":
            item["declared_dependencies"] = [
                _dependency_review(dependency, proposal["text"]) for dependency in proposal["dependencies"]
            ]
        else:
            item["declared_dependencies"] = []
        items.append(item)
    return {
        "schema": SCHEMA,
        "request_sha256": validated["request_sha256"],
        "raw_proposals_sha256": validated["raw_proposals_sha256"],
        "evidence_pack_sha256": validated["evidence_pack_sha256"],
        "items": items,
        "cross_section_duplicate_review": _duplicates(validated["items"]),
        "duplicate_diagnostic": {
            "minimum_word_tokens": MIN_DUPLICATE_WORDS,
            "sequence_ratio_threshold": DUPLICATE_RATIO,
            "normalization": "casefolded_unicode_word_tokens; punctuation_and_whitespace_ignored",
            "quality_score": "not_provided",
        },
        "additional_model_calls": 0,
        "new_transport_capture": False,
        "input_origin": "caller_supplied_revalidated",
        "request_origin_attestation": "not_performed",
        "semantic_support": "unknown",
        "condition_preservation": "unknown",
        "declared_dependency_completeness": "unknown",
        "manual_review_required": True,
        "semantic_accuracy": None,
        "full_report_coverage": "not_evaluated",
        "production_enabled": False,
        "release_gate": {"active": False},
        "limitations": [
            "This is a lexical advisory, not a complete report or provider proof.",
            "Marker agreement or no listed difference does not establish semantic support or condition preservation.",
            "Unless and except always require exception-scope review; this is not an error finding.",
            "Lexical duplicate findings can falsely flag shared disclaimers or independently similar drafts.",
            "Short repeated text can be omitted by the fixed minimum-token duplicate diagnostic.",
        ],
    }


def _safe_json(value):
    import json

    return contract._safe(json.dumps(value, ensure_ascii=False, sort_keys=True))


def render_advisory(raw, typed_request):
    """Render a new escaped advisory from raw JSON; advisory dictionaries are rejected."""
    advisory = review_proposals(raw, typed_request)
    safe = contract._safe
    lines = [
        "# OFFLINE PROPOSAL EVIDENCE ADVISORY",
        "# NOT REPORT OR PROVIDER PROOF",
        "",
        "Caller-supplied raw proposals were structurally revalidated. No additional model calls or transport capture occurred.",
        "This is not a complete report, historical response, remote-provider proof, or semantic-support verdict.",
        "Semantic and condition preservation remain unknown; manual review is required even without a listed lexical difference.",
        "",
        "Request SHA256: " + safe(advisory["request_sha256"]),
        "Raw proposals SHA256: " + safe(advisory["raw_proposals_sha256"]),
        "Evidence pack SHA256: " + safe(advisory["evidence_pack_sha256"]),
    ]
    for item in advisory["items"]:
        lines.extend(["", f"## Section {item['section_id']}"])
        proposal = item["proposal"]
        if proposal["kind"] == "requires_evidence":
            lines.extend(["State: requires_evidence", safe(proposal["application_message"])])
            continue
        lines.extend(["", "### Proposal draft — unverified", safe(proposal["text"])])
        for reviewed in item["declared_dependencies"]:
            dependency, marker_review = reviewed["dependency"], reviewed["marker_review"]
            lines.extend(
                [
                    "",
                    "### Declared dependency — full recorded visible passage; support unknown",
                    "Reference: " + safe(dependency["passage_ref"]),
                    "Source: " + safe(dependency["source_id"]),
                    "Chunk: " + safe(dependency["chunk_id"]),
                    "Text SHA256: " + safe(dependency["text_sha256"]),
                    safe(dependency["text"]),
                    "Proposal markers: " + _safe_json(marker_review["proposal_markers"]),
                    "Source markers: " + _safe_json(marker_review["source_markers"]),
                    "Marker differences: " + _safe_json(marker_review["marker_difference"]),
                    "Exception-scope review required: " + str(marker_review["exception_scope_review_required"]),
                ]
            )
    lines.extend(["", "## Cross-section lexical duplicate review"])
    lines.append("Diagnostic settings: " + _safe_json(advisory["duplicate_diagnostic"]))
    if advisory["cross_section_duplicate_review"]:
        lines.extend(_safe_json(finding) for finding in advisory["cross_section_duplicate_review"])
    else:
        lines.append("No possible cross-section lexical duplicate listed; this is not semantic approval.")
    lines.extend(["", "## Limitations", *(safe(note) for note in advisory["limitations"])])
    return "\n".join(lines)
