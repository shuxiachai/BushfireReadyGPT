"""Detached, literal-only report-content review clues.

This deliberately has no provider, environment, filesystem, or transport
dependency.  It is not a report-quality decision: semantic correctness,
conditions, and provenance remain unknown.
"""

from __future__ import annotations

import copy
import re

from scripts import atomic_claim_contract as contract
from scripts.proposal_evidence_advisory import _marker_review
from src import report_claim_evidence as body
from src import source_attribution as attribution

SCHEMA = "report-content-advisory-v1"
MAX_REPORT_CHARACTERS = 200_000
MAX_FACT_TARGETS = 128
MAX_LOCAL_ACTIONS = 128
MAX_PROBES_PER_TARGET = 12
MAX_PROBE_CHARACTERS = 240
MAX_TARGET_UNIT_REVIEWS = 8192
MAX_PROBE_MATCHES = 16384
_PREFIX = "Unverified proposal for local review:"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")
_CITATION_SHAPED = re.compile(r"\[O1(?:-[A-Za-z0-9_-]+)?\](?:[ \t]*\[[^\]\r\n]*\]?)?", re.I)
_HTML_TAG = re.compile(r"<(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>")
_ENTITY = re.compile(r"&(?:#[0-9]+|#x[0-9a-f]+|[a-z][a-z0-9]+);", re.I)
_REFERENCE_LINK = re.compile(r"(?<!\\)\[([^\]\r\n]*)\](\[[^\]\r\n]*\])")
_EMPHASIS = re.compile(r"(?<!\\)(\*\*|__|\*|_)(?=\S)(.+?\S|\S)\1")


class ContentAdvisoryError(ValueError):
    """A caller-supplied review target is not a bounded literal target."""


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ContentAdvisoryError("Object has missing or unknown fields.")


def _text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or _CONTROL.search(value):
        raise ContentAdvisoryError(f"Invalid {name} text.")
    return value


def _identifier(value, name, *, nullable=False):
    if nullable and value is None:
        return None
    value = _text(value, 64, name)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value) is None:
        raise ContentAdvisoryError(f"Invalid {name} identifier.")
    return value


def _span(value, text, exact, name):
    _keys(value, {"start", "end"})
    start, end = value["start"], value["end"]
    empty_root = exact == "" and text == "" and start == end == 0
    if type(start) is not int or type(end) is not int or not (empty_root or 0 <= start < end <= len(text)):
        raise ContentAdvisoryError(f"Invalid {name} span.")
    if text[start:end] != exact:
        raise ContentAdvisoryError(f"{name} span does not exactly match its text.")
    return {"start": start, "end": end}


def _catalog_identities(analysis):
    if type(analysis) is not dict:
        raise ContentAdvisoryError("analysis must be a dictionary.")
    identities = {}
    for item in (analysis.get("knowledge") or {}).get("retrieved_chunks") or []:
        if type(item) is dict and isinstance(item.get("source_id"), str):
            source_id = attribution._normalise_source_id(item["source_id"])
            identities.setdefault(source_id, set()).add(("rag", source_id))
    for item in (analysis.get("data") or {}).get("sources") or []:
        if type(item) is dict and isinstance(item.get("id"), str):
            source_id = attribution._normalise_source_id(item["id"])
            identities.setdefault(source_id, set()).add(("official", source_id))
    return identities


def _claim_units(report_text, analysis):
    return body.extract_body_claims(report_text, analysis)


def _find_unit(units, span, exact):
    found = [unit for unit in units if unit["span"] == span and unit["claim"] == exact]
    if len(found) != 1:
        raise ContentAdvisoryError("Report target must be one complete extracted visible body unit.")
    return found[0]


def _units_in_range(units, span):
    selected = []
    for unit in units:
        current = unit["span"]
        if span["start"] < current["end"] and current["start"] < span["end"]:
            if current["start"] < span["start"] or current["end"] > span["end"]:
                raise ContentAdvisoryError("Fact search range cuts through an extracted visible body unit.")
            selected.append(unit)
    return selected


def _blank(text):
    return re.sub(r"[^\r\n]", " ", text)


