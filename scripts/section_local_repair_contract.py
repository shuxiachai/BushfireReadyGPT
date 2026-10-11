"""Isolated, in-memory experiment for caller-declared section repair preservation.

This module never dispatches a model, assesses token fit, or grants production or
human approval. Submitted records and hashes establish internal consistency, not
real SDK transport, provider receipt, or semantic completeness of source evidence.
No scope is inferred from report-wide check names, word counts, or failure text.

UTF-8 byte caps (reject, never truncate): raw response 65,536; analysis and the
complete two-message array 262,144 each; evidence snapshot and rendered narrative
131,072 each; frozen prepared payload 1,048,576. JSON input additionally has at
most 32 nesting levels, 32,768 nodes and 4,096-bit integers. Only builtin JSON
types are admitted. Prepared objects are detached immutable strings; their hashes
detect accidental drift, not a malicious Python caller able to rebuild records.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from src.model_evidence import MODEL_CAPTURE_SCHEMA, text_sha256, validate_model_evidence
from src.model_response import ModelResponseError
from src.report_generation_quality import assess_generated_narrative
from src.report_repair_guard import (
    ReportRepairRegressionError,
    reject_repair_regression,
    snapshot_repair_assessment,
)
from src.report_section_protocol import MAX_RAW_BYTES, SECTION_KEYS, decode_section_response, render_section_report
from src.report_template import extract_narrative_body

RESULT_SCHEMA = "experimental-section-local-repair-assessment-v1"
PREPARED_SCHEMA = "experimental-section-local-repair-base-v1"
UNASSESSED_BUDGET_STATUS = "not_assessed"
MAX_ANALYSIS_BYTES = 262_144
MAX_MESSAGES_BYTES = 262_144
MAX_SNAPSHOT_BYTES = 131_072
MAX_NARRATIVE_BYTES = 131_072
MAX_PREPARED_BYTES = 1_048_576
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 32_768
MAX_INTEGER_BITS = 4_096
REASON_CODES = frozenset(
    {
        "input_invalid",
        "input_limit_exceeded",
        "scope_invalid",
        "prepared_base_invalid",
        "analysis_mismatch",
        "section_protocol_invalid",
        "messages_invalid",
        "evidence_invalid",
        "evidence_capture_required",
        "evidence_passages_required",
        "evidence_binding_mismatch",
        "evidence_context_not_unique",
        "evidence_passage_not_preserved",
        "attempt_invalid",
        "attempt_order_invalid",
        "no_sections_changed",
        "section_outside_scope_changed",
        "quality_assessment_invalid",
        "whole_report_gate_failed",
        "repair_regression",
    }
)
_DIGEST_NAMES = (
    "analysis",
    "raw_response",
    "rendered_narrative",
    "system_message",
    "user_message",
    "submitted_messages",
    "model_evidence",
    *SECTION_KEYS,
)
_INPUT_EXCEPTIONS = (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError, RecursionError)


class ContractInputError(ValueError):
    """A fixed code, with no user text or underlying exception in its message."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in REASON_CODES else "input_invalid"
        super().__init__(self.code)


def _fail(code):
    raise ContractInputError(code) from None


def _bounded_text(value, limit):
    if type(value) is not str:
        _fail("input_invalid")
    if len(value) > limit:
        _fail("input_limit_exceeded")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        _fail("input_invalid")
    if size > limit:
        _fail("input_limit_exceeded")
    return value


def _preflight_json(value, limit):
    """Bound traversal and every scalar before the encoder can allocate output."""
    nodes, minimum_bytes, ancestors = 0, 0, set()

    def visit(item, depth):
        nonlocal nodes, minimum_bytes
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            _fail("input_limit_exceeded")
        kind = type(item)
        if kind is str:
            _bounded_text(item, limit)
            minimum_bytes += len(item.encode("utf-8")) + 2
        elif kind is int:
            if item.bit_length() > MAX_INTEGER_BITS:
                _fail("input_limit_exceeded")
            minimum_bytes += 1
        elif kind is float:
            if not math.isfinite(item):
                _fail("input_invalid")
            minimum_bytes += 1
        elif item is None or kind is bool:
            minimum_bytes += 1
        elif kind in (dict, list):
            if id(item) in ancestors:
                _fail("input_invalid")
            if len(item) > MAX_JSON_NODES:
                _fail("input_limit_exceeded")
            ancestors.add(id(item))
            minimum_bytes += 2
            for key in item:
                if kind is dict:
                    if type(key) is not str:
                        _fail("input_invalid")
                    visit(key, depth + 1)
                    visit(item[key], depth + 1)
                else:
                    visit(key, depth + 1)
            ancestors.remove(id(item))
        else:
            _fail("input_invalid")
        if minimum_bytes > limit:
            _fail("input_limit_exceeded")

    visit(value, 0)


