"""Current-only, deterministic report fields; never an approval or text repair.

Only exact standalone slots are expanded during generation. Assessment and
revision projection compare against frozen inputs without changing saved text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.agents.planner_agent import PlannerAgent
from src.agents.profile_agent import ProfileAgent
from src.markdown_tables import is_markdown_table_separator
from src.source_attribution import has_model_authored_raw_html, normalise_markdown_heading

OWNED_FIELDS_CHECK = "Application-owned report fields"
OWNED_FIELDS_RULESET = "frozen-fields-exact-slots-v1"
OWNED_TEMPLATE_RULESET = "administrative-confirmation-templates-v1"
PROPOSAL_PREFIX = "Unverified proposal for local review:"
OWNED_SECTIONS = {
    "p2": ("4. Selected Geography and Key Assumptions", "[APP_P2_FIELDS]"),
    "roles": ("10. Roles and Responsibilities", "[APP_ROLE_FIELDS]"),
    "actions": ("13. Action Plan", "[APP_ACTION_FIELDS]"),
    "review": ("14. Human Review and Approval Checklist", "[APP_REVIEW_FIELDS]"),
}
_WORD = re.compile(r"\b[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*\b")
_MEASUREMENTS = (
    ("population", "Population"),
    ("older_people_pct", "older-people"),
    ("no_car_households_pct", "no-car households"),
    ("language_other_than_english_pct", "language other than English at home"),
)
# Fresh administrative objects, never Planner priorities or RAG instructions.
_SCENARIO_OBJECTS = {
    "school_preparedness": "school supervision and parent communication records",
    "council_community_preparedness": "council coordination and community consultation records",
    "community_workshop": "community workshop audience and review records",
    "household_preparedness": "household planning and pet preparedness records",
    "aged_care_preparedness": "aged care clinical governance and resident support records",
    "farm_land_management": "farm livestock, machinery, vegetation and water records",
    "live_route_request": "official emergency information boundaries",
}
_FOCUS_OBJECTS = {
    "evacuation": "evacuation planning",
    "candidate_assembly_points": "candidate assembly point criteria",
    "first_aid": "first aid and training",
    "roles": "roles and responsibilities",
    "communications": "communication channels",
    "smoke_health": "health support",
    "road_access": "road access",
    "power_continuity": "backup power and communications outage",
    "official_sources": "official sources",
    "human_review": "human review",
    "vulnerable_people": "support needs",
    "property_preparation": "property preparation",
    "emergency_kits": "emergency kits",
    "pets": "pet preparedness",
    "medication_continuity": "medication continuity",
    "livestock": "livestock",
    "vegetation": "vegetation management",
    "machinery": "machinery",
    "water": "water continuity",
    "live_information_boundary": "official emergency information",
}


class OwnedFieldError(ValueError):
    """A content-free, fail-closed owned-field diagnostic."""


@dataclass(frozen=True)
class CommunityMeasurement:
    field: str
    value: str | None


@dataclass(frozen=True)
class OwnedFieldSpec:
    scenario_id: str | None
    timeframe_id: str | None
    focus_ids: tuple[str, ...]
    measurements: tuple[CommunityMeasurement, ...]
    matched_location: str | None
    source_period: str | None
    geography_type: str | None
    matched_sa2_count: str | None
    match_basis: str | None
    role_ids: tuple[str, ...] = ("organisation", "staff_volunteers", "communications", "first_aid", "review")
    template_id: str = OWNED_TEMPLATE_RULESET


def _mapping(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise OwnedFieldError("owned_fields_invalid_frozen_mapping")
    return value


def _plain_basis(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or len(value) > 240 or value != value.strip():
        raise OwnedFieldError("owned_fields_invalid_frozen_basis")
    # Reject Markdown/control syntax rather than silently escaping or truncating
    # qualifiers. Ordinary geographic punctuation remains visible verbatim.
    if (
        re.search(r"[<>|\[\]`*{}\\#]", value)
        or re.search(r"https?://|www\.", value, re.I)
        or any(unicodedata.category(character).startswith("C") or character in "\u2028\u2029" for character in value)
    ):
        raise OwnedFieldError("owned_fields_unsafe_frozen_basis")
    if re.search(r"\b(?:must|should|will|ignore|instructions?|evacuate|approved|safe|open|closed)\b", value, re.I):
        raise OwnedFieldError("owned_fields_unsafe_frozen_basis")
    return value


def _number(value, *, percentage=False, count=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise OwnedFieldError("owned_fields_invalid_frozen_measurement")
    raw = str(value)
    if len(raw) > 40 or not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
        raise OwnedFieldError("owned_fields_invalid_frozen_measurement")
    try:
        number = Decimal(raw.replace(",", ""))
    except InvalidOperation as error:
        raise OwnedFieldError("owned_fields_invalid_frozen_measurement") from error
    if not number.is_finite() or number < 0 or (percentage and number > 100):
        raise OwnedFieldError("owned_fields_invalid_frozen_measurement")
    if count and (number < 1 or number != number.to_integral_value()):
        raise OwnedFieldError("owned_fields_invalid_sa2_count")
    return format(number, "f")


def _concept_id(candidate, catalog):
    if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
        raise OwnedFieldError("owned_fields_canonical_selector_missing")
    identifier = candidate.get("id")
    if identifier in {"live_route_request", "immediate_live_decision"}:
        raise OwnedFieldError("owned_fields_unsupported_live_selection")
    if not any(identifier == item["id"] for item in catalog.values()):
        raise OwnedFieldError("owned_fields_invalid_selector")
    return identifier


def build_owned_field_spec(analysis):
    """Freeze canonical selectors and validated measurements, without mutation."""
    analysis = _mapping(analysis)
    profile = _mapping(analysis.get("profile"))
    community = _mapping(analysis.get("community"))
    indicators = _mapping(community.get("indicators"))
    quality = _mapping(community.get("data_quality"))
    measurements = tuple(
        CommunityMeasurement(field, _number(indicators.get(field), percentage=field != "population"))
        for field, _label in _MEASUREMENTS
    )
    source_period = _plain_basis(quality.get("source_period"))
    geography = _plain_basis(indicators.get("geography_type"))
    if any(item.value is not None for item in measurements):
        if not source_period or not re.search(r"\b(?:19|20)\d{2}\b", source_period):
            raise OwnedFieldError("owned_fields_source_period_missing")
        if not geography:
            raise OwnedFieldError("owned_fields_geographic_basis_missing")
    candidates = _mapping(analysis.get("plan")).get("focus_area_concepts", [])
    if not isinstance(candidates, (list, tuple)):
        raise OwnedFieldError("owned_fields_invalid_selectors")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or PlannerAgent.canonical_focus_concept(item.get("id")) is None
        for item in candidates
    ):
        raise OwnedFieldError("owned_fields_invalid_selectors")
    selected = {item["id"] for item in candidates}
    if selected - _FOCUS_OBJECTS.keys():
        raise OwnedFieldError("owned_fields_unsupported_focus")
    return OwnedFieldSpec(
        scenario_id=_concept_id(profile.get("scenario_concept"), ProfileAgent._SCENARIO_CONCEPTS),
        timeframe_id=_concept_id(profile.get("timeframe_concept"), ProfileAgent._TIMEFRAME_CONCEPTS),
        focus_ids=tuple(identifier for identifier in _FOCUS_OBJECTS if identifier in selected),
        measurements=measurements,
        matched_location=_plain_basis(community.get("matched_location")),
        source_period=source_period,
        geography_type=geography,
        matched_sa2_count=_number(indicators.get("matched_sa2_count"), count=True),
        match_basis=_plain_basis(quality.get("match_basis")),
    )


def _p2_block(spec):
    available, unknown = [], []
    for measurement, (_field, label) in zip(spec.measurements, _MEASUREMENTS, strict=True):
        if measurement.value is None:
            unknown.append(label)
        else:
            suffix = "" if measurement.field == "population" else "%"
            assertion_label = {"no_car_households_pct": "no-car", "language_other_than_english_pct": "language"}.get(
                measurement.field, label
            )
            qualifier = {
                "no_car_households_pct": " (households)",
                "language_other_than_english_pct": " (other than English at home)",
            }.get(measurement.field, "")
            available.append(f"{assertion_label} {measurement.value}{suffix}{qualifier}")
    rows = ["| Community evidence | Frozen measurement and basis |", "| --- | --- |"]
    if available:
        basis = [spec.source_period, spec.geography_type]
        if spec.matched_sa2_count:
            basis.append(f"{spec.matched_sa2_count}-SA2 aggregation")
        if spec.matched_location:
            basis.append(spec.matched_location)
        # Preserve supplied geographic qualifications in the same cell as every
        # measurement, including any explicit approximation/boundary limitation.
        if spec.match_basis:
            basis.append(spec.match_basis.rstrip("."))
        rows.append(
            "| Available | "
            + "; ".join(available)
            + "; "
            + "; ".join(basis)
            + "; community figures, not site occupancy or a premises boundary [P2]. |"
        )
    if unknown:
        rows.append("| Unknown | " + "; ".join(unknown) + ": unknown, not measured in the supplied snapshot [P2]. |")
    return "\n".join(rows)


def _proposal(object_text):
    return f"{PROPOSAL_PREFIX} the responsible organisation must confirm {object_text} [R3]."


def render_owned_blocks(spec):
    """Render fresh administrative templates, never arbitrary task strings."""
    timeframe = next(
        (item["label"] for item in ProfileAgent._TIMEFRAME_CONCEPTS.values() if item["id"] == spec.timeframe_id),
        "Unspecified window",
    )
    objects = [_FOCUS_OBJECTS[identifier] for identifier in spec.focus_ids]
    scope = "; ".join(objects) if objects else "preparedness evidence gaps"
    scenario = _SCENARIO_OBJECTS.get(spec.scenario_id, "local planning records")
    return {
        "p2": _p2_block(spec),
        "roles": "\n".join(
            [
                "| Proposed roles | Confirmation duty |",
                "| --- | --- |",
                "| Organisation, staff/volunteers, communications, first aid, review | "
                + _proposal(
                    "role appointments, duties, qualifications and backup coverage; appointments remain unconfirmed"
                )
                + " |",
            ]
        ),
        "actions": "\n".join(
            [
                "| Proposed review window | Action and checkpoint |",
                "| --- | --- |",
                "| Day 1 | "
                + _proposal("the preparedness lead, official contacts, action owners and review checkpoints")
                + " |",
                f"| {timeframe} | "
                + _proposal(f"review timing, accountable owners and evidence requirements for {scope}; {scenario}")
                + " |",
            ]
        ),
        "review": "- [ ] "
        + _proposal("evidence gaps, local applicability, outstanding decisions and the approval process before use"),
    }


def owned_field_word_count(spec):
    """Same word grammar as the body budget; these body fields are not exempt."""
    from src.report_content_contract import _WORD, _plain

    return len(_WORD.findall(_plain("\n".join(render_owned_blocks(spec).values()), {})))


def owned_fields_budget(analysis):
    """Allocate the unchanged final-body budget without borrowing prose words."""
    from src.report_template import REPORT_TEMPLATE_SECTIONS

    fixed = owned_field_word_count(build_owned_field_spec(analysis))
    heading_words = len(_WORD.findall(" ".join(title for title, _instruction in REPORT_TEMPLATE_SECTIONS)))
    minimum = max(650 - fixed, 300 + heading_words)
    maximum = 800 - fixed
    if minimum > maximum:
        raise OwnedFieldError("owned_fields_body_budget_infeasible")
    return {"owned_word_count": fixed, "model_body_min_words": minimum, "model_body_max_words": maximum}


def build_owned_field_prompt_guidance(analysis):
    budget = owned_fields_budget(analysis)
    fixed = budget["owned_word_count"]
    slots = "; ".join(f"section {title.split('.')[0]}: {slot}" for title, slot in OWNED_SECTIONS.values())
    return (
        "Application-owned fields: emit each exact standalone slot once in its section: " + slots + ".\n"
        "These slots become frozen P2, role/action tables and unchecked review tasks. Do not author these fields "
        "or additional tables/lists in those sections; retain concise explanatory prose. Do not repeat P2 numbers.\n"
        f"Completed body: 650–800 words including {fixed} application field words. "
        f"Write {budget['model_body_min_words']}–{budget['model_body_max_words']} "
        "other words including headings, with at least 300 prose words; exclude slot tokens, notice, source-register "
        "lines and appendices. Every model-authored task elsewhere still needs its own proposal prefix and confirmer."
    )


def _section_spans(text):
    """Find visible root headings while retaining original string offsets."""
    if has_model_authored_raw_html(text):
        raise OwnedFieldError("owned_fields_hidden_markup")
    headings, offset, fence = [], 0, None
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]))
        else:
            heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*$", line)
            if heading:
                headings.append((normalise_markdown_heading(heading[1]), offset, offset + len(raw_line)))
        offset += len(raw_line)
    spans = {}
    for key, (title, _slot) in OWNED_SECTIONS.items():
        matches = [(index, item) for index, item in enumerate(headings) if item[0] == normalise_markdown_heading(title)]
        if len(matches) != 1:
            raise OwnedFieldError("owned_fields_section_cardinality")
        index, (_heading, _start, body_start) = matches[0]
        body_end = headings[index + 1][1] if index + 1 < len(headings) else len(text)
        spans[key] = (body_start, body_end)
    return spans


def _standalone_position(text, value, start, end):
    positions = [match.start() for match in re.finditer(re.escape(value), text)]
    if len(positions) != 1:
        raise OwnedFieldError("owned_fields_block_cardinality")
    position = positions[0]
    if not start <= position < position + len(value) <= end:
        raise OwnedFieldError("owned_fields_misplaced_block")
    if position and text[position - 1] != "\n":
        raise OwnedFieldError("owned_fields_block_not_standalone")
    after = text[position + len(value) :]
    if after and not after.startswith(("\r\n", "\n")):
        raise OwnedFieldError("owned_fields_block_not_standalone")
    # A standalone line within a fenced block is still not a visible slot.
    prefix = text[start:position]
    if re.search(r"(?m)^ {0,3}(?:`{3,}|~{3,}|>)", prefix):
        raise OwnedFieldError("owned_fields_fenced_block")
    return position


def assemble_owned_fields(raw_markdown, analysis):
    """Replace exactly four slots; preserve every other byte or reject."""
    text = str(raw_markdown)
    blocks = render_owned_blocks(build_owned_field_spec(analysis))
    spans = _section_spans(text)
    if len(re.findall(r"APP_[A-Za-z0-9_]*FIELDS", text)) != len(OWNED_SECTIONS):
        raise OwnedFieldError("owned_fields_slot_cardinality")
    replacements = []
    for key, (_title, slot) in OWNED_SECTIONS.items():
        position = _standalone_position(text, slot, *spans[key])
        replacements.append((position, slot, blocks[key]))
    for position, slot, block in sorted(replacements, reverse=True):
        text = text[:position] + block + text[position + len(slot) :]
    return text


def _verified_block_positions(text, analysis):
    blocks = render_owned_blocks(build_owned_field_spec(analysis))
    spans = _section_spans(text)
    if "APP_" in text:
        raise OwnedFieldError("owned_fields_unexpanded_slot")
    positions = {}
    for key, block in blocks.items():
        start, end = spans[key]
        position = _standalone_position(text, block, start, end)
        remainder = text[start:position] + text[position + len(block) : end]
        if re.search(r"(?m)^\s*(?:[>|]|[-+*]\s|\d+[.)]\s|`{3,}|~{3,})", remainder) or any(
            is_markdown_table_separator("|" + line.strip().strip("|") + "|")
            for line in remainder.splitlines()
            if "|" in line
        ):
            raise OwnedFieldError("owned_fields_extra_authored_structure")
        positions[key] = (position, block)
    return positions


def evaluate_owned_fields(final_markdown, analysis):
    """Read-only exact ownership check, including old reports and exports."""
    try:
        positions = _verified_block_positions(str(final_markdown), analysis)
    except OwnedFieldError as error:
        return {
            "name": OWNED_FIELDS_CHECK,
            "status": "fail",
            "detail": str(error),
            "findings": [{"code": str(error), "count": 1}],
        }
    return {
        "name": OWNED_FIELDS_CHECK,
        "status": "pass",
        "detail": "Exact frozen application fields retained.",
        "findings": [],
        "block_sha256": {
            key: hashlib.sha256(block.encode("utf-8")).hexdigest() for key, (_position, block) in positions.items()
        },
    }


def project_owned_fields_for_prompt(final_markdown, analysis):
    """Prompt-only projection of verified exact blocks; no saved-body repair."""
    text = str(final_markdown)
    positions = _verified_block_positions(text, analysis)
    for key, (position, block) in sorted(positions.items(), key=lambda item: item[1][0], reverse=True):
        text = text[:position] + OWNED_SECTIONS[key][1] + text[position + len(block) :]
    return text
