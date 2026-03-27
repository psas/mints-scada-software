# Known-Issues

## This place is used to store any strange issues that is found


## Template

What happened: This is placeholder for template

Reproducibility: This is placeholder for template

This is placeholder for template

- a template
- a template
- a template
- a template

---

## Logic bug after close controller window during recording

What happened: respawn the controller window after start recording, it will jump back to not recording on recording clock, and can not click stop recording button because the button think it's not in recording. Also, the listener think user is still in recording so for user side, they can not even turn off the software because it will respawn every time they close it.

Reproducibility: Happen everytime. make run -> start recording -> close controller window

Possible causes:

- gui/controller_window.py
- backend/*

---

## Logic bug after enter playback mode

What happened: By design playback mode is entirely saparated from live mode, which means everything inside will be static including logs to make a full replay. Right now when enter playback mode, the logs still apply "live mode backend" and mix the logs.

Reproducibility: Happen everytime when enter playback mode.

Possible causes:

- gui/controller_window.py
- gui/scada_window.py

---

## Software crash after drag and drop widget to workspace

What happened: By drag and drop widget to workspace in controller window, the software will frozen, crash and close itself.

Reproducibility: Happen everytime when drag and drop to workspace.

Possible causes:

- gui/controller_window.py

---

## Software crash after click run script button in script control

What happened: By click run script button in script control in controller window, the software will crash.

Reproducibility: Happen everytime when click on the button.

Possible causes:

- gui/controller_window.py

---

## Logic bug on no device displayed in live mode device library

What happened: when entering the live mode, all devices in the device library are missing and can not can not test drag and drop.
- Live mode device library is populated from backend device inventory instead of directly from `settings.py`, so if inventory initialization/update fails the library appears empty.
- Unlike playback, live mode may not have a fallback path that seeds devices directly from static configuration.
- Devices can be filtered out during registry/schema normalization or by flags such as inactive/not controllable.
- A live-mode UI regression may prevent the controller window from adding backend inventory entries into the visible device library after connect.

Reproducibility: Happen everytime. make run -> go live

Possible causes:
- `gui/window_host.py`: live mode device library likely depends on backend-provided device inventory / presentation updates. If live inventory is not forwarded into the controller window correctly after connect, the library can stay empty.
- `gui/controller_window.py`: device library rendering/population logic may only update when specific inventory events arrive, so the visible list may remain blank even though live mode is running.
- `backend/service.py`: live startup path may not be publishing the expected device inventory payload, or may only publish state snapshots without the device list required by the controller UI.
- `backend/device_registry.py`: devices may be filtered out during live registry loading / normalization if metadata does not satisfy the expected schema or controllable/active conditions.
- `settings.py`: device placeholders may exist, but live mode does not appear to seed the library directly from static settings the same way playback/fallback paths do.
- Integration between live backend inventory and GUI library population appears inconsistent compared with playback mode, suggesting a regression in the live-only device-list initialization path.

---

## Logic bug no command signal send from SCADA page

What happened: solinoid valve signal seems not send successfully when click it in the SCADA page because backend refresh will overwrite the state change.

Reproducibility: Happen everytime. make run -> live -> click valves in SCADA

Possible causes:

- `gui/scada_window.py`: SCADA click/manual interaction may not consistently enter `_request_xv_command(...)`.
- `gui/scada_bridge.py` + `src/MinTS_SCADA_stable_v1_bridge_ready.svg`: SVG click event / JS-to-Python bridge may fail before backend command dispatch starts.
- `gui/scada_window.py`: valve-id to backend-device mapping may fail for some SCADA valves.
- `backend/service.py`: live initialization / registration state may keep backend authoritative valve state unchanged, causing periodic refresh to overwrite local SCADA state changes.
- `backend/gateway_bus_proxy.py` and `backend/gateway_client.py`: gateway forwarding / acknowledgement path may fail even if SCADA interaction reaches backend.

---

## Logic bug abort request not accepted from GUI

What happened: when pressing Abort, GUI shows popup: "Backend did not accept the abort request."

Reproducibility: Happens in live mode when pressing Abort.

Possible causes:
- `gui/scada_window.py` / `gui/controller_window.py`: Abort button handler may be sending the request through the wrong GUI path or with the wrong payload/IPC shape.
- `gui/window_host.py` / GUI action API layer: abort request may not be reaching backend correctly, or the response may be interpreted as failure even when backend state is changing.
- `backend/service.py`: backend abort handler may reject requests unless the system is in a specific live/recording/running state.
- `backend/service.py`: abort authority / interlock logic may be stricter than the GUI expects, causing backend to reject the request outside the exact allowed state.
- `backend/state_store.py` or related command-result/state-update flow: abort handling may fail while recording/reporting result status back to GUI, making the GUI think backend rejected the request.
- Supervisor / process-lifecycle integration may leave GUI and backend out of sync about whether a live run is active, so Abort is offered in the UI while backend believes there is nothing valid to abort.

---

## Logic bug Checklist window still showing dev bypass even plug in to the real system

What happened: when open checklist window, GUI shows dev bypass even when plugin to the real system, with incorrect devices, need more detailed specificaitons.

Reproducibility: Happens everytime when make run.

Possible causes:
- `gui/checklist_window.py`: checklist device/source selection may still be using a dev/default fallback path instead of live hardware/runtime detection.
- `gui/window_host.py` or checklist launch path: checklist window may be opened before live hardware initialization / gateway registration state is fully available, so it falls back to dev bypass content.
- `backend/service.py`: backend may not be publishing the real connected hardware/device status that checklist expects, causing GUI to assume dev mode.
- `settings.py`: checklist may still reference static placeholder/dev device metadata instead of the actual live registered device list.
- Integration between live hardware initialization and checklist population appears inconsistent, so the checklist can display stale/default dev-bypass data even when connected to the real system.

---

## Logic bug Controller window will be turned off without turn off any other related process

What happened: when close controller window, only the controller window got closed, no linkage that close the SCADA window and other related processes. close the SCADA window will perform correctly.

Reproducibility: Happens everytime when close controller window.

Possible causes:
- `gui/window_host.py`: controller window close event may not be routed into the same shutdown/exit path used by the SCADA window.
- `gui/window_host.py` or related supervisor/launcher logic: controller close may be treated as a local window close only, instead of an application-level shutdown signal.
- `gui/scada_window.py` / controller-window host integration: close-handling behavior appears inconsistent between the two windows, suggesting the linkage logic is only implemented for SCADA-side close.
- Shutdown watcher / supervisor coordination may only react correctly when the SCADA window closes, but not when the controller window closes first.
- Process-lifecycle handling for controller/scada dual-window mode may be asymmetric, so controller exit does not propagate to the other GUI window, backend, gateway, or watcher processes.

---