def _mask_link_destinations(text):
    """Keep link labels, but not balanced destinations or their optional titles."""
    masked = list(text)
    covered, unsupported = -1, []
    for match in re.finditer(r"(?<!\\)\]\(", text):
        start = match.end() - 1
        if start < covered:
            continue
        depth, end, quote, title_closed = 1, start + 1, None, False
        while end < len(text) and depth:
            # Once a quoted title closes, only whitespace and the link's final
            # parenthesis have a known boundary. Keep uncertain suffixes unknown.
            if title_closed and not text[end].isspace() and text[end] != ")":
                end = len(text)
                break
            if text[end] == "\\" and end + 1 < len(text):
                end += 2
                continue
            if quote is not None:
                if text[end] == quote:
                    quote, title_closed = None, True
            elif depth == 1 and text[end] in "\"'" and text[end - 1].isspace():
                quote = text[end]
            elif text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
            end += 1
        masked[start:end] = _blank(text[start:end])
        covered = end
        if depth:
            unsupported.append((match.start(), end))
    return "".join(masked), unsupported


def _metadata_shadow(text):
    """A bounded static-markup shadow, not a browser visibility decision."""
    visible = body._visible_mask(text)
    visible = _HTML_TAG.sub(lambda match: _blank(match[0]), visible)
    visible, unsupported = _mask_link_destinations(visible)
    # A remaining tag opener has no trusted closing boundary. Its attributes
    # may span sentences or lines, so every following affected unit is unknown.
    unsupported.extend((match.start(), len(visible)) for match in re.finditer(r"<[A-Za-z!/?]", visible))
    unsupported.extend(match.span() for match in re.finditer(r"&(?:#|[A-Za-z])", visible))
    visible = _ENTITY.sub(lambda match: _blank(match[0]), visible)
    visible = _REFERENCE_LINK.sub(
        lambda match: (
            match[0]
            if re.fullmatch(r"O1(?:-[A-Za-z0-9_-]+)?", match[1], re.I)
            else match[0][: -len(match[2])] + _blank(match[2])
        ),
        visible,
    )
    return visible, unsupported


def _citation_shadow(metadata, bindings):
    """Resolve metadata before sentence or table boundaries can split a title."""
    visible, unsupported = metadata
    citations = []
    for label in sorted(bindings, key=len, reverse=True):
        identity = bindings[label]
        citations.extend(
            (match.start(), (identity["source_type"], identity["source_id"]))
            for match in re.finditer(re.escape(label), visible)
        )
        visible = visible.replace(label, _blank(label))
    # An unknown display label has no trusted boundary; its trailing title can
    # cross body units. Conservatively leave the remaining report unassessed.
    unknown = _CITATION_SHAPED.search(visible)
    unknown_ranges = [] if unknown is None else [(unknown.start(), len(visible))]
    if unknown is not None:
        visible = visible[: unknown.start()] + _blank(visible[unknown.start() :])
    return visible, unsupported, citations, unknown_ranges


def _literal_shadow(unit, metadata):
    """Use the same visible shadow for probes, citations and action markers."""
    shadow, unsupported, citations, unknown_ranges = metadata
    start, end = unit["span"]["start"], unit["span"]["end"]
    visible = shadow[start:end]
    supported = not any(start < right and left < end for left, right in unsupported)
    observed = {identity for position, identity in citations if start <= position < end}
    unknown_citation = any(start < right and left < end for left, right in unknown_ranges)
    return visible, supported and not unknown_citation, observed, unknown_citation


def _has_literal_prefix(visible):
    # Paired Markdown emphasis is presentation only. Do not normalise Unicode,
    # remove zero-width characters, or repair a non-literal prefix.
    plain = visible.strip()
    previous = None
    while plain != previous:
        previous = plain
        plain = _EMPHASIS.sub(lambda match: match[2], plain)
    return plain.startswith(_PREFIX)


def _citation_binding(expected, observed, supported):
    if not supported or expected is None:
        return "unassessed"
    return "observed" if expected in observed else "not_observed"


