"""Download and transactionally publish the optional Australia-wide SA2 map."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_artifacts import (  # noqa: E402
    atomic_publish_files,
    download_url_bytes,
    recover_atomic_publish,
    sha256_file,
)
from src.data_paths import get_data_paths  # noqa: E402

ABS_PROFILE_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_Population_and_people_by_2021_SA2_Nov_2023/FeatureServer/1/query"
)
ABS_SA2_BOUNDARY_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SA2/MapServer/0/query"
POPULATION_FIELD = "erp_p_202022"
OLDER_COUNT_FIELDS = ["erp_p_152022", "erp_p_162022", "erp_p_172022", "erp_p_182022", "erp_p_192022"]
LANGUAGE_COUNT_FIELD = "census_392021"
PAGE_SIZE = 2000
MAX_PAGES = 100


def resolve_paths(data_dir=None):
    root = Path(data_dir or get_data_paths().data_dir).expanduser().resolve()
    raw = root / "raw"
    processed = root / "processed"
    return root, {
        "raw_profile": raw / "abs_population_people_sa2_all.json",
        "raw_boundary": raw / "abs_sa2_boundaries_all.geojson",
        "profile": processed / "sa2_profiles_all.csv",
        "boundary": processed / "sa2_boundaries_all.geojson",
        "states": processed / "sa2_boundaries_by_state",
        "metadata": processed / "sa2_map_bundle.json",
    }


def number(value):
    if value in {None, ""}:
        return 0.0
    return float(value)


def download_paged_json(base_url, params, feature_collection=False):
    features = []
    template = None
    for page_number in range(MAX_PAGES):
        page_params = {
            **params,
            "resultRecordCount": str(PAGE_SIZE),
            "resultOffset": str(page_number * PAGE_SIZE),
        }
        url = f"{base_url}?{urlencode(page_params)}"
        raw = download_url_bytes(
            url,
            timeout=60,
            attempts=3,
            max_bytes=256 * 1024 * 1024,
        )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("ABS returned an invalid JSON page.") from error
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(
                f"ABS returned an API error: {payload.get('error') if isinstance(payload, dict) else payload}"
            )
        page_features = payload.get("features")
        if not isinstance(page_features, list):
            raise ValueError("ABS page has no valid features list.")
        if page_number == 0 and not page_features:
            raise ValueError("ABS layer contains no features; existing files were preserved.")
        if template is None:
            template = {key: value for key, value in payload.items() if key != "features"}
        features.extend(page_features)
        if len(page_features) < PAGE_SIZE:
            break
    else:
        raise ValueError("ABS pagination exceeded the safety limit.")

    result = template or {}
    result["features"] = features
    result["_downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["_source_url"] = base_url
    result["_feature_count"] = len(features)
    if feature_collection:
        if result.get("type") not in {None, "FeatureCollection"}:
            raise ValueError("ABS boundary response is not a GeoJSON FeatureCollection.")
        result["type"] = "FeatureCollection"
    return result


def load_official_layers():
    profile_fields = [
        "sa2_code_2021",
        "sa2_name_2021",
        POPULATION_FIELD,
        LANGUAGE_COUNT_FIELD,
        *OLDER_COUNT_FIELDS,
    ]
    profile = download_paged_json(
        ABS_PROFILE_URL,
        {
            "f": "json",
            "where": "1=1",
            "outFields": ",".join(profile_fields),
            "returnGeometry": "false",
        },
    )
    boundary = download_paged_json(
        ABS_SA2_BOUNDARY_URL,
        {
            "f": "geojson",
            "where": "1=1",
            "outFields": (
                "sa2_code_2021,sa2_name_2021,sa3_code_2021,sa3_name_2021,"
                "sa4_code_2021,sa4_name_2021,state_code_2021,state_name_2021"
            ),
            "returnGeometry": "true",
            "outSR": "4326",
        },
        feature_collection=True,
    )
    return profile, boundary


def validate_layers(profile_payload, boundary_payload):
    required_profile = {
        "sa2_code_2021",
        "sa2_name_2021",
        POPULATION_FIELD,
        LANGUAGE_COUNT_FIELD,
        *OLDER_COUNT_FIELDS,
    }
    profile_codes = []
    for feature in profile_payload.get("features", []):
        if not isinstance(feature, dict) or not isinstance(feature.get("attributes"), dict):
            raise ValueError("ABS profile layer contains an invalid feature.")
        values = feature["attributes"]
        if not required_profile.issubset(values):
            raise ValueError("ABS profile layer is missing required columns.")
        code = str(values.get("sa2_code_2021", "")).strip()
        if not code or not str(values.get("sa2_name_2021", "")).strip():
            raise ValueError("ABS profile layer contains an empty SA2 ID or name.")
        profile_codes.append(code)

    required_boundary = {
        "sa2_code_2021",
        "sa2_name_2021",
        "sa3_code_2021",
        "sa3_name_2021",
        "sa4_code_2021",
        "sa4_name_2021",
        "state_code_2021",
        "state_name_2021",
    }
    boundary_codes = []
    spatial_feature_count = 0
    for feature in boundary_payload.get("features", []):
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise ValueError("ABS boundary layer contains an invalid GeoJSON feature.")
        geometry = feature.get("geometry")
        if geometry is not None:
            if (
                not isinstance(geometry, dict)
                or not str(geometry.get("type", "")).strip()
                or not isinstance(geometry.get("coordinates"), list)
                or not geometry["coordinates"]
            ):
                raise ValueError("ABS boundary layer contains invalid geometry.")
            spatial_feature_count += 1
        values = feature["properties"]
        if not required_boundary.issubset(values) or any(
            not str(values.get(field, "")).strip() for field in required_boundary
        ):
            raise ValueError("ABS boundary layer contains an incomplete ASGS hierarchy.")
        boundary_codes.append(str(values["sa2_code_2021"]).strip())

    if not profile_codes or not boundary_codes:
        raise ValueError("ABS layers contain no SA2 records.")
    if not spatial_feature_count:
        raise ValueError("ABS boundary layer contains no spatial SA2 features.")
    if len(set(profile_codes)) != len(profile_codes):
        raise ValueError("ABS profile layer contains duplicate SA2 IDs.")
    if len(set(boundary_codes)) != len(boundary_codes):
        raise ValueError("ABS boundary layer contains duplicate SA2 IDs.")
    missing_profile = set(boundary_codes) - set(profile_codes)
    missing_boundary = set(profile_codes) - set(boundary_codes)
    if missing_profile or missing_boundary:
        raise ValueError(
            "ABS profile/boundary SA2 join is incomplete "
            f"({len(missing_profile)} missing profiles; {len(missing_boundary)} missing boundaries)."
        )


def support_level(language_pct):
    if language_pct >= 20:
        return "high"
    if language_pct >= 8:
        return "medium"
    return "low"


def build_profiles(profile_payload, boundary_payload):
    profile_by_code = {
        str(feature["attributes"]["sa2_code_2021"]): feature["attributes"] for feature in profile_payload["features"]
    }
    rows = []
    for feature in boundary_payload["features"]:
        props = feature["properties"]
        sa2_code = str(props["sa2_code_2021"])
        attrs = profile_by_code[sa2_code]
        population = number(attrs.get(POPULATION_FIELD))
        older_count = sum(number(attrs.get(field)) for field in OLDER_COUNT_FIELDS)
        language_count = number(attrs.get(LANGUAGE_COUNT_FIELD))
        older_pct = round(older_count / population * 100, 1) if population else ""
        language_pct = round(language_count / population * 100, 1) if population else ""
        rows.append(
            {
                "state_name": props["state_name_2021"],
                "state_code": props["state_code_2021"],
                "sa4_name": props["sa4_name_2021"],
                "sa4_code": props["sa4_code_2021"],
                "sa3_name": props["sa3_name_2021"],
                "sa3_code": props["sa3_code_2021"],
                "sa2_name": props["sa2_name_2021"],
                "sa2_code": sa2_code,
                "population": int(population) if population else "",
                "older_people_count": int(older_count) if older_count else "",
                "older_people_pct": older_pct,
                "language_other_than_english_count": int(language_count) if language_count else "",
                "language_other_than_english_pct": language_pct,
                "language_support_needed": support_level(language_pct) if population else "unknown",
                "source": "ABS Data by Region / Digital Atlas SA2 population and ASGS 2021 SA2 boundary layers",
                "source_years": "2021 Census and 2022 ERP fields",
            }
        )
    return rows


def enrich_geojson(boundary_payload, rows):
    row_by_code = {row["sa2_code"]: row for row in rows}
    for feature in boundary_payload["features"]:
        props = feature["properties"]
        row = row_by_code[str(props["sa2_code_2021"])]
        props["population"] = row["population"]
        props["older_people_pct"] = row["older_people_pct"]
        props["language_other_than_english_pct"] = row["language_other_than_english_pct"]
        props["language_support_needed"] = row["language_support_needed"]
        props["mapped_location"] = props["sa4_name_2021"]
        level = row["language_support_needed"]
        props["fill_color"] = (
            [180, 61, 31, 85] if level == "high" else [35, 117, 150, 85] if level == "medium" else [46, 125, 50, 75]
        )
        props["line_color"] = [24, 33, 47, 180]
    return boundary_payload


def slugify(value):
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def write_json(path, payload, *, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=indent)
        file.write("\n")


def write_profiles(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def stage_bundle(staging_dir, profile_payload, boundary_payload, rows):
    staged = {}
    raw_profile = staging_dir / "raw_profile.json"
    raw_boundary = staging_dir / "raw_boundary.geojson"
    profile = staging_dir / "profiles.csv"
    boundary = staging_dir / "boundaries.geojson"
    write_json(raw_profile, profile_payload, indent=2)
    write_json(raw_boundary, boundary_payload, indent=2)
    write_profiles(profile, rows)
    write_json(boundary, boundary_payload)
    staged.update(raw_profile=raw_profile, raw_boundary=raw_boundary, profile=profile, boundary=boundary)

    states_dir = staging_dir / "states"
    features_by_state = {}
    for feature in boundary_payload["features"]:
        state_name = feature["properties"]["state_name_2021"]
        features_by_state.setdefault(state_name, []).append(feature)
    state_paths = {}
    for state_name, features in features_by_state.items():
        state_path = states_dir / f"{slugify(state_name)}.geojson"
        write_json(state_path, {**boundary_payload, "features": features})
        state_paths[state_name] = state_path
    return staged, state_paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Data root (defaults to BUSHFIRE_DATA_DIR).")
    args = parser.parse_args(argv)
    data_dir, paths = resolve_paths(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    recover_atomic_publish(data_dir, transaction_name="abs-sa2-national-map")
    profile_payload, boundary_payload = load_official_layers()
    validate_layers(profile_payload, boundary_payload)
    rows = build_profiles(profile_payload, boundary_payload)
    if len(rows) != len(profile_payload["features"]):
        raise ValueError("Processed SA2 row count does not match the validated ID join.")
    enriched = enrich_geojson(boundary_payload, rows)

    with tempfile.TemporaryDirectory(prefix=".sa2-map-validate-", dir=data_dir) as temporary:
        staging_dir = Path(temporary)
        staged, state_paths = stage_bundle(staging_dir, profile_payload, enriched, rows)
        files = {
            paths["raw_profile"]: staged["raw_profile"],
            paths["raw_boundary"]: staged["raw_boundary"],
            paths["profile"]: staged["profile"],
            paths["boundary"]: staged["boundary"],
        }
        expected_state_targets = set()
        for state_name, staged_path in state_paths.items():
            target = paths["states"] / f"{slugify(state_name)}.geojson"
            expected_state_targets.add(target.resolve())
            files[target] = staged_path

        metadata_path = staging_dir / "metadata.json"
        metadata = {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "profile_rows": len(rows),
            "boundary_features": len(enriched["features"]),
            "shared_sa2_codes": len(rows),
            "artifacts": {
                "profile": {"sha256": sha256_file(staged["profile"]), "size_bytes": staged["profile"].stat().st_size},
                "boundary": {
                    "sha256": sha256_file(staged["boundary"]),
                    "size_bytes": staged["boundary"].stat().st_size,
                },
            },
        }
        write_json(metadata_path, metadata, indent=2)
        files[paths["metadata"]] = metadata_path
        stale_states = (
            {
                path.resolve()
                for path in paths["states"].glob("*.geojson")
                if path.resolve() not in expected_state_targets
            }
            if paths["states"].is_dir()
            else set()
        )
        atomic_publish_files(
            files,
            transaction_root=data_dir,
            transaction_name="abs-sa2-national-map",
            remove_paths=stale_states,
        )

    print(f"Raw all-Australia SA2 profile data saved: {paths['raw_profile']}")
    print(f"Raw all-Australia SA2 boundaries saved: {paths['raw_boundary']}")
    print(f"Processed all-Australia SA2 profiles saved: {paths['profile']}")
    print(f"Processed all-Australia SA2 boundaries saved: {paths['boundary']}")
    print(f"State SA2 boundary files saved: {paths['states']}")
    print(f"SA2 rows: {len(rows)}")


if __name__ == "__main__":
    main()
