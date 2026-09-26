"""Offline lexical review clues; neither entailment nor historical SDK attestation."""

from __future__ import annotations

import hashlib
import json
import re

from scripts import atomic_claim_adapter as adapter
from scripts import atomic_claim_contract as contract
from src.report_grounding import _tokens

SCHEMA = "atomic-quote-advisory-v1"
MAX_LISTED_DIFFERENCES = 64
MAX_CUE_OCCURRENCES = 8
CUE_CONTEXT_CHARACTERS = 80
_NUMBER = re.compile(r"(?<!\w)[+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)%?(?!\w)")
_MARKERS = {
    "negation": re.compile(r"\b(?:not|never|without|cannot|no|neither|nor)\b|n['’]t\b", re.I),
    "condition": re.compile(r"\b(?:if|unless|only|except|when|until|before|after|provided|subject\s+to)\b", re.I),
    "qualifier": re.compile(
        r"\b(?:may|might|could|some|all|any|up\s+to|at\s+least|at\s+most|trained|adult|adults|eligible|approved|excluded|excluding|usually|generally)\b",
        re.I,
    ),
}
_TOPIC_CUES = {
    7: {
        "preparation": r"prepar(?:e|ed|ation|ations)|preparedness",
        "supplies": r"emergency\s+kits?|supplies",
        "plans": r"plans?|planning",
        "maintenance": r"inspect(?:ion|ions)?|maintenance|maintain",
        "warnings": r"warnings?|alerts?",
    },
    11: {
        "communication": r"communicat(?:ion|ions|e|es|ed|ing)",
        "support_contacts_agencies": r"support|contacts?|agenc(?:y|ies)",
        "warnings_updates": r"warnings?|alerts?|updates?",
        "easy_english": r"easy[\s-]*english|plain[\s-]+language",
        "language_access": r"interpreters?|translation|translations|multilingual|accessibility",
    },
    12: {
        "first_aid": r"first[\s-]+aid",
        "cpr": r"CPR",
        "aed": r"AED",
        "training": r"training",
        "drills": r"drills?",
        "exercises": r"exercises?",
    },
}
_LIMITATIONS = [
    "Selected-quote lexical differences are review clues, not judgments of truth or semantic support.",
    "English-oriented tokenization, synonyms, abbreviations and inflection can produce false alarms; missing terms are not semantic verdicts.",
    "Matching words or numbers cannot establish populations, roles, relations, conditions, or causality.",
    "Context outside the selected quote is displayed separately and never resolves a selected-quote difference.",
    "Topic cues include negated mentions: observed does not make abstention wrong; not_observed does not mean no evidence.",
    "Every claim, abstention and local proposal needs manual review even when no difference is listed.",
]


def _numbers(text):
    """Literal comparison includes 000; no numeric equivalence is inferred."""
    return {match[0] for match in _NUMBER.finditer(text)}


def _markers(text):
    return {
        name: sorted({match[0].casefold() for match in pattern.finditer(text)}) for name, pattern in _MARKERS.items()
    }


def _context_segment(text, start, end, missing_terms, missing_numbers):
    segment = text[start:end]
    return {
        "span": {"start": start, "end": end},
        "text": segment,
        "claim_terms_missing_from_quote_found_here": sorted(set(missing_terms) & _tokens(segment)),
        "numeric_literals_missing_from_quote_found_here": sorted(set(missing_numbers) & _numbers(segment)),
        "markers_observed_here": _markers(segment),
        "characters_omitted": 0,
    }


