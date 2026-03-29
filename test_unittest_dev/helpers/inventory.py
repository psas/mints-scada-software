from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _extract_ids_from_obj(obj: Any, output: set[str]) -> None:
    if isinstance(obj, dict):
        maybe_id = obj.get("id")
        if isinstance(maybe_id, str) and maybe_id:
            output.add(maybe_id)
        for value in obj.values():
            _extract_ids_from_obj(value, output)
    elif isinstance(obj, list):
        for item in obj:
            _extract_ids_from_obj(item, output)


def load_device_ids(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # fallback: one device ID per line
        return [line.strip() for line in text.splitlines() if line.strip()]
    output: set[str] = set()
    _extract_ids_from_obj(data, output)
    return sorted(output)
