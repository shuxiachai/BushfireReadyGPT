from datetime import datetime
from pathlib import Path

from src.data_paths import get_data_paths, safe_data_path_label

DATA_REGISTER = [
    {
        "name": "ABS Data by Region / Digital Atlas SA2 population layer",
        "provider": "Australian Bureau of Statistics",
        "url": "https://geo.abs.gov.au/arcgis/rest/services/Hosted/ABS_Population_and_people_by_2021_SA2_Nov_2023/FeatureServer/1",
        "licence": "Verify ABS conditions of use before commercial deployment",
        "local_files": [
            "data_australia/processed/sa2_profiles_all.csv",
            "data_australia/raw/abs_population_people_sa2_all.json",
        ],
        "used_for": "Community profile indicators including population, older people percentage, and language support needs.",
        "limitations": "Does not provide real-time emergency conditions or no-car household transport vulnerability in the current layer.",
    },
    {
        "name": "ABS ASGS 2021 SA2 boundary layer",
        "provider": "Australian Bureau of Statistics",
        "url": "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SA2/MapServer/0",
        "licence": "Verify ABS conditions of use before commercial deployment",
        "local_files": [
            "data_australia/processed/sa2_boundaries_all.geojson",
            "data_australia/processed/sa2_boundaries_by_state/",
        ],
        "used_for": "Offline SA2/SA3/SA4 map selection and geographic evidence display.",
        "limitations": "SA2/SA3/SA4 statistical areas are not the same as official LGA boundaries.",
    },
    {
        "name": "ABS ASGS Edition 3 allocation and correspondence files",
        "provider": "Australian Bureau of Statistics",
        "url": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files",
        "licence": "Verify ABS conditions of use before commercial deployment",
        "local_files": [
            "data_australia/raw/asgs_allocations/",
            "data_australia/processed/asgs_allocations/sa2_to_sa3_sa4_state_2021.csv",
            "data_australia/processed/asgs_allocations/lga_2025_summary.csv",
            "data_australia/processed/asgs_allocations/lga_2024_to_2025_correspondence.csv",
            "data_australia/processed/asgs_allocations/metadata.json",
        ],
        "used_for": "Official geography hierarchy checks, LGA reference context and data traceability for pilot reports.",
        "limitations": "Allocation files are planning context only; LGA and SA2 boundaries may not align cleanly enough for operational decisions without GIS review.",
    },
    {
        "name": "Australian state and territory official emergency and preparedness sources",
        "provider": "State and territory governments, fire services, local councils (see official_sources.yml for per-source attribution)",
        "url": "https://www.australia.gov.au/about-australia/australian-government/emergency-management",
        "licence": "Terms vary by agency and page; use the page-level licence register and obtain review where reuse is restricted or unclear.",
        "local_files": ["data_australia/official_sources.yml"],
        "used_for": "Official source register for all states and territories. Report verification links for fire services, emergency portals, local councils and Bureau of Meteorology.",
        "limitations": "The app links to official sources but does not issue or verify live warnings, fire bans or evacuation orders.",
    },
    {
        "name": "Bureau of Meteorology warning and data service references",
        "provider": "Bureau of Meteorology",
        "url": "https://www.bom.gov.au/resources/data-services",
        "licence": "Verify BoM copyright and data service terms before commercial use.",
        "local_files": ["data_australia/official_sources.yml"],
        "used_for": "Weather and warning source attribution in preparedness reports.",
        "limitations": "The current app does not ingest live BoM warnings or fire danger ratings.",
    },
    {
        "name": "Optional static official preparedness RAG corpus",
        "provider": "Australian state and territory fire/emergency agencies covering QLD, NSW, VIC, WA, SA, TAS, ACT and NT (see rag/sources.yml)",
        "url": "https://www.qld.gov.au/emergency/dealing-disasters/disaster-types/bushfires",
        "licence": "Reuse terms are tracked per page; restricted or ambiguous entries require permission review before redistribution.",
        "local_files": [
            "data_australia/rag/sources.yml",
            "data_australia/rag/raw/",
            "data_australia/rag/index/",
        ],
        "used_for": "Local hybrid dense + BM25 retrieval of attributed cross-jurisdiction preparedness passages for draft reports.",
        "limitations": "Static planning references only; similarity does not establish currency, correctness, live conditions or operational applicability.",
    },
]


def get_data_register(data_paths=None):
    paths = data_paths or get_data_paths()
    rows = []
    for item in DATA_REGISTER:
        rows.append(
            {
                **item,
                "local_file_status": "; ".join(_file_status(path, paths) for path in item["local_files"]),
            }
        )
    return rows


def _file_status(path, data_paths):
    configured_path = Path(path)
    path_parts = configured_path.parts
    if path_parts and path_parts[0] == "data_australia":
        local_path = data_paths.data_dir.joinpath(*path_parts[1:])
    elif configured_path.is_absolute():
        local_path = configured_path
    else:
        local_path = data_paths.project_root / configured_path
    display_path = safe_data_path_label(local_path, data_paths)
    if not local_path.exists():
        return f"{display_path}: not found"
    if local_path.is_dir():
        file_count = len([item for item in local_path.iterdir() if item.is_file()])
        return f"{display_path}: {file_count} files"
    timestamp = datetime.fromtimestamp(local_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"{display_path}: updated {timestamp}"