def _claim_review(item, passages):
    basis, quote_info = item["basis"], item["basis"]["evidence"]
    claim, quote = basis["text"], quote_info["quote"]
    passage = passages[quote_info["passage_ref"]]
    missing_terms = sorted(_tokens(claim) - _tokens(quote))
    missing_numbers = sorted(_numbers(claim) - _numbers(quote))
    claim_markers, quote_markers = _markers(claim), _markers(quote)
    differences = {
        name: {
            "claim_only": sorted(set(claim_markers[name]) - set(quote_markers[name])),
            "quote_only": sorted(set(quote_markers[name]) - set(claim_markers[name])),
        }
        for name in _MARKERS
    }
    clues = []
    if missing_terms:
        clues.append("possible_claim_content_difference")
    if missing_numbers:
        clues.append("possible_numeric_literal_difference")
    clues.extend(f"possible_{name}_marker_difference" for name, values in differences.items() if any(values.values()))
    return {
        "claim_text": claim,
        "selected_quote": {**quote_info, "source_id": passage["source_id"], "chunk_id": passage["chunk_id"]},
        "claim_content_terms_not_in_quote": missing_terms[:MAX_LISTED_DIFFERENCES],
        "numeric_literals_not_in_quote": missing_numbers[:MAX_LISTED_DIFFERENCES],
        "marker_difference": differences,
        "possible_review_clues": clues,
        "context_review": {
            "scope": "selected_passage_only; before_and_after_are_independent_fragments",
            "used_to_resolve_selected_quote_differences": False,
            "other_passages_used": False,
            "before": _context_segment(passage["text"], 0, quote_info["quote_start"], missing_terms, missing_numbers),
            "after": _context_segment(
                passage["text"], quote_info["quote_end"], len(passage["text"]), missing_terms, missing_numbers
            ),
        },
        "processing": {
            "missing_terms_total": len(missing_terms),
            "missing_terms_omitted": max(0, len(missing_terms) - MAX_LISTED_DIFFERENCES),
            "missing_numeric_literals_total": len(missing_numbers),
            "missing_numeric_literals_omitted": max(0, len(missing_numbers) - MAX_LISTED_DIFFERENCES),
        },
    }


def _cue_occurrence(passage, match):
    text = passage["text"]
    left, right = max(0, match.start() - CUE_CONTEXT_CHARACTERS), min(len(text), match.end() + CUE_CONTEXT_CHARACTERS)
    return {
        "passage_ref": passage["passage_ref"],
        "source_id": passage["source_id"],
        "chunk_id": passage["chunk_id"],
        "span": {"start": match.start(), "end": match.end()},
        "matched_text": match[0],
        "context": {
            "span": {"start": left, "end": right},
            "text": text[left:right],
            "characters_omitted_before": left,
            "characters_omitted_after": len(text) - right,
            "markers_observed": _markers(text[left:right]),
        },
    }


def _cue_review(section, passages):
    inventory = []
    for name, expression in _TOPIC_CUES[section].items():
        pattern = re.compile(r"(?<!\w)(?:" + expression + r")(?!\w)", re.I)
        listed, total, omitted_refs = [], 0, set()
        for passage in passages.values():
            for match in pattern.finditer(passage["text"]):
                total += 1
                if len(listed) < MAX_CUE_OCCURRENCES:
                    listed.append(_cue_occurrence(passage, match))
                else:
                    omitted_refs.add(passage["passage_ref"])
        inventory.append(
            {
                "cue": name,
                "observation": "observed" if total else "not_observed",
                "occurrences": listed,
                "occurrences_total": total,
                "occurrences_omitted": total - len(listed),
                "omitted_occurrence_passage_refs": sorted(omitted_refs),
            }
        )
    return {
        "version": "limited-topic-cues-v1",
        "topic_cue_inventory": inventory,
        "local_sufficiency": "unknown",
        "abstention_correctness": "unknown",
        "interpretation": "Cues may be negated or unrelated to local needs. Neither observation state decides sufficiency or abstention correctness.",
        "processing": {
            "passages_scanned": len(passages),
            "passages_omitted": 0,
            "max_listed_occurrences_per_cue": MAX_CUE_OCCURRENCES,
            "all_visible_text_scanned": True,
        },
    }