def _canonical_json(value, limit):
    _preflight_json(value, limit)
    chunks, size = [], 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(value):
        size += len(chunk.encode("utf-8"))
        if size > limit:
            _fail("input_limit_exceeded")
        chunks.append(chunk)
    return "".join(chunks)


def _scope(section_ids):
    if type(section_ids) not in (tuple, list) or not 0 < len(section_ids) < len(SECTION_KEYS):
        _fail("scope_invalid")
    if any(type(key) is not str or key not in SECTION_KEYS for key in section_ids):
        _fail("scope_invalid")
    if len(set(section_ids)) != len(section_ids):
        _fail("scope_invalid")
    return tuple(key for key in SECTION_KEYS if key in section_ids)


def _attempt(value):
    if type(value) is not int or not 1 <= value <= 3:
        _fail("attempt_invalid")
    return value


def _messages(value):
    encoded = _canonical_json(value, MAX_MESSAGES_BYTES)
    messages = json.loads(encoded)
    if type(messages) is not list or len(messages) != 2:
        _fail("messages_invalid")
    for item, role in zip(messages, ("system", "user"), strict=True):
        if type(item) is not dict or set(item) != {"role", "content"}:
            _fail("messages_invalid")
        if item["role"] != role or type(item["content"]) is not str:
            _fail("messages_invalid")
    return messages, encoded


def _record(*, analysis, raw_response, submitted_messages, model_evidence):
    analysis_json = _canonical_json(analysis, MAX_ANALYSIS_BYTES)
    analysis = json.loads(analysis_json)
    if type(analysis) is not dict:
        _fail("input_invalid")
    raw_response = _bounded_text(raw_response, MAX_RAW_BYTES)
    messages, messages_json = _messages(submitted_messages)
    evidence_json = _canonical_json(model_evidence, MAX_SNAPSHOT_BYTES)
    evidence = json.loads(evidence_json)
    if type(evidence) is not dict or evidence.get("status") != "captured":
        _fail("evidence_capture_required")
    attempt = _attempt(evidence.get("attempt_number"))
    try:
        sections = decode_section_response(raw_response, analysis)
        narrative = render_section_report(sections, analysis)
    except (*_INPUT_EXCEPTIONS, ModelResponseError):
        _fail("section_protocol_invalid")
    _bounded_text(narrative, MAX_NARRATIVE_BYTES)
    try:
        verified = validate_model_evidence(evidence, analysis, report_text=narrative)
    except _INPUT_EXCEPTIONS:
        _fail("evidence_invalid")
    if any(not passage["text"] for passage in verified):
        _fail("evidence_passages_required")
    expected_binding = {
        "schema": MODEL_CAPTURE_SCHEMA,
        "system_prompt_sha256": text_sha256(messages[0]["content"]),
        "user_prompt_sha256": text_sha256(messages[1]["content"]),
        "messages_sha256": text_sha256(messages_json),
        "response_sha256": text_sha256(raw_response),
    }
    if evidence["request_binding"] != expected_binding or evidence["normalized_narrative_sha256"] != text_sha256(
        extract_narrative_body(narrative)
    ):
        _fail("evidence_binding_mismatch")
    if messages[1]["content"].count(evidence["context"]) != 1:
        _fail("evidence_context_not_unique")
    digest_values = (
        analysis_json,
        raw_response,
        narrative,
        messages[0]["content"],
        messages[1]["content"],
        messages_json,
        evidence_json,
        *(sections[key] for key in SECTION_KEYS),
    )
    return {
        "analysis": analysis,
        "raw_response": raw_response,
        "submitted_messages": messages,
        "model_evidence": evidence,
        "narrative": narrative,
        "sections": sections,
        "attempt": attempt,
        "digests": {name: text_sha256(value) for name, value in zip(_DIGEST_NAMES, digest_values, strict=True)},
    }


