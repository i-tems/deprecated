from pathlib import Path
from datetime import date
import json
from typing import Any


def read_json(path: Path) -> Any | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_date_files(
    directory: Path,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Path]:
    """Return sorted list of YYYY-MM-DD.json files in directory within the date range."""
    if not directory.exists():
        return []

    files: list[Path] = []
    for f in directory.glob("*.json"):
        stem = f.stem  # e.g. "2026-04-10"
        try:
            file_date = date.fromisoformat(stem)
        except ValueError:
            continue
        if from_date and file_date < from_date:
            continue
        if to_date and file_date > to_date:
            continue
        files.append(f)

    files.sort(key=lambda p: p.stem)
    return files
