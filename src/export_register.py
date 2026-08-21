"""Frozen data and licence register snapshots for governed exports."""

import csv
import hashlib
from io import StringIO

from src.data_register import get_data_register
from src.licence_register import (
    get_licence_register,
    licence_register_csv,
    licence_register_markdown,
)

REGISTER_SNAPSHOT_FILES = (
    "governance/data_register.csv",
    "governance/data_register.md",
    "governance/licence_register.csv",
    "governance/licence_register.md",
)


class ExportRegisterSnapshotError(ValueError):
    """Raised when a frozen register snapshot is missing or malformed."""


def build_export_register_snapshot():
    """Read each register once and render the exact files frozen with a report."""

    data_rows = get_data_register()
    licence_payload = get_licence_register()
    return {
        "governance/data_register.csv": _data_register_csv(data_rows),
        "governance/data_register.md": _data_register_markdown(data_rows),
        "governance/licence_register.csv": licence_register_csv(licence_payload),
        "governance/licence_register.md": licence_register_markdown(licence_payload),
    }


def canonical_export_register_snapshot(snapshot):
    """Validate and copy the complete, allow-listed export-register snapshot."""

    if not isinstance(snapshot, dict):
        raise ExportRegisterSnapshotError("Export register snapshot must be a dictionary.")
    unknown = sorted(set(snapshot) - set(REGISTER_SNAPSHOT_FILES))
    missing = sorted(set(REGISTER_SNAPSHOT_FILES) - set(snapshot))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unsupported: " + ", ".join(unknown))
        raise ExportRegisterSnapshotError(
            "Export register snapshot has an invalid file set (" + "; ".join(details) + ")."
        )
    canonical = {}
    for path in REGISTER_SNAPSHOT_FILES:
        value = snapshot[path]
        if not isinstance(value, str):
            raise ExportRegisterSnapshotError(f"Export register snapshot file must be text: {path}")
        canonical[path] = value
    return canonical


def export_register_snapshot_hashes(snapshot):
    """Return SHA-256 bindings for every exact frozen register file."""

    canonical = canonical_export_register_snapshot(snapshot)
    return {path: hashlib.sha256(canonical[path].encode("utf-8")).hexdigest() for path in REGISTER_SNAPSHOT_FILES}


def _data_register_csv(rows):
    output = StringIO()
    fieldnames = [
        "name",
        "provider",
        "url",
        "licence",
        "used_for",
        "limitations",
        "local_file_status",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fieldnames})
    return output.getvalue()


def _data_register_markdown(rows):
    lines = [
        "# Data Register",
        "",
        "This register summarises local data sources used by the pilot package. "
        "Licence and terms of use must be reviewed before commercial deployment.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row.get('name')}",
                "",
                f"- Provider: {row.get('provider')}",
                f"- URL: {row.get('url')}",
                f"- Licence position: {row.get('licence')}",
                f"- Used for: {row.get('used_for')}",
                f"- Limitations: {row.get('limitations')}",
                f"- Local file status: {row.get('local_file_status')}",
                "",
            ]
        )
    return "\n".join(lines)
