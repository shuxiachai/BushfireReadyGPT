"""Synthetic offline records only: no real SDK capture, model, network or replay."""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from scripts import section_local_repair_contract as contract
from src.model_evidence import (
    MODEL_CAPTURE_SCHEMA,
    EvidencePrompt,
    bind_normalized_narrative,
    capture_model_evidence,
    json_sha256,
    text_sha256,
    unavailable_model_evidence,
    validate_model_evidence,
)
from src.rag.context import assemble_planning_context
from src.report_generation_quality import CURRENT_POLICY, QUALITY_POLICY_FINGERPRINT, assess_generated_narrative
from src.report_section_protocol import SECTION_KEYS, render_section_report
from src.source_attribution import fold_known_attribution_labels
from tests.support.repair_quality_fixtures import repair_quality
from tests.support.report_fixtures import _valid_report, section_response_for_report


def _chunk(text, identity="guide"):
    return {
        "source_id": identity,
        "chunk_id": identity + "-1",
        "title": "Preparedness guide " + identity,
        "agency": "Test authority",
        "text": text,
        "chunk_sha256": text_sha256(text),
        "jurisdictions": ["Queensland"],
    }


def _synthetic_record(analysis, sections, *, attempt=1, assembly=None, ensure_ascii=False):
    """Fabricated fixtures for contract tests, never attestation of real transport."""
    raw = json.dumps(sections, ensure_ascii=ensure_ascii)
    narrative = render_section_report(sections, analysis)
    if assembly is None:
        assembly = assemble_planning_context(analysis["knowledge"])
    prompt = EvidencePrompt("PRIVATE synthetic user\n" + assembly["context"], assembly=assembly)
    messages = [{"role": "system", "content": "PRIVATE synthetic system"}, {"role": "user", "content": str(prompt)}]
    binding = {
        "schema": MODEL_CAPTURE_SCHEMA,
        "system_prompt_sha256": text_sha256(messages[0]["content"]),
        "user_prompt_sha256": text_sha256(messages[1]["content"]),
        "messages_sha256": json_sha256(messages),
        "response_sha256": text_sha256(raw),
    }
    snapshot = capture_model_evidence(
        prompt, SimpleNamespace(last_request_capture=binding), raw, attempt_number=attempt
    )
    return {
        "analysis": copy.deepcopy(analysis),
        "raw_response": raw,
        "submitted_messages": messages,
        "model_evidence": bind_normalized_narrative(snapshot, narrative),
    }


@pytest.fixture
def pair():
    body, analysis = _valid_report()
    sections = json.loads(section_response_for_report(body, analysis))
    analysis["knowledge"]["retrieved_chunks"] = [_chunk("Families prepare household emergency supplies.")]
    analysis["fixture_marker"] = "PRIVATE synthetic analysis"
    chunks = analysis["knowledge"]["retrieved_chunks"]
    claim = "[O1-RAG][source_id=guide] Preparedness guide guide says families prepare household emergency supplies."
    sections["s06"] += "\n\n" + fold_known_attribution_labels(
        claim,
        official_sources=analysis["data"]["sources"],
        rag_sources=chunks,
    )
    sections["s02"] = "  " + sections["s02"] + "  "
    sections["s01"] += " café"
    base_sections = dict(sections)
    # The fault is a real report-wide word-budget failure. Scope remains an
    # independent caller declaration; it is never inferred from that check.
    base_sections["s15"] += " This draft remains subject to accountable organisational review." * 20
    return _synthetic_record(analysis, base_sections), _synthetic_record(analysis, sections, attempt=2)


def _prepare(record, scope=("s15",)):
    return contract.prepare_base(**record, declared_section_ids=scope)


def _rebind_messages(record):
    messages = record["submitted_messages"]
    record["model_evidence"]["request_binding"].update(
        system_prompt_sha256=text_sha256(messages[0]["content"]),
        user_prompt_sha256=text_sha256(messages[1]["content"]),
        messages_sha256=json_sha256(messages),
    )


def _reason(result, expected):
    assert result.status == "offline_contract_rejected"
    assert result.reason_codes == (expected,)
    assert result.to_dict()["eligible_for_model_dispatch"] is False
    assert result.to_dict()["token_budget"] == "not_assessed"
    assert "PRIVATE" not in json.dumps(result.to_dict())


