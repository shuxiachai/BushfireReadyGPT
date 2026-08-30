EVIDENCE_LEVELS = {
    "O1": {
        "evidence_class": "Official-source reference",
        "confidence_boundary": (
            "High source authority, but this report does not confirm currency, completeness or "
            "operational applicability."
        ),
        "required_review": "Open the official source and verify current information before use.",
    },
    "P2": {
        "evidence_class": "Processed official-origin data",
        "confidence_boundary": (
            "Moderate and context-dependent; processing, aggregation and geographic matching can introduce limitations."
        ),
        "required_review": "Check source year, transformation method, coverage and selected geography.",
    },
    "R3": {
        "evidence_class": "Deterministic rule inference",
        "confidence_boundary": (
            "Indicative and reproducible, but dependent on configured rules and input matching; it "
            "is not observed incident evidence."
        ),
        "required_review": "Validate the inference with local officers, plans and current conditions.",
    },
    "A4": {
        "evidence_class": "AI-generated draft synthesis",
        "confidence_boundary": (
            "Not an evidence source. Model-generated narrative can omit, simplify or invent details."
        ),
        "required_review": "A responsible human must verify every operational claim before approval.",
    },
    "U0": {
        "evidence_class": "User-provided / unverified context",
        "confidence_boundary": "Unverified unless supported by organisational records or an official source.",
        "required_review": "Confirm inputs with the responsible organisation.",
    },
}


def build_evidence_confidence_rows(analysis):
    """Describe evidence provenance and review boundaries for one analysis run."""

    analysis = analysis or {}
    profile = analysis.get("profile", {})
    data_result = analysis.get("data", {})
    community = analysis.get("community", {})
    risk_context = analysis.get("risk_context", {})
    knowledge = analysis.get("knowledge", {})
    geography_reference = community.get("geography_reference", {})
    selected_asgs = geography_reference.get("selected_asgs_area") or {}

    official_count = len(data_result.get("sources", []))
    official_use = f"{official_count} official entry-point reference(s) selected"
    if selected_asgs.get("source_file"):
        official_use += f"; ASGS provenance recorded from {selected_asgs['source_file']}"
    retrieved_count = len(knowledge.get("retrieved_chunks", []))
    if retrieved_count:
        official_use += (
            f"; {retrieved_count} static official RAG passage(s) retrieved from verified index "
            f"{knowledge.get('index_manifest_sha256', '')[:12]} using "
            f"{knowledge.get('retrieval_mode') or 'the configured retriever'}"
        )

    matched_location = community.get("matched_location") or "No community profile matched"
    processed_use = f"Community context: {matched_location}"
    if community.get("data_source_note"):
        processed_use += f"; {community['data_source_note']}"

    matched_rules = [item for item in risk_context.get("matched_rule_ids", []) if item]
    rule_use = (
        f"{len(matched_rules)} configured rule(s) matched: {', '.join(matched_rules)}"
        if matched_rules
        else "No configured local rule matched; generic planning fallback used"
    )

    user_use = (
        f"Location: {profile.get('location') or 'not provided'}; audience: {profile.get('audience') or 'not provided'}"
    )

    current_uses = {
        "O1": official_use,
        "P2": processed_use,
        "R3": rule_use,
        "A4": "The configured language model produces the narrative draft after deterministic analysis.",
        "U0": user_use,
    }
    return [
        {
            "code": code,
            **definition,
            "current_use": current_uses[code],
        }
        for code, definition in EVIDENCE_LEVELS.items()
    ]


def format_evidence_confidence_for_prompt(rows):
    return "\n".join(
        f"- {row['code']} {row['evidence_class']}: {row['current_use']} "
        f"Boundary: {row['confidence_boundary']} Review: {row['required_review']}"
        for row in rows
    )


def format_evidence_confidence_rules_for_prompt():
    """Render only application-owned evidence rules for model instructions."""

    return "\n".join(
        f"- {code} {definition['evidence_class']}. "
        f"Boundary: {definition['confidence_boundary']} Review: {definition['required_review']}"
        for code, definition in EVIDENCE_LEVELS.items()
    )