@dataclass(frozen=True)
class PreparedBase:
    """Opaque detached data; assessment revalidates every field and binding."""

    _payload_json: str = field(repr=False)
    _binding_sha256: str = field(repr=False)


def _prepared(record, scope):
    payload = _canonical_json(
        {"schema": PREPARED_SCHEMA, "scope_basis": "caller_declared", "scope": list(scope), "record": record},
        MAX_PREPARED_BYTES,
    )
    return PreparedBase(payload, text_sha256(payload))


def prepare_base(*, analysis, raw_response, submitted_messages, model_evidence, declared_section_ids):
    """Admit a complete base and explicit proper-subset scope without assessing fit."""
    try:
        scope = _scope(declared_section_ids)
        record = _record(
            analysis=analysis,
            raw_response=raw_response,
            submitted_messages=submitted_messages,
            model_evidence=model_evidence,
        )
        return _prepared(record, scope)
    except ContractInputError:
        raise
    except _INPUT_EXCEPTIONS:
        raise ContractInputError("input_invalid") from None


def _revalidate_prepared(prepared):
    try:
        if type(prepared) is not PreparedBase:
            _fail("prepared_base_invalid")
        payload = _bounded_text(prepared._payload_json, MAX_PREPARED_BYTES)
        if type(prepared._binding_sha256) is not str or text_sha256(payload) != prepared._binding_sha256:
            _fail("prepared_base_invalid")
        data = json.loads(payload)
        _preflight_json(data, MAX_PREPARED_BYTES)
        record = data["record"]
        rebuilt = prepare_base(
            analysis=record["analysis"],
            raw_response=record["raw_response"],
            submitted_messages=record["submitted_messages"],
            model_evidence=record["model_evidence"],
            declared_section_ids=data["scope"],
        )
        if rebuilt != prepared:
            _fail("prepared_base_invalid")
        return record, tuple(data["scope"])
    except _INPUT_EXCEPTIONS:
        raise ContractInputError("prepared_base_invalid") from None


def _valid_digests(values):
    return (
        type(values) is tuple
        and len(values) == len(_DIGEST_NAMES)
        and all(
            type(pair) is tuple
            and len(pair) == 2
            and type(pair[0]) is str
            and pair[0] == name
            and type(pair[1]) is str
            and re.fullmatch(r"[a-f0-9]{64}", pair[1]) is not None
            for pair, name in zip(values, _DIGEST_NAMES, strict=True)
        )
    )


@dataclass(frozen=True)
class OfflineAssessment:
    """A content-free experimental result, never a repaired report or dispatch plan."""

    status: str
    reason_codes: tuple[str, ...]
    declared_section_ids: tuple[str, ...] = ()
    changed_section_ids: tuple[str, ...] = ()
    base_attempt: int | None = None
    candidate_attempt: int | None = None
    base_digests: tuple[tuple[str, str], ...] = ()
    candidate_digests: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if type(self.status) is not str or self.status not in {
            "offline_contract_accepted",
            "offline_contract_rejected",
        }:
            _fail("input_invalid")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or code not in REASON_CODES for code in self.reason_codes
        ):
            _fail("input_invalid")
        if len(self.reason_codes) != (0 if self.status == "offline_contract_accepted" else 1):
            _fail("input_invalid")
        if type(self.declared_section_ids) is not tuple or (
            self.declared_section_ids and _scope(self.declared_section_ids) != self.declared_section_ids
        ):
            _fail("input_invalid")
        if (
            type(self.changed_section_ids) is not tuple
            or any(type(key) is not str or key not in SECTION_KEYS for key in self.changed_section_ids)
            or self.changed_section_ids != tuple(key for key in SECTION_KEYS if key in self.changed_section_ids)
        ):
            _fail("input_invalid")
        for attempt in (self.base_attempt, self.candidate_attempt):
            if attempt is not None:
                _attempt(attempt)
        for digests in (self.base_digests, self.candidate_digests):
            if type(digests) is not tuple or (digests and not _valid_digests(digests)):
                _fail("input_invalid")
        if self.status == "offline_contract_accepted" and (
            not self.changed_section_ids
            or not set(self.changed_section_ids) <= set(self.declared_section_ids)
            or self.base_attempt is None
            or self.candidate_attempt is None
            or self.base_attempt >= self.candidate_attempt
            or not self.base_digests
            or not self.candidate_digests
        ):
            _fail("input_invalid")

    def to_dict(self):
        """Recheck even frozen fields before returning the fixed public shape."""
        try:
            self.__post_init__()
        except _INPUT_EXCEPTIONS:
            raise ContractInputError("input_invalid") from None
        return {
            "schema": RESULT_SCHEMA,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "scope_basis": "caller_declared",
            "declared_section_ids": list(self.declared_section_ids),
            "changed_section_ids": list(self.changed_section_ids),
            "base_attempt": self.base_attempt,
            "candidate_attempt": self.candidate_attempt,
            "base_digests": dict(self.base_digests),
            "candidate_digests": dict(self.candidate_digests),
            "token_budget": UNASSESSED_BUDGET_STATUS,
            "eligible_for_model_dispatch": False,
            "production_acceptance": False,
        }