def test_real_current_gate_passing_scoped_repair_and_fixed_content_free_result(pair):
    base, candidate = pair
    prepared = _prepare(base)
    for record, expected in ((base, False), (candidate, True)):
        body = render_section_report(json.loads(record["raw_response"]), record["analysis"])
        assert record["model_evidence"]["visible_passages"]
        assert validate_model_evidence(record["model_evidence"], record["analysis"], report_text=body)
        assert (
            assess_generated_narrative(body, record["analysis"], model_evidence=record["model_evidence"])[
                "approval_gate"
            ]["passed"]
            is expected
        )
    result = contract.assess_candidate(prepared, **candidate)
    assert result.status == "offline_contract_accepted"
    assert result.changed_section_ids == ("s15",)
    output = result.to_dict()
    assert set(output) == {
        "schema",
        "status",
        "reason_codes",
        "scope_basis",
        "declared_section_ids",
        "changed_section_ids",
        "base_attempt",
        "candidate_attempt",
        "base_digests",
        "candidate_digests",
        "token_budget",
        "eligible_for_model_dispatch",
        "production_acceptance",
    }
    assert output["schema"] == contract.RESULT_SCHEMA
    assert output["scope_basis"] == "caller_declared"
    assert (output["base_attempt"], output["candidate_attempt"]) == (1, 2)
    assert output["token_budget"] == "not_assessed" and output["eligible_for_model_dispatch"] is False
    assert output["production_acceptance"] is False
    assert "PRIVATE" not in json.dumps(output)
    assert "narrative" not in output and "report" not in output
    assert len(output["base_digests"]) == 22
    for key in SECTION_KEYS[:-1]:
        assert output["base_digests"][key] == output["candidate_digests"][key]
    with pytest.raises(FrozenInstanceError):
        result.status = "production_accepted"
    with pytest.raises(FrozenInstanceError):
        prepared._payload_json = "PRIVATE"


@pytest.mark.parametrize("scope", [(), [], list(SECTION_KEYS), ["s15", "s15"], ["s16"], ["s1"], "s15", [True], [None]])
def test_explicit_nonempty_duplicate_free_proper_subset_required(pair, scope):
    with pytest.raises(contract.ContractInputError, match="^scope_invalid$"):
        _prepare(pair[0], scope)


def test_scope_is_canonical_caller_declaration_not_failure_mapping(pair):
    prepared = _prepare(pair[0], ("s15", "s02"))
    assert contract.assess_candidate(prepared, **pair[1]).declared_section_ids == ("s02", "s15")
    _reason(contract.assess_candidate(_prepare(pair[0], ("s01",)), **pair[1]), "section_outside_scope_changed")


@pytest.mark.parametrize("raw", ['{"s15":"PRIVATE partial"}', '{"s01":"PRIVATE","s01":"duplicate"}', "{} trailing"])
@pytest.mark.parametrize("is_base", [True, False])
def test_partial_duplicate_or_trailing_json_is_not_merged(pair, raw, is_base):
    record = copy.deepcopy(pair[0 if is_base else 1])
    record["raw_response"] = raw
    if is_base:
        with pytest.raises(contract.ContractInputError, match="^section_protocol_invalid$"):
            _prepare(record)
    else:
        _reason(contract.assess_candidate(_prepare(pair[0]), **record), "section_protocol_invalid")


@pytest.mark.parametrize("mutation", ["leading_space", "trailing_space", "blank_line", "unicode", "citation"])
def test_unmodified_decoded_strings_preserve_whitespace_unicode_and_citations(pair, mutation):
    base, candidate = pair
    sections = json.loads(candidate["raw_response"])
    if mutation == "leading_space":
        sections["s02"] = sections["s02"][1:]
    elif mutation == "trailing_space":
        sections["s02"] = sections["s02"][:-1]
    elif mutation == "blank_line":
        sections["s06"] = sections["s06"].replace("\n\n", "\n")
    elif mutation == "unicode":
        sections["s01"] = sections["s01"].replace("é", "e\u0301")
    else:
        sections["s06"] = sections["s06"].split("\n\n")[0]
    candidate = _synthetic_record(candidate["analysis"], sections, attempt=2)
    _reason(contract.assess_candidate(_prepare(base), **candidate), "section_outside_scope_changed")


