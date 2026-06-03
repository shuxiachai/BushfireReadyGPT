import csv
import json
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.data_register import get_data_register
from src.docx_export import create_report_docx
from src.licence_register import licence_register_csv, licence_register_markdown
from src.pdf_export import create_report_pdf


def create_pilot_export_package(report_text, audit_path=None, review_record=None, package_context=None):
    """Create a zip package for pilot review and stakeholder handover."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    context = package_context or {}
    review_record = review_record or {}
    report_markdown = _normalise_report_markdown(report_text)
    file_prefix = _file_prefix(context, timestamp)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app_name": "BushfireReadyGPT",
        "package_schema": "pilot-export-v1",
        "purpose": "Pilot review package for a draft Australian bushfire preparedness report.",
        "safety_boundary": (
            "Preparedness planning support only. Not live emergency advice, not an evacuation order, "
            "and not endorsed by any agency unless separately approved by the responsible organisation."
        ),
        "context": context,
        "review_record": review_record,
        "included_files": [
            f"reports/{file_prefix}.md",
            f"reports/{file_prefix}.pdf",
            f"reports/{file_prefix}.docx",
            "governance/reviewer_signoff.json",
            "governance/data_register.csv",
            "governance/data_register.md",
            "governance/licence_register.csv",
            "governance/licence_register.md",
            "governance/package_manifest.json",
        ],
    }

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as package:
        package.writestr(f"reports/{file_prefix}.md", report_markdown)
        package.writestr(f"reports/{file_prefix}.pdf", create_report_pdf(report_markdown))
        package.writestr(f"reports/{file_prefix}.docx", create_report_docx(report_markdown))
        package.writestr("governance/reviewer_signoff.json", json.dumps(review_record, ensure_ascii=False, indent=2))
        package.writestr("governance/data_register.csv", _data_register_csv())
        package.writestr("governance/data_register.md", _data_register_markdown())
        package.writestr("governance/licence_register.csv", licence_register_csv())
        package.writestr("governance/licence_register.md", licence_register_markdown())
        package.writestr("governance/package_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if audit_path and Path(audit_path).exists():
            package.write(audit_path, "governance/audit_record.json")
            manifest["included_files"].append("governance/audit_record.json")
            package.writestr("governance/package_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buffer.seek(0)
    return {
        "filename": f"{file_prefix}_pilot_export_package.zip",
        "content": buffer.getvalue(),
        "manifest": manifest,
    }


def _normalise_report_markdown(report_text):
    text = report_text or ""
    if text.lstrip().startswith("#"):
        return text
    return f"# BushfireReadyGPT Report\n\n{text.lstrip()}"


def _file_prefix(context, timestamp):
    location = context.get("location") or "bushfire_ready"
    slug = []
    for char in str(location).lower():
        if char.isalnum():
            slug.append(char)
        elif slug and slug[-1] != "_":
            slug.append("_")
    return f"{''.join(slug).strip('_')[:48] or 'bushfire_ready'}_{timestamp}"


def _data_register_csv():
    rows = get_data_register()
    output = StringIO()
    fieldnames = ["name", "provider", "url", "licence", "used_for", "limitations", "local_file_status"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fieldnames})
    return output.getvalue()


def _data_register_markdown():
    lines = [
        "# Data Register",
        "",
        "This register summarises local data sources used by the pilot package. Licence and terms of use must be reviewed before commercial deployment.",
        "",
    ]
    for row in get_data_register():
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
