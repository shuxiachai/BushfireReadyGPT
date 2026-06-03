"""Download and process ABS ASGS allocation/correspondence files.

The app already uses ABS SA2 boundaries for map selection. This script adds a
stable official geography reference layer so pilot reports can show where SA2,
SA3, SA4, State and LGA source files came from.
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlretrieve


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data_australia" / "raw" / "asgs_allocations"
PROCESSED_DIR = PROJECT_ROOT / "data_australia" / "processed" / "asgs_allocations"

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


def column_index(cell_reference: str) -> int:
    letters = "".join(char for char in cell_reference if char.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + (ord(char.upper()) - ord("A") + 1)
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


def read_xlsx_first_sheet(path: Path):
    with zipfile.ZipFile(path) as workbook:
        shared_strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", XLSX_NS):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", XLSX_NS)))

        sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
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
        return rows


def normalise_header(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip()).lower()


def rows_to_dicts(rows):
    if not rows:
        return []
    headers = [normalise_header(value) for value in rows[0]]
    records = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        records.append({header: padded[index] for index, header in enumerate(headers)})
    return records


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def download_sources():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = {}
    for key, source in SOURCES.items():
        output_path = RAW_DIR / source["raw_file"]
        urlretrieve(source["url"], output_path)
        downloaded[key] = output_path
    return downloaded


def process_sa2_allocation(path: Path):
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
    return [{field: record.get(field, "") for field in fields} for record in records]


def process_lga_allocation(path: Path):
    records = rows_to_dicts(read_xlsx_first_sheet(path))
    grouped = {}
    for record in records:
        code = record.get("lga_code_2025", "")
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
        except ValueError:
            pass

    rows = []
    for item in grouped.values():
        rows.append(
            {
                **item,
                "area_albers_sqkm": round(item["area_albers_sqkm"], 4),
            }
        )
    return sorted(rows, key=lambda row: (row["state_name_2021"], row["lga_name_2025"]))


def process_lga_correspondence(path: Path):
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_metadata(row_counts):
    def relative(path: Path) -> str:
        return path.relative_to(PROJECT_ROOT).as_posix()

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_page": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/allocation-files",
        "correspondence_page": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/correspondences",
        "sources": {
            key: {
                "description": source["description"],
                "url": source["url"],
                "raw_file": relative(RAW_DIR / source["raw_file"]),
                "processed_file": relative(PROCESSED_DIR / source["processed_file"]),
                "row_count": row_counts.get(key, 0),
            }
            for key, source in SOURCES.items()
        },
        "limitations": [
            "Allocation files provide official statistical geography hierarchy or mesh-block allocation context; they are not live emergency data.",
            "LGA allocation is mesh-block based. Direct SA2-to-LGA operational decisions still require human GIS review where boundaries do not align cleanly.",
            "Correspondence ratios help convert historical LGA boundaries but should not be treated as current fire-risk evidence.",
        ],
    }
    (PROCESSED_DIR / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = download_sources()

    processed = {
        "sa2_allocation_2021": process_sa2_allocation(downloaded["sa2_allocation_2021"]),
        "lga_allocation_2025": process_lga_allocation(downloaded["lga_allocation_2025"]),
        "lga_2024_to_2025_correspondence": process_lga_correspondence(downloaded["lga_2024_to_2025_correspondence"]),
    }

    row_counts = {}
    for key, rows in processed.items():
        output_path = PROCESSED_DIR / SOURCES[key]["processed_file"]
        write_csv(output_path, rows)
        row_counts[key] = len(rows)
        print(f"Processed {key}: {output_path} ({len(rows)} rows)")

    write_metadata(row_counts)
    print(f"Metadata saved: {PROCESSED_DIR / 'metadata.json'}")


if __name__ == "__main__":
    main()