def test_json_escape_spelling_changes_only_raw_binding(pair):
    base, candidate = pair
    escaped = _synthetic_record(
        candidate["analysis"], json.loads(candidate["raw_response"]), attempt=2, ensure_ascii=True
    )
    result = contract.assess_candidate(_prepare(base), **escaped)
    assert result.status == "offline_contract_accepted"
    assert escaped["raw_response"] != candidate["raw_response"]
    assert json.loads(escaped["raw_response"]) == json.loads(candidate["raw_response"])
    assert dict(result.candidate_digests)["raw_response"] == text_sha256(escaped["raw_response"])
    assert dict(result.base_digests)["s01"] == dict(result.candidate_digests)["s01"]


def test_analysis_drift_is_rejected_before_candidate_reinterpretation(pair):
    pair[1]["analysis"]["fixture_marker"] += " changed"
    _reason(contract.assess_candidate(_prepare(pair[0]), **pair[1]), "analysis_mismatch")


@pytest.mark.parametrize(
    "binding", ["system_prompt_sha256", "user_prompt_sha256", "messages_sha256", "response_sha256"]
)
@pytest.mark.parametrize("is_base", [True, False])
def test_every_submitted_binding_is_recomputed(pair, binding, is_base):
    record = copy.deepcopy(pair[0 if is_base else 1])
    record["model_evidence"]["request_binding"][binding] = "0" * 64
    if is_base:
        with pytest.raises(contract.ContractInputError, match="^evidence_binding_mismatch$"):
            _prepare(record)
    else:
        _reason(contract.assess_candidate(_prepare(pair[0]), **record), "evidence_binding_mismatch")


@pytest.mark.parametrize("is_base", [True, False])
def test_normalized_narrative_binding_is_recomputed(pair, is_base):
    record = copy.deepcopy(pair[0 if is_base else 1])
    record["model_evidence"]["normalized_narrative_sha256"] = "0" * 64
    if is_base:
        with pytest.raises(contract.ContractInputError, match="^evidence_invalid$"):
            _prepare(record)
    else:
        _reason(contract.assess_candidate(_prepare(pair[0]), **record), "evidence_invalid")


@pytest.mark.parametrize("occurrences", [0, 2])
@pytest.mark.parametrize("is_base", [True, False])
def test_context_must_occur_exactly_once_even_with_matching_message_hashes(pair, occurrences, is_base):
    record = copy.deepcopy(pair[0 if is_base else 1])
    record["submitted_messages"][1]["content"] = "PRIVATE\n" + record["model_evidence"]["context"] * occurrences
    _rebind_messages(record)
    if is_base:
        with pytest.raises(contract.ContractInputError, match="^evidence_context_not_unique$"):
            _prepare(record)
    else:
        _reason(contract.assess_candidate(_prepare(pair[0]), **record), "evidence_context_not_unique")


@pytest.mark.parametrize("mutation", ["extra", "role", "missing", "extra_message", "content_type"])
def test_only_exact_system_user_message_records_are_accepted(pair, mutation):
    candidate = copy.deepcopy(pair[1])
    messages = candidate["submitted_messages"]
    if mutation == "extra":
        messages[0]["PRIVATE"] = "hidden"
    elif mutation == "role":
        messages.reverse()
    elif mutation == "missing":
        messages[0].pop("content")
    elif mutation == "extra_message":
        messages.append({"role": "assistant", "content": "PRIVATE"})
    else:
        messages[0]["content"] = 123
    _reason(contract.assess_candidate(_prepare(pair[0]), **candidate), "messages_invalid")


@pytest.mark.parametrize("snapshot", [None, {}, unavailable_model_evidence()])
def test_unavailable_records_cannot_be_upgraded_into_capture(pair, snapshot):
    candidate = copy.deepcopy(pair[1])
    candidate["model_evidence"] = snapshot
    _reason(contract.assess_candidate(_prepare(pair[0]), **candidate), "evidence_capture_required")


