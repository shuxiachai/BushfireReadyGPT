"""Shared presentation of nullable evidence values, without UI dependencies."""

import math


def format_evidence_value(value, suffix=""):
    """Missing indicators are unknown, not zero; a real zero remains visible."""
    missing = "To be confirmed"
    if value is None or isinstance(value, bool):
        return missing
    text = str(value).strip()
    if not text:
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return missing if suffix else text
    if not math.isfinite(number) or suffix == "%" and not 0 <= number <= 100:
        return missing
    return f"{text}{suffix}"
