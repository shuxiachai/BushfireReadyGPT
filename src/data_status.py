import csv
import json
from datetime import datetime
from pathlib import Path


COMMUNITY_PROCESSED_PATH = Path("data_australia/processed/community_profiles.csv")
COMMUNITY_SAMPLE_PATH = Path("data_australia/community_profile_sample.csv")
ABS_RAW_PATH = Path("data_australia/raw/abs_population_people_sa2_qld_subset.json")
ASGS_METADATA_PATH = Path("data_australia/processed/asgs_allocations/metadata.json")


def _format_timestamp(path):
    if not path.exists():
        return "Not available"
    timestamp = datetime.fromtimestamp(path.stat().st_mtime)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _read_csv_rows(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def get_community_data_status():
    active_path = COMMUNITY_PROCESSED_PATH if COMMUNITY_PROCESSED_PATH.exists() else COMMUNITY_SAMPLE_PATH
    rows = _read_csv_rows(active_path)
    raw_metadata = {}
    asgs_metadata = {}

    if ABS_RAW_PATH.exists():
        try:
            raw_payload = json.loads(ABS_RAW_PATH.read_text(encoding="utf-8"))
            raw_metadata = {
                "downloaded_at_utc": raw_payload.get("_downloaded_at_utc", "Not recorded"),
                "source_query_url": raw_payload.get("_source_query_url", ""),
            }
        except json.JSONDecodeError:
            raw_metadata = {"downloaded_at_utc": "Raw file could not be parsed", "source_query_url": ""}

    if ASGS_METADATA_PATH.exists():
        try:
            asgs_metadata = json.loads(ASGS_METADATA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            asgs_metadata = {"generated_at_utc": "Metadata file could not be parsed", "sources": {}}

    asgs_sources = asgs_metadata.get("sources", {})

    return {
        "active_path": str(active_path),
        "active_type": "ABS processed data" if active_path == COMMUNITY_PROCESSED_PATH else "Sample fallback data",
        "active_exists": active_path.exists(),
        "row_count": len(rows),
        "locations": [row.get("location", "") for row in rows if row.get("location")],
        "mapping_summary": [
            {
                "location": row.get("location", ""),
                "population": row.get("population", ""),
                "matched_sa2_count": row.get("matched_sa2_count", ""),
                "geography_type": row.get("geography_type", ""),
            }
            for row in rows
        ],
        "updated_at": _format_timestamp(active_path),
        "raw_path": str(ABS_RAW_PATH),
        "raw_exists": ABS_RAW_PATH.exists(),
        "raw_updated_at": _format_timestamp(ABS_RAW_PATH),
        "downloaded_at_utc": raw_metadata.get("downloaded_at_utc", "Not available"),
        "source_query_url": raw_metadata.get("source_query_url", ""),
        "asgs_metadata_path": str(ASGS_METADATA_PATH),
        "asgs_exists": ASGS_METADATA_PATH.exists(),
        "asgs_updated_at": _format_timestamp(ASGS_METADATA_PATH),
        "asgs_generated_at_utc": asgs_metadata.get("generated_at_utc", "Not available"),
        "asgs_row_counts": {
            key: value.get("row_count", 0) for key, value in asgs_sources.items()
        },
        "limitations": [
            "Current processed rows are keyword-matched SA2 subsets, not complete Local Government Area profiles.",
            "The current ABS population-and-people layer does not include no-car household percentage, so transport vulnerability must be verified separately.",
            "ASGS allocation and correspondence files improve official geography traceability, but they are not live emergency data.",
            "This data supports planning context only and does not replace live warnings, evacuation orders, or official emergency instructions.",
        ],
    }
