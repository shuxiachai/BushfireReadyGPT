"""Synthetic inputs only: missing values and Census/ERP bases stay distinct."""

import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from src.abs_indicators import (
    INDICATOR_SCHEMA,
    LANGUAGE_COUNT_FIELD,
    LANGUAGE_PERCENT_FIELD,
    OLDER_COUNT_FIELDS,
    POPULATION_FIELD,
    derive_abs_indicators,
    nullable_count,
    summarise_indicator_values,
    trusted_language_percentage,
)
from src.agents.community_vulnerability_agent import CommunityVulnerabilityAgent
from src.coverage_map import _filter_all_geojson, _summarize_rows, get_coverage_table


def _script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _attributes(**changes):
    return {
        "sa2_code_2021": "101",
        "sa2_name_2021": "Alpha",
        POPULATION_FIELD: 1000,
        **{field: 40 for field in OLDER_COUNT_FIELDS},
        LANGUAGE_COUNT_FIELD: 100,
        LANGUAGE_PERCENT_FIELD: 25.0,
        **changes,
    }


def _national_row(attributes):
    module = _script("download_abs_sa2_all")
    boundary = {
        "features": [
            {
                "properties": {
                    "state_name_2021": "Queensland",
                    "state_code_2021": "3",
                    "sa4_name_2021": "Test SA4",
                    "sa4_code_2021": "100",
                    "sa3_name_2021": "Test SA3",
                    "sa3_code_2021": "10",
                    "sa2_name_2021": attributes["sa2_name_2021"],
                    "sa2_code_2021": attributes["sa2_code_2021"],
                }
            }
        ]
    }
    return module.build_profiles({"features": [{"attributes": attributes}]}, boundary)[0]


def _community_row(attributes):
    return _script("download_abs_community_profiles").aggregate(
        [{"attributes": attributes}], [{"location": "Example", "sa2_names": [attributes["sa2_name_2021"]]}]
    )[0]


@pytest.mark.parametrize("missing", [None, "", "null", "NaN", float("inf"), -1, 0.5, True])
@pytest.mark.parametrize("builder", [_national_row, _community_row])
def test_missing_or_invalid_counts_never_become_zero_or_low_support(builder, missing):
    row = builder(_attributes(**{field: missing for field in [LANGUAGE_COUNT_FIELD, *OLDER_COUNT_FIELDS]}))
    assert row["population"] == 1000
    assert row["older_people_count"] is None
    assert row["older_people_pct"] is None
    assert row["language_other_than_english_count"] is None
    assert row["language_other_than_english_pct"] is None
    assert row["language_support_needed"] == "unknown"


@pytest.mark.parametrize("builder", [_national_row, _community_row])
def test_real_zero_counts_survive_csv_round_trip(builder):
    row = builder(
        _attributes(**{field: 0 for field in [LANGUAGE_COUNT_FIELD, LANGUAGE_PERCENT_FIELD, *OLDER_COUNT_FIELDS]})
    )
    assert row["older_people_count"] == row["language_other_than_english_count"] == 0
    assert row["older_people_pct"] == row["language_other_than_english_pct"] == 0
    assert row["language_support_needed"] == "low"
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    restored = next(csv.DictReader(io.StringIO(text.getvalue())))
    assert restored["older_people_count"] == restored["language_other_than_english_count"] == "0"


def test_partial_age_coverage_records_only_aligned_pairs_without_full_area_percentage():
    first = _attributes()
    second = _attributes(**{OLDER_COUNT_FIELDS[0]: None, POPULATION_FIELD: 9000})
    result = derive_abs_indicators([first, second])
    evidence = json.loads(result["indicator_evidence"])["older_people_pct"]

    assert result["population"] == 10000
    assert result["older_people_pct"] is None
    assert result["older_people_count"] is None
    assert evidence["valid_sa2_count"] == 1
    assert evidence["expected_sa2_count"] == 2
    assert evidence["valid_sa2_coverage_pct"] == 50
    assert evidence["numerator"] == 200
    assert evidence["denominator"] == 1000
    assert evidence["year"] == 2022


def test_age_counts_above_the_same_year_population_do_not_form_a_percentage():
    result = derive_abs_indicators([_attributes(**{POPULATION_FIELD: 100})])
    assert result["older_people_pct"] is None
    assert json.loads(result["indicator_evidence"])["older_people_pct"]["valid_sa2_count"] == 0