def _passages(record):
    return {
        tuple(passage[key] for key in ("source_id", "chunk_id", "retrieved_rank", "text"))
        for passage in record["model_evidence"]["visible_passages"]
    }


def _assess_quality(base, candidate):
    try:
        baseline_quality = assess_generated_narrative(
            base["narrative"],
            base["analysis"],
            model_evidence=base["model_evidence"],
        )
        baseline_snapshot = snapshot_repair_assessment(baseline_quality)
        candidate_quality = assess_generated_narrative(
            candidate["narrative"],
            candidate["analysis"],
            model_evidence=candidate["model_evidence"],
        )
        reject_repair_regression(
            baseline_snapshot,
            snapshot_repair_assessment(candidate_quality),
            baseline_attempt_number=base["attempt"],
            candidate_attempt_number=candidate["attempt"],
        )
        if candidate_quality["approval_gate"]["passed"] is not True:
            _fail("whole_report_gate_failed")
    except ReportRepairRegressionError:
        _fail("repair_regression")
    except ContractInputError:
        raise
    except _INPUT_EXCEPTIONS:
        _fail("quality_assessment_invalid")


def assess_candidate(prepared_base, *, analysis, raw_response, submitted_messages, model_evidence):
    """Compare complete independently bound bodies and rerun the current gate."""
    details = {}
    try:
        base, scope = _revalidate_prepared(prepared_base)
        details.update(
            declared_section_ids=scope,
            base_attempt=base["attempt"],
            base_digests=tuple((key, base["digests"][key]) for key in _DIGEST_NAMES),
        )
        if text_sha256(_canonical_json(analysis, MAX_ANALYSIS_BYTES)) != base["digests"]["analysis"]:
            _fail("analysis_mismatch")
        candidate = _record(
            analysis=analysis,
            raw_response=raw_response,
            submitted_messages=submitted_messages,
            model_evidence=model_evidence,
        )
        details.update(
            candidate_attempt=candidate["attempt"],
            candidate_digests=tuple((key, candidate["digests"][key]) for key in _DIGEST_NAMES),
        )
        if candidate["attempt"] <= base["attempt"]:
            _fail("attempt_order_invalid")
        changed = tuple(key for key in SECTION_KEYS if base["sections"][key] != candidate["sections"][key])
        details["changed_section_ids"] = changed
        if not changed:
            _fail("no_sections_changed")
        if not set(changed) <= set(scope):
            _fail("section_outside_scope_changed")
        if not _passages(base) <= _passages(candidate):
            _fail("evidence_passage_not_preserved")
        _assess_quality(base, candidate)
        return OfflineAssessment("offline_contract_accepted", (), **details)
    except ContractInputError as error:
        return OfflineAssessment("offline_contract_rejected", (error.code,), **details)
    except _INPUT_EXCEPTIONS:
        return OfflineAssessment("offline_contract_rejected", ("input_invalid",), **details)
