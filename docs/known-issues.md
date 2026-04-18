# Known Issues

Tracked bugs and current limitations in the codebase.

Items below were retained after the latest code audit where no clear fix was found in the source, or where the current behavior remains intentionally limited. Some GUI- and workflow-level behaviors may still require manual re-validation.

Issues removed during audit were either confirmed fixed, no longer reproducible from the current code, or moved to [Future Ideas](future-ideas.md).

---

## Contents

- [GUI Issues](#gui-issues)
- [Backend / Architecture Limitations](#backend--architecture-limitations)
- [Nexus / Hardware Issues](#nexus--hardware-issues)
- [Playback Issues](#playback-issues)
- [Recording / History Issues](#recording--history-issues)
- [Process / Lifecycle Issues](#process--lifecycle-issues)
- [Other / Miscellaneous](#other--miscellaneous)
- [Issue Entry Format](#issue-entry-format)
- [See Also](#see-also)

---

## GUI Issues

No currently confirmed issues in this category after the latest code audit. Manual GUI validation may still be needed for behaviors that were not re-tested live.

---

## Backend / Architecture Limitations

### Software abort is a placeholder

**What happened:** The GUI abort button and the `abort()` script function trigger a software abort path that records the request and sets a gateway latch flag, but do **not** send hardware stop commands to devices. The gateway code contains explicit TODO markers (`TODO(psas-abort-fastpath)`) for defining real hardware-side abort behavior.

The abort latch message reads: *"ABORT LATCHED !!! PRESS THE E-STOP BUTTON NOW !!!"* - reinforcing that the physical E-stop is the real emergency stop mechanism.

**Reproducibility:** Every time the software abort path is used.

**Possible causes:**
- `scripts/script_runtime/script_contract.py`
- `gateway/service.py`
- `backend/abort_command.py`

**Workaround:** Use the physical E-stop button for real emergency stops.

---

### Writer processes are daemon children

**What happened:** History writer processes run with `daemon=True`. If the parent process (backend or gateway) exits unexpectedly, the OS kills the writer processes without flushing. Events in writer queues at the time of unexpected exit are lost.

**Reproducibility:** Only when the parent process exits unexpectedly.

**Possible causes:**
- `historymanager/writers.py`

**Workaround:** None. Normal shutdown flushes correctly; only unexpected crashes cause data loss.

---

## Nexus / Hardware Issues

No currently confirmed issues in this category after the latest code audit.

---

## Playback Issues

No currently confirmed issues in this category after the latest code audit.

---

## Recording / History Issues

No currently confirmed issues in this category after the latest code audit.

---

## Process / Lifecycle Issues

No currently confirmed issues in this category after the latest code audit.

---

## Other / Miscellaneous

No currently confirmed issues in this category after the latest code audit.

---

## Issue Entry Format

Use this format when adding new issues later:

### Issue title

**What happened:** _(describe the observed behavior)_

**Reproducibility:** _(for example: every time / intermittent / only under specific conditions)_

**Possible causes:**
- _(file / module / subsystem)_
- _(file / module / subsystem)_

**Workaround:** _(if any)_

---

## See Also

- [Future Ideas](future-ideas.md) -- deferred improvements and enhancement opportunities
- [Troubleshooting](troubleshooting.md) -- common problems and how to fix them
- [Architecture](architecture.md) -- system design context
