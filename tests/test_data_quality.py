from src.data_quality import assess_source_period, build_community_data_quality
from src.report_template import build_evidence_tables


def test_source_period_assessment_uses_latest_non_future_year():
    result = assess_source_period(
        "2021 Census and 2022 ERP fields; downloaded 2026",
        current_year=2025,
    )

    assert result["latest_source_year"] == 2022
    assert result["source_age_years"] == 3
    assert result["freshness"] == "Aging planning baseline"


def test_configured_community_profile_records_age_match_quality_and_warnings():
    result = build_community_data_quality(
        matched_location="Cairns, Queensland",
        source_period="2021 Census and 2022 ERP fields",
        match_method="configured_sa2_names",
        geography_type="LGA approximation from 2021 SA2 names",
        transport_value="",
        current_year=2026,
    )

    assert result["source_age_years"] == 4
    assert result["match_quality"] == "Moderate — configured SA2 aggregation"
    assert any("4 years old" in warning for warning in result["warnings"])
    assert any("approximation" in warning for warning in result["warnings"])
    assert any("Transport vulnerability" in warning for warning in result["warnings"])


def test_explicit_map_selection_is_high_match_but_preserves_aggregation_warning():
    result = build_community_data_quality(
        matched_location="Cairns City, Queensland",
        source_period="2021 Census and 2022 ERP fields",
        match_method="user_selected_sa2",
        geography_type="SA2 selected from all-Australia ABS SA2 dataset",
        area_selection={"level": "SA2", "area_name": "Cairns City"},
        transport_value=None,
        current_year=2026,
    )

    assert result["match_quality"] == "High — explicit ASGS area selection"
    assert "matched exactly" in result["match_basis"]
    assert any("aggregates SA2" in warning for warning in result["warnings"])


def test_unmatched_profile_has_explicit_no_match_warning():
    result = build_community_data_quality(
        matched_location=None,
        current_year=2026,
    )

    assert result["freshness"] == "Unknown source age"
    assert result["match_quality"].startswith("None")
    assert any("No community profile matched" in warning for warning in result["warnings"])


def test_evidence_tables_export_structured_data_quality_assessment():
    data_quality = build_community_data_quality(
        matched_location="Cairns, Queensland",
        source_period="2021 Census and 2022 ERP fields",
        match_method="configured_sa2_names",
        geography_type="LGA approximation from 2021 SA2 names",
        transport_value="",
        current_year=2026,
    )

    table = build_evidence_tables(
        {
            "community": {
                "matched_location": "Cairns, Queensland",
                "data_quality": data_quality,
            }
        }
    )

    assert "Evidence Table 2A: Data Currency and Geographic Match" in table
    assert "Aging planning baseline" in table
    assert "Moderate — configured SA2 aggregation" in table
    assert "newest recorded community indicator year is 4 years old" in table
