from src.agents import run_analysis_pipeline


GOVERNANCE_NOTICE_MARKDOWN = """**DRAFT STATUS NOTICE**

This report is a preparedness planning draft. It is not emergency advice, does not provide live fire conditions, and does not issue evacuation orders, fire bans or life-safety directions. The responsible organisation must review and approve this draft before formal use. In a life-threatening emergency, call 000.

Safety disclaimer: live warnings, fire bans, evacuation orders and life-safety decisions must come from official emergency services and authorised public information sources.
"""


def apply_governance_notice(report_text):
    text = report_text or ""
    if "DRAFT STATUS NOTICE" in text:
        return text
    return f"{GOVERNANCE_NOTICE_MARKDOWN}\n\n{text.lstrip()}"


def append_evidence_tables(report_text, analysis):
    """Append deterministic evidence tables so exported reports keep source traceability."""

    text = report_text or ""
    if "## Evidence Tables" in text:
        return text

    appendix = build_evidence_tables(analysis or {})
    if not appendix:
        return text
    return f"{text.rstrip()}\n\n{appendix}\n"


def append_human_signoff(report_text, review_record=None):
    text = _remove_section(report_text or "", "## Human Review Sign-off")
    record = review_record or {}
    appendix = build_human_signoff(record)
    return f"{text.rstrip()}\n\n{appendix}\n"


def build_human_signoff(review_record):
    return "\n".join(
        [
            "## Human Review Sign-off",
            "",
            "This section records human review status for pilot governance. It does not convert the report into official emergency advice.",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Review status | {_md_value(review_record.get('approval_status') or review_record.get('report_status'))} |",
            f"| Reviewer name | {_md_value(review_record.get('reviewer_name'))} |",
            f"| Reviewer role | {_md_value(review_record.get('reviewer_role'))} |",
            f"| Review date | {_md_value(review_record.get('review_date'))} |",
            f"| Organisation / department | {_md_value(review_record.get('organisation_name'))} |",
            f"| Notes | {_md_value(review_record.get('review_notes'))} |",
            "",
            "- [ ] Official warnings, fire danger information and emergency instructions were checked separately.",
            "- [ ] Candidate assembly points and evacuation routes were reviewed by the responsible organisation.",
            "- [ ] Data sources, limitations and geography assumptions were checked by a human reviewer.",
            "- [ ] This output remains a draft unless the responsible organisation has formally approved it.",
        ]
    )