def _observe_unit(unit, probes, expected, metadata, budget):
    visible, supported, citations, unknown_citation = _literal_shadow(unit, metadata)
    positions = []
    for probe in probes:
        matches = []
        if supported:
            for match in re.finditer(r"(?<!\w)" + re.escape(probe) + r"(?!\w)", visible):
                budget["probe_matches"] += 1
                if budget["probe_matches"] > MAX_PROBE_MATCHES:
                    raise ContentAdvisoryError("Total probe match limit exceeded.")
                matches.append(match.start())
        positions.append(
            {
                "probe": probe,
                "positions": matches if supported else None,
                "observation": ("observed" if matches else "not_observed") if supported else "unassessed",
            }
        )
    return {
        "unit": {"span": copy.deepcopy(unit["span"]), "text": unit["claim"]},
        "probe_observations": positions,
        "co_occurrence": (
            ("observed" if all(item["positions"] for item in positions) else "not_observed")
            if supported
            else "unassessed"
        ),
        "citation_binding": _citation_binding(expected, citations, supported),
        "citation_visibility": (("observed" if citations else "not_observed") if supported else "unassessed"),
        "unassessed_reason": (
            "unknown_citation_boundary" if unknown_citation else "unsupported_static_markup" if not supported else None
        ),
    }


def _validate_fact_targets(fact_targets, report_text, passages, units, identities, metadata, budget):
    if type(fact_targets) is not list or len(fact_targets) > MAX_FACT_TARGETS:
        raise ContentAdvisoryError("Invalid fact target collection.")
    seen, result = set(), []
    for target in fact_targets:
        _keys(target, {"id", "passage_ref", "source_span", "source_text", "report_span", "report_text", "probes"})
        identity = _identifier(target["id"], "fact target")
        if identity in seen:
            raise ContentAdvisoryError("Duplicate fact target identifier.")
        seen.add(identity)
        ref = _text(target["passage_ref"], 64, "passage reference")
        if ref not in passages:
            raise ContentAdvisoryError("Unknown passage reference.")
        source_text = _text(target["source_text"], contract.MAX_QUOTE_CHARACTERS, "source")
        source_span = _span(target["source_span"], passages[ref]["text"], source_text, "source")
        report_piece = target["report_text"]
        if report_piece == "" and report_text == "":
            report_piece = ""
        else:
            report_piece = _text(report_piece, MAX_REPORT_CHARACTERS, "report search range")
        report_span = _span(target["report_span"], report_text, report_piece, "report")
        selected_units = _units_in_range(units, report_span)
        budget["units_scanned"] += len(selected_units)
        if budget["units_scanned"] > MAX_TARGET_UNIT_REVIEWS:
            raise ContentAdvisoryError("Total target-unit review limit exceeded.")
        probes = target["probes"]
        if type(probes) is not list or not 1 <= len(probes) <= MAX_PROBES_PER_TARGET:
            raise ContentAdvisoryError("Fact target requires one to twelve probes.")
        checked = []
        for probe in probes:
            probe = _text(probe, MAX_PROBE_CHARACTERS, "probe")
            if probe not in source_text:
                raise ContentAdvisoryError("A literal probe is absent from its source span.")
            checked.append(probe)
        expected_candidates = identities.get(attribution._normalise_source_id(passages[ref]["source_id"]), set())
        expected = next(iter(expected_candidates)) if len(expected_candidates) == 1 else None
        observations = [_observe_unit(unit, checked, expected, metadata, budget) for unit in selected_units]
        states = {item["co_occurrence"] for item in observations}
        result.append(
            {
                "id": identity,
                "passage_ref": ref,
                "source_span": source_span,
                "report_span": report_span,
                "unit_observations": observations,
                "units_scanned": len(observations),
                "co_occurrence": (
                    "observed" if "observed" in states else "unassessed" if "unassessed" in states else "not_observed"
                ),
                "expected_citation": (
                    {"source_type": expected[0], "source_id": expected[1]} if expected is not None else None
                ),
            }
        )
    return result


