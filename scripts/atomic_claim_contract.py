"""Synthetic offline quote-binding contract; never a complete or approved report.

Bounds are Unicode codepoints, except MAX_PAYLOAD_BYTES (strict UTF-8 bytes).
One text node is a bounded string, not a claim of verified semantic atomicity.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass

from src.model_evidence import json_sha256, text_sha256, validate_recorded_assembly

PAYLOAD_SCHEMA = "atomic-claim-contract-v1"
PACK_SCHEMA = "atomic-claim-evidence-pack-v1"
MAX_PAYLOAD_BYTES = 16_384
MAX_CLAIM_CHARACTERS = 480
MAX_QUOTE_CHARACTERS = 600
MAX_REASON_CHARACTERS = 280
MAX_PROPOSAL_CHARACTERS = 480
_VALIDATOR_TOKEN = object()
_PACK_KEYS = {"schema", "origin", "length_unit", "assembly_sha256", "passages", "evidence_pack_sha256"}
_PASSAGE_KEYS = {"passage_ref", "source_id", "chunk_id", "retrieved_rank", "text", "text_sha256"}


class ContractError(ValueError):
    """The input does not meet the bounded offline contract."""


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ContractError("Object has missing or unknown fields.")


def _node(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError("Expected one non-empty bounded text node.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]", value):
        raise ContractError("Text contains unsupported control or surrogate codepoints.")
    return value


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def build_evidence_pack(analysis, assembly):
    """Copy only validated recorded visible text; this performs no SDK capture."""
    try:
        visible = validate_recorded_assembly(assembly, analysis)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ContractError("Recorded assembly validation failed.") from error
    passages = []
    for index, passage in enumerate(visible, 1):
        passages.append(
            {
                "passage_ref": f"passage-{index:03d}",
                "source_id": _node(passage["source_id"], 512),
                "chunk_id": _node(passage["chunk_id"], 512),
                "retrieved_rank": passage["retrieved_rank"],
                "text": _node(passage["text"], 2200),
                "text_sha256": text_sha256(passage["text"]),
            }
        )
    pack = {
        "schema": PACK_SCHEMA,
        "origin": "recorded_assembly_visible_text",
        "length_unit": "python_unicode_codepoints",
        "assembly_sha256": json_sha256(assembly),
        "passages": passages,
    }
    pack["evidence_pack_sha256"] = json_sha256(pack)
    return pack


def _pack_passages(pack):
    _keys(pack, _PACK_KEYS)
    if (
        pack["schema"] != PACK_SCHEMA
        or pack["origin"] != "recorded_assembly_visible_text"
        or pack["length_unit"] != "python_unicode_codepoints"
        or not _hash(pack["assembly_sha256"])
        or pack["evidence_pack_sha256"] != json_sha256({k: v for k, v in pack.items() if k != "evidence_pack_sha256"})
    ):
        raise ContractError("Evidence pack binding is invalid.")
    if type(pack["passages"]) is not list or len(pack["passages"]) > 32:
        raise ContractError("Invalid passage collection.")
    refs, ranks = {}, set()
    for passage in pack["passages"]:
        _keys(passage, _PASSAGE_KEYS)
        ref = _node(passage["passage_ref"], 64)
        rank = passage["retrieved_rank"]
        if ref in refs or type(rank) is not int or not 1 <= rank <= 32 or rank in ranks:
            raise ContractError("Duplicate passage reference or invalid retrieval rank.")
        _node(passage["source_id"], 512)
        _node(passage["chunk_id"], 512)
        text = _node(passage["text"], 2200)
        if passage["text_sha256"] != text_sha256(text):
            raise ContractError("Visible passage text hash differs.")
        refs[ref] = passage
        ranks.add(rank)
    return refs


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("Duplicate JSON object key.")
        result[key] = value
    return result


def _reject_number(_value):
    raise ContractError("Non-integer or non-finite JSON number is not allowed.")


def _parse(payload):
    if not isinstance(payload, (str, bytes)):
        raise ContractError("Payload must be a strict JSON string or UTF-8 bytes.")
    try:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ContractError("JSON payload exceeds its byte limit.")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_number,
            parse_float=_reject_number,
        )
    except ContractError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ContractError("Payload is not a complete strict JSON document.") from error


def _basis(basis, passages):
    if type(basis) is not dict:
        raise ContractError("basis must be an object.")
    if basis.get("kind") == "abstention":
        _keys(basis, {"kind", "reason"})
        return {"kind": "abstention", "reason": _node(basis["reason"], MAX_REASON_CHARACTERS)}
    _keys(basis, {"kind", "text", "evidence"})
    if basis["kind"] != "claim":
        raise ContractError("Unknown evidence basis kind.")
    text = _node(basis["text"], MAX_CLAIM_CHARACTERS)
    evidence = basis["evidence"]
    _keys(evidence, {"passage_ref", "quote_start", "quote_end", "quote"})
    ref = _node(evidence["passage_ref"], 64)
    if ref not in passages:
        raise ContractError("Unknown passage reference.")
    passage = passages[ref]
    start, end = evidence["quote_start"], evidence["quote_end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(passage["text"]):
        raise ContractError("Quote offsets must be valid Python Unicode codepoint integers.")
    quote = _node(evidence["quote"], MAX_QUOTE_CHARACTERS)
    if quote != passage["text"][start:end]:
        raise ContractError("Quote does not exactly match the specified visible passage slice.")
    return {
        "kind": "claim",
        "text": text,
        "literal_quote_match": True,
        "evidence": {
            **evidence,
            "source_id": passage["source_id"],
            "chunk_id": passage["chunk_id"],
            "retrieved_rank": passage["retrieved_rank"],
            "visible_text_sha256": passage["text_sha256"],
        },
    }


@dataclass(frozen=True, init=False)
class _ValidatedResult:
    """Immutable validator output; dictionaries are not accepted by the renderer."""

    _json: str

    def __init__(self, data, token=None):
        if token is not _VALIDATOR_TOKEN:
            raise TypeError("Use parse_and_validate to create a review result.")
        object.__setattr__(self, "_json", json.dumps(data, ensure_ascii=False, sort_keys=True))

    def to_dict(self):
        return json.loads(self._json)


def parse_and_validate(payload, evidence_pack):
    """Validate syntax and literal binding only; all semantic review stays open."""
    passages = _pack_passages(evidence_pack)
    parsed = _parse(payload)
    _keys(parsed, {"schema", "evidence_pack_sha256", "items"})
    if parsed["schema"] != PAYLOAD_SCHEMA or parsed["evidence_pack_sha256"] != evidence_pack["evidence_pack_sha256"]:
        raise ContractError("Payload schema or evidence pack hash differs.")
    if type(parsed["items"]) is not list or not 1 <= len(parsed["items"]) <= 3:
        raise ContractError("One to three items are required.")
    ids, sections, items = set(), set(), []
    for item in parsed["items"]:
        _keys(item, {"id", "section_id", "basis", "local_proposal"})
        identity = _node(item["id"], 32)
        section = item["section_id"]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", identity) or identity in ids:
            raise ContractError("Item identifiers must be unique bounded identifiers.")
        if type(section) is not int or section not in {7, 11, 12} or section in sections:
            raise ContractError("Unique section identifiers must be 7, 11, or 12.")
        items.append(
            {
                "id": identity,
                "section_id": section,
                "basis": _basis(item["basis"], passages),
                "local_proposal": _node(item["local_proposal"], MAX_PROPOSAL_CHARACTERS),
                "topic_relevance": "unknown",
                "condition_preservation": "unknown",
                "semantic_atomicity": "unknown",
                "local_proposal_review": "required",
            }
        )
        ids.add(identity)
        sections.add(section)
    return _ValidatedResult(
        {
            "schema": "atomic-claim-review-fragment-v1",
            "evidence_pack_sha256": evidence_pack["evidence_pack_sha256"],
            "contract_valid": True,
            "reference_binding_valid": True,
            "items": items,
            "production_enabled": False,
            "release_gate": {"active": False},
            "model_calls": 0,
            "response_origin": "synthetic_offline",
            "transport_capture": "not_performed",
            "full_report_coverage": "not_evaluated",
            "semantic_accuracy": None,
            "topic_relevance": "unknown",
            "condition_preservation": "unknown",
            "semantic_atomicity": "unknown",
            "local_proposal_review": "required",
        },
        _VALIDATOR_TOKEN,
    )


def _safe(value):
    text = "".join(
        f"\\u{ord(char):04x}" if unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} else char for char in value
    )
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~:/-])", r"\\\1", html.escape(text, quote=False))


def render_preview(validated_result):
    """Render a review fragment; proposal text never inherits the basis evidence."""
    if type(validated_result) is not _ValidatedResult:
        raise TypeError("render_preview requires a result from parse_and_validate.")
    data = validated_result.to_dict()
    lines = [
        "# EXPERIMENTAL REVIEW FRAGMENT",
        "# NOT COMPLETE REPORT",
        "",
        "Synthetic offline input; no model calls or transport capture. Production and release gates are inactive.",
        "Literal quote matching does not establish semantic support, topic relevance, preserved conditions, or atomicity.",
        "Full report coverage is not evaluated. Every local proposal requires separate review.",
        "",
    ]
    for item in data["items"]:
        lines.extend([f"## Review item {_safe(item['id'])} — target section {item['section_id']}", ""])
        basis = item["basis"]
        if basis["kind"] == "claim":
            evidence = basis["evidence"]
            lines.extend(
                [
                    "Evidence basis (semantic support unknown): " + _safe(basis["text"]),
                    "",
                    "Literal matched quote: " + _safe(evidence["quote"]),
                    "",
                    f"Recorded passage: {_safe(evidence['passage_ref'])}; source {_safe(evidence['source_id'])}; "
                    f"chunk {_safe(evidence['chunk_id'])}; codepoints [{evidence['quote_start']}, {evidence['quote_end']}).",
                    "",
                ]
            )
        else:
            lines.extend(["Abstention: " + _safe(basis["reason"]), ""])
        lines.extend(
            [
                "### Local proposal — review required; no inherited evidence support",
                "",
                _safe(item["local_proposal"]),
                "",
            ]
        )
    return "\n".join(lines)
