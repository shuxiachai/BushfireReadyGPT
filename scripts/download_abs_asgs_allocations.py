"""Download and transactionally publish validated ABS ASGS reference files."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from defusedxml import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_artifacts import (  # noqa: E402
    BUNDLED_CORE_TRANSACTION_NAME,
    atomic_publish_files,
    download_url_bytes,
    recover_atomic_publish,
    render_updated_manifest,
    sha256_file,
    validate_data_manifest,
)
from src.data_paths import get_data_paths  # noqa: E402

SOURCES = {
    "sa2_allocation_2021": {
        "url": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files/SA2_2021_AUST.xlsx",
        "raw_file": "SA2_2021_AUST.xlsx",
        "processed_file": "sa2_to_sa3_sa4_state_2021.csv",
        "description": "ABS ASGS Edition 3 SA2 allocation hierarchy.",
    },
    "lga_allocation_2025": {
        "url": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files/LGA_2025_AUST.xlsx",
        "raw_file": "LGA_2025_AUST.xlsx",
        "processed_file": "lga_2025_summary.csv",
        "description": "ABS ASGS Edition 3 Local Government Area allocation file.",
    },
    "lga_2024_to_2025_correspondence": {
        "url": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/correspondences/CG_LGA_2024_LGA_2025.csv",
        "raw_file": "CG_LGA_2024_LGA_2025.csv",
        "processed_file": "lga_2024_to_2025_correspondence.csv",
        "description": "ABS correspondence for converting 2024 LGAs to 2025 LGAs.",
    },
}
XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAX_XLSX_MEMBERS = 1000
MAX_XLSX_MEMBER_BYTES = 200 * 1024 * 1024
MAX_XLSX_TOTAL_BYTES = 256 * 1024 * 1024


def resolve_paths(data_dir=None):
    root = Path(data_dir or get_data_paths().data_dir).expanduser().resolve()
    return root, root / "raw" / "asgs_allocations", root / "processed" / "asgs_allocations"


def column_index(cell_reference):
    value = 0
    for char in (char for char in cell_reference if char.isalpha()):
        value = value * 26 + ord(char.upper()) - ord("A") + 1
    return value - 1


def cell_value(cell, shared_strings):
    value_node = cell.find("a:v", XLSX_NS)
    inline_node = cell.find("a:is/a:t", XLSX_NS)
    if inline_node is not None:
        return inline_node.text or ""
    if value_node is None:
        return ""
    value = value_node.text or ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(value)]
    return value


def read_xlsx_first_sheet(path):
    try:
        with zipfile.ZipFile(path) as workbook:
            members = workbook.infolist()
            if (
                len(members) > MAX_XLSX_MEMBERS
                or any(member.file_size > MAX_XLSX_MEMBER_BYTES for member in members)
                or sum(member.file_size for member in members) > MAX_XLSX_TOTAL_BYTES
            ):
                raise ValueError("Downloaded XLSX exceeds safe archive expansion limits.")
            bad_member = workbook.testzip()
            if bad_member:
                raise ValueError(f"XLSX archive has a corrupt member: {bad_member}")
            required_members = {"xl/worksheets/sheet1.xml", "[Content_Types].xml"}
            if not required_members.issubset(workbook.namelist()):
                raise ValueError("Downloaded file is not a supported XLSX workbook.")
            shared_strings = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                for item in root.findall("a:si", XLSX_NS):
                    shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", XLSX_NS)))
            sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError) as error:
        raise ValueError(f"Downloaded XLSX could not be parsed: {path.name}") from error
    rows = []
    for row_node in sheet_root.findall(".//a:sheetData/a:row", XLSX_NS):
        row = []
        for cell in row_node.findall("a:c", XLSX_NS):
            index = column_index(cell.attrib.get("r", "A1"))
            while len(row) <= index:
                row.append("")
            row[index] = cell_value(cell, shared_strings)
        if any(value != "" for value in row):
            rows.append(row)
    if len(rows) < 2:
        raise ValueError(f"Downloaded XLSX contains no data rows: {path.name}")
    return rows


def normalise_header(value):
    return re.sub(r"\s+", "_", value.strip()).lower()


def rows_to_dicts(rows):
    headers = [normalise_header(value) for value in rows[0]]
    if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
        raise ValueError("Downloaded workbook has invalid or duplicate column headings.")
    records = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        records.append({header: padded[index] for index, header in enumerate(headers)})
    return records


def download_bytes(url):
    return download_url_bytes(url, timeout=120, attempts=3, max_bytes=64 * 1024 * 1024)


def process_sa2_allocation(path):
    records = rows_to_dicts(read_xlsx_first_sheet(path))
    fields = [
        "sa2_code_2021",
        "sa2_name_2021",
        "sa3_code_2021",
        "sa3_name_2021",
        "sa4_code_2021",
        "sa4_name_2021",
        "gccsa_code_2021",
        "gccsa_name_2021",
        "state_code_2021",
        "state_name_2021",
        "area_albers_sqkm",
        "asgs_loci_uri_2021",
    ]
    if not records or not set(fields).issubset(records[0]):
        raise ValueError("SA2 allocation workbook is missing required ASGS columns.")
    rows = [{field: record.get(field, "") for field in fields} for record in records]
    codes = [row["sa2_code_2021"].strip() for row in rows]
    if any(not code for code in codes) or len(set(codes)) != len(codes):
        raise ValueError("SA2 allocation contains empty or duplicate SA2 codes.")
    if any(not row["sa3_code_2021"] or not row["sa4_code_2021"] or not row["state_code_2021"] for row in rows):
        raise ValueError("SA2 allocation contains an incomplete hierarchy join.")
    return rows


def process_lga_allocation(path):
    records = rows_to_dicts(read_xlsx_first_sheet(path))
    required = {"lga_code_2025", "lga_name_2025", "state_code_2021", "state_name_2021"}
    if not records or not required.issubset(records[0]):
        raise ValueError("LGA allocation workbook is missing required ASGS columns.")
    grouped = {}
    for record in records:
        code = record.get("lga_code_2025", "").strip()
        if not code:
            continue
        item = grouped.setdefault(
            code,
            {
                "lga_code_2025": code,
                "lga_name_2025": record.get("lga_name_2025", ""),
                "state_code_2021": record.get("state_code_2021", ""),
                "state_name_2021": record.get("state_name_2021", ""),
                "mesh_block_count": 0,
                "area_albers_sqkm": 0.0,
            },
        )
        item["mesh_block_count"] += 1
        try:
            item["area_albers_sqkm"] += float(record.get("area_albers_sqkm", "") or 0)
        except ValueError as error:
            raise ValueError(f"LGA {code} has an invalid area value.") from error
    if not grouped:
        raise ValueError("LGA allocation contains no usable LGA rows.")
    rows = [{**item, "area_albers_sqkm": round(item["area_albers_sqkm"], 4)} for item in grouped.values()]
    return sorted(rows, key=lambda row: (row["state_name_2021"], row["lga_name_2025"]))


def process_lga_correspondence(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required = {"LGA_CODE_2024", "LGA_CODE_2025", "RATIO_FROM_TO"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("LGA correspondence CSV is missing required columns.")
            rows = list(reader)
    except (UnicodeError, csv.Error) as error:
        raise ValueError("LGA correspondence CSV could not be parsed.") from error
    if not rows or any(not row["LGA_CODE_2024"] or not row["LGA_CODE_2025"] for row in rows):
        raise ValueError("LGA correspondence CSV contains no valid ID joins.")
    return rows


def validate_processed_joins(processed):
    allocation_codes = {row["lga_code_2025"] for row in processed["lga_allocation_2025"]}
    correspondence_codes = {row["LGA_CODE_2025"] for row in processed["lga_2024_to_2025_correspondence"]}
    if allocation_codes != correspondence_codes:
        raise ValueError(
            "LGA allocation/correspondence ID sets differ "
            f"({len(correspondence_codes - allocation_codes)} correspondence-only; "
            f"{len(allocation_codes - correspondence_codes)} allocation-only)."
        )


def csv_bytes(rows):
    if not rows:
        raise ValueError("Refusing to publish an empty processed CSV.")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def metadata_payload(data_dir, raw_dir, processed_dir, row_counts):
    def relative(path):
        return path.relative_to(data_dir).as_posix()

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_page": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files",
        "correspondence_page": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/correspondences",
        "sources": {
            key: {
                "description": source["description"],
                "url": source["url"],
                "raw_file": relative(raw_dir / source["raw_file"]),
                "processed_file": relative(processed_dir / source["processed_file"]),
                "row_count": row_counts[key],
            }
            for key, source in SOURCES.items()
        },
        "limitations": [
            "Allocation files provide statistical geography context; they are not live emergency data.",
            "LGA allocation is mesh-block based and boundary decisions still require human GIS review.",
            "Correspondence ratios must not be treated as current fire-risk evidence.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Data root (defaults to BUSHFIRE_DATA_DIR).")
    args = parser.parse_args(argv)
    data_dir, raw_dir, processed_dir = resolve_paths(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    recover_atomic_publish(data_dir, transaction_name=BUNDLED_CORE_TRANSACTION_NAME)
    validate_data_manifest(data_dir / "manifest.json", data_dir=data_dir)
    base_manifest_sha256 = sha256_file(data_dir / "manifest.json")

    raw_payloads = {key: download_bytes(source["url"]) for key, source in SOURCES.items()}
    with tempfile.TemporaryDirectory(prefix=".asgs-validate-", dir=data_dir) as temporary:
        temporary_dir = Path(temporary)
        downloaded = {}
        for key, source in SOURCES.items():
            path = temporary_dir / source["raw_file"]
            path.write_bytes(raw_payloads[key])
            downloaded[key] = path
        processed = {
            "sa2_allocation_2021": process_sa2_allocation(downloaded["sa2_allocation_2021"]),
            "lga_allocation_2025": process_lga_allocation(downloaded["lga_allocation_2025"]),
            "lga_2024_to_2025_correspondence": process_lga_correspondence(
                downloaded["lga_2024_to_2025_correspondence"]
            ),
        }
        validate_processed_joins(processed)

    row_counts = {key: len(rows) for key, rows in processed.items()}
    files = {raw_dir / source["raw_file"]: raw_payloads[key] for key, source in SOURCES.items()}
    processed_payloads = {key: csv_bytes(rows) for key, rows in processed.items()}
    files.update(
        {processed_dir / SOURCES[key]["processed_file"]: payload for key, payload in processed_payloads.items()}
    )
    metadata = metadata_payload(data_dir, raw_dir, processed_dir, row_counts)
    metadata_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files[processed_dir / "metadata.json"] = metadata_bytes
    manifest_path = data_dir / "manifest.json"
    generated_at = metadata["generated_at_utc"]
    manifest_updates = {
        f"processed/asgs_allocations/{SOURCES[key]['processed_file']}": {
            "data": processed_payloads[key],
            "row_count": row_counts[key],
        }
        for key in processed
    }
    manifest_updates["processed/asgs_allocations/metadata.json"] = {"data": metadata_bytes}
    files[manifest_path] = render_updated_manifest(
        manifest_path,
        manifest_updates,
        generated_at_utc=generated_at,
    )
    if sha256_file(manifest_path) != base_manifest_sha256:
        raise RuntimeError("Data manifest changed while the download was being prepared.")
    atomic_publish_files(
        files,
        transaction_root=data_dir,
        transaction_name=BUNDLED_CORE_TRANSACTION_NAME,
        expected_current_hashes={manifest_path: base_manifest_sha256},
    )
    for key, rows in processed.items():
        print(f"Processed {key}: {processed_dir / SOURCES[key]['processed_file']} ({len(rows)} rows)")
    print(f"Metadata saved: {processed_dir / 'metadata.json'}")


if __name__ == "__main__":
    main()