def review_selection(raw_selection, evidence_pack):
    checked = adapter.validate_selection(raw_selection, evidence_pack)
    passages = {passage["passage_ref"]: passage for passage in evidence_pack["passages"]}
    rows = []
    for item in checked["canonical_payload"]["items"]:
        row = {
            "id": item["id"],
            "section_id": item["section_id"],
            "basis_kind": item["basis"]["kind"],
            "manual_review_required": True,
            "semantic_support": "unknown",
            "local_proposal": {
                "text": item["local_proposal"],
                "review_required": True,
                "semantic_support": "unknown",
                "basis_evidence_inherited": False,
            },
        }
        if item["basis"]["kind"] == "claim":
            row["claim_review"] = _claim_review(item, passages)
        else:
            row["abstention_reason"] = item["basis"]["reason"]
            row["abstention_review"] = _cue_review(item["section_id"], passages)
        rows.append(row)
    raw_bytes = raw_selection if isinstance(raw_selection, bytes) else raw_selection.encode("utf-8")
    return {
        "schema": SCHEMA,
        "raw_selection_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canonical_payload_sha256": checked["canonical_payload_sha256"],
        "evidence_pack_sha256": evidence_pack["evidence_pack_sha256"],
        "items": rows,
        "additional_model_calls": 0,
        "new_transport_capture": False,
        "input_origin": "caller_supplied_revalidated",
        "span_unit": "python_unicode_codepoints",
        "full_report_coverage": "not_evaluated",
        "semantic_support": "unknown",
        "semantic_accuracy": None,
        "manual_review_required": True,
        "production_enabled": False,
        "release_gate": {"active": False},
        "limitations": list(_LIMITATIONS),
    }


def _render_claim(review):
    safe = contract._safe
    quote = review["selected_quote"]
    lines = [
        "Claim: " + safe(review["claim_text"]),
        "",
        "Selected quote: " + safe(quote["quote"]),
        "",
        f"Source {safe(quote['source_id'])}; chunk {safe(quote['chunk_id'])}; reference {safe(quote['passage_ref'])}; "
        f"codepoints [{quote['quote_start']}, {quote['quote_end']}).",
        "",
        "Content terms absent from selected quote: "
        + safe(", ".join(review["claim_content_terms_not_in_quote"]) or "none listed"),
        "Numeric literals absent from selected quote: "
        + safe(", ".join(review["numeric_literals_not_in_quote"]) or "none listed"),
        "Possible marker differences: " + safe(json.dumps(review["marker_difference"], ensure_ascii=False)),
        "Processing: " + safe(json.dumps(review["processing"])),
        "",
    ]
    for side in ("before", "after"):
        context = review["context_review"][side]
        lines.extend(
            [
                f"Context {side} selected quote [{context['span']['start']}, {context['span']['end']}), separately reviewed:",
                safe(context["text"]) or "(empty)",
                "Context-only clues: "
                + safe(
                    json.dumps(
                        {key: value for key, value in context.items() if key not in {"text", "span"}},
                        ensure_ascii=False,
                    )
                ),
                "",
            ]
        )
    return lines


def render_advisory(raw_selection, evidence_pack):
    """Always revalidate raw input; no already-reviewed dictionary is accepted."""
    review = review_selection(raw_selection, evidence_pack)
    safe = contract._safe
    lines = [
        "# OFFLINE REVIEW",
        "# NOT REPORT",
        "",
        "Manual review required. Semantic support remains unknown.",
        "No additional model calls or new transport capture; this does not attest any historical SDK request.",
        "",
    ]
    lines.extend(safe(text) for text in review["limitations"])
    for item in review["items"]:
        lines.extend(["", f"## Item {safe(item['id'])} — section {item['section_id']}", ""])
        if item["basis_kind"] == "claim":
            lines.extend(_render_claim(item["claim_review"]))
        else:
            details = item["abstention_review"]
            lines.extend(
                [
                    "Abstention reason: " + safe(item["abstention_reason"]),
                    "",
                    safe(details["interpretation"]),
                    "Local sufficiency and abstention correctness: unknown.",
                ]
            )
            for cue in details["topic_cue_inventory"]:
                lines.append(
                    f"Cue {safe(cue['cue'])}: {cue['observation']}; total {cue['occurrences_total']}; omitted {cue['occurrences_omitted']}."
                )
                for occurrence in cue["occurrences"]:
                    lines.append(safe(json.dumps(occurrence, ensure_ascii=False)))
                if cue["occurrences_omitted"]:
                    lines.append(
                        "Omitted occurrence references: " + safe(", ".join(cue["omitted_occurrence_passage_refs"]))
                    )
        lines.extend(
            [
                "",
                "### Local proposal — separate review required; no inherited evidence support",
                "",
                safe(item["local_proposal"]["text"]),
                "",
            ]
        )
    return "\n".join(lines)