@pytest.mark.parametrize("builder", [_national_row, _community_row])
def test_single_sa2_uses_official_census_percentage_not_cross_year_erp_ratio(builder):
    result = builder(_attributes())
    # The synthetic official percentage is 25%; 100 / ERP(1000) would be 10%.
    assert result["language_other_than_english_pct"] == 25
    assert result["language_support_needed"] == "high"
    assert result["older_people_pct"] == 20  # This ratio really is aligned 2022 ERP.
    evidence = json.loads(result["indicator_evidence"])["language_other_than_english_pct"]
    assert evidence["year"] == 2021
    assert evidence["source_field"] == "census_332021"
    assert evidence["numerator_field"] == "census_392021"
    assert evidence["denominator"] is None
    assert evidence["method"] == "official_published_single_sa2"


def test_multiple_sa2_percentages_are_not_averaged_or_weighted_by_erp():
    result = derive_abs_indicators([_attributes(), _attributes(**{POPULATION_FIELD: 9000, LANGUAGE_PERCENT_FIELD: 1})])
    assert result["language_other_than_english_count"] == 200
    assert result["language_other_than_english_pct"] is None
    assert result["language_support_needed"] == "unknown"
    evidence = json.loads(result["indicator_evidence"])["language_other_than_english_pct"]
    assert evidence["denominator"] is None
    assert evidence["valid_sa2_coverage_pct"] == 100
    assert evidence["method"] == "unavailable_without_same_population_denominator"


def test_missing_population_does_not_erase_an_independent_official_census_percentage():
    result = derive_abs_indicators([_attributes(**{POPULATION_FIELD: None})])
    assert result["population"] is None
    assert result["older_people_pct"] is None
    assert result["language_other_than_english_pct"] == 25


def test_query_builders_request_the_verified_official_percentage_field(monkeypatch):
    community = _script("download_abs_community_profiles")
    query = parse_qs(urlsplit(community.build_query_url([{"sa2_names": ["Alpha"]}])).query)
    assert LANGUAGE_PERCENT_FIELD in query["outFields"][0].split(",")
    national = _script("download_abs_sa2_all")
    calls = []
    monkeypatch.setattr(national, "download_paged_json", lambda _url, params, **_kwargs: calls.append(params) or {})
    national.load_official_layers()
    assert LANGUAGE_PERCENT_FIELD in calls[0]["outFields"].split(",")


def test_legacy_abs_profile_language_values_are_hidden_in_runtime_without_rewriting_files(tmp_path):
    profile = tmp_path / "profiles.csv"
    row = {
        "location": "Example",
        "state": "Queensland",
        "population": "1000",
        "older_people_pct": "20",
        "no_car_households_pct": "",
        "language_other_than_english_pct": "10",
        "language_support_needed": "medium",
        "risk_notes": "Legacy ABS demonstration context.",
        "source": "ABS Data by Region",
    }
    with profile.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    before = profile.read_bytes()

    result = CommunityVulnerabilityAgent(profile_path=profile).run({"locality": "Example", "state": "Queensland"})

    assert result["indicators"]["language_support_needed"] == "unknown"
    assert "language_other_than_english_pct" not in result["indicators"]
    assert result["indicators"]["older_people_pct"] == "20"
    assert any("not been recalculated" in note for note in result["vulnerability_notes"])
    assert profile.read_bytes() == before


def test_selected_area_does_not_turn_a_missing_old_age_count_into_zero(monkeypatch):
    agent = CommunityVulnerabilityAgent()
    rows = [
        {"sa3_name": "Example", "state_name": "Queensland", "population": "1000", "older_people_count": "200"},
        {"sa3_name": "Example", "state_name": "Queensland", "population": "9000", "older_people_count": ""},
    ]
    monkeypatch.setattr(agent, "_load_all_sa2_profiles", lambda: rows)

    result = agent._run_selected_area({"level": "SA3", "area_name": "Example", "state": "Queensland"})

    assert result["indicators"]["older_people_pct"] == ""
    assert result["indicators"]["language_support_needed"] == "unknown"
    assert any("1/2" in note and "numerator=200" in note for note in result["vulnerability_notes"])


