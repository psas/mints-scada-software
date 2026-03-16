from __future__ import annotations

import importlib
import json
import os
import sys
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

# Help Qt-based tests run in a headless session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ensure_repo_root_on_path() -> Path:
    root = repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def import_module_or_skip(module_name: str):
    ensure_repo_root_on_path()
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - only used when local env differs
        raise unittest.SkipTest(f"Could not import {module_name}: {exc}") from exc


def get_qapplication():
    ensure_repo_root_on_path()
    try:
        from PyQt5.QtWidgets import QApplication
    except Exception as exc:  # pragma: no cover
        raise unittest.SkipTest(f"PyQt5 is not available: {exc}") from exc

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@contextmanager
def temp_project_root():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def wait_until(predicate, timeout_s: float = 2.0, step_s: float = 0.02, message: str | None = None):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    raise AssertionError(message or "Timed out waiting for condition")


def make_identity_event(event_uid: str, stream_seq: int, *, canonical_hash: str | None = None, recorded_at: str = "2026-03-15T00:00:00Z", **extra):
    return {
        "event_uid": event_uid,
        "stream_seq": int(stream_seq),
        "canonical_hash": canonical_hash or f"hash-{event_uid}",
        "recorded_at": recorded_at,
        **extra,
    }
