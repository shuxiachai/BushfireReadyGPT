import re
from datetime import datetime


def build_community_data_quality(
    *,
    matched_location,
    source_period="",
    match_method="",
    geography_type="",
    area_selection=None,
    transport_value=None,
    current_year=None,
):
    """Describe data vintage and geographic-match limits for one community result."""

    source_period = str(source_period or "").strip()
    method = str(match_method or "").strip()
    geography = str(geography_type or "").strip()
    source_assessment = assess_source_period(source_period, current_year=current_year)
    year = source_assessment["assessed_for_year"]
    source_age_years = source_assessment["source_age_years"]
    match_quality, match_basis = _match_quality(
        matched_location=matched_location,
        match_method=method,
        geography_type=geography,
        area_selection=area_selection,
    )
    warnings = _quality_warnings(
        matched_location=matched_location,
        source_period=source_period,
        source_age_years=source_age_years,
        match_method=method,
        geography_type=geography,
        area_selection=area_selection,
        transport_value=transport_value,
    )
    return {
        "source_period": source_period or "Not recorded",
        "latest_source_year": source_assessment["latest_source_year"],
        "source_age_years": source_age_years,
        "freshness": source_assessment["freshness"],
        "match_quality": match_quality,
        "match_method": method or "none",
        "match_basis": match_basis,
        "warnings": warnings,
        "assessed_for_year": year,
    }


def assess_source_period(source_period, *, current_year=None):
    """Return a small, display-safe assessment for a declared data source period."""

    year = current_year or datetime.now().year
    period = str(source_period or "").strip()
    source_years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", period)]
    latest_source_year = max((value for value in source_years if value <= year), default=None)
    source_age_years = year - latest_source_year if latest_source_year is not None else None
    return {
        "source_period": period or "Not recorded",
        "latest_source_year": latest_source_year,
        "source_age_years": source_age_years,
        "freshness": _freshness_label(period, source_age_years),
        "assessed_for_year": year,
    }


def _freshness_label(source_period, source_age_years):
    if "synthetic" in source_period.lower() or "prototype" in source_period.lower():
        return "Synthetic prototype data"
    if source_age_years is None:
        return "Unknown source age"
    if source_age_years <= 2:
        return "Recent planning baseline"
    if source_age_years <= 5:
        return "Aging planning baseline"
    return "Historical planning baseline"


def _match_quality(*, matched_location, match_method, geography_type, area_selection):
    if not matched_location:
        return "None — no community profile matched", "No location-based community indicators were used."
    if area_selection:
        level = area_selection.get("level") or "ASGS"
        area_name = area_selection.get("area_name") or matched_location
        return (
            "High — explicit ASGS area selection",
            f"The user selected {level} area '{area_name}', which was matched exactly before aggregation.",
        )
    if match_method == "configured_sa2_names":
        return (
            "Moderate — configured SA2 aggregation",
            "The typed location matched a configured profile built from named SA2 areas; it is not an exact LGA boundary join.",
        )
    if "approximation" in geography_type.lower() or "demonstration" in geography_type.lower():
        return (
            "Moderate — approximate geography",
            f"The typed location matched a processed profile described as: {geography_type}.",
        )
    return (
        "Low — prototype fallback match",
        "The typed location matched a prototype profile without a recorded official geographic match method.",
    )


def _quality_warnings(
    *,
    matched_location,
    source_period,
    source_age_years,
    match_method,
    geography_type,
    area_selection,
    transport_value,
):
    warnings = []
    if not matched_location:
        warnings.append(
            "No community profile matched; verify current population, vulnerability and transport needs from official local data."
        )
    elif "synthetic" in source_period.lower() or "prototype" in source_period.lower():
        warnings.append("Synthetic fallback indicators must not be treated as official statistics.")
    elif source_age_years is None:
        warnings.append("The community indicator source period is unknown and must be verified before use.")
    elif source_age_years > 2:
        warnings.append(
            f"The newest recorded community indicator year is {source_age_years} years old; verify material changes with current official or organisational data."
        )

    if area_selection:
        warnings.append(
            "The selected ASGS area aggregates SA2 records; confirm that this statistical geography matches the organisation's operational area."
        )
    elif match_method == "configured_sa2_names" or any(
        marker in geography_type.lower() for marker in ("approximation", "demonstration", "subset")
    ):
        warnings.append(
            "The configured SA2 grouping is an approximation; confirm boundaries against the current official correspondence or GIS layer."
        )
    if transport_value in {None, ""}:
        warnings.append("Transport vulnerability is unavailable in this profile and requires separate verification.")
    warnings.append(
        "Community indicators are planning context only and must not be used as live incident, warning or evacuation data."
    )
    return warnings
