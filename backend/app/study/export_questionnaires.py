"""Researcher export of submitted questionnaire responses.

Run from backend/:
    python -m app.study.export_questionnaires --out data/questionnaire-export
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.dependencies import study_service


def _csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def export(out_dir: Path) -> None:
    rows = study_service().export_questionnaire_rows(submitted_only=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "questionnaires.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    csv_path = out_dir / "questionnaires.csv"
    fieldnames = [
        "participant_id",
        "subject",
        "questionnaire_key",
        "scope",
        "version",
        "status",
        "interface_a",
        "interface_b",
        "answers_json",
        "score_json",
        "started_at",
        "updated_at",
        "submitted_at",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            labels = row.get("interface_labels") or {}
            writer.writerow(
                {
                    "participant_id": row["participant_id"],
                    "subject": _csv_cell(row.get("subject")),
                    "questionnaire_key": row["questionnaire_key"],
                    "scope": row["scope"],
                    "version": row["version"],
                    "status": row["status"],
                    "interface_a": _csv_cell(labels.get("A")),
                    "interface_b": _csv_cell(labels.get("B")),
                    "answers_json": _csv_cell(json.dumps(row["answers"])),
                    "score_json": _csv_cell(json.dumps(row["score"]) if row.get("score") is not None else ""),
                    "started_at": row["started_at"],
                    "updated_at": row["updated_at"],
                    "submitted_at": row.get("submitted_at") or "",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export submitted study questionnaires")
    parser.add_argument("--out", default="data/questionnaire-export")
    args = parser.parse_args()
    export(Path(args.out))


if __name__ == "__main__":
    main()
