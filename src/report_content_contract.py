"""Bounded content/provenance guards, never a semantic or operational approval.

Only the final validated SDK submission can discharge a passage-dependent
check. Retrieved-but-omitted text remains useful for detecting a source conflict,
but cannot support a report claim. Findings retain codes/counts, not user prose.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from src.markdown_tables import is_markdown_table_separator, parse_markdown_table_row
from src.model_evidence import unavailable_model_evidence, validate_model_evidence
from src.report_basis import build_community_p2_basis
from src.report_claim_evidence import extract_body_claims
from src.report_template import extract_narrative_body
from src.source_attribution import (
    normalise_markdown_heading,
    plain_markdown_claim_text,
    strip_application_source_bindings,
    strip_known_attribution_labels,
    visible_markdown_text,
)

_WORD = re.compile(r"\b[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*\b")
_PROPOSAL = re.compile(r"^Unverified proposal for local review:\s*", re.I)
_NON_DIRECTIVE_DISCLAIMER = "this draft contains no direction about when or where people should move."
_CONFIRMER = re.compile(
    r"\b(?:responsible organisation|responsible organization|school leadership|local council|"
    r"emergency services|preparedness lead|first[- ]aid coordinator|qualified (?:reviewer|clinician)|"
    r"(?:communications?|review|safety|training) (?:officer|coordinator|lead))\b.{0,100}"
    r"\b(?:must|will|should|to)\s+(?:review and )?(?:confirm|verify|approve|review)\b",
    re.I,
)
_TASK_FRAME = re.compile(
    r"^(?:(?:day|week)\s+\d+\s*:\s*)?(?:assign|appoint|nominate|record|document|schedule|maintain|"
    r"review|update|confirm|verify|approve|monitor|check|prepare|define|identify|conduct|coordinate|"
    r"establish|develop|practise|practice|train|test|inspect|remove|repair|replace|arrange|provide|"
    r"select|choose|use|keep)\b|\b(?:must|should|will|needs? to|propos\w*)\b",
    re.I,
)
_CAUSAL = re.compile(
    r"\b(?:affects?|increases?|reduces?|prevents?|protects?|improves?|causes?|supports? readiness|"
    r"leads? to|results? in|can affect|can disrupt)\b",
    re.I,
)
_PHYSICAL = re.compile(
    r"\b(?:shade|smoke exposure|water|traffic separation|indoor|outdoor|accessibility|"
    r"distance|clearance|capacity|ventilation|first aid)\b",
    re.I,
)
_GAP = re.compile(
    r"\b(?:not (?:established|supplied|supported|available)|does not (?:establish|support|specify)|"
    r"no .{0,45}(?:evidence|criteria|support)|evidence gap|criteria .{0,35}(?:unknown|unconfirmed)|"
    r"(?:not verified|unverified) for .{0,35}use|"
    r"unresolved (?:source )?conflict)\b",
    re.I,
)
_HOUSEHOLD = re.compile(r"\b(?:households?|homes?|famil(?:y|ies))\b", re.I)
_CAMPUS = re.compile(r"\b(?:schools?|campus|students?|class(?:es)?)\b", re.I)
_CONFLICT = re.compile(
    r"\b(?:maintenance|prepar\w*)\b[^.!?]{0,240}\b(?:increase\w*\s+(?:the\s+)?impacts?|"
    r"reduc\w*\s+(?:(?:your|the)\s+)?(?:chance\w*\s+of\s+)?surviv\w*)",
    re.I,
)
_CONFLICT_NOTICE = re.compile(r"\b(?:contradict\w*|conflict\w*)\b", re.I)
_INFERENCE = re.compile(r"\b(?:planning inference|rule[- ]derived inference)\b", re.I)
_UNKNOWN = re.compile(r"\b(?:unknown|unavailable|not supplied|not measured)\b", re.I)
_FIELDS = {
    "population": re.compile(r"\b(?:population|residents)\b", re.I),
    "older_people_pct": re.compile(r"\bolder (?:people|residents|adults)\b", re.I),
    "no_car_households_pct": re.compile(r"\b(?:no[- ]car|transport)\b", re.I),
    "language_other_than_english_pct": re.compile(r"\b(?:language|linguistic)\b", re.I),
}


def _check(name, codes, success, **metrics):
    counts = Counter(codes)
    return {
        "name": name,
        "status": "fail" if counts else "pass",
        "detail": "; ".join(f"{code}: {counts[code]}" for code in sorted(counts)) if counts else success,
        "findings": [{"code": code, "count": counts[code]} for code in sorted(counts)],
        **metrics,
    }


def _plain(claim, analysis):
    return plain_markdown_claim_text(
        strip_known_attribution_labels(
            claim,
            official_sources=(analysis.get("data") or {}).get("sources") or [],
            rag_sources=(analysis.get("knowledge") or {}).get("retrieved_chunks") or [],
        )
    ).strip()


def _claim_shadow(claim, analysis):
    """Normalize wrapping only inside an already extracted claim unit.

    Raw report bytes, claim offsets/citations and SDK snapshot bindings remain
    untouched. Separate sentences, paragraphs and cells never share a shadow.
    """
    return " ".join(_plain(claim, analysis).split())


def _measurements(text, field):
    """Bind explicit values to their own measure and percentage unit.

    A period, SA2 count or other indicator elsewhere in the sentence cannot
    satisfy the measure. This is deliberately narrow numeric syntax.
    """
    number = r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<percent>%)?"
    label = r"\bpopulation\b" if field == "population" else _FIELDS[field].pattern
    patterns = [
        label
        + r"\s*(?:(?:is|was|of|estimate|percentage|share|represent|represents|account for)\s*|[:=]\s*){0,3}"
        + number
    ]
    preceding_label = r"\bresidents\b" if field == "population" else label
    patterns.append(number + r"\s*(?:of\s+)?" + preceding_label)
    return [
        (Decimal(match["number"].replace(",", "")), bool(match["percent"]))
        for pattern in patterns
        for match in re.finditer(pattern, text, re.I)
    ]


def _action_columns(narrative):
    """Resolve action cells from authored headers, never assume a column order."""
    columns, section = set(), ""
    lines = narrative.splitlines()
    for index, line in enumerate(lines):
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+)$", line)
        if heading:
            section = normalise_markdown_heading(heading[1])
        if index + 1 >= len(lines):
            continue
        normalised_next = "|" + lines[index + 1].strip().strip("|") + "|"
        if not is_markdown_table_separator(normalised_next):
            continue
        cells = parse_markdown_table_row("|" + line.strip().strip("|") + "|") or []
        for number, cell in enumerate(cells, 1):
            if re.search(r"\b(?:responsibilit\w*|actions?|tasks?|duties|what to do|checkpoints?)\b", cell, re.I):
                columns.add((section, number))
    return columns


def _p2_checks(units, analysis):
    basis = build_community_p2_basis(analysis)
    indicators = basis["indicators"]
    if not (analysis.get("community") or {}).get("indicators"):
        return _check("Processed community provenance", [], "No frozen community indicators require narration.")
    codes = []
    years = re.findall(r"\b(?:19|20)\d{2}\b", str(basis["data_quality"]["source_period"] or ""))
    geography = str(basis["geography_type"] or "").casefold()
    count = basis["matched_sa2_count"]
    for field, pattern in _FIELDS.items():
        value = indicators[field]
        relevant = [(unit, text) for unit, text, _ in units if pattern.search(text)]
        if value is None:
            if field in {"no_car_households_pct", "language_other_than_english_pct"}:
                if not any(_UNKNOWN.search(text) for _, text in relevant):
                    codes.append("p2_unknown_measurement_omitted")
                if any(_measurements(text, field) for _, text in relevant):
                    codes.append("p2_unknown_measurement_promoted")
            continue
        try:
            numeric_value = Decimal(str(value).replace(",", ""))
        except InvalidOperation:
            codes.append("p2_invalid_frozen_measurement")
            continue
        if not numeric_value.is_finite():
            codes.append("p2_invalid_frozen_measurement")
            continue
        wanted = (numeric_value, field != "population")
        factual = [(unit, text) for unit, text in relevant if wanted in _measurements(text, field)]
        if not factual:
            codes.append("p2_available_fact_omitted")
        for unit, text in relevant:
            measured = _measurements(text, field)
            if not measured:
                continue
            if any(item != wanted for item in measured):
                codes.append("p2_value_mismatch")
            if "[P2]" not in unit["claim"] or unit["citations"]:
                codes.append("p2_adjacent_provenance_missing")
            if not years or not all(year in text for year in years):
                codes.append("p2_period_missing")
            if count is not None:
                if not re.search(rf"\b{re.escape(str(count))}\s*[- ]?SA2\b", text, re.I):
                    codes.append("p2_geographic_basis_missing")
                if count != 1 and not re.search(r"\b(?:aggregat\w*|group\w*|approximat\w*)\b", text, re.I):
                    codes.append("p2_aggregation_limit_missing")
            elif not geography or geography not in text.casefold():
                codes.append("p2_geographic_basis_missing")
            if _CAMPUS.search(text) and not re.search(
                r"\b(?:not|rather than)\b.{0,40}(?:school|campus|student)", text, re.I
            ):
                codes.append("p2_community_not_campus_scope_missing")
    return _check(
        "Processed community provenance",
        codes,
        "Available community figures retain adjacent P2, period, geographic limits and unknowns.",
    )


def evaluate_report_content_contract(report_text, analysis, *, model_evidence=None):
    """Return conservative checks; a pass never certifies truth or applicability."""
    analysis = analysis if isinstance(analysis, dict) else {}
    narrative = extract_narrative_body(str(report_text or ""))
    authored = strip_application_source_bindings(
        visible_markdown_text(narrative),
        official_sources=(analysis.get("data") or {}).get("sources") or [],
        rag_sources=(analysis.get("knowledge") or {}).get("retrieved_chunks") or [],
    )
    words = len(_WORD.findall(_plain(authored, analysis)))
    checks = [
        _check(
            "Narrative word budget",
            ["narrative_word_budget"] if not 650 <= words <= 800 else [],
            "The authored narrative is within 650–800 words.",
            word_count=words,
            minimum=650,
            maximum=800,
        )
    ]
    units = [
        (unit, _claim_shadow(unit["claim"], analysis), normalise_markdown_heading(unit["section"]))
        for unit in extract_body_claims(narrative, analysis)
    ]
    action_columns = _action_columns(narrative)
    checks.append(_p2_checks(units, analysis))
    model_evidence = unavailable_model_evidence() if model_evidence is None else model_evidence
    try:
        visible = validate_model_evidence(model_evidence, analysis, report_text=str(report_text or ""))
        snapshot_status = model_evidence["status"]
    except (ValueError, TypeError, KeyError, AttributeError):
        visible, snapshot_status = [], "invalid_snapshot"
    by_source = {}
    for passage in visible:
        by_source.setdefault(str(passage.get("source_id")), []).append(passage["text"])
    conflicts = {
        str(item.get("source_id"))
        for item in (analysis.get("knowledge") or {}).get("retrieved_chunks") or []
        if isinstance(item, dict) and _CONFLICT.search(str(item.get("text") or ""))
    }
    task_codes, inference_codes, evidence_codes = [], [], []
    for unit, text, section in units:
        if not text:
            continue
        proposal = bool(_PROPOSAL.search(text))
        confirmer = bool(_CONFIRMER.search(text))
        # A gap sentence cannot append criteria/advice in the same unit and
        # inherit an exemption from the first half of that sentence.
        gap = bool(_GAP.search(text)) and not re.search(
            r"\b(?:but|however|propos\w*|should|must|will|use|select|choose|adopt|include|recommend\w*)\b", text, re.I
        )
        cited = [entry["source_id"] for entry in unit["citations"] if entry["source_type"] == "rag"]
        submitted = [passage for source_id in cited for passage in by_source.get(source_id, [])]
        if any(source_id not in by_source for source_id in cited):
            evidence_codes.append("cited_passage_not_final_submitted")
        local_section = section in {
            "preparedness priorities",
            "evacuation planning",
            "candidate assembly point criteria",
            "roles and responsibilities",
            "communication and inclusion needs",
            "first aid, training and exercises",
            "action plan",
            "human review and approval checklist",
        }
        table_task = (
            unit["block_type"] == "table_cell"
            and section in {"roles and responsibilities", "action plan"}
            and (section, unit["table_column"]) in action_columns
        )
        # A citation alone cannot turn an imperative into a source description.
        # Task cells and checklists always carry their own local qualification.
        source_frame = re.search(
            r"^(?:(?:the )?(?:source|guidance|passage|guide)\b.{0,50}\b(?:states|says|describes|advises)|"
            r"(?:households?|families|homeowners)\b)",
            text,
            re.I,
        )
        sourced_description = bool(
            cited
            and source_frame
            and not _CAMPUS.search(text)
            and not proposal
            and not table_task
            and unit["block_type"] != "checklist"
        )
        local_task = local_section and (table_task or unit["block_type"] == "checklist" or _TASK_FRAME.search(text))
        # This exact complete sentence describes the absence of instructions.
        # It is not a general negation rule and exempts no other content check.
        non_directive = text.casefold() == _NON_DIRECTIVE_DISCLAIMER
        if local_task and not non_directive and not sourced_description and not gap and not (proposal and confirmer):
            task_codes.append("local_task_requires_own_proposal_and_confirmer")
        if proposal and not confirmer:
            task_codes.append("proposal_confirmer_missing")
        if section == "local risk context" and _CAUSAL.search(text) and not gap:
            if not ("[R3]" in unit["claim"] and _INFERENCE.search(text) and confirmer):
                inference_codes.append("causal_planning_inference_unqualified")
            if unit["citations"]:
                inference_codes.append("r3_inference_cannot_borrow_official_citation")
        elif _CAUSAL.search(text) and not cited and not gap:
            inference_codes.append("unsupported_causal_effect_assertion")
        if section == "candidate assembly point criteria" and _PHYSICAL.search(text) and not gap:
            # The application has no vetted criterion-to-premises applicability
            # binding. Even a verbatim passage, audience/keyword overlap or a
            # proposal label cannot establish a physical criterion for local use.
            evidence_codes.append("physical_assembly_criteria_require_authority_verification")
        if submitted and not gap:
            if any(_HOUSEHOLD.search(item) and not _CAMPUS.search(item) for item in submitted):
                if not _HOUSEHOLD.search(text) or _CAMPUS.search(text):
                    evidence_codes.append("household_source_scope_not_preserved")
        if set(cited) & conflicts:
            notice = _CONFLICT_NOTICE.search(text) and re.search(
                r"\b(?:unresolved|review|confirm|verify)\b", text, re.I
            )
            if not notice:
                evidence_codes.append("contradictory_source_used_as_advice")
    checks.extend(
        [
            _check(
                "Local proposal attribution", task_codes, "Targeted local tasks carry their own proposal and confirmer."
            ),
            _check(
                "Rule-derived causal qualification",
                inference_codes,
                "Targeted causal planning inferences remain qualified.",
            ),
            _check(
                "Submitted passage scope and conflicts",
                evidence_codes,
                "No targeted submitted-passage, audience or source-conflict violation detected.",
                snapshot_status=snapshot_status,
            ),
        ]
    )
    return checks