@pytest.mark.parametrize("mutation", ["visible_text", "rank", "manifest_digest", "context", "extra_field"])
def test_structural_evidence_corruption_fails_closed(pair, mutation):
    candidate = copy.deepcopy(pair[1])
    evidence = candidate["model_evidence"]
    if mutation == "visible_text":
        evidence["visible_passages"][0]["text"] += " PRIVATE"
    elif mutation == "rank":
        evidence["visible_passages"][0]["retrieved_rank"] = 2
    elif mutation == "manifest_digest":
        evidence["assembly_manifest"]["context_sha256"] = "0" * 64
    elif mutation == "context":
        evidence["context"] += " PRIVATE"
    else:
        evidence["PRIVATE"] = "unexpected"
    _reason(contract.assess_candidate(_prepare(pair[0]), **candidate), "evidence_invalid")


def test_valid_shorter_window_is_not_preserved_by_matching_raw_source_hash(pair):
    analysis = pair[0]["analysis"]
    analysis["knowledge"]["retrieved_chunks"][0] = _chunk(
        "Families prepare household emergency supplies. Local records are unverified. "
        "Administrative record maintenance remains a topic for responsible local review."
    )
    base = _synthetic_record(analysis, json.loads(pair[0]["raw_response"]))
    shorter = assemble_planning_context(analysis["knowledge"], max_chunk_characters=80)
    candidate = _synthetic_record(analysis, json.loads(pair[1]["raw_response"]), attempt=2, assembly=shorter)
    assert validate_model_evidence(candidate["model_evidence"], analysis)
    assert (
        base["model_evidence"]["assembly_manifest"]["chunks"][0]["raw_text_sha256"]
        == candidate["model_evidence"]["assembly_manifest"]["chunks"][0]["raw_text_sha256"]
    )
    _reason(contract.assess_candidate(_prepare(base), **candidate), "evidence_passage_not_preserved")


def test_missing_visible_passage_rejected_and_added_passages_allowed(pair):
    analysis = pair[0]["analysis"]
    analysis["knowledge"]["retrieved_chunks"].append(_chunk("Review records need local confirmation.", "extra"))
    full_assembly = assemble_planning_context(analysis["knowledge"])
    limit = len(
        assemble_planning_context({"retrieved_chunks": analysis["knowledge"]["retrieved_chunks"][:1]})["context"]
    )
    limited_assembly = assemble_planning_context(analysis["knowledge"], max_characters=limit)
    assert len(limited_assembly["visible_chunks"]) == 1
    base = _synthetic_record(analysis, json.loads(pair[0]["raw_response"]), assembly=full_assembly)
    candidate = _synthetic_record(analysis, json.loads(pair[1]["raw_response"]), attempt=2, assembly=limited_assembly)
    _reason(contract.assess_candidate(_prepare(base), **candidate), "evidence_passage_not_preserved")
    base = _synthetic_record(analysis, json.loads(pair[0]["raw_response"]), assembly=limited_assembly)
    candidate = _synthetic_record(analysis, json.loads(pair[1]["raw_response"]), attempt=2, assembly=full_assembly)
    assert contract.assess_candidate(_prepare(base), **candidate).status == "offline_contract_accepted"


def test_empty_captured_snapshot_does_not_gain_a_source_support_claim():
    body, analysis = _valid_report()
    sections = json.loads(section_response_for_report(body, analysis))
    base = _synthetic_record(analysis, sections)
    sections["s01"] += " Revised"
    candidate = _synthetic_record(analysis, sections, attempt=2)
    result = contract.assess_candidate(_prepare(base, ("s01",)), **candidate)
    assert result.status == "offline_contract_accepted"
    assert base["model_evidence"]["visible_passages"] == []
    assert "support" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("attempt", [True, False, 0, -1, 4, 2.0, "2", None])
@pytest.mark.parametrize("is_base", [True, False])
def test_attempts_must_be_integers_inside_three_call_ceiling(pair, attempt, is_base):
    record = copy.deepcopy(pair[0 if is_base else 1])
    record["model_evidence"]["attempt_number"] = attempt
    if is_base:
        with pytest.raises(contract.ContractInputError, match="^attempt_invalid$"):
            _prepare(record)
    else:
        _reason(contract.assess_candidate(_prepare(pair[0]), **record), "attempt_invalid")


@pytest.mark.parametrize("base_attempt,candidate_attempt", [(1, 1), (2, 1), (3, 2), (3, 3)])
def test_attempt_order_is_strict(pair, base_attempt, candidate_attempt):
    pair[0]["model_evidence"]["attempt_number"] = base_attempt
    pair[1]["model_evidence"]["attempt_number"] = candidate_attempt
    _reason(contract.assess_candidate(_prepare(pair[0]), **pair[1]), "attempt_order_invalid")


