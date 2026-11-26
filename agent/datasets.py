"""Validate all samples before a potentially paid API call."""

from __future__ import annotations

import json
from pathlib import Path


def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    ids: set[str] = set()
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"{path}: invalid JSON at line {number}") from None
            if not isinstance(record, dict):
                raise ValueError(f"{path}: line {number} must be an object")
            for key in ("id", "text"):
                if not isinstance(record.get(key), str) or not record[key].strip():
                    raise ValueError(f"{path}: line {number} requires non-empty {key}")
            if record["id"] in ids:
                raise ValueError(f"{path}: duplicate sample id at line {number}")
            ids.add(record["id"])
            records.append(record)
    if not records:
        raise ValueError(f"{path}: dataset is empty")
    return records


def select_record(path: Path, record_id: str) -> dict:
    for record in load_records(path):
        if record["id"] == record_id:
            return record
    raise ValueError(f"sample id not found: {record_id}")
