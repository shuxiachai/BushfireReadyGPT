"""Isolated claim-pair experiment. Nothing here is imported by production code."""

from __future__ import annotations

import copy
import re
import time

from src.model_evidence import (
    EvidencePrompt,
    EvidenceResponse,
    capture_model_evidence,
    json_sha256,
    normalized_evidence_response,
    text_sha256,
    unavailable_model_evidence,
)

TARGET_SECTIONS = (7, 11, 12)
VARIANTS = ("baseline", "claim_pair_v1")
LAYOUT_GUIDANCE = """

Experimental claim-pair layout (claim_pair_v1):
Keep the complete report with all 15 required sections, the 650 to 800 word
budget, at least 300 words of substantive prose, and every existing safety,
source, draft, and human-review requirement. In each of sections 7, 11 and 12,
include exactly one pair of adjacent ordinary paragraphs, in this order:
Evidence basis: one narrow statement supported by a supplied passage, immediately
followed by its complete existing opaque citation token copied exactly.
Local application: a proposed local action, proposed owner, or item requiring local
confirmation. Do not claim the passage establishes local conditions or approval.
Use these exact paragraph labels, separated by a blank line; do not make this
pair a list, table, heading, quotation, or code block. Use one statement in the
Evidence basis paragraph. If no supplied passage supports a suitable statement,
write "Evidence basis: To be confirmed." without inventing evidence or a source.
That is an abstention, not an evidenced answer. The Local application paragraph
has the same citation obligations as all other prose; its label grants no
exemption. Preserve other required section content. Do not add sources, repeat
the evidence context, or shorten the report to just these pairs.
"""


def build_variant_prompt(base: EvidencePrompt, variant: str) -> EvidencePrompt:
    """Copy request metadata; baseline's characters remain exactly unchanged."""
    if variant not in VARIANTS:
        raise ValueError("Unknown experimental variant.")
    if not isinstance(base, EvidencePrompt):
        raise TypeError("An EvidencePrompt is required.")
    return EvidencePrompt(
        str(base) + (LAYOUT_GUIDANCE if variant == "claim_pair_v1" else ""),
        assembly=base.assembly,
        request_kind=base.request_kind,
    )


def _sections(report):
    """Offsets in the original text; ignore fenced examples and hidden markup."""
    from src.report_claim_evidence import _visible_mask

    masked = _visible_mask(report)
    headings, offset, fence = [], 0, None
    for line in masked.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        elif fence is None:
            heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
            if heading:
                number = re.match(r"(\d+)[.)]\s", heading[1])
                headings.append((int(number[1]) if number else None, offset, offset + len(line)))
        offset += len(line)
    return [
        (number, start, end, headings[index + 1][1] if index + 1 < len(headings) else len(report))
        for index, (number, start, end) in enumerate(headings)
    ]


def _paragraphs(report, start, end):
    return [
        {"text": match[0].strip(), "span": {"start": start + match.start(), "end": start + match.end()}}
        for match in re.finditer(r"[^\r\n]+(?:\r?\n(?![ \t]*\r?\n)[^\r\n]+)*", report[start:end])
        if match[0].strip()
    ]


def _plain_pair_paragraph(report, paragraph, label):
    raw = report[paragraph["span"]["start"] : paragraph["span"]["end"]]
    first_line = raw.splitlines()[0].expandtabs(4)
    return (
        len(first_line) - len(first_line.lstrip(" ")) < 4
        and paragraph["text"].startswith(label)
        and not re.search(r"(?m)^\s*(?:[-+*>#|`~]|\d+[.)]\s)", paragraph["text"])
    )


def _citation_follows_statement(value, bindings):
    labels = [label for label in sorted(bindings, key=len, reverse=True) if label in value]
    if not labels:
        return False
    first = min(value.index(label) for label in labels)
    if len(re.findall(r"[A-Za-z]+", value[:first])) < 2:
        return False
    tail = value[first:]
    for label in labels:
        tail = tail.replace(label, " ")
    return re.fullmatch(r"[\s.!?]*", tail) is not None


