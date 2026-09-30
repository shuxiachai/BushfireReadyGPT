"""Narrow, non-scoring advisories about an excerpt's stated audience.

This diagnostic deliberately examines only the already-validated passages that
were submitted with a final SDK request.  It does not alter body-claim evidence,
quality gates, or a report record.
"""

from __future__ import annotations

import re
from hashlib import sha256

SOURCE_APPLICABILITY_METHOD = "source_applicability_advisory_v1"
_CAMPUS_EVACUATION = re.compile(
    r"\b(?:your\s+|a\s+|the\s+)?(?:school|campus)(?:\s+groups?)?\s+(?:will\s+)?need\s+support\s+to\s+evacuate\b",
    re.I,
)
_HOUSEHOLD_EVACUATION = re.compile(r"\b(?:your\s+)?household\s+(?:will\s+)?need\s+support\s+to\s+evacuate\b", re.I)
_SENTENCE = re.compile(r"[^.!?]*(?:[.!?]|$)", re.S)
_CAMPUS_CONDITION_PREFIX = re.compile(r"(?:[-*]\s+)?if(?:\s+(?:your\s+|a\s+|the\s+)?household\s+or)?", re.I)
_COUNCIL_SUPPORT_INSTRUCTION = re.compile(
    r",\s*(?:contact\s+(?:your\s+|the\s+)?(?:local\s+)?council"
    r"|find\s+out\s+what\s+help\s+is\s+available\s+from\s+(?:your\s+|the\s+)?local\s+council)"
    r"(?:\s+and\s+support\s+agencies)?[.!]?",
    re.I,
)


def _source_sentences(text):
    """Return local submitted sentences containing the narrowly scoped action."""

    sentences = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0)
        start = match.start()
        leading = len(sentence) - len(sentence.lstrip())
        trailing = len(sentence.rstrip())
        sentence = sentence.strip()
        if not sentence:
            continue
        sentences.append((sentence, {"start": start + leading, "end": start + trailing}))
    return sentences


def _finding_reason(claim):
    if claim.get("classification") == "uncertain" or str(claim.get("claim") or "").lower().startswith(
        "unverified proposal"
    ):
        return (
            "This unverified proposal still applies the household-only submitted source wording to a school or "
            "campus audience. Confirm local application."
        )
    return (
        "The submitted source sentence names a household as the audience for this evacuation support action, "
        "while the report names a school or campus audience. Confirm local applicability."
    )


def _claim_applies_campus_action(text):
    """Reject explicit unknown-question wording without interpreting general prose."""

    for match in _CAMPUS_EVACUATION.finditer(text):
        before = text[max(0, match.start() - 24) : match.start()]
        after = text[match.end() : match.end() + 48]
        if re.search(r"\bwhether\s+(?:a\s+|the\s+|your\s+)?$", before, re.I) and re.search(
            r"\bis\s+unknown\b", after, re.I
        ):
            continue
        return True
    return False


def _source_has_explicit_campus_instruction(sentence):
    """Recognise only a local conditional instruction in the two scoped forms.

    The whole sentence must say "If <audience> need support to evacuate,
    contact ... council" or "find out what help is available from ... council".
    A quoted example, denied statement or unknown premise alone is not such an
    instruction. This is an audience check, not a general entailment judgment.
    """

    return any(
        _CAMPUS_CONDITION_PREFIX.fullmatch(sentence[: match.start()].strip())
        and _COUNCIL_SUPPORT_INSTRUCTION.fullmatch(sentence[match.end() :].strip())
        for match in _CAMPUS_EVACUATION.finditer(sentence)
    )


def _resolved_passages(refs, visible_passages, source_id):
    """Resolve only hash-bound references; never fall back to a whole chunk."""

    if not isinstance(refs, list):
        return []
    resolved = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        index = ref.get("passage_index")
        if type(index) is not int or not 0 <= index < len(visible_passages):
            continue
        passage = visible_passages[index]
        if not isinstance(passage, dict):
            continue
        text = str(passage.get("text") or "")
        if (
            passage.get("source_id") != source_id
            or ref.get("source_id") != source_id
            or passage.get("chunk_id") != ref.get("chunk_id")
            or sha256(text.encode("utf-8")).hexdigest() != ref.get("visible_text_sha256")
        ):
            continue
        resolved.append((ref, text))
    return resolved


