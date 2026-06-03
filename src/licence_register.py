import csv
from io import StringIO
from pathlib import Path

import yaml


LICENCE_REGISTER_PATH = Path("data_australia/licence_register.yml")


def get_licence_register(path=LICENCE_REGISTER_PATH):
    if not Path(path).exists():
        return {"licence_register": [], "notes": ["Licence register file not found."]}
    with open(path, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return {
        "licence_register": payload.get("licence_register", []),
        "notes": payload.get("notes", []),
    }


def licence_register_rows():
    return get_licence_register().get("licence_register", [])


def licence_register_csv():
    rows = licence_register_rows()
    output = StringIO()
    fieldnames = [
        "id",
        "source_name",
        "provider",
        "source_url",
        "licence_position",
        "commercial_position",
        "attribution_required",
        "caching_position",
        "review_status",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fieldnames})
    return output.getvalue()


def licence_register_markdown():
    payload = get_licence_register()
    lines = [
        "# Licence Register",
        "",
        "This register is a planning aid, not legal advice. Commercial deployment requires source-by-source review.",
        "",
    ]
    for row in payload.get("licence_register", []):
        lines.extend(
            [
                f"## {row.get('source_name')}",
                "",
                f"- Provider: {row.get('provider')}",
                f"- Source URL: {row.get('source_url')}",
                f"- Licence position: {row.get('licence_position')}",
                f"- Commercial position: {row.get('commercial_position')}",
                f"- Attribution required: {row.get('attribution_required')}",
                f"- Caching position: {row.get('caching_position')}",
                f"- Exclusions / risks: {row.get('exclusions_or_risks')}",
                f"- Current project use: {row.get('current_project_use')}",
                f"- Review status: {row.get('review_status')}",
                "",
            ]
        )
    if payload.get("notes"):
        lines.append("## Notes")
        lines.append("")
        for note in payload["notes"]:
            lines.append(f"- {note}")
    return "\n".join(lines)
