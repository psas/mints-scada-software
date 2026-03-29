from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def sanitize_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def write_json_artifact(base_dir: Path, test_name: str, payload: dict[str, Any]) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = base_dir / f"{sanitize_name(test_name)}_{ts}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return path
