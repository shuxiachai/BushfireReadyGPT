"""Offline image smoke checks; use only on a disposable CI/demo-test volume."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pypdf import PdfReader  # noqa: E402

from src.container_runtime import prepare_runtime  # noqa: E402
from src.data_artifacts import atomic_write_json  # noqa: E402
from src.model_limits import acquire_model_slot, load_model_limits  # noqa: E402
from src.pdf_export import create_report_pdf  # noqa: E402
from src.runtime_paths import runtime_path  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("first", "restart"), required=True)
    args = parser.parse_args()
    if os.environ.get("BUSHFIRE_CONTAINER_SMOKE") != "true":
        raise RuntimeError("Smoke checks require BUSHFIRE_CONTAINER_SMOKE=true and a disposable volume.")
    if os.getuid() == 0:
        raise RuntimeError("The application smoke checks must run as the non-root worker.")
    ready = prepare_runtime()
    manifest = Path(os.environ["BUSHFIRE_RAG_INDEX_DIR"]) / "manifest.json"
    identity = {"manifest_sha256": ready["rag"]["manifest_sha256"], "mtime_ns": manifest.stat().st_mtime_ns}
    sentinel = runtime_path("container-smoke.json")
    if args.phase == "first":
        if sentinel.exists():
            raise RuntimeError("The smoke volume is not fresh.")
        atomic_write_json(sentinel, identity)
    elif json.loads(sentinel.read_text(encoding="utf-8")) != identity:
        raise RuntimeError("A restart lost persistent data or overwrote the existing RAG version.")
    pdf = create_report_pdf("# Container export check\n\n**Reviewer: 测试审核员**\n\n学校防火准备。")
    extracted = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    if "测试审核员" not in extracted or "学校防火准备" not in extracted:
        raise RuntimeError("The image cannot export readable Chinese reviewer text.")
    # Exercise the real persistent quota without sending any model/network request.
    slot = acquire_model_slot()
    try:
        slot.consume_call()
    finally:
        slot.release()
    today = datetime.now(timezone.utc).date().isoformat()
    with closing(sqlite3.connect(load_model_limits().database)) as connection:
        calls = connection.execute("SELECT calls FROM daily_calls WHERE day = ?", (today,)).fetchone()[0]
    expected = 1 if args.phase == "first" else 2
    if calls != expected:
        raise RuntimeError("The daily model-call counter did not persist across container restarts.")
    print(json.dumps({"smoke": "passed", "phase": args.phase, "uid": os.getuid(), "rag": ready["rag"]}))


if __name__ == "__main__":
    main()