def test_third_attempt_remains_offline_only(pair):
    pair[1]["model_evidence"]["attempt_number"] = 3
    result = contract.assess_candidate(_prepare(pair[0]), **pair[1])
    assert result.status == "offline_contract_accepted"
    assert result.candidate_attempt == 3 and result.to_dict()["eligible_for_model_dispatch"] is False


def test_preparation_detaches_all_caller_owned_mutable_data(pair):
    prepared = _prepare(pair[0])
    pair[0]["analysis"].clear()
    pair[0]["submitted_messages"][0]["content"] = "PRIVATE mutated"
    pair[0]["model_evidence"]["visible_passages"].clear()
    assert contract.assess_candidate(prepared, **pair[1]).status == "offline_contract_accepted"
    assert "PRIVATE" not in repr(prepared)


@pytest.mark.parametrize(
    "field",
    ["analysis", "raw_response", "submitted_messages", "model_evidence", "narrative", "sections", "attempt", "digests"],
)
def test_forged_prepared_payload_revalidates_every_stored_field_even_with_new_outer_hash(pair, field):
    prepared = _prepare(pair[0])
    data = json.loads(prepared._payload_json)
    if field == "digests":
        data["record"][field]["raw_response"] = "0" * 64
    elif field == "attempt":
        data["record"][field] = 2
    elif field == "sections":
        data["record"][field]["s01"] += " PRIVATE"
    elif field in ("analysis", "model_evidence"):
        data["record"][field]["PRIVATE"] = "drift"
    elif field == "submitted_messages":
        data["record"][field][0]["content"] += " PRIVATE"
    else:
        data["record"][field] += " PRIVATE"
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    forged = contract.PreparedBase(encoded, text_sha256(encoded))
    _reason(contract.assess_candidate(forged, **pair[1]), "prepared_base_invalid")


@pytest.mark.parametrize("forged", [None, {}, contract.PreparedBase("PRIVATE", "0" * 64)])
def test_foreign_prepared_objects_and_outer_hash_mismatch_rejected(pair, forged):
    _reason(contract.assess_candidate(forged, **pair[1]), "prepared_base_invalid")


def test_noop_does_not_count_as_a_repair(pair):
    candidate = _synthetic_record(
        pair[0]["analysis"], json.loads(pair[0]["raw_response"]), attempt=2, ensure_ascii=True
    )
    _reason(contract.assess_candidate(_prepare(pair[0]), **candidate), "no_sections_changed")


def test_whole_gate_failure_cannot_be_hidden_by_in_scope_change(pair):
    sections = json.loads(pair[0]["raw_response"])
    sections["s01"] = sections["s01"].replace("Synthetic", "Hypothetical")
    candidate = _synthetic_record(pair[0]["analysis"], sections, attempt=2)
    _reason(contract.assess_candidate(_prepare(pair[0], ("s01",)), **candidate), "whole_report_gate_failed")


def test_real_regression_guard_stops_a_new_word_budget_failure(pair):
    base = _synthetic_record(pair[0]["analysis"], json.loads(pair[1]["raw_response"]))
    candidate = _synthetic_record(pair[0]["analysis"], json.loads(pair[0]["raw_response"]), attempt=2)
    _reason(contract.assess_candidate(_prepare(base), **candidate), "repair_regression")


def test_regression_guard_still_required_when_candidate_whole_gate_says_pass(pair, monkeypatch):
    outcomes = iter(
        [
            repair_quality(passed=True),
            repair_quality(passed=True, statuses={"Safety disclaimer": "warning"}),
        ]
    )
    calls = []

    def assess(body, analysis, *, model_evidence):
        calls.append((body, analysis, model_evidence))
        return next(outcomes)

    monkeypatch.setattr(contract, "assess_generated_narrative", assess)
    _reason(contract.assess_candidate(_prepare(pair[0]), **pair[1]), "repair_regression")
    assert len(calls) == 2
    assert calls[0][2] == pair[0]["model_evidence"] and calls[1][2] == pair[1]["model_evidence"]
    assert calls[0][0] != calls[1][0]


