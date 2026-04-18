# History Format

This document describes the recording archive structure and data formats used by MINTS SCADA.

## Archive Overview

Each recording run produces data in three archive directories at the repository root:

| Archive | Path Pattern | Writer | Purpose |
|---------|-------------|--------|---------|
| Raw | `.ignitionraw/{run_id}/` | Gateway (raw writer process) | First-order events as received |
| Raw backup | `.ignitionrawbak/{run_id}/` | Gateway (rawbak writer process) | Redundant copy, failure-isolated |
| Structured | `ignitionhistory/{run_id}/` | Backend (structured writer process) | Semantically decoded events, snapshots, merged stream |

The directory names are defined in `historymanager/paths.py`:
- `RAW_ROOT_DIRNAME = ".ignitionraw"`
- `RAWBAK_ROOT_DIRNAME = ".ignitionrawbak"`
- `HISTORY_ROOT_DIRNAME = "ignitionhistory"`

Raw and raw backup receive identical events through separate, failure-isolated writer processes. If one writer crashes, the other continues independently.

The structured archive contains richer versions of the same events with additional fields like semantic decode (pressure values, valve states), plus snapshots and a merged timeline.

## Per-Run Directory Structure

### Raw and Raw Backup Archives

File names are defined in `historymanager/models.py` (`RAW_STREAM_FILENAMES`):

```
.ignitionraw/{run_id}/
  metadata.json
  telemetry_in.raw.jsonl
  wire_command_out.raw.jsonl
  operator_action.jsonl
  system_event.jsonl
  writer_stats.json
  complete.json
```

`.ignitionrawbak/{run_id}/` has the same structure.

### Structured Archive

File names are defined in `historymanager/models.py` (`STRUCTURED_STREAM_FILENAMES`):

```
ignitionhistory/{run_id}/
  metadata.json
  telemetry_in.jsonl
  command_out.jsonl
  operator_action.jsonl
  system_event.jsonl
  merged.jsonl
  snapshots/
    000000.json
    ...
  writer_stats.json
  complete.json
```

The snapshots directory name is `SNAPSHOTS_DIRNAME = "snapshots"`.

## Event Streams

Four event streams are recorded during a run.

### `telemetry_in`

Inbound sensor readings from the CAN bus.

- Raw file: `telemetry_in.raw.jsonl` (wire-level packet data)
- Structured file: `telemetry_in.jsonl` (semantically decoded values)

### `command_out` / `wire_command_out`

Outbound commands sent to hardware.

- Raw file: `wire_command_out.raw.jsonl` (wire-level CAN packet bytes, gateway-owned)
- Structured file: `command_out.jsonl` (semantic command dispatch: command name, device, interlocks, result, backend-owned)

The raw and structured versions describe the same logical event differently. Raw records what bytes went on the wire. Structured records what the operator intended and what the command router decided. These are intentionally separate streams with different names and are not cross-comparable.

### `operator_action`

Operator/GUI actions that are not hardware commands.

- Raw file: `operator_action.jsonl`
- Structured file: `operator_action.jsonl`

### `system_event`

Backend and gateway lifecycle events.

- Raw file: `system_event.jsonl` (gateway-owned)
- Structured file: `system_event.jsonl` (backend-owned)

Note: raw `system_event` and structured `system_event` are written by different processes (gateway vs backend) with independent sequence counters and different event subsets. They are excluded from cross-archive integrity comparison for this reason (confirmed in `historymanager/integrity.py`).

## Shared Streams for Integrity

The streams suitable for cross-archive identity/hash comparison are defined in `historymanager/integrity.py` as `SHARED_STREAM_NAMES`. This currently includes `telemetry_in` and `operator_action`, but excludes `system_event` (different writers) and the command streams (different names and schemas).

## Event Identity Fields

Every recorded event carries these identity fields (defined in `historymanager/manager.py`):

| Field | Description |
|-------|-------------|
| `run_id` | Run identifier |
| `stream` | Stream name (e.g., `telemetry_in`) |
| `recorded_at` | ISO-8601 UTC timestamp |
| `event_uid` | Unique ID: `{run_id}:{stream}:{stream_seq:08d}` |
| `stream_seq` | 1-based per-stream sequence counter |
| `global_seq` | Cross-stream global sequence counter |
| `canonical_hash` | SHA-256 of event content (excluding identity fields and `structured_at`) |

Structured events additionally carry `structured_at` (when the structured builder processed them).

## Merged Timeline

The structured archive includes `merged.jsonl` (filename: `MERGED_FILENAME = "merged.jsonl"` in models), which contains all structured events from all streams in append order. This is the primary data source for playback.

## Snapshots

Snapshots are complete JSON dumps of the system state at a point in time. They are stored in `ignitionhistory/{run_id}/snapshots/` as numbered JSON files.

Currently, two snapshots are taken per run:
- Snapshot at run start
- Snapshot at run finish

## Metadata

Each archive directory contains a `metadata.json` (filename: `METADATA_FILENAME`) with run information including run ID, test name, start time, and end time (written on completion).

## Completion Marker

When a run finishes cleanly, a `complete.json` (filename: `COMPLETE_FILENAME`) file is written to each archive directory. Runs without this file may have been interrupted.

## Writer Stats

Each archive directory contains a `writer_stats.json` (filename: `WRITER_STATS_FILENAME`) tracking write counts, errors, and timing for the writer process.

## Archive Validation

The integrity scanner (`historymanager/integrity.py`) validates archives after recording by:

- Comparing event UIDs across raw, rawbak, and structured archives for shared streams
- Checking canonical hashes for cross-archive consistency
- Detecting sequence gaps or mismatches
- Reporting results per stream with sample details (up to 25 samples per mismatch)
- Writing an `integrity_report.json` file consumed by the playback catalog

An integrity scan runs automatically at the end of each recording run.

## Archive Rebuild

The rebuild tool (`historymanager/rebuild.py`) can attempt to reconstruct a damaged or incomplete archive from the available sources. Rebuilt artifacts are kept separate from native archive data (published as distinct rebuild artifacts) and do not silently overwrite original files.

Rebuild can help when:
- One archive is missing but others are intact
- A writer crashed mid-run but the other writers captured the data
- The structured archive needs to be regenerated from raw data

## See Also

- [Playback](playback.md) -- reviewing recorded test runs
- [Architecture](architecture.md) -- system design context
- [Developer Guide](developer-guide.md) -- codebase orientation