def build_evidence_tables(analysis):
    profile = analysis.get("profile", {})
    community = analysis.get("community", {})
    data_result = analysis.get("data", {})
    risk_context = analysis.get("risk_context", {})
    geography_reference = community.get("geography_reference", {})
    selected_asgs = geography_reference.get("selected_asgs_area") or {}
    lga_candidates = geography_reference.get("lga_candidates", [])
    indicators = community.get("indicators", {})

    lines = [
        "## Evidence Tables",
        "",
        "These tables are generated from local pipeline outputs to support human review and audit traceability. They are not live emergency data.",
        "",
        "### Evidence Table 1: Selected Geography",
        "",
        "| Field | Value | Source / note |",
        "| --- | --- | --- |",
        f"| User location | {_md_value(profile.get('location'))} | Form input |",
        f"| Inferred state / territory | {_md_value(profile.get('state'))} | Profile Agent inference |",
        f"| Selected ASGS level | {_md_value(selected_asgs.get('selected_level'))} | ABS ASGS allocation reference |",
        f"| Selected ASGS area | {_md_value(selected_asgs.get('selected_area'))} | Map selection / ASGS reference |",
        f"| SA2 rows in selected area | {_md_value(selected_asgs.get('sa2_count'))} | { _md_value(selected_asgs.get('source_file')) } |",
        f"| SA3 reference | {_md_value(selected_asgs.get('sa3_names'))} | ABS ASGS hierarchy |",
        f"| SA4 reference | {_md_value(selected_asgs.get('sa4_names'))} | ABS ASGS hierarchy |",
        f"| GCCSA reference | {_md_value(selected_asgs.get('gccsa_names'))} | ABS ASGS hierarchy |",
        f"| Albers area | {_md_value(_with_unit(selected_asgs.get('area_albers_sqkm'), 'sq km'))} | ABS ASGS allocation area field |",
        "",
        "### Evidence Table 2: Community Indicators",
        "",
        "| Indicator | Value | Source / note |",
        "| --- | --- | --- |",
        f"| Matched community profile | {_md_value(community.get('matched_location'))} | Community Vulnerability Agent |",
        f"| Population | {_md_value(indicators.get('population'))} | ABS Data by Region / local processed data |",
        f"| Older people percentage | {_md_value(_with_unit(indicators.get('older_people_pct'), '%'))} | ABS-derived planning indicator |",
        f"| Language other than English at home | {_md_value(_with_unit(indicators.get('language_other_than_english_pct'), '%'))} | ABS-derived planning indicator |",
        f"| Language support need | {_md_value(indicators.get('language_support_needed'))} | Derived from local processed data |",
        f"| Matched SA2 count | {_md_value(indicators.get('matched_sa2_count'))} | Community Vulnerability Agent |",
        f"| Transport vulnerability | {_md_value(indicators.get('no_car_households_pct'))} | To be confirmed if blank |",
        "",
        "### Evidence Table 3: LGA 2025 Candidate Reference",
        "",
        "| LGA code | LGA name | State / territory | Mesh blocks | Albers area | Source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    if lga_candidates:
        for item in lga_candidates:
            lines.append(
                "| "
                f"{_md_value(item.get('lga_code_2025'))} | "
                f"{_md_value(item.get('lga_name_2025'))} | "
                f"{_md_value(item.get('state_name_2021'))} | "
                f"{_md_value(item.get('mesh_block_count'))} | "
                f"{_md_value(_with_unit(item.get('area_albers_sqkm'), 'sq km'))} | "
                f"{_md_value(item.get('source_file'))} |"
            )
    else:
        lines.append("| To be confirmed | To be confirmed | To be confirmed | To be confirmed | To be confirmed | No LGA candidate matched from local ASGS summary |")

    lines.extend(
        [
            "",
            "### Evidence Table 4: Official Source Register",
            "",
            "| Source | Purpose | URL |",
            "| --- | --- | --- |",
        ]
    )
    for source in data_result.get("sources", []):
        lines.append(
            "| "
            f"{_md_value(source.get('name'))} | "
            f"{_md_value(source.get('purpose'))} | "
            f"{_md_value(source.get('url'))} |"
        )
    if not data_result.get("sources"):
        lines.append("| To be confirmed | No official source matched by the data agent | To be confirmed |")

    lines.extend(
        [
            "",
            "### Evidence Table 5: Limitations Requiring Human Review",
            "",
        ]
    )
    limitations = []
    limitations.extend(data_result.get("data_limitations", []))
    limitations.extend(geography_reference.get("limitations", []))
    limitations.extend(risk_context.get("assumptions", []))
    if community.get("data_source_note"):
        limitations.append(community.get("data_source_note"))
    for limitation in limitations:
        lines.append(f"- {_md_value(limitation)}")

    return "\n".join(lines)


def _with_unit(value, unit):
    if value in {None, ""}:
        return ""
    return f"{value} {unit}"


def _md_value(value):
    text = str(value) if value not in {None, ""} else "To be confirmed"
    return text.replace("|", "/").replace("\n", " ").strip()


def _remove_section(text, heading):
    marker = text.find(heading)
    if marker == -1:
        return text
    next_heading = text.find("\n## ", marker + len(heading))
    if next_heading == -1:
        return text[:marker].rstrip()
    return f"{text[:marker].rstrip()}\n\n{text[next_heading + 1:].lstrip()}"


REPORT_TEMPLATE_SECTIONS = [
    ("1. Title", "Use a clear title that includes the selected geography, scenario and audience."),
    ("2. Executive Summary", "Summarise the preparedness purpose, selected geography, audience and draft status."),
    ("3. Purpose and Scope", "Explain what the report supports and explicitly state that it does not provide live emergency direction."),
    ("4. Selected Geography and Key Assumptions", "List the selected map area, ABS geography level, ASGS SA2/SA3/SA4/State reference details, any LGA candidate reference, known assumptions and items requiring local confirmation."),
    ("5. Data Sources and Limitations", "List ABS Data by Region, ASGS allocation/correspondence files, official source registers, data years, limitations and licence checks required before operational use."),
    ("6. Local Risk Context", "Describe bushfire, smoke, heat, road, power, communications and community vulnerability considerations."),
    ("7. Preparedness Priorities", "List the highest-priority preparedness actions for the selected scenario."),
    ("8. Evacuation Planning", "Describe warning monitoring, notification, movement, accountability and update processes."),
    ("9. Candidate Assembly Point Criteria", "Provide criteria only; do not claim that any venue is confirmed safe without local approval."),
    ("10. Roles and Responsibilities", "Use a table for responsible organisation, staff, volunteers, communications, first aid and review roles."),
    ("11. Communication and Inclusion Needs", "Address internal communication, public/parent communication, multilingual needs and backup channels."),
    ("12. First Aid, Training and Exercises", "Cover first aid, smoke/heat exposure, AED/burn response, drill frequency and exercise records."),
    ("13. Action Plan", "Use the selected timeframe and provide concrete actions with owners and review checkpoints."),
    ("14. Human Review and Approval Checklist", "Provide a checklist for human review before the report is used operationally."),
    ("15. Safety Disclaimer", "State that live warnings, fire bans, evacuation orders and life-safety decisions must come from official emergency services; call 000 in life-threatening emergencies."),
]


def build_report_prompt(
    location,
    audience,
    scenario,
    concerns,
    timeframe,
    extra_context,
    analysis=None,
    area_selection=None,
    governance_context=None,
):
    concerns_text = ", ".join(concerns) if concerns else "Evacuation, assembly points, first aid, roles, official sources"
    extra = extra_context.strip() if extra_context.strip() else "No additional context provided."
    if analysis is None:
        analysis = run_analysis_pipeline(location, audience, scenario, concerns, timeframe, extra_context, area_selection=area_selection)
    section_text = "\n".join(
        f"{title}\nWriting requirement: {instruction}" for title, instruction in REPORT_TEMPLATE_SECTIONS
    )

    return f"""Generate a formal English bushfire preparedness planning report using the form inputs and evidence context below.

Location: {location}
Audience: {audience}
Scenario: {scenario}
Focus areas: {concerns_text}
Timeframe: {timeframe}
Additional context: {extra}

{governance_context or ""}

{analysis["prompt_context"]}

Follow this fixed report structure. Do not omit sections and do not change the section order:
{section_text}

Formatting and safety requirements:
- Start the report with this exact notice block:
{GOVERNANCE_NOTICE_MARKDOWN}
- Write in formal English suitable for a government, school, council or community preparedness pilot.
- Treat the output as a draft for human review unless explicitly marked approved by the responsible organisation.
- Use tables for roles/responsibilities and the action plan where helpful.
- Use Markdown checklist items such as `- [ ] Confirm candidate assembly point criteria with responsible officers`.
- Do not invent live fire conditions, evacuation orders, fire bans, road closures or unverified official links.
- If information is missing, write "To be confirmed by the responsible organisation / official source".
- Include data sources, data limitations and human review requirements.
- Official sources are verification entry points only. Live warnings, fire bans, evacuation orders and life-safety decisions must come from official emergency services. Call 000 in life-threatening emergencies.
"""
