import json
import os
from datetime import datetime
from pathlib import Path


AUDIT_DIR = Path("chat_history/audit")


def save_report_audit(payload):
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    location_slug = _slugify(payload.get("inputs", {}).get("location", "unknown"))
    output_path = AUDIT_DIR / f"audit_{timestamp}_{location_slug}.json"
    audit_payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app_name": "BushfireReadyGPT",
        "audit_schema": "government-pilot-v1",
        **payload,
    }
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(audit_payload, file, ensure_ascii=False, indent=2)
    return str(output_path)


def _slugify(value):
    cleaned = []
    for char in str(value).lower():
        if char.isalnum():
            cleaned.append(char)
        elif cleaned and cleaned[-1] != "_":
            cleaned.append("_")
    return "".join(cleaned).strip("_")[:80] or "unknown"
