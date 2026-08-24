"""Shared size and shape limits for user-controlled report text."""

REPORT_FIELD_LIMITS = {
    "organisation_name": ("Organisation / department", 300),
    "reviewer_name": ("Reviewer name", 200),
    "reviewer_role": ("Reviewer role", 300),
    "review_notes": ("Review notes", 4_000),
    "location": ("Location", 200),
    "audience": ("Audience", 500),
    "scenario": ("Scenario", 200),
    "timeframe": ("Timeframe", 100),
    "extra_context": ("Additional context", 4_000),
}
REVIEW_FIELD_LIMITS = {
    "approval_status": ("Approval status", 100),
    "organisation_name": ("Organisation / department", 300),
    "reviewer_name": ("Reviewer name", 200),
    "reviewer_role": ("Reviewer role", 300),
    "review_notes": ("Review notes", 4_000),
    "review_date": ("Review date", 10),
}
REVISION_REQUEST_MAX_CHARS = 4_000
CONCERN_MAX_ITEMS = 20
CONCERN_MAX_CHARS = 200
REPORT_INPUT_MAX_BYTES = 16 * 1024
REVIEW_INPUT_MAX_BYTES = 12 * 1024


def _validate_fields(values, limits, *, total_bytes, scope):
    encoded_size = 0
    for key, (label, max_chars) in limits.items():
        value = values.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return f"{label} must be text."
        if len(value) > max_chars:
            return f"{label} exceeds the {max_chars:,}-character limit."
        encoded_size += len(value.encode("utf-8"))
    if encoded_size > total_bytes:
        return f"The combined {scope} text exceeds the {total_bytes:,}-byte limit."
    return None


def validate_report_input_budget(inputs):
    if not isinstance(inputs, dict):
        return "Report inputs must be an object."
    error = _validate_fields(
        inputs,
        REPORT_FIELD_LIMITS,
        total_bytes=REPORT_INPUT_MAX_BYTES,
        scope="report input",
    )
    if error:
        return error

    concerns = inputs.get("concerns", [])
    if concerns is None:
        concerns = []
    if not isinstance(concerns, list):
        return "Focus areas must be a list."
    if len(concerns) > CONCERN_MAX_ITEMS:
        return f"Focus areas exceed the {CONCERN_MAX_ITEMS}-item limit."
    if any(not isinstance(item, str) or len(item) > CONCERN_MAX_CHARS for item in concerns):
        return f"Each focus area must be text no longer than {CONCERN_MAX_CHARS} characters."
    concern_bytes = sum(len(item.encode("utf-8")) for item in concerns)
    if concern_bytes > REPORT_INPUT_MAX_BYTES:
        return "Focus-area text exceeds the report input budget."
    field_bytes = sum(
        len(inputs.get(key, "").encode("utf-8")) for key in REPORT_FIELD_LIMITS if isinstance(inputs.get(key), str)
    )
    if field_bytes + concern_bytes > REPORT_INPUT_MAX_BYTES:
        return f"The combined report input text exceeds the {REPORT_INPUT_MAX_BYTES:,}-byte limit."
    return None


def validate_review_input_budget(review_record):
    if not isinstance(review_record, dict):
        return "Review record must be an object."
    return _validate_fields(
        review_record,
        REVIEW_FIELD_LIMITS,
        total_bytes=REVIEW_INPUT_MAX_BYTES,
        scope="review",
    )


def validate_revision_request_budget(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return "Revision request must be text."
    if len(value) > REVISION_REQUEST_MAX_CHARS:
        return f"Revision request exceeds the {REVISION_REQUEST_MAX_CHARS:,}-character limit."
    if len(value.encode("utf-8")) > REVIEW_INPUT_MAX_BYTES:
        return f"Revision request exceeds the {REVIEW_INPUT_MAX_BYTES:,}-byte limit."
    return None
