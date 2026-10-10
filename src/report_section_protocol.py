"""Current report protocol: preserve admitted prose in an application-owned body.

Decoding is separate from rendering. No report extraction or text repair is
permitted before every decoded value has passed admission. Saved-body projection
is a pure inverse and never upgrades or repairs historical text.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata

from src.markdown_tables import is_markdown_table_separator
from src.model_response import validate_operational_directions
from src.report_owned_fields import build_owned_field_spec, render_owned_blocks
from src.section_protocol_error import SectionProtocolError
from src.source_attribution import (
    _CANONICAL_RAG_RETRIEVAL_CLAIM,
    canonical_attribution_bindings,
    canonical_source_token_data,
    expand_known_attribution_tokens,
    fold_known_attribution_labels,
    has_model_authored_raw_html,
    has_model_authored_url,
    has_unbound_attribution_marker,
    normalise_render_equivalent_text,
)

SECTION_KEYS = tuple(f"s{number:02d}" for number in range(1, 16))
SECTION_PROTOCOL_RULESET = "strict-section-prose-json-v1"
SECTION_PROSE_CHECK = "Application-owned section protocol"
MODEL_PROSE_CHECK = "Model prose word budget"
MAX_RAW_BYTES = 65_536
MAX_DECODED_CHARACTERS = 16_384
MAX_SECTION_CHARACTERS = 4_096
_BLOCK_SECTIONS = {"s04": "p2", "s10": "roles", "s13": "actions", "s14": "review"}
_STRUCTURE = re.compile(r"(?m)^\s*(?:#{1,6}(?:\s|$)|>|[-+*]\s|\d+[.)]\s|[|]|`{3,}|~{3,}|[-=]{3,}\s*$)")
# Reference definitions can hide their destination and optional title from the
# rendered report. Match the definition prefix, including multiline labels,
# rather than depending on URL recognition or the rest of its body. Footnote
# definitions share the same prefix. A single '-' or '=' is a setext underline.
_REFERENCE_DEFINITION = re.compile(r"(?m)^[ \t]*\[(?:\\.|[^\]\\])+\][ \t]*:")
_SETEXT_UNDERLINE = re.compile(r"(?m)^[ \t]*[-=]+[ \t]*$")
_SENTINEL = re.compile(
    r"DRAFT\s+STATUS\s+NOTICE|Evidence\s+Tables|Human\s+Review\s+Sign[- ]off|APP_[A-Z0-9_]*|"
    r"<\|[^\n]*|(?:BEGIN|END)_[A-Z_]*(?:DATA|CONTEXT)|\[/?(?:SYSTEM|INST)\]",
    re.I,
)


def _sources(analysis):
    return {
        "official_sources": (analysis.get("data") or {}).get("sources") or [],
        "rag_sources": (analysis.get("knowledge") or {}).get("retrieved_chunks") or [],
    }


def _headings():
    from src.report_template import REPORT_TEMPLATE_SECTIONS

    return tuple(f"{'#' if index == 0 else '##'} {title}" for index, (title, _) in enumerate(REPORT_TEMPLATE_SECTIONS))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SectionProtocolError()
        result[key] = value
    return result


def _reject_constant(_value):
    raise SectionProtocolError()


def validate_section_prose(sections, analysis):
    """Validate all decoded bytes before any stripping, hiding or extraction."""
    if not isinstance(sections, dict) or set(sections) != set(SECTION_KEYS):
        raise SectionProtocolError()
    if any(not isinstance(value, str) or not value.strip() for value in sections.values()):
        raise SectionProtocolError()
    if sum(map(len, sections.values())) > MAX_DECODED_CHARACTERS:
        raise SectionProtocolError()
    bindings = canonical_attribution_bindings(**_sources(analysis))
    for key in SECTION_KEYS:
        value = sections[key]
        decoded_shadow = unicodedata.normalize("NFKC", html.unescape(value))
        if len(value) > MAX_SECTION_CHARACTERS or any(
            (unicodedata.category(character).startswith("C") and character != "\n") or character in "\u2028\u2029"
            for character in value + decoded_shadow
        ):
            raise SectionProtocolError()
        shadow = normalise_render_equivalent_text(value)
        # Encoded markup receives the same rejection as literal markup. These
        # shadows are only detectors; the accepted string is never rewritten.
        if (
            has_model_authored_raw_html(value)
            or has_model_authored_url(value)
            or _STRUCTURE.search(shadow)
            or _REFERENCE_DEFINITION.search(shadow)
            or _SETEXT_UNDERLINE.search(shadow)
            or _SENTINEL.search(shadow)
            or "`" in shadow
            or "~~~" in shadow
            or any(
                is_markdown_table_separator("|" + line.strip().strip("|") + "|")
                for line in shadow.splitlines()
                if "|" in line
            )
            or re.search(r"(?m)^(?: {4}|\t)|\n\s*[-=]{2,}\s*(?:\n|$)", shadow)
        ):
            raise SectionProtocolError()
        remainder = value
        for token in bindings:
            remainder = remainder.replace(token, "")
        if has_unbound_attribution_marker(remainder):
            raise SectionProtocolError()
    return sections


def decode_section_response(response, analysis):
    if not isinstance(response, str):
        raise SectionProtocolError()
    try:
        if len(response.encode("utf-8")) > MAX_RAW_BYTES:
            raise SectionProtocolError()
        sections = json.loads(response, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise SectionProtocolError() from None
    validate_section_prose(sections, analysis)
    # New-response admission is deliberately separate from the pure saved-body
    # inverse below. Inspect every decoded value before extraction or rendering;
    # saved assessments retain their own quality and approval-entry checks.
    for key in SECTION_KEYS:
        validate_operational_directions(sections[key])
    return sections


def canonical_section_source_register(analysis):
    """Fresh append-only register, never a filter over model-authored prose."""
    sources = _sources(analysis)
    canonical_attribution_bindings(**sources)
    tokens = canonical_source_token_data(**sources)
    official = tokens["official_source_tokens"][:2]
    if len(official) != 2 or (sources["rag_sources"] and not tokens["rag_source_tokens"]):
        raise SectionProtocolError()
    lines = [*(f"- {token}" for token in official)]
    if tokens["rag_source_tokens"]:
        lines.extend(["", f"{_CANONICAL_RAG_RETRIEVAL_CLAIM} {tokens['rag_source_tokens'][0]}"])
    return expand_known_attribution_tokens("\n".join(lines), **sources)


def render_section_report(sections, analysis):
    """Render each complete admitted value exactly once; expand only known tokens."""
    validate_section_prose(sections, analysis)
    blocks = render_owned_blocks(build_owned_field_spec(analysis))
    register = canonical_section_source_register(analysis)
    rendered = []
    for key, heading in zip(SECTION_KEYS, _headings(), strict=True):
        value = expand_known_attribution_tokens(sections[key], **_sources(analysis))
        body = heading + "\n\n" + value
        if key in _BLOCK_SECTIONS:
            body += "\n\n" + blocks[_BLOCK_SECTIONS[key]]
        if key == "s05":
            body += "\n\n" + register
        rendered.append(body)
    return "\n\n".join(rendered)


def assemble_section_response(response, analysis):
    return render_section_report(decode_section_response(response, analysis), analysis)


def project_section_report(narrative, analysis):
    """Invert an exact current body. The caller explicitly removes trusted appendices."""
    text = str(narrative)
    headings = _headings()
    if not text.startswith(headings[0] + "\n\n"):
        raise SectionProtocolError()
    blocks = render_owned_blocks(build_owned_field_spec(analysis))
    register = canonical_section_source_register(analysis)
    remaining = text[len(headings[0]) + 2 :]
    sections = {}
    for index, key in enumerate(SECTION_KEYS):
        if index < len(SECTION_KEYS) - 1:
            delimiter = "\n\n" + headings[index + 1] + "\n\n"
            if remaining.count(delimiter) != 1:
                raise SectionProtocolError()
            value, remaining = remaining.split(delimiter, 1)
        else:
            value = remaining
        suffix = blocks[_BLOCK_SECTIONS[key]] if key in _BLOCK_SECTIONS else register if key == "s05" else None
        if suffix:
            if not value.endswith("\n\n" + suffix):
                raise SectionProtocolError()
            value = value[: -len(suffix) - 2]
        sections[key] = fold_known_attribution_labels(value, **_sources(analysis))
    validate_section_prose(sections, analysis)
    if render_section_report(sections, analysis) != text:
        raise SectionProtocolError()
    return sections


def model_prose_word_count(sections, analysis):
    from src.report_content_contract import _WORD, _plain

    expanded = expand_known_attribution_tokens("\n\n".join(sections[key] for key in SECTION_KEYS), **_sources(analysis))
    return len(_WORD.findall(_plain(expanded, analysis)))


def section_protocol_budget(analysis):
    from src.report_content_contract import _WORD, _plain
    from src.report_owned_fields import OwnedFieldError

    blocks = render_owned_blocks(build_owned_field_spec(analysis))
    fixed = len(_WORD.findall(_plain("\n\n".join((*_headings(), *blocks.values())), analysis)))
    minimum, maximum = max(300, 650 - fixed), 800 - fixed
    if minimum > maximum:
        raise OwnedFieldError("owned_fields_body_budget_infeasible")
    return {"fixed_word_count": fixed, "model_prose_min_words": minimum, "model_prose_max_words": maximum}


def section_protocol_guidance(analysis):
    budget = section_protocol_budget(analysis)
    return (
        "Output contract: one strict JSON object with exactly s01 through s15, each a nonempty English prose "
        "string for the corresponding section below. No headings, slots, tables, lists, fences, notice, "
        "appendices, URLs, extra keys or text outside JSON. The application adds all headings, the source register "
        "and frozen P2/role/action/review fields. Keep s13 and s14 as short explanatory prose. Do not repeat P2 numbers. "
        f"Write {budget['model_prose_min_words']}–{budget['model_prose_max_words']} model prose words, at least 300; "
        f"the headings and frozen fields add {budget['fixed_word_count']} words to the 650–800 word body. "
        "Citation tokens do not count as prose. Describe the recognised scenario and selected focus naturally in s03 "
        "and address each in the relevant substantive sections. Do not copy coverage declarations."
    )


def section_coverage_text(sections):
    """Keep the existing source-section exclusion without allowing owned blocks to supply coverage."""
    return "\n\n".join(value for key, value in sections.items() if key != "s05")
