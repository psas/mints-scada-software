from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Iterable

from .models import GoldenTrace, PacketRecord


PACKET_LINE_RE = re.compile(
    r"^(?P<timestamp>\S+)\s+"
    r"(?P<err>.)(?P<reserved>\S)\s+"
    r"(?P<direction>[<>])(?P<address>[0-9A-Fa-f]+)\s+"
    r"#(?P<sequence>[0-9A-Fa-f]+)\s+"
    r"!(?P<command>[0-9A-Fa-f]+):\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s*)+)$"
)

HEX_PAIR_RE = re.compile(r"[0-9A-Fa-f]{2}")


def bookmark_file(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    return path.stat().st_size


def read_new_text(path: Path | None, start_offset: int) -> str:
    if path is None or not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(start_offset)
        return fh.read()


def wait_for_new_text(path: Path | None, start_offset: int, timeout: float) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = read_new_text(path, start_offset)
        if text.strip():
            return text
        time.sleep(0.25)
    return read_new_text(path, start_offset)


def parse_packet_records(text: str) -> list[PacketRecord]:
    packets: list[PacketRecord] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pkt = parse_packet_record_line(line)
        if pkt is not None:
            packets.append(pkt)
    return packets


def parse_packet_record_line(line: str) -> PacketRecord | None:
    # JSON first
    if line.startswith("{") and line.endswith("}"):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            payload = (
                data.get("payload_bytes")
                or data.get("data")
                or data.get("bytes")
                or data.get("payload")
                or []
            )
            if isinstance(payload, str):
                payload_list = HEX_PAIR_RE.findall(payload)
            elif isinstance(payload, list):
                payload_list = [str(x).upper() for x in payload]
            else:
                payload_list = []
            direction = data.get("direction")
            address = data.get("address")
            command = data.get("command")
            sequence = data.get("sequence") or data.get("seq")
            timestamp = data.get("timestamp") or data.get("time")
            return PacketRecord(
                raw=line,
                direction=str(direction) if direction is not None else None,
                address=str(address) if address is not None else None,
                command=str(command) if command is not None else None,
                payload_bytes=payload_list,
                sequence=str(sequence) if sequence is not None else None,
                timestamp=str(timestamp) if timestamp is not None else None,
                extra={k: v for k, v in data.items() if k not in {"direction", "address", "command", "payload_bytes", "data", "bytes", "payload", "sequence", "seq", "timestamp", "time"}},
            )
    match = PACKET_LINE_RE.match(line)
    if match:
        data_field = match.group("data")
        payload = [token.upper() for token in HEX_PAIR_RE.findall(data_field)]
        return PacketRecord(
            raw=line,
            direction=match.group("direction"),
            address=match.group("address").upper(),
            command=match.group("command").upper(),
            payload_bytes=payload,
            sequence=match.group("sequence").upper(),
            timestamp=match.group("timestamp"),
            extra={"error_bit": match.group("err"), "reserved": match.group("reserved")},
        )
    return None


def load_golden_trace(path: Path) -> GoldenTrace:
    data = json.loads(path.read_text(encoding="utf-8"))
    packets = []
    for entry in data.get("expected_packets", []):
        packets.append(
            PacketRecord(
                raw=entry.get("raw", ""),
                direction=entry.get("direction"),
                address=str(entry.get("address")).upper() if entry.get("address") is not None else None,
                command=str(entry.get("command")).upper() if entry.get("command") is not None else None,
                payload_bytes=[str(x).upper() for x in entry.get("payload_bytes", [])],
                sequence=str(entry.get("sequence")).upper() if entry.get("sequence") is not None else None,
                timestamp=entry.get("timestamp"),
                extra=dict(entry.get("extra", {})),
            )
        )
    return GoldenTrace(
        trace_id=str(data.get("trace_id", path.stem)),
        description=str(data.get("description", "")),
        expected_packets=packets,
        notes=dict(data.get("notes", {})),
    )


def packet_matches(expected: PacketRecord, actual: PacketRecord) -> bool:
    if expected.direction and actual.direction and expected.direction != actual.direction:
        return False
    if expected.address and actual.address and expected.address.upper() != actual.address.upper():
        return False
    if expected.command and actual.command and expected.command.upper() != actual.command.upper():
        return False
    if expected.payload_bytes:
        if [x.upper() for x in expected.payload_bytes] != [x.upper() for x in actual.payload_bytes]:
            return False
    if expected.sequence and actual.sequence and expected.sequence.upper() != actual.sequence.upper():
        return False
    for key, value in expected.extra.items():
        if value is None:
            continue
        if actual.extra.get(key) != value:
            return False
    return True


def compare_expected_sequence(
    expected_packets: list[PacketRecord],
    actual_packets: list[PacketRecord],
) -> tuple[bool, str]:
    if not expected_packets:
        return False, "Golden trace contains no expected packets."
    if not actual_packets:
        return False, "No parseable packets were captured after the operator action."

    cursor = 0
    matched_lines: list[str] = []
    for expected in expected_packets:
        found = False
        while cursor < len(actual_packets):
            candidate = actual_packets[cursor]
            cursor += 1
            if packet_matches(expected, candidate):
                matched_lines.append(candidate.raw)
                found = True
                break
        if not found:
            return False, (
                "Did not find expected packet in order.\n"
                f"Expected: direction={expected.direction} address={expected.address} "
                f"command={expected.command} payload={expected.payload_bytes}\n"
                f"Actual captured packets:\n" + "\n".join(pkt.raw for pkt in actual_packets)
            )
    return True, "Matched expected packet sequence in order."


def first_text_match(path: Path | None, pattern: str | None) -> tuple[bool, str]:
    if path is None or pattern is None:
        return False, "No file/pattern configured."
    if not path.exists():
        return False, f"Configured file does not exist: {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if pattern in text:
        return True, f"Found pattern {pattern!r} in {path}"
    return False, f"Pattern {pattern!r} not found in {path}"