def _pair_row(report, section, ranges, body, bindings):
    row = {"section": section, "status": "missing", "reasons": [], "citations": [], "source_checks": []}
    if not ranges:
        return row
    if len(ranges) != 1:
        return {**row, "status": "duplicate", "reasons": ["duplicate_section"]}
    _, heading_start, start, end = ranges[0]
    row["section_span"] = {"start": heading_start, "end": end}
    paragraphs = _paragraphs(report, start, end)
    basis = [index for index, p in enumerate(paragraphs) if "Evidence basis:" in p["text"]]
    local = [index for index, p in enumerate(paragraphs) if "Local application:" in p["text"]]
    if len(basis) > 1 or len(local) > 1:
        return {**row, "status": "duplicate", "reasons": ["duplicate_pair_label"]}
    if not basis or not local:
        return {**row, "reasons": ["missing_pair_label"]}
    evidence, application = paragraphs[basis[0]], paragraphs[local[0]]
    row.update(evidence_basis=evidence, local_application=application)
    plain = all(
        _plain_pair_paragraph(report, p, label)
        for p, label in ((evidence, "Evidence basis:"), (application, "Local application:"))
    )
    if not plain or local[0] != basis[0] + 1:
        return {**row, "status": "malformed", "reasons": ["pair_must_be_adjacent_plain_paragraphs"]}
    if not application["text"].removeprefix("Local application:").strip():
        return {**row, "status": "malformed", "reasons": ["empty_local_application"]}
    value = evidence["text"].removeprefix("Evidence basis:").strip()
    if re.fullmatch(r"To be confirmed[.!]?", value, flags=re.I):
        return {**row, "status": "abstained", "reasons": ["no_evidence_claim_offered"]}
    leftover = value
    for label in sorted(bindings, key=len, reverse=True):
        if label in leftover:
            row["citations"].append({"label": label, **bindings[label]})
            leftover = leftover.replace(label, " ")
    unknown = re.findall(r"\[O1(?:-RAG)?\][^\s]*", leftover)
    if unknown:
        row["unknown_tokens"] = unknown
        row["reasons"].append("unknown_source")
    if not row["citations"]:
        row["reasons"].append("missing_citation")
    elif not _citation_follows_statement(value, bindings):
        row["reasons"].append("citation_must_follow_complete_statement")
    if len(re.findall(r"[A-Za-z]+", leftover)) < 2:
        row["reasons"].append("missing_evidence_statement")
    from src.report_claim_evidence import _sentence_spans

    if len([leftover[a:b] for a, b in _sentence_spans(leftover, {}) if leftover[a:b].strip()]) != 1:
        row["reasons"].append("multiple_or_empty_evidence_statements")
    claims = [
        claim
        for claim in body["claims"]
        if claim["span"]["start"] < evidence["span"]["end"] and claim["span"]["end"] > evidence["span"]["start"]
    ]
    row["body_claim_ids"] = [claim["claim_id"] for claim in claims]
    row["source_checks"] = [check for claim in claims for check in claim["source_checks"]]
    row["status"] = "malformed" if row["reasons"] else "complete"
    support_reasons = set()
    if body["snapshot_status"] != "captured":
        support_reasons.add("snapshot_unavailable")
    for check in row["source_checks"]:
        if "cited_source_not_submitted" in check["reasons"]:
            support_reasons.add("not_submitted")
        if check["support_status"] == "no_lexical_match":
            support_reasons.add("no_lexical_match")
        support_reasons.update(check["reasons"])
    row["support_reasons"] = sorted(support_reasons)
    row["lexically_supported"] = (
        row["status"] == "complete"
        and bool(row["source_checks"])
        and all(check["support_status"] == "lexical_match" for check in row["source_checks"])
    )
    return row


def parse_claim_pairs(report, analysis, snapshot=None):
    """Format diagnostics only; never alter existing body claim classification."""
    from src.report_claim_evidence import _bindings, _catalog, evaluate_body_claim_evidence

    report = str(report or "")
    body = evaluate_body_claim_evidence(report, analysis, snapshot)
    sections = _sections(report)
    bindings = _bindings(_catalog(analysis))
    rows = [_pair_row(report, n, [s for s in sections if s[0] == n], body, bindings) for n in TARGET_SECTIONS]
    # Preserve unknown tokens anywhere, including Local application and non-target sections.
    unbound = report
    for label in sorted(bindings, key=len, reverse=True):
        unbound = unbound.replace(label, " " * len(label))
    unknown = [
        {"text": match[0], "span": {"start": match.start(), "end": match.end()}, "reason": "unknown_source"}
        for match in re.finditer(r"\[O1(?:-RAG)?[^\s]*", unbound)
    ]
    return {
        "schema": "body-evidence-claim-pairs-v1",
        "target_sections": list(TARGET_SECTIONS),
        "pairs": rows,
        "unknown_citations": unknown,
        "complete_pairs": sum(row["status"] == "complete" for row in rows),
        "pair_completeness_rate": sum(row["status"] == "complete" for row in rows) / len(TARGET_SECTIONS),
        "abstained_pairs": sum(row["status"] == "abstained" for row in rows),
        "lexically_supported_pairs": sum(row.get("lexically_supported", False) for row in rows),
        "semantic_accuracy": None,
        "interpretation": "Candidate layout compliance only; lexical alignment is not semantic accuracy.",
    }


def _report_result(narrative, analysis, snapshot, *, generation_quality=None, normalization_result=None):
    from src.report_claim_evidence import evaluate_body_claim_evidence
    from src.report_generation_quality import evaluate_governed_report, retain_generation_assembly_failure
    from src.report_template import append_evidence_tables, append_human_signoff, apply_governance_notice

    report = append_human_signoff(append_evidence_tables(apply_governance_notice(narrative), analysis), {})
    quality = evaluate_governed_report(report, analysis, model_evidence=snapshot)
    quality = retain_generation_assembly_failure(quality, generation_quality, normalization_result=normalization_result)
    return {
        "report": report,
        "report_sha256": text_sha256(report),
        "model_evidence": snapshot,
        "governed_quality": quality,
        "body_claim_evidence": evaluate_body_claim_evidence(report, analysis, snapshot),
        "claim_pairs": parse_claim_pairs(report, analysis, snapshot),
    }


