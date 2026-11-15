"""Crew procedures: the checklist for the PEOPLE of an emergency, next to the playbook (the safing of the machine).

A procedure is chosen when an emergency is ``confirmed`` (by kind, cause and severity) and walks through its steps:

* ``instruction``  text for the crew, closed with "done" (``ack_step`` from the UI, or an NPC of the step's role after
  ``duration_s`` when ``crew_response.npc_follows_procedures``): so a run without a UI is complete too;
* ``action``       a normal ``ActionSpec`` (auto, or a proposal any crew member approves), with the same safety guard and
  timeout as a playbook step; it passes when the action was executed, fails when it was blocked or dropped;
* ``check``        an automatic verification on SENSED values (the monitor never reads the truth) that has to hold within
  ``within_s``: the outcome of the treatment is judged on what the wearables and sensors say;
* ``question``     yes / no for the crew ("do you see smoke?"), branching; an NPC answers ``auto_answer``;
* ``escalate``     the procedure ends as ``escalated``: the next level (evacuation, ground) is up to the people.

The runner only decides and reports (``ProcedureState`` in the tick, ``MonitorEvent`` log); the actions it starts go through
the :class:`~ares3.core.responder.Responder` and are applied by the engine one tick later, like everything else.
A treatment has no effect on the physiology of the simulation (it would need Luca's model): the checks are written on what
the simulator can produce (moving someone to clean air, removing the source).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ares3.schemas.monitor import MODULE_TEMPLATE, SUBJECT_TEMPLATE, Procedure, ProcedureStep
from ares3.sdk.types import (
    Action,
    Emergency,
    MonitorEvent,
    NPCState,
    Observation,
    ProcedureState,
    ProcedureStepState,
)

from .responder import Responder

KEEP_S = 300.0  # a finished procedure stays in the tick this long, with its outcome


@dataclass
class _Run:
    id: str
    proc: Procedure
    em: Emergency
    t_start: float
    status: str = "running"
    current: str | None = None
    steps: dict[str, ProcedureStepState] = field(default_factory=dict)
    t_active: float = 0.0
    action_id: str | None = None
    t_end: float | None = None


def _fill(text: str, em: Emergency) -> str:
    return text.replace(SUBJECT_TEMPLATE, em.subject or "the crew").replace(MODULE_TEMPLATE, em.module_id)


class ProcedureRunner:
    def __init__(self, procedures: list[Procedure], responder: Responder, follow: bool = True,
                 profile_roles: Mapping[str, str] | None = None, succession: Sequence[str] = ()) -> None:
        self.procedures = procedures
        self.responder = responder
        self.follow = follow  # the NPCs close instruction / question steps by themselves
        self.profile_roles = dict(profile_roles or {})  # crew profile -> role (``crew_response.roles``)
        self.succession = list(succession)  # who steps in when nobody with the role can
        self._runs: dict[str, _Run] = {}
        self._acks: list[tuple[str, str, str | None, str | None]] = []
        self._last: dict[tuple[str, str], float] = {}  # (entity, metric) -> last SENSED value

    # ---- requests from the outside (ControlAPI) --------------------------------------------------
    def ack(self, procedure_id: str, step_id: str, by: str | None = None, answer: str | None = None) -> None:
        """Close the active step ``step_id`` of a running procedure (``answer`` yes / no for a question). Anyone can."""
        run = self._runs.get(procedure_id)
        if run is None or run.status != "running":
            raise KeyError(f"no running procedure {procedure_id}")
        if run.current != step_id:
            raise KeyError(f"step {step_id} of {procedure_id} is not the active one ({run.current})")
        kind = run.proc.steps[self._index(run, step_id)].do
        if kind not in ("instruction", "question", "escalate"):
            raise ValueError(f"step {step_id} ({kind}) closes by itself")
        if kind == "question" and answer not in ("yes", "no"):
            raise ValueError("a question is answered yes or no")
        self._acks.append((procedure_id, step_id, by, answer))

    # ---- one tick --------------------------------------------------------------------------------
    def step(self, t: float, emergencies: Iterable[Emergency], observations: Iterable[Observation],
             npcs: Mapping[str, NPCState], roles: Mapping[str, str]) -> tuple[tuple[ProcedureState, ...], list[MonitorEvent], list[Action]]:
        events: list[MonitorEvent] = []
        actions: list[Action] = []
        for o in observations:
            self._last[(o.entity_id, o.metric)] = o.value

        for em in emergencies:
            if em.state == "confirmed":
                proc = self._choose(em)
                key = f"{proc.id}:{em.id}" if proc else None
                if proc and key not in self._runs:
                    self._start(t, key, proc, em, events)
            for run in self._runs.values():
                if run.em.id == em.id:
                    run.em = em
                    if em.state == "cleared" and run.status == "running":
                        self._finish(t, run, "closed", events)

        acks, self._acks = self._acks, []
        for pid, sid, by, answer in acks:
            run = self._runs.get(pid)
            if run is not None and run.status == "running" and run.current == sid:
                self._close(t, run, "done", by, answer, events, actions)
        for run in list(self._runs.values()):
            if run.status == "running":
                self._advance(t, run, npcs, roles, events, actions)
            elif run.t_end is not None and t - run.t_end > KEEP_S:
                del self._runs[run.id]
        return self.states(), events, actions

    def states(self) -> tuple[ProcedureState, ...]:
        return tuple(ProcedureState(
            id=r.id, procedure_id=r.proc.id, emergency_id=r.em.id, title=_fill(r.proc.title, r.em), subject=r.em.subject,
            module_id=r.em.module_id, status=r.status, current=r.current, steps=tuple(r.steps[s.id] for s in r.proc.steps),
            t_start_s=r.t_start, t_end_s=r.t_end) for r in self._runs.values())

    # ---- internals -------------------------------------------------------------------------------
    def _choose(self, em: Emergency) -> Procedure | None:
        fits = [p for p in self.procedures if p.emergency == em.kind and p.severity in (None, em.severity)
                and p.cause in (None, em.cause)]
        fits.sort(key=lambda p: p.cause is None)  # the one that names the cause first
        return fits[0] if fits else None

    @staticmethod
    def _index(run: _Run, step_id: str) -> int:
        return next(i for i, s in enumerate(run.proc.steps) if s.id == step_id)

    def _start(self, t: float, key: str, proc: Procedure, em: Emergency, events: list[MonitorEvent]) -> None:
        run = _Run(id=key, proc=proc, em=em, t_start=t)
        for s in proc.steps:
            run.steps[s.id] = ProcedureStepState(id=s.id, kind=s.do, text=_fill(s.text, em))
        self._runs[key] = run
        events.append(MonitorEvent(t_s=t, kind="procedure_started", emergency_id=em.id,
                                   message=f"procedure: {_fill(proc.title, em)}"))
        self._activate(t, run, proc.steps[0].id, events)

    def _activate(self, t: float, run: _Run, step_id: str, events: list[MonitorEvent]) -> None:
        spec = run.proc.steps[self._index(run, step_id)]
        run.current, run.t_active, run.action_id = step_id, t, None
        deadline = t + spec.within_s if spec.do == "check" else None
        run.steps[step_id] = run.steps[step_id].model_copy(update={"status": "active", "t_start_s": t, "deadline_s": deadline})

    def _finish(self, t: float, run: _Run, status: str, events: list[MonitorEvent]) -> None:
        run.status, run.current, run.t_end = status, None, t
        for sid, st in run.steps.items():  # what was never reached (or was still open when the emergency ended)
            if st.status in ("pending", "active"):
                run.steps[sid] = st.model_copy(update={"status": "skipped"})
        kind = {"done": "procedure_done", "escalated": "procedure_escalated", "closed": "procedure_done"}[status]
        events.append(MonitorEvent(t_s=t, kind=kind, emergency_id=run.em.id,
                                   message=f"procedure {status}: {_fill(run.proc.title, run.em)}"))

    def _close(self, t: float, run: _Run, status: str, by: str | None, answer: str | None,
               events: list[MonitorEvent], actions: list[Action]) -> None:
        """Close the active step as done / failed and move on (the branch of a check or a question, else the next step)."""
        spec = run.proc.steps[self._index(run, run.current)]
        run.steps[spec.id] = run.steps[spec.id].model_copy(update={"status": status, "by": by, "answer": answer, "t_end_s": t})
        verb = "step_done" if status == "done" else "step_failed"
        who = f" by {by}" if by else ""
        events.append(MonitorEvent(t_s=t, kind=verb, emergency_id=run.em.id, by=by,
                                   message=f"{run.proc.id}/{spec.id} {status}{who}: {run.steps[spec.id].text or spec.do}"))
        if spec.do == "escalate":
            return self._finish(t, run, "escalated", events)
        branch = spec.on_pass if (status == "done" and answer != "no") else spec.on_fail
        if branch is None:
            i = self._index(run, spec.id) + 1
            branch = run.proc.steps[i].id if i < len(run.proc.steps) else "done"
        if branch == "done":
            return self._finish(t, run, "done", events)
        self._activate(t, run, branch, events)

    def _advance(self, t: float, run: _Run, npcs: Mapping[str, NPCState], roles: Mapping[str, str],
                 events: list[MonitorEvent], actions: list[Action]) -> None:
        for _ in range(len(run.proc.steps) + 1):  # steps that settle at once chain in the same tick
            if run.status != "running" or run.current is None:
                return
            spec = run.proc.steps[self._index(run, run.current)]
            before = run.current
            if spec.do == "action":
                self._advance_action(t, run, spec, events, actions)
            elif spec.do == "check":
                self._advance_check(t, run, spec, events, actions)
            else:
                self._advance_people(t, run, spec, npcs, roles, events, actions)
            if run.current == before and run.status == "running":
                return

    def _advance_action(self, t, run, spec: ProcedureStep, events, actions) -> None:
        if run.action_id is None:
            run.action_id = self.responder.run_spec(t, run.em, spec.action, actions, events)
            if run.action_id is None:  # the step does not apply to this emergency (module filter)
                return self._close(t, run, "done", None, None, events, actions)
        outcome = self.responder.outcome(run.action_id)
        if outcome != "pending":
            self._close(t, run, "done" if outcome == "executed" else "failed", None, None, events, actions)

    def _advance_check(self, t, run, spec: ProcedureStep, events, actions) -> None:
        entity = run.em.subject or run.em.module_id
        v = self._last.get((entity, spec.metric))
        ok = v is not None and (spec.min is None or v >= spec.min) and (spec.max is None or v <= spec.max)
        if ok:
            self._close(t, run, "done", None, None, events, actions)
        elif t - run.t_active >= spec.within_s:
            self._close(t, run, "failed", None, None, events, actions)

    def _advance_people(self, t, run, spec: ProcedureStep, npcs, roles, events, actions) -> None:
        if spec.do == "escalate":
            return self._close(t, run, "done", None, None, events, actions)  # the text is the order: it ends the procedure
        if not self.follow or t - run.t_active < spec.duration_s:
            return
        capable = [(n, npc) for n, npc in sorted(npcs.items()) if n != run.em.subject  # nobody treats themselves
                   and npc.vitals.get("health_state", 0.0) < 2.0 and npc.response_phase != "incapacitated"]
        role = lambda n, npc: roles.get(n) or self.profile_roles.get(npc.profile)
        doers = [n for n, npc in capable if spec.role is None or role(n, npc) == spec.role]
        if not doers:  # the person with the role is the patient or cannot: the next in the line of succession
            line = {p: i for i, p in enumerate(self.succession)}
            doers = [n for n, npc in sorted(capable, key=lambda c: line.get(c[1].profile, len(line)))]
        if doers:
            self._close(t, run, "done", doers[0], spec.auto_answer if spec.do == "question" else None, events, actions)