def _validate_local_actions(local_actions, report_text, units, metadata):
    if type(local_actions) is not list or len(local_actions) > MAX_LOCAL_ACTIONS:
        raise ContentAdvisoryError("Invalid local action collection.")
    seen, actions, plain_actions = set(), [], {}
    for action in local_actions:
        _keys(action, {"id", "unit_span", "unit_text", "group_id"})
        identity = _identifier(action["id"], "local action")
        if identity in seen:
            raise ContentAdvisoryError("Duplicate local action identifier.")
        seen.add(identity)
        text = _text(action["unit_text"], contract.MAX_CLAIM_CHARACTERS, "action")
        span = _span(action["unit_span"], report_text, text, "action")
        unit = _find_unit(units, span, text)
        visible, supported, _, _ = _literal_shadow(unit, metadata)
        plain = visible.strip()
        plain_actions[identity] = plain if supported else None
        actions.append(
            {
                "id": identity,
                "unit": {"span": copy.deepcopy(unit["span"]), "text": unit["claim"]},
                "group_id": _identifier(action["group_id"], "group", nullable=True),
                "prefix_observation": (
                    ("observed" if _has_literal_prefix(visible) else "not_observed") if supported else "unassessed"
                ),
                "marker_review": _marker_review(plain, plain) if supported else None,
            }
        )
    pairs = []
    for index, left in enumerate(actions):
        if left["group_id"] is None:
            continue
        left_plain = plain_actions[left["id"]]
        for right in actions[index + 1 :]:
            if right["group_id"] != left["group_id"]:
                continue
            right_plain = plain_actions[right["id"]]
            supported = left_plain is not None and right_plain is not None
            pairs.append(
                {
                    "group_id": left["group_id"],
                    "action_ids": [left["id"], right["id"]],
                    "marker_reviews": (
                        [_marker_review(left_plain, right_plain), _marker_review(right_plain, left_plain)]
                        if supported
                        else None
                    ),
                    "unassessed_reason": None if supported else "unsupported_unit_visibility",
                }
            )
    return actions, pairs


def _mixed_unit_clues(facts, actions):
    """Flag caller-selected fact/action overlap without classifying either text."""
    clues = []
    for fact in facts:
        for observation in fact["unit_observations"]:
            if observation["co_occurrence"] != "observed":
                continue
            for action in actions:
                if action["unit"]["span"] != observation["unit"]["span"]:
                    continue
                clues.append(
                    {
                        "fact_target_id": fact["id"],
                        "local_action_id": action["id"],
                        "unit_span": copy.deepcopy(observation["unit"]["span"]),
                        "citation_binding": observation["citation_binding"],
                        "citation_visibility": observation["citation_visibility"],
                        "finding": "possible_mixed_fact_action_unit",
                        "semantics": "unknown",
                        "review_required": True,
                    }
                )
    return clues


def review_report_content(report_text, analysis, evidence_pack, *, fact_targets, local_actions):
    """Return bounded literal observations; it never makes a semantic verdict."""
    if not isinstance(report_text, str) or len(report_text) > MAX_REPORT_CHARACTERS or _CONTROL.search(report_text):
        raise ContentAdvisoryError("Invalid report text.")
    passages = contract._pack_passages(evidence_pack)
    identities = _catalog_identities(analysis)
    units = _claim_units(report_text, analysis)
    bindings = body._bindings(body._catalog(analysis))
    metadata = _citation_shadow(_metadata_shadow(report_text), bindings)
    budget = {"units_scanned": 0, "probe_matches": 0}
    facts = _validate_fact_targets(fact_targets, report_text, passages, units, identities, metadata, budget)
    actions, group_reviews = _validate_local_actions(local_actions, report_text, units, metadata)
    return {
        "schema": SCHEMA,
        "evidence_pack_sha256": evidence_pack["evidence_pack_sha256"],
        "fact_observations": facts,
        "local_action_observations": actions,
        "same_group_marker_reviews": group_reviews,
        "mixed_unit_review_clues": _mixed_unit_clues(facts, actions),
        "units_scanned": budget["units_scanned"],
        "probe_matches": budget["probe_matches"],
        "semantics": "unknown",
        "conditions": "unknown",
        "manual_review": True,
        "production": False,
        "additional_model_calls": 0,
        "semantic_accuracy": None,
        "limitations": [
            "Literal observations do not establish fact preservation, semantic support, provenance, or condition preservation.",
            "Caller-provided target spans, groups, and roles are not origin proof.",
            "Citation-shaped metadata that is not safely bound is unassessed and is masked from literal observation.",
            "Only complete extracted body units within each search range are checked; probes never combine across units.",
            "Visibility masking handles static markup only; it is not browser rendering or a semantic absence test.",
            "Unknown citation boundaries and unsupported markup are unassessed; positions are unit-relative codepoints.",
            "An unknown citation boundary leaves the remaining report suffix unassessed, including later body units.",
        ],
    }