def test_verified_single_sa2_language_rate_survives_runtime_but_cannot_be_reaggregated(monkeypatch):
    row = _national_row(_attributes())
    assert trusted_language_percentage(row) == 25
    agent = CommunityVulnerabilityAgent()
    monkeypatch.setattr(agent, "_load_all_sa2_profiles", lambda: [row])
    result = agent._run_selected_area({"level": "SA2", "area_name": "Alpha", "state": "Queensland"})
    assert result["indicators"]["language_other_than_english_pct"] == "25.0"
    assert result["indicators"]["language_support_needed"] == "high"
    assert result["indicators"]["indicator_schema"] == INDICATOR_SCHEMA
    assert summarise_indicator_values([row, row])["language_support_needed"] == "unknown"


@pytest.mark.parametrize("value", [None, "", "NaN", float("inf"), -1, True, 1.2])
def test_count_parser_is_nullable_not_a_zero_default(value):
    assert nullable_count(value) is None


def test_map_aggregation_shares_nullable_and_same_population_rules():
    first = _national_row(_attributes())
    second = _national_row(_attributes(**{OLDER_COUNT_FIELDS[0]: None, POPULATION_FIELD: 9000}))

    result = _summarize_rows([first, second], "SA3", "Example")[0]

    assert result["population"] == 10000
    assert result["older_people_pct"] == ""
    assert result["language_other_than_english_pct"] == ""
    assert result["language_support_needed"] == "unknown"
    evidence = json.loads(result["indicator_evidence"])
    assert evidence["older_people_pct"]["valid_sa2_coverage_pct"] == 50


def test_legacy_map_table_suppresses_old_language_ratios_without_rewriting_csv(tmp_path):
    profile = tmp_path / "legacy.csv"
    profile.write_text(
        "location,population,older_people_pct,language_other_than_english_pct,language_support_needed,source\n"
        "Example,1000,20,10,medium,ABS Data by Region\n",
        encoding="utf-8",
    )
    original = profile.read_bytes()

    table = get_coverage_table(data_paths=SimpleNamespace(community_profile=profile))

    assert table[0]["language_other_than_english_pct"] == ""
    assert table[0]["language_support_needed"] == "unknown"
    assert "not been recalculated" in table[0]["language_indicator_note"]
    assert table[0]["older_people_pct"] == "20"
    assert profile.read_bytes() == original


def test_legacy_geojson_tooltips_and_colours_do_not_imply_known_low_support():
    geojson = {
        "features": [
            {
                "properties": {
                    "sa2_name_2021": "Alpha",
                    "state_name_2021": "Queensland",
                    "language_other_than_english_pct": 0,
                    "language_support_needed": "low",
                    "fill_color": [46, 125, 50, 75],
                },
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }
        ]
    }
    original = copy.deepcopy(geojson)

    filtered = _filter_all_geojson(geojson, "SA2", "Alpha", "Queensland")
    properties = filtered["features"][0]["properties"]

    assert properties["language_support_needed"] == "unknown"
    assert properties["language_other_than_english_pct"] == ""
    assert properties["fill_color"] == [108, 117, 125, 70]
    assert geojson == original  # Never mutate the cached or frozen source object.


def test_newly_enriched_geojson_preserves_verified_indicator_basis():
    module = _script("download_abs_sa2_all")
    row = _national_row(_attributes())
    boundary = {
        "features": [
            {
                "properties": {
                    "sa2_code_2021": "101",
                    "sa2_name_2021": "Alpha",
                    "sa4_name_2021": "Test SA4",
                    "state_name_2021": "Queensland",
                }
            }
        ]
    }

    enriched = module.enrich_geojson(boundary, [row])
    filtered = _filter_all_geojson(enriched, "SA2", "Alpha", "Queensland")
    properties = filtered["features"][0]["properties"]

    assert properties["language_other_than_english_pct"] == 25
    assert properties["language_support_needed"] == "high"
    assert properties["indicator_schema"] == INDICATOR_SCHEMA


def test_unknown_upstream_language_indicator_is_not_coloured_as_low_support():
    module = _script("download_abs_sa2_all")
    row = _national_row(_attributes(**{LANGUAGE_COUNT_FIELD: None}))
    boundary = {"features": [{"properties": {"sa2_code_2021": "101", "sa4_name_2021": "Test SA4"}}]}

    properties = module.enrich_geojson(boundary, [row])["features"][0]["properties"]

    assert properties["language_support_needed"] == "unknown"
    assert properties["fill_color"] == [108, 117, 125, 70]
