"""Output helpers: data-directory resolution and CSV/JSON writers."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from typing import Any, Sequence

DATA_DIR = os.environ.get("DATA_DIR", "data")


def default_output_path(filename: str) -> str:
    """Resolve a default output filename inside DATA_DIR, creating the dir."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, filename)


def write_csv(path: str, records: Sequence[Any], fields: list[str]) -> None:
    """Write dataclass records to CSV using the given field order."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))


def write_json(path: str, records: Sequence[Any]) -> None:
    """Write dataclass records to a pretty-printed JSON array."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2, ensure_ascii=False)
