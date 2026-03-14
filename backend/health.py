from __future__ import annotations

from typing import Any

from historymanager import HistoryManager
from historymanager.manager import isoformat_z


class HealthPublisher:
    """Record backend lifecycle/system events into history.

    Current behavior:
    - if no active run, emit nothing to history
    - if a run is active, record both:
      - raw system_event
      - structured system_event
    """

    def __init__(self, *, history_manager: HistoryManager) -> None:
        self.history_manager = history_manager

    def record_system_event(
        self,
        event_type: str,
        *,
        severity: str = "info",
        **extra: Any,
    ) -> dict[str, Any]:
        event = {
            "event_kind": "system_event",
            "event_type": event_type,
            "severity": severity,
            "recorded_by": "backend",
            "wall_time": isoformat_z(),
            **extra,
        }

        if self.history_manager.is_running:
            self.history_manager.record_raw_event("system_event", event)

            structured_event = {
                **event,
                "structured_at": isoformat_z(),
            }
            self.history_manager.record_structured_event(
                "system_event",
                structured_event,
            )

        return event
