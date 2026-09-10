"""Nullable ABS indicators with explicit, non-interchangeable population bases.

Field labels verified against the source layer on 2026-09-10. The layer provides
2021 language counts and a published percentage, but no confirmed matching
Census denominator. Neither 2022 ERP nor an inverse of a rounded percentage is
an acceptable weight for aggregating that language percentage.
"""

from __future__ import annotations

import json
import math

ABS_INDICATOR_METADATA_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/ABS_Population_and_people_by_2021_SA2_Nov_2023/FeatureServer/1"
)
ABS_INDICATOR_METHODOLOGY_URL = "https://www.abs.gov.au/methodologies/data-region-methodology/2011-23"
INDICATOR_SCHEMA = "abs-indicators-v2"
POPULATION_FIELD = "erp_p_202022"  # Estimated resident population: Persons (no.), 2022.
OLDER_COUNT_FIELDS = ["erp_p_152022", "erp_p_162022", "erp_p_172022", "erp_p_182022", "erp_p_192022"]
LANGUAGE_COUNT_FIELD = "census_392021"  # Other language at home (no.), 2021 Census.
LANGUAGE_PERCENT_FIELD = "census_332021"  # Other language at home (%), 2021 Census.
LANGUAGE_BASIS_WARNING = (
    "Language diversity percentage and its support proxy are unavailable: use a verified official single-SA2 "
    "2021 Census percentage, or obtain matching Census population weights for aggregation. "
    "2021 Census language counts must not be divided by 2022 ERP. Existing dataset files have not been recalculated."
)


