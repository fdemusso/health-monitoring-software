"""What a UI (or any outside caller) can ask of a running simulation.

This is the only inbound surface for the dashboard: the future WebSocket adapter wraps these calls and
nothing else. ``by`` is the crew member or UI user acting; it is only logged, never checked, because the
monitor is open to everyone: a life-saving action must not wait for a particular role.
"""

from __future__ import annotations

from typing import Protocol

from ares3.schemas.faults import FaultSpec
from ares3.schemas.monitor import EmergencyKind


class ControlAPI(Protocol):
    def inject_event(self, fault: FaultSpec, *, now: bool = True) -> FaultSpec:
        """Cause an event (same ``FaultSpec`` as in a scenario). Returns it as scheduled."""
        ...

    def stop_event(self, fault_id: str) -> None:
        """End an event now."""
        ...

    def approve_action(self, action_id: str, by: str | None = None) -> None:
        """Approve a pending ``confirm`` action; it executes on the next tick."""
        ...

    def reject_action(self, action_id: str, by: str | None = None) -> None:
        """Reject a pending action (it is discarded, whatever its ``on_timeout``)."""
        ...

    def declare_emergency(self, kind: EmergencyKind, module_id: str, by: str | None = None) -> str:
        """Manual alarm, as a crew member can on the ISS. Returns the emergency id."""
        ...
