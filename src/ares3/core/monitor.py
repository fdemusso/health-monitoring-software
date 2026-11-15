"""The monitoring system: detectors -> classifier -> emergencies (+ a log of what happened).

Detectors (plugins, from the YAML) read SENSED observations and return :class:`Signal`s. The classifier
debounces them per (emergency kind, module): ``suspected`` on the first signal, ``confirmed`` after
``confirm_s`` of continuous signal, ``cleared`` after ``clear_s`` without one. A cleared emergency is
reported once more in its tick (state ``cleared``) and then dropped. The YAML spec of a detector decides
the emergency kind and severity; the detector only supplies the evidence.

The whole system is also in one of three modes (``Monitor.mode``): ``passive`` (nothing open), ``alert`` (a problem is
being recognised) and ``reaction`` (a response is running). The mode is the maximum over the open emergencies; it rises at
once and falls only after ``mode_hold_s`` of quiet. Each ``Emergency`` carries its ``alert_class`` (emergency / warning /
caution / advisory) from ``classifier.classes``, so the UI needs no rules of its own.

Responses (playbooks, confirm/timeout) are the next layer and consume ``Emergency`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ares3.schemas.monitor import ClassifierConfig, DetectorSpec, MonitorConfig, MonitorMode
from ares3.sdk.base import BaseDetector
from ares3.sdk.context import StepContext
from ares3.sdk.registry import resolve
from ares3.sdk.types import Emergency, MonitorEvent, Observation, Signal

from .rng import derive

_SEVERITY_RANK = {"warning": 0, "critical": 1}
_MODE_RANK = {"passive": 0, "alert": 1, "reaction": 2}


@dataclass
class _Track:
    """One emergency being tracked: a (kind, module, subject) triple."""

    id: str
    kind: str
    module_id: str
    t_open_s: float
    confirmed: bool = False
    last_signal_s: float = 0.0
    streak_start_s: float = 0.0  # start of the current uninterrupted run of signals
    seen_prev: bool = False
    severity: str = "warning"
    detectors: set[str] = field(default_factory=set)
    tres_s: float | None = None
    detail: str = ""
    confirm_s: float = 0.0
    clear_s: float = 0.0
    subject: str | None = None
    cause: str | None = None
    cause_rank: int = 10**9  # index of the detector that gave the cause: lower = more specific


class Monitor:
    def __init__(self, config: MonitorConfig, module_ids: list[str], seed: int, npc_ids: list[str] = ()) -> None:
        self.config = config
        self._rank = {d.id: i for i, d in enumerate(config.detectors)}
        self.specs: dict[str, DetectorSpec] = {d.id: d for d in config.detectors}
        self.detectors: list[BaseDetector] = []
        for spec in config.detectors:
            targets = []
            for t in spec.targets:
                targets += module_ids if t == "all_modules" else list(npc_ids) if t == "all_npcs" else [t]
            self.detectors.append(resolve(spec.kind).from_config(
                spec.id, spec.params, derive(seed, "detector", spec.id), metric=spec.metric, targets=list(targets)))
        for d in self.detectors:
            d.reset()
        self._tracks: dict[tuple[str, str, str], _Track] = {}
        self._count = 0
        self._declared: list[MonitorEvent] = []  # events of manual alarms, flushed by the next step
        self.mode: MonitorMode = "passive"  # state of the whole system after the last step
        self._mode_high_s = 0.0  # last time something asked for the current mode or a higher one

    def _target_mode(self, open_: list[Emergency]) -> MonitorMode:
        """The highest mode any open emergency asks for. A confirmed emergency whose class is ``emergency``/``warning``, or
        that has a playbook, is a REACTION; a suspected one, or a confirmed ``caution``/``advisory`` nobody responds to,
        is an ALERT."""
        mode: MonitorMode = "passive"
        for em in open_:
            if em.state == "confirmed" and (em.alert_class in ("emergency", "warning") or any(
                    pb.emergency == em.kind and pb.severity in (None, em.severity) for pb in self.config.playbooks)):
                return "reaction"
            mode = "alert"
        return mode

    def _update_mode(self, t: float, open_: list[Emergency], events: list[MonitorEvent]) -> None:
        target = self._target_mode(open_)
        if _MODE_RANK[target] >= _MODE_RANK[self.mode]:
            self._mode_high_s = t  # going up is immediate
        elif t - self._mode_high_s < self.config.classifier.mode_hold_s:
            return  # going down waits for ``mode_hold_s`` of quiet
        if target != self.mode:
            events.append(MonitorEvent(t_s=t, kind="mode_changed", message=f"monitoring: {self.mode} -> {target}"))
            self.mode = target

    def forget(self, module_id: str) -> None:
        """A repair was done in ``module_id``: the detectors drop their history there, so the emergency it caused clears
        after its ``clear_s`` instead of when the evidence has slid out of a window that may span hours."""
        for det in self.detectors:
            det.forget(module_id)

    def _timing(self, spec: DetectorSpec) -> tuple[float, float]:
        c: ClassifierConfig = self.config.classifier
        return (c.confirm_s if spec.confirm_s is None else spec.confirm_s,
                c.clear_s if spec.clear_s is None else spec.clear_s)

    def declare(self, kind: str, module_id: str, t: float, by: str | None) -> str:
        """A crew member raises the alarm by hand: confirmed at once, closed after ``clear_s`` unless detectors back it."""
        key = (kind, module_id, "")
        tr = self._tracks.get(key)
        if tr is None:
            self._count += 1
            c = self.config.classifier
            tr = _Track(id=f"{kind}:{module_id}:{self._count}", kind=kind, module_id=module_id, t_open_s=t,
                        confirm_s=c.confirm_s, clear_s=c.clear_s, severity="critical")
            self._tracks[key] = tr
            self._declared.append(MonitorEvent(t_s=t, kind="emergency_opened", emergency_id=tr.id, by=by,
                                               message=f"{kind} declared in {module_id}"))
        if not tr.confirmed:
            tr.confirmed = True
            self._declared.append(MonitorEvent(t_s=t, kind="emergency_confirmed", emergency_id=tr.id, by=by,
                                               message=f"{kind} confirmed in {module_id} (manual alarm)"))
        tr.last_signal_s, tr.detail = t, f"declared by {by or 'crew'}"
        return tr.id

    def step(self, ctx: StepContext, observations: list[Observation]) -> tuple[tuple[Emergency, ...], tuple[MonitorEvent, ...]]:
        t = ctx.tick.t_sim_s
        signals: list[Signal] = []
        for det in self.detectors:
            spec = self.specs[det.id]
            for s in det.detect(ctx, observations):
                signals.append(s.model_copy(update={"emergency": spec.emergency, "severity": spec.severity}))

        events: list[MonitorEvent] = self._declared
        self._declared = []
        seen: set[tuple[str, str, str]] = set()
        for s in signals:
            key = (s.emergency, s.module_id, s.subject or "")
            seen.add(key)
            confirm_s, clear_s = self._timing(self.specs[s.detector_id])
            tr = self._tracks.get(key)
            if tr is None:
                self._count += 1
                tr = _Track(id=f"{s.emergency}:{s.subject or s.module_id}:{self._count}", kind=s.emergency,
                            module_id=s.module_id, t_open_s=t, confirm_s=confirm_s, clear_s=clear_s, subject=s.subject)
                self._tracks[key] = tr
                events.append(MonitorEvent(t_s=t, kind="emergency_opened", emergency_id=tr.id,
                                           message=f"{s.emergency} suspected{f' for {s.subject}' if s.subject else ''} "
                                                   f"in {s.module_id}: {s.detail}"))
                tr.severity = s.severity
            if not tr.seen_prev:
                tr.streak_start_s = t
            tr.last_signal_s = t
            tr.confirm_s, tr.clear_s = min(tr.confirm_s, confirm_s), max(tr.clear_s, clear_s)
            tr.detectors.add(s.detector_id)
            spec = self.specs[s.detector_id]
            if spec.cause is not None and self._rank[s.detector_id] < tr.cause_rank:
                tr.cause, tr.cause_rank = spec.cause, self._rank[s.detector_id]
            if _SEVERITY_RANK[s.severity] > _SEVERITY_RANK[tr.severity]:
                tr.severity = s.severity
            if s.tres_s is not None:
                tr.tres_s = s.tres_s if tr.tres_s is None else min(tr.tres_s, s.tres_s)
            tr.detail = s.detail

        out: list[Emergency] = []
        for key, tr in list(self._tracks.items()):
            cleared = key not in seen and t - tr.last_signal_s >= tr.clear_s
            if not tr.confirmed and key in seen and t - tr.streak_start_s >= tr.confirm_s:
                tr.confirmed = True
                events.append(MonitorEvent(t_s=t, kind="emergency_confirmed", emergency_id=tr.id,
                                           message=f"{tr.kind} confirmed{f' for {tr.subject}' if tr.subject else ''} "
                                                   f"in {tr.module_id}{f' ({tr.cause})' if tr.cause else ''}: {tr.detail}"))
            if cleared:
                events.append(MonitorEvent(t_s=t, kind="emergency_cleared", emergency_id=tr.id,
                                           message=f"{tr.kind} cleared in {tr.module_id}"))
                del self._tracks[key]
            state = "cleared" if cleared else ("confirmed" if tr.confirmed else "suspected")
            out.append(Emergency(id=tr.id, kind=tr.kind, module_id=tr.module_id, severity=tr.severity, state=state,
                                 t_open_s=tr.t_open_s, t_update_s=t, detectors=tuple(sorted(tr.detectors)),
                                 tres_s=tr.tres_s if key in seen else None, detail=tr.detail, subject=tr.subject,
                                 cause=tr.cause, alert_class=self.config.classifier.alert_class(tr.kind, tr.severity, tr.cause)))
            tr.seen_prev = key in seen
            tr.tres_s, tr.detectors = None, set()  # recomputed from the next tick's signals
        self._update_mode(t, [e for e in out if e.state != "cleared"], events)
        return tuple(out), tuple(events)