def nullable_count(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(number) if math.isfinite(number) and number >= 0 and number.is_integer() else None


def nullable_percentage(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 100 else None


def support_level(language_pct):
    percentage = nullable_percentage(language_pct)
    if percentage is None:
        return "unknown"
    if percentage >= 20:
        return "high"
    if percentage >= 8:
        return "medium"
    return "low"


def _complete_sum(values, expected):
    return sum(values) if expected and len(values) == expected and all(value is not None for value in values) else None


def _coverage(valid, expected):
    return {
        "valid_sa2_count": valid,
        "expected_sa2_count": expected,
        "valid_sa2_coverage_pct": round(valid / expected * 100, 1) if expected else None,
    }


def summarise_indicator_values(values, *, expected_sa2_count=None):
    """Produce full-area indicators only where their individual evidence permits."""

    expected = len(values) if expected_sa2_count is None else expected_sa2_count
    populations = [nullable_count(row.get("population")) for row in values]
    population = _complete_sum(populations, expected)
    age_pairs = []
    language_counts = []
    language_pairs = []
    for row, denominator in zip(values, populations):
        older = nullable_count(row.get("older_people_count"))
        if denominator is not None and older is not None and older <= denominator:
            age_pairs.append((older, denominator))
        language = nullable_count(row.get("language_other_than_english_count"))
        language_counts.append(language)
        official_pct = nullable_percentage(row.get("official_language_pct"))
        if language is not None and official_pct is not None:
            language_pairs.append((language, official_pct))
    age_numerator = sum(pair[0] for pair in age_pairs) if age_pairs else None
    age_denominator = sum(pair[1] for pair in age_pairs) if age_pairs else None
    age_complete = bool(expected and len(age_pairs) == expected)
    older_pct = round(age_numerator / age_denominator * 100, 1) if age_complete and age_denominator else None
    language_pct = language_pairs[0][1] if expected == len(values) == len(language_pairs) == 1 else None
    language_method = (
        "official_published_single_sa2"
        if language_pct is not None
        else "unavailable_without_same_population_denominator"
    )
    evidence = {
        "schema": INDICATOR_SCHEMA,
        "source_metadata_url": ABS_INDICATOR_METADATA_URL,
        "population": {
            "year": 2022,
            "method": "sum_complete_erp_counts",
            "source_field": POPULATION_FIELD,
            **_coverage(sum(value is not None for value in populations), expected),
        },
        "older_people_pct": {
            "numerator": age_numerator,
            "denominator": age_denominator,
            "year": 2022,
            "numerator_fields": OLDER_COUNT_FIELDS,
            "denominator_field": POPULATION_FIELD,
            "method": "ratio_of_sums_complete_coverage" if age_complete else "unavailable_incomplete_coverage",
            **_coverage(len(age_pairs), expected),
        },
        "language_other_than_english_pct": {
            "numerator": sum(value for value in language_counts if value is not None)
            if any(value is not None for value in language_counts)
            else None,
            "numerator_scope": "Available source counts; not a full-area total when count coverage is incomplete.",
            "count_valid_sa2_count": sum(value is not None for value in language_counts),
            "numerator_field": LANGUAGE_COUNT_FIELD,
            "denominator": None,
            "denominator_basis": "Matching Census denominator is not supplied by the configured source layer.",
            "year": 2021,
            "source_field": LANGUAGE_PERCENT_FIELD,
            "published_pct": language_pct,
            "method": language_method,
            "interpretation": "Language diversity proxy, not measured English proficiency or support demand.",
            **_coverage(len(language_pairs), expected),
        },
    }
    return {
        "population": population,
        "older_people_count": age_numerator if age_complete else None,
        "older_people_pct": older_pct,
        "language_other_than_english_count": _complete_sum(language_counts, expected),
        "language_other_than_english_pct": language_pct,
        "language_support_needed": support_level(language_pct),
        "indicator_schema": INDICATOR_SCHEMA,
        "indicator_evidence": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
    }


def derive_abs_indicators(attributes, *, expected_sa2_count=None):
    values = []
    for row in attributes:
        age_counts = [nullable_count(row.get(field)) for field in OLDER_COUNT_FIELDS]
        values.append(
            {
                "population": row.get(POPULATION_FIELD),
                "older_people_count": _complete_sum(age_counts, len(OLDER_COUNT_FIELDS)),
                "language_other_than_english_count": row.get(LANGUAGE_COUNT_FIELD),
                "official_language_pct": row.get(LANGUAGE_PERCENT_FIELD),
            }
        )
    return summarise_indicator_values(values, expected_sa2_count=expected_sa2_count)


def trusted_language_percentage(row):
    """Do not promote legacy cross-year ratios to same-population evidence."""

    if row.get("indicator_schema") != INDICATOR_SCHEMA:
        return None
    try:
        evidence = json.loads(row.get("indicator_evidence") or "{}")
        language = evidence["language_other_than_english_pct"]
        percentage = nullable_percentage(row.get("language_other_than_english_pct"))
        if (
            evidence.get("schema") != INDICATOR_SCHEMA
            or language.get("method") != "official_published_single_sa2"
            or language.get("year") != 2021
            or language.get("source_field") != LANGUAGE_PERCENT_FIELD
            or language.get("valid_sa2_count") != 1
            or language.get("expected_sa2_count") != 1
            or percentage is None
            or percentage != nullable_percentage(language.get("published_pct"))
            or nullable_count(row.get("language_other_than_english_count")) is None
            or nullable_count(row.get("language_other_than_english_count")) != language.get("numerator")
        ):
            return None
        return percentage
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def language_display_fields(row, *, assume_abs=False):
    """Expose only provenance-backed ABS rates, including in legacy map displays."""

    source = str(row.get("source") or "").casefold()
    if not (
        assume_abs or row.get("indicator_schema") or source.startswith(("abs ", "australian bureau of statistics"))
    ):
        return {
            "language_other_than_english_pct": row.get("language_other_than_english_pct", ""),
            "language_support_needed": row.get("language_support_needed", "unknown"),
            "language_indicator_note": "",
        }
    percentage = trusted_language_percentage(row)
    return {
        "language_other_than_english_pct": "" if percentage is None else percentage,
        "language_support_needed": support_level(percentage),
        "language_indicator_note": LANGUAGE_BASIS_WARNING
        if percentage is None
        else "Official published 2021 Census single-SA2 percentage; not measured English proficiency.",
    }


def indicator_warnings(indicators):
    evidence = json.loads(indicators["indicator_evidence"])
    warnings = []
    older = evidence["older_people_pct"]
    if indicators["older_people_pct"] is None:
        warnings.append(
            f"Older-person percentage is unavailable: {older['valid_sa2_count']}/{older['expected_sa2_count']} "
            f"SA2 records have valid paired evidence; available-subset numerator={older['numerator']}, "
            f"denominator={older['denominator']} (2022 ERP). Missing values are not zero."
        )
    if indicators["language_other_than_english_pct"] is None:
        warnings.append(LANGUAGE_BASIS_WARNING)
        language = evidence["language_other_than_english_pct"]
        warnings.append(
            f"Language evidence coverage: {language['valid_sa2_count']}/{language['expected_sa2_count']} SA2 records "
            f"have a valid count and official percentage; available-count numerator={language['numerator']}, "
            "matching Census denominator=unavailable (2021). No cross-area weighted percentage was inferred."
        )
    return warnings