@pytest.mark.parametrize("name", ["analysis", "submitted_messages", "model_evidence", "raw_response"])
def test_utf8_caps_reject_before_large_input_can_be_serialized_or_admitted(pair, name):
    record = copy.deepcopy(pair[0])
    if name == "analysis":
        record[name]["PRIVATE"] = "é" * (contract.MAX_ANALYSIS_BYTES // 2 + 1)
    elif name == "submitted_messages":
        record[name][0]["content"] = "é" * (contract.MAX_MESSAGES_BYTES // 2 + 1)
    elif name == "model_evidence":
        record[name]["context"] = "é" * (contract.MAX_SNAPSHOT_BYTES // 2 + 1)
    else:
        record[name] = "é" * (contract.MAX_RAW_BYTES // 2 + 1)
    with pytest.raises(contract.ContractInputError, match="^input_limit_exceeded$"):
        _prepare(record)


@pytest.mark.parametrize("malformed", [float("nan"), float("inf"), {1: "PRIVATE"}, {"PRIVATE"}, "\ud800", object()])
def test_non_json_and_invalid_unicode_inputs_fail_without_echo(pair, malformed):
    pair[0]["analysis"]["PRIVATE"] = malformed
    with pytest.raises(contract.ContractInputError, match="^input_invalid$"):
        _prepare(pair[0])


@pytest.mark.parametrize("kind", ["depth", "nodes", "integer", "cycle"])
def test_json_traversal_is_bounded_before_encoding(pair, kind):
    analysis = pair[0]["analysis"]
    expected = "input_limit_exceeded"
    if kind == "depth":
        value = []
        for _ in range(contract.MAX_JSON_DEPTH + 1):
            value = [value]
        analysis["extra"] = value
    elif kind == "nodes":
        analysis["extra"] = [0] * (contract.MAX_JSON_NODES + 1)
    elif kind == "integer":
        analysis["extra"] = 1 << contract.MAX_INTEGER_BITS
    else:
        analysis["extra"] = analysis
        expected = "input_invalid"
    with pytest.raises(contract.ContractInputError, match="^" + expected + "$"):
        _prepare(pair[0])


def test_repeated_noncyclic_alias_is_ordinary_json(pair):
    extra = ["PRIVATE alias"]
    for record in pair:
        record["analysis"]["extra"] = [extra, extra]
    assert contract.assess_candidate(_prepare(pair[0]), **pair[1]).status == "offline_contract_accepted"


def test_oversized_forged_prepared_payload_is_bounded_before_json_parse(pair):
    forged = contract.PreparedBase("PRIVATE" * (contract.MAX_PREPARED_BYTES // 7 + 1), "0" * 64)
    _reason(contract.assess_candidate(forged, **pair[1]), "prepared_base_invalid")


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "PRIVATE"),
        ("reason_codes", ("PRIVATE",)),
        ("base_digests", (("PRIVATE", "0" * 64),)),
        ("declared_section_ids", ("PRIVATE",)),
        ("base_attempt", True),
        ("changed_section_ids", ("PRIVATE",)),
    ],
)
def test_result_serialization_revalidates_forged_fields(pair, field, value):
    result = contract.assess_candidate(_prepare(pair[0]), **pair[1])
    object.__setattr__(result, field, value)
    with pytest.raises(contract.ContractInputError, match="^input_invalid$"):
        result.to_dict()


def test_forged_digest_name_subclass_cannot_escape_output_allowlist(pair):
    class ForgedName(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    result = contract.assess_candidate(_prepare(pair[0]), **pair[1])
    forged = ((ForgedName("PRIVATE"), result.base_digests[0][1]), *result.base_digests[1:])
    object.__setattr__(result, "base_digests", forged)
    with pytest.raises(contract.ContractInputError, match="^input_invalid$"):
        result.to_dict()


def test_current_v12_fingerprint_is_unchanged():
    assert CURRENT_POLICY == "governed-report-v12"
    assert QUALITY_POLICY_FINGERPRINT == "39c7ae6687fcef29f4ce1e8f6c3d7d04d13a65f89f2b15ea667a0a1af2140130"


def test_unknown_error_codes_cannot_echo_private_text():
    assert str(contract.ContractInputError("PRIVATE")) == "input_invalid"
    with pytest.raises(contract.ContractInputError):
        replace(contract.OfflineAssessment("offline_contract_rejected", ("input_invalid",)), reason_codes=("PRIVATE",))
