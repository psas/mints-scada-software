from __future__ import annotations

import sys
from typing import Any

import pytest

from .artifacts import write_json_artifact
from .models import LabConfig


def _interactive_available() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def manual_confirm(
    config: LabConfig,
    test_name: str,
    prompt: str,
    artifact_payload: dict[str, Any] | None = None,
) -> bool:
    if config.no_manual_prompts:
        pytest.fail(
            f"Manual confirmation required for {test_name}, but --mints-no-manual-prompts "
            "was set."
        )
    if not _interactive_available():
        pytest.fail(
            f"Manual confirmation required for {test_name}, but stdin is not interactive. "
            "Run pytest with -s in a terminal."
        )

    print("\n" + "=" * 80)
    print(f"[MANUAL STEP] {test_name}")
    print(prompt.strip())
    print("Type 'y' for yes, 'n' for no, or 'a' to abort this test.")
    print("=" * 80)
    while True:
        answer = input("> ").strip().lower()
        if answer in {"y", "yes"}:
            if artifact_payload is not None:
                artifact_payload["manual_confirmation"] = True
            return True
        if answer in {"n", "no"}:
            if artifact_payload is not None:
                artifact_payload["manual_confirmation"] = False
            return False
        if answer in {"a", "abort"}:
            pytest.fail(f"Operator aborted test {test_name}.")
        print("Please type y / n / a.")


def manual_text(
    config: LabConfig,
    test_name: str,
    prompt: str,
    artifact_payload: dict[str, Any] | None = None,
    field_name: str = "operator_note",
) -> str:
    if config.no_manual_prompts:
        pytest.fail(
            f"Operator note required for {test_name}, but --mints-no-manual-prompts was set."
        )
    if not _interactive_available():
        pytest.fail(
            f"Operator note required for {test_name}, but stdin is not interactive. "
            "Run pytest with -s in a terminal."
        )

    print("\n" + "=" * 80)
    print(f"[OPERATOR NOTE] {test_name}")
    print(prompt.strip())
    print("=" * 80)
    note = input("> ").strip()
    if artifact_payload is not None:
        artifact_payload[field_name] = note
    return note
