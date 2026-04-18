# Playback Mode

Playback mode lets you review a previously recorded test run without connecting to hardware.

## Starting Playback

1. Run `make run`
2. In the startup checklist, select **Playback mode**
3. Select a recorded run from the list
4. Click **Continue**

The launcher starts the backend service (no gateway, no hardware connection needed) and opens two operator windows in playback mode. The abort relay is not started in playback mode since there is no hardware to control.

The checklist displays available runs from `ignitionhistory/` along with integrity status badges (green/yellow/red) based on cross-archive validation results. It also offers rebuilt playback artifacts when native ones have issues.

## Playback Controls

### Timeline

The controller window shows a timeline bar at the bottom. You can:
- Click on the timeline to seek to a specific point in the run
- Drag the timeline cursor to scrub through the recording
- Press **P** to start/pause auto-play

### Auto-Play

When auto-play is running:
- The timeline advances at real-time speed
- Device states, graphs, and the SCADA schematic update as events are replayed
- The console shows events as they occurred

Press **P** again to pause.

### Split-Window Synchronization

Both windows stay synchronized during playback. The SCADA window receives seek position changes through a shared seek file that is polled at 120ms intervals.

## What You See in Playback

### Controller Window
- Device states as they were at the selected point in time
- Graphs showing telemetry data up to the selected time
- Console showing events up to the selected time
- Recording clock showing the position within the run

### SCADA Window
- P&ID schematic with valve states matching the selected point in time
- Valve colors update as you seek through the timeline

## How Playback Works Internally

Playback reads from the structured archive in `ignitionhistory/{run_id}/`:

1. Loads `metadata.json` for run timing information
2. Loads all events from `merged.jsonl` into memory
3. Loads available snapshots from `snapshots/`
4. When seeking to a time position:
   - Finds the nearest snapshot at or before the target time
   - Loads that snapshot to set baseline state
   - Replays all events between the snapshot time and the target time

The `PlaybackStateManager` (`gui/playback_state_manager.py`) tracks playback position, play/pause state, speed, and the most recent reconstructed GUI-visible state.

## Playback Data Sources

Playback uses the structured archive (`ignitionhistory/`), not the raw archives. The structured archive contains semantically decoded events with human-readable fields (pressure values, valve states, command names) rather than raw CAN bus bytes.

If the structured archive has integrity issues, the integrity scanner can detect mismatches and the rebuild tool (`historymanager/rebuild.py`) can attempt reconstruction from raw archives when they are available. The checklist offers rebuilt artifacts as an alternative playback source when native artifacts have issues.

## Commands in Playback

Commands are **disabled** in playback mode. The backend's command router rejects all command requests when in playback mode. There is no abort button and no abort relay.

## Limitations

- Seek performance depends on snapshot density. Currently, two snapshots are taken per run (start and finish). Seeking to the middle of a long run requires replaying all events from the beginning.
- Events are loaded entirely into memory. Very large runs may use significant RAM.
- Graphs and SCADA state update independently, which can cause brief visual inconsistencies during rapid seeking.

## See Also

- [Live Mode](live-mode.md) -- operating with real hardware
- [History Format](history-format.md) -- recording archive structure
- [Troubleshooting](troubleshooting.md) -- common problems and fixes