def build_source_applicability_advisory(body_evaluation, visible_passages, *, snapshot_status) -> dict:
    """Identify the one known household-versus-campus evacuation wording gap.

    Results are advisory findings or explicit unassessed records.  They never
    describe a claim as passed, supported, accurate, or scored.
    """

    evaluation = body_evaluation if isinstance(body_evaluation, dict) else {}
    claims = evaluation.get("claims") if isinstance(evaluation.get("claims"), list) else []
    passages = visible_passages if isinstance(visible_passages, list) else []
    findings, unassessed = [], []
    processing_complete = isinstance(body_evaluation, dict) and isinstance(visible_passages, list)

    for claim in claims:
        if not isinstance(claim, dict):
            processing_complete = False
            continue
        claim_text = str(claim.get("claim") or "")
        if not _claim_applies_campus_action(claim_text):
            continue
        claim_id = str(claim.get("claim_id") or "")
        checks = claim.get("source_checks") if isinstance(claim.get("source_checks"), list) else []
        rag_checks = [
            check
            for check in checks
            if isinstance(check, dict) and check.get("source_type") == "rag" and check.get("source_id")
        ]
        if snapshot_status != "captured":
            unassessed.append(
                {
                    "claim_id": claim_id,
                    "rule_id": "household_evacuation_audience_v1",
                    "reason": "final_submitted_passages_unavailable",
                }
            )
            continue
        if not rag_checks:
            unassessed.append(
                {
                    "claim_id": claim_id,
                    "rule_id": "household_evacuation_audience_v1",
                    "reason": "no_cited_submitted_rag_passage_to_assess",
                }
            )
            continue
        for check in rag_checks:
            source_id = str(check["source_id"])
            resolved = _resolved_passages(check.get("passage_refs"), passages, source_id)
            if not resolved:
                unassessed.append(
                    {
                        "claim_id": claim_id,
                        "rule_id": "household_evacuation_audience_v1",
                        "source_id": source_id,
                        "reason": "cited_source_not_visible_in_final_submitted_passages",
                    }
                )
                continue
            local_sentences = [
                (ref, sentence, span) for ref, text in resolved for sentence, span in _source_sentences(text)
            ]
            # An audience phrase alone can also be a question, denial or quoted
            # wording. Only an explicit local conditional instruction resolves
            # the narrow discrepancy; it does not mark the report claim passed.
            if any(_source_has_explicit_campus_instruction(sentence) for _, sentence, _ in local_sentences):
                continue
            household_sentences = [
                (ref, sentence, span)
                for ref, sentence, span in local_sentences
                if _HOUSEHOLD_EVACUATION.search(sentence)
            ]
            if not household_sentences and any(
                _CAMPUS_EVACUATION.search(sentence) for _, sentence, _ in local_sentences
            ):
                unassessed.append(
                    {
                        "claim_id": claim_id,
                        "rule_id": "household_evacuation_audience_v1",
                        "source_id": source_id,
                        "reason": "campus_wording_without_explicit_conditional_support",
                    }
                )
            for ref, sentence, span in household_sentences:
                findings.append(
                    {
                        "claim_id": claim_id,
                        "rule_id": "household_evacuation_audience_v1",
                        "type": "audience_applicability_review",
                        "source_id": source_id,
                        "passage_refs": [dict(ref)],
                        "source_sentence": sentence,
                        "source_sentence_span": span,
                        "reason": _finding_reason(claim),
                    }
                )

    return {
        "method": SOURCE_APPLICABILITY_METHOD,
        "snapshot_status": snapshot_status,
        "processing_complete": processing_complete,
        "findings": findings,
        "unassessed": unassessed,
    }
