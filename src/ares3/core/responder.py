"""Playbook executor: turns confirmed emergencies into actions, ISS style.

* ``auto`` steps run at once (reversible safing). ``confirm`` steps become a :class:`PendingAction` that
  any crew member (or the UI) can approve or reject until its deadline; on timeout ``on_timeout`` decides.
* Every executed action goes through the safety guard first: a hatch is never closed in a way that cuts an
  occupant off from a return vehicle (NASA SpaceOps 2023, "Safe Haven and Safe Return").
* When an emergency clears, actuators that were forced ``on``/``off`` go back to ``auto``. Hatches stay as
  they are: reopening a sealed module is a crew decision.

The responder only *decides*; the engine applies the returned actions on the next tick.
"""

from __future__ import annotations

from collections.abc import Callable

from ares3.schemas.monitor import MODULE_TEMPLATE, ActionSpec, Playbook
from ares3.sdk.types import Action, Emergency, MonitorEvent, PendingAction

Guard = Callable[..., str | None]  # (action, also_closed=...) -> the reason to block an action, or None
ISOLATE = "isolate:"  # hatch target "isolate:USL": close every closable hatch of that module


class Responder:
    def __init__(self, playbooks: list[Playbook], actuators: set[str], hatches: set[frozenset[str]],
                 guard: Guard, modules: set[str] = frozenset(), closable: frozenset[frozenset[str]] | None = None) -> None:
        self.playbooks = playbooks
        self.actuators = actuators
        self.hatches = hatches
        self.closable = hatches if closable is None else closable  # hatches that can be shut (not the vent openings)
        self.modules = modules
        self.guard = guard
        self._started: set[tuple[str, str]] = set()  # (emergency id, severity) whose playbooks already ran
        self._pending: dict[str, tuple[PendingAction, ActionSpec]] = {}
        self._forced: dict[str, list[tuple[str, str]]] = {}  # emergency id -> (kind, target) forced, restored on clear
        self._approved: dict[str, str | None] = {}
        self._rejected: dict[str, str | None] = {}
        self._n = 0

    # ---- requests from the outside (ControlAPI) --------------------------------------------------
    def approve(self, action_id: str, by: str | None) -> None:
        if action_id not in self._pending:
            raise KeyError(f"no pending action {action_id}")
        self._approved.setdefault(action_id, by)  # the first approver is the one logged

    def reject(self, action_id: str, by: str | None) -> None:
        if action_id not in self._pending:
            raise KeyError(f"no pending action {action_id}")
        self._rejected[action_id] = by

    @property
    def pending(self) -> tuple[PendingAction, ...]:
        return tuple(pa for pa, _ in self._pending.values())

    # ---- one tick --------------------------------------------------------------------------------
    def step(self, t: float, emergencies: tuple[Emergency, ...]) -> tuple[list[Action], list[MonitorEvent]]:
        run: list[Action] = []
        events: list[MonitorEvent] = []

        for em in emergencies:
            if em.state == "confirmed" and (em.id, em.severity) not in self._started:
                self._started.add((em.id, em.severity))  # a worse severity later runs its own playbook once more
                self._start(t, em, run, events)
            elif em.state == "cleared":
                self._finish(t, em, run, events)

        for aid, by in self._approved.items():
            pa, _ = self._pending.pop(aid)
            events.append(MonitorEvent(t_s=t, kind="action_approved", emergency_id=pa.action.emergency_id, action_id=aid,
                                       by=by, message=f"approved: {self._describe(pa.action)}"))
            self._execute(t, pa.action, run, events)
        for aid, by in self._rejected.items():
            if aid in self._pending:  # an approval of the same action in the same tick wins
                pa, _ = self._pending.pop(aid)
                events.append(MonitorEvent(t_s=t, kind="action_rejected", emergency_id=pa.action.emergency_id,
                                           action_id=aid, by=by, message=f"rejected: {self._describe(pa.action)}"))
        self._approved.clear()
        self._rejected.clear()

        for aid, (pa, _) in list(self._pending.items()):
            if t < pa.deadline_s:
                continue
            del self._pending[aid]
            if pa.on_timeout == "execute":
                events.append(MonitorEvent(t_s=t, kind="action_expired_executed", emergency_id=pa.action.emergency_id,
                                           action_id=aid, message=f"no answer, going ahead: {self._describe(pa.action)}"))
                self._execute(t, pa.action, run, events)
            else:
                events.append(MonitorEvent(t_s=t, kind="action_expired_discarded", emergency_id=pa.action.emergency_id,
                                           action_id=aid, message=f"no answer, dropped: {self._describe(pa.action)}"))
        return run, events

    # ---- internals -------------------------------------------------------------------------------
    @staticmethod
    def _describe(a: Action) -> str:
        return f"{a.kind} {a.target} -> {a.command}" + (f" ({a.reason})" if a.reason else "")

    def _start(self, t: float, em: Emergency, run: list[Action], events: list[MonitorEvent]) -> None:
        specs = [s for pb in self.playbooks if pb.emergency == em.kind and pb.severity in (None, em.severity)
                 for s in pb.actions]
        for spec in specs:
            target = spec.target.replace(MODULE_TEMPLATE, em.module_id)
            if spec.do == "hatch" and not target.startswith(ISOLATE) and len(set(target.split(":"))) == 1:
                continue  # "hab:hab": the playbook step is about the hatch between this module and another: none here
            self._n += 1
            action = Action(id=f"a{self._n}", emergency_id=em.id, kind=spec.do,
                            target=target, command=spec.command,
                            value=spec.value, level=spec.level, reversible=spec.reversible, reason=spec.reason)
            problem = self._unknown_target(action)
            if problem:
                events.append(MonitorEvent(t_s=t, kind="action_blocked", emergency_id=em.id, action_id=action.id,
                                           message=f"skipped {self._describe(action)}: {problem}"))
            elif spec.level == "auto":
                self._execute(t, action, run, events)
            else:
                pa = PendingAction(action=action, t_proposed_s=t, deadline_s=t + spec.confirm_timeout_s,
                                   on_timeout=spec.on_timeout)
                self._pending[action.id] = (pa, spec)
                events.append(MonitorEvent(t_s=t, kind="action_proposed", emergency_id=em.id, action_id=action.id,
                                           message=f"proposed: {self._describe(action)} "
                                                   f"(confirm within {spec.confirm_timeout_s:.0f} s)"))

    def _unknown_target(self, a: Action) -> str | None:
        if a.kind == "actuator" and a.target not in self.actuators:
            return f"no actuator {a.target}"
        if a.kind in ("ventilation", "extinguish") and a.target not in self.modules:
            return f"no module {a.target}"
        if a.kind == "hatch" and a.target.startswith(ISOLATE):
            return None if a.target[len(ISOLATE):] in self.modules else f"no module {a.target[len(ISOLATE):]}"
        if a.kind == "hatch":
            ends = a.target.split(":")
            if len(ends) != 2 or frozenset(ends) not in self.hatches:
                return f"no hatch {a.target}"
        return None

    def _isolate(self, t: float, a: Action, run: list[Action], events: list[MonitorEvent]) -> None:
        """Close every closable hatch of a module, each one through the guard (the ones already closed by this step count)."""
        module = a.target[len(ISOLATE):]
        closed: set[frozenset[str]] = set()
        for pair in sorted(self.closable, key=sorted):
            if module not in pair:
                continue
            (other,) = pair - {module}
            sub = a.model_copy(update={"target": f"{module}:{other}", "command": "close"})
            reason = self.guard(sub, also_closed=frozenset(closed))
            if reason:
                events.append(MonitorEvent(t_s=t, kind="action_blocked", emergency_id=a.emergency_id, action_id=a.id,
                                           message=f"blocked {self._describe(sub)}: {reason}"))
                continue
            closed.add(pair)
            run.append(sub)
            events.append(MonitorEvent(t_s=t, kind="action_executed", emergency_id=a.emergency_id, action_id=a.id,
                                       message=self._describe(sub)))

    def _execute(self, t: float, a: Action, run: list[Action], events: list[MonitorEvent]) -> None:
        if a.kind == "hatch" and a.target.startswith(ISOLATE):
            return self._isolate(t, a, run, events)
        reason = self.guard(a)
        if reason:
            events.append(MonitorEvent(t_s=t, kind="action_blocked", emergency_id=a.emergency_id, action_id=a.id,
                                       message=f"blocked {self._describe(a)}: {reason}"))
            return
        forced = a.command == "off" or (a.kind == "actuator" and a.command == "on")  # ventilation is only ever forced off
        if a.kind in ("actuator", "ventilation") and forced and a.reversible:
            self._forced.setdefault(a.emergency_id, []).append((a.kind, a.target))
        run.append(a)
        events.append(MonitorEvent(t_s=t, kind="action_executed", emergency_id=a.emergency_id, action_id=a.id,
                                   message=self._describe(a)))

    def _finish(self, t: float, em: Emergency, run: list[Action], events: list[MonitorEvent]) -> None:
        for aid, (pa, _) in list(self._pending.items()):
            if pa.action.emergency_id == em.id:
                del self._pending[aid]
                events.append(MonitorEvent(t_s=t, kind="action_expired_discarded", emergency_id=em.id, action_id=aid,
                                           message=f"emergency over, dropped: {self._describe(pa.action)}"))
        for kind, target in self._forced.pop(em.id, []):
            self._n += 1
            a = Action(id=f"a{self._n}", emergency_id=em.id, kind=kind, target=target,
                       command="auto" if kind == "actuator" else "on",
                       reason="emergency cleared: back to automatic control")
            run.append(a)
            events.append(MonitorEvent(t_s=t, kind="action_executed", emergency_id=em.id, action_id=a.id,
                                       message=self._describe(a)))