def run_arm(scenario, frozen_analysis, variant, client):
    """Use production repair policy; preserve failed arms and every admitted draft."""
    from src.report_generation_quality import (
        MAX_REPORT_REPAIR_ATTEMPTS,
        MAX_REPORT_REPAIR_PROMPT_CHARACTERS,
        _normalise_generation_response,
        generate_narrative_with_repairs,
    )
    from src.report_template import build_report_prompt

    analysis = copy.deepcopy(frozen_analysis)
    frozen_hash = json_sha256(analysis)
    result = {
        "case_id": scenario["id"],
        "variant": variant,
        "analysis_sha256": frozen_hash,
        "assembly_sha256": json_sha256(analysis.get("rag_context_assembly")),
        "status": "failed",
        "attempts": [],
        "model_calls": 0,
        "initial": None,
        "final": None,
        "governed_gate_passed": False,
        "semantic_accuracy": None,
    }
    started = time.perf_counter()

    def generate_attempt(attempt_prompt, attempt_number, is_repair):
        submitted = build_variant_prompt(attempt_prompt, variant)
        record = {
            "attempt_number": attempt_number,
            "request_kind": submitted.request_kind,
            "prompt_characters": len(submitted),
            "prompt_sha256": text_sha256(str(submitted).strip()),
            "assembly_sha256": json_sha256(submitted.assembly),
            "model_call_started": False,
            "usage": None,
        }
        result["attempts"].append(record)
        if attempt_number > MAX_REPORT_REPAIR_ATTEMPTS + 1:
            raise ValueError("Shared three-attempt budget exceeded.")
        # Protocol retries replay the full original request; only the compact
        # structural-repair contract has this character cap in production.
        if submitted.request_kind == "structural_repair" and len(submitted) > MAX_REPORT_REPAIR_PROMPT_CHARACTERS:
            record["error_code"] = "repair_prompt_limit_exceeded"
            raise ValueError("Actual variant repair prompt exceeds the unchanged 18000-character limit.")
        try:
            budget = getattr(client, "budget", None)
            if budget is not None and budget.used >= budget.maximum:
                record["error_code"] = "experiment_call_budget_exhausted"
                raise RuntimeError("experiment_call_budget_exhausted")
            record["model_call_started"] = True
            result["model_calls"] += 1
            response = client.generate(submitted)
            snapshot = capture_model_evidence(submitted, client, response, attempt_number=attempt_number)
            record.update(
                response_boundary="client_admitted_before_report_normalization_not_raw_transport",
                admitted_response=str(response),
                admitted_response_sha256=text_sha256(str(response)),
                model_evidence=snapshot,
            )
            return EvidenceResponse(response, snapshot)
        except Exception as error:
            record.setdefault("error_code", type(error).__name__)
            raise

    try:
        prompt = build_report_prompt(
            scenario["location"],
            scenario["audience"],
            scenario["scenario"],
            scenario["concerns"],
            scenario["timeframe"],
            scenario.get("extra_context", ""),
            analysis=analysis,
            governance_context="Government pilot governance context: Draft - human review required.",
        )
        prompt = EvidencePrompt(prompt, assembly=analysis.get("rag_context_assembly"), request_kind="initial")
        narrative, generation_quality, attempts = generate_narrative_with_repairs(prompt, analysis, generate_attempt)
        result["final"] = _report_result(
            narrative,
            analysis,
            getattr(narrative, "model_evidence", None) or unavailable_model_evidence(),
            generation_quality=generation_quality,
        )
        result["generation_attempts"] = attempts
        result["status"] = "completed"
        result["governed_gate_passed"] = result["final"]["governed_quality"]["approval_gate"]["passed"]
    except Exception as error:
        result["error_code"] = type(error).__name__
        result["generation_attempts"] = len(result["attempts"])
    for record in result["attempts"]:
        if "admitted_response" not in record:
            continue
        try:
            response = EvidenceResponse(record["admitted_response"], record["model_evidence"])
            composed = _normalise_generation_response(response, analysis)
            normalized = normalized_evidence_response(response, composed)
            record["normalized"] = _report_result(
                normalized, analysis, normalized.model_evidence, normalization_result=composed
            )
        except Exception as error:
            record["normalization_error_code"] = type(error).__name__
    if result["attempts"]:
        result["initial"] = result["attempts"][0].get("normalized")
    result["analysis_unchanged"] = json_sha256(analysis) == frozen_hash == json_sha256(frozen_analysis)
    result["capture_valid"] = bool(
        result["final"] and result["final"]["body_claim_evidence"]["snapshot_status"] == "captured"
    )
    if not result["analysis_unchanged"]:
        result.update(status="invalid", governed_gate_passed=False, error_code="frozen_analysis_mutated")
    result["latency_seconds"] = round(time.perf_counter() - started, 3)
    return result
