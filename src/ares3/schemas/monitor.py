"""Configuration of the monitoring system: detectors, the classifier and the response playbooks.

Everything refers to *metrics on modules* (``P``, ``ppCO2``, ...), never to sensor ids, so a change of the
sensor set (the physicist has not finalised it) does not touch the rules. The monitor reads sensed values only.

Response model (ISS-like, see docs of the emergency research): the first actions of a playbook are
``auto`` (reversible safing, immediate). Heavier ones are ``confirm``: the crew sees a proposal and any
member can approve it until ``confirm_timeout_s``; when nobody answers, ``on_timeout`` decides
(``execute`` for life-saving actions, ``discard`` otherwise). The monitor is open to every crew member:
no role is needed to approve a life-saving action.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EmergencyKind = Literal["depressurization", "fire", "toxic", "medical", "equipment", "sensor_fault", "anomaly"]
EmergencyState = Literal["suspected", "confirmed", "cleared"]
Severity = Literal["warning", "critical"]
# ISS alert levels [R1][R2]: what the crew sees, derived from (kind, severity, cause) by ``ClassifierConfig.classes``
AlertClass = Literal["emergency", "warning", "caution", "advisory"]
# the three states of the monitoring system: nothing open / a problem is being recognised / a response is running
MonitorMode = Literal["passive", "alert", "reaction"]
CrewRole = Literal["incident_commander", "systems", "medical", "sensing"]
# ``power`` cuts / restores the electrical supply of a module (the ISS answers smoke by removing power from the racks [R3]);
# ``sensor`` makes the control loops read a redundant sensor instead of a faulty one ("substitute")
ActionKind = Literal["actuator", "hatch", "announce", "ventilation", "extinguish", "power", "sensor"]
ActionLevel = Literal["auto", "confirm"]
OnTimeout = Literal["execute", "discard"]

MODULE_TEMPLATE = "{module}"  # in a playbook target: the module where the emergency is
SUBJECT_TEMPLATE = "{subject}"  # ... the subject of the emergency: a crew member, or the faulty sensor of a sensor_fault


class ClassifierConfig(BaseModel):
    """Debounce: an emergency is ``confirmed`` after ``confirm_s`` of continuous signal and ``cleared``
    after ``clear_s`` without it. Stops a noise spike from opening an emergency."""

    model_config = ConfigDict(extra="forbid")

    confirm_s: float = Field(default=5.0, ge=0)
    clear_s: float = Field(default=60.0, ge=0)
    # The system drops to a lower mode only after this long without anything at the higher one (hysteresis: no flicker
    # between alert and passive when an emergency clears and the next one opens seconds later). ESTIMATE.
    mode_hold_s: float = Field(default=60.0, ge=0)
    # alert class per emergency, keyed ``kind:severity:cause``, ``kind:severity`` or ``kind`` (most specific wins); what is
    # not listed is ``emergency`` when critical and ``warning`` otherwise
    classes: dict[str, AlertClass] = {}
    # ``connected``: a leak drains every module its open hatches connect, so the rate detectors fire in all of them; the signals
    # of one detector in one such group are fused into ONE, in the module whose pressure falls fastest (the sheet 06 hint for the
    # rapid leak). After an isolation the sides are separate groups and the side that keeps falling is the one with the hole.
    group_by: Literal["module", "connected"] = "module"

    def alert_class(self, kind: str, severity: str, cause: str | None = None) -> AlertClass:
        keys = ([f"{kind}:{severity}:{cause}"] if cause else []) + [f"{kind}:{severity}", kind]
        for k in keys:
            if k in self.classes:
                return self.classes[k]
        return "emergency" if severity == "critical" else "warning"


class DiagnosisClass(BaseModel):
    """What a diagnosed class (a label of the fault catalog) becomes in the monitor: a ``diagnosis`` detector (stage B) says WHICH
    fault it sees in ``Signal.cause``; this table, in the YAML and not in the code, gives the kind and severity of the emergency
    it opens and how long it must hold (``None``: the classifier's own timing)."""

    model_config = ConfigDict(extra="forbid")

    emergency: EmergencyKind
    severity: Severity = "warning"
    confirm_s: float | None = Field(default=None, ge=0)
    clear_s: float | None = Field(default=None, ge=0)


class DetectorSpec(BaseModel):
    """One detector: a class ``package.module:Class`` (importable, like sensors) watching ``metric`` on ``targets``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    # what a firing of this detector is evidence of; ``diagnosis``: the detector names the fault (``Signal.cause``) and the
    # ``diagnosis`` table of the config says what it opens (stage B of the ML monitor)
    emergency: EmergencyKind | Literal["diagnosis"]
    severity: Severity = "critical"
    targets: list[str] = ["all_modules"]  # module ids, or ``all_modules``; NPC detectors: crew ids or ``all_npcs``
    metric: str | None = None  # e.g. "P"; some detectors (crosscheck, NPC health) do not use it
    params: dict[str, Any] = {}
    # what the evidence says went wrong (e.g. ``co_poisoning``). When several detectors fire on the same emergency, the
    # one listed first in ``detectors`` that has a cause wins: list the specific ones before the generic ones
    cause: str | None = None
    confirm_s: float | None = Field(default=None, ge=0)  # override of the classifier
    clear_s: float | None = Field(default=None, ge=0)


class ActionSpec(BaseModel):
    """One step of a playbook. ``target``: actuator id, hatch as ``a:b``, module id (``ventilation`` on/off,
    ``extinguish``), or the announcement channel; ``{module}`` stands for the module of the emergency."""

    model_config = ConfigDict(extra="forbid")

    do: ActionKind
    target: str  # ``power``: a module id; ``sensor``: the faulty sensor id (``{subject}`` in a sensor_fault playbook)
    command: str  # actuator: on/off/set, hatch: open/close, power: on/off, sensor: substitute, announce: free label
    value: float | None = None
    value_id: str | None = None  # ``sensor substitute``: the sensor to read instead; ``auto`` = the first of ``substitutes.yaml``
    # the step applies only to emergencies in these modules / not in these (a vital module is cut off only after a confirmation)
    in_modules: list[str] | None = None
    except_modules: list[str] = []
    level: ActionLevel = "auto"
    confirm_timeout_s: float = Field(default=30.0, gt=0)
    on_timeout: OnTimeout = "discard"
    reversible: bool = True
    reason: str = ""


class Playbook(BaseModel):
    """The steps for one kind of emergency. ``severity`` limits it to emergencies at that severity (``None``: any), so
    a slow leak (warning) and a rapid depressurization (critical) can have different responses. An emergency that
    worsens runs the playbook of its new severity too, on top of what already ran."""

    model_config = ConfigDict(extra="forbid")

    emergency: EmergencyKind
    severity: Severity | None = None
    actions: list[ActionSpec]


StepKind = Literal["instruction", "action", "check", "question", "escalate"]


class ProcedureStep(BaseModel):
    """One step of a crew procedure. ``{subject}`` and ``{module}`` in the text stand for the crew member in trouble and the
    module of the emergency. ``on_pass`` / ``on_fail`` (a step id, or ``done``) branch after a ``check`` and a ``question``
    (yes -> ``on_pass``, no -> ``on_fail``); without them the next step of the list follows."""

    model_config = ConfigDict(extra="forbid")

    id: str
    do: StepKind
    text: str = ""
    # instruction / question: who does it (an NPC with this role, when nobody from the UI has), and how long it takes them
    role: CrewRole | None = None
    duration_s: float = Field(default=30.0, ge=0)
    action: ActionSpec | None = None  # do = action: a normal playbook step, with its level, timeout and safety guard
    # do = check: a SENSED metric of the subject (or of the module) must get into [min, max] within ``within_s``
    metric: str | None = None
    min: float | None = None
    max: float | None = None
    within_s: float = Field(default=300.0, gt=0)
    auto_answer: Literal["yes", "no"] = "no"  # do = question: what an NPC answers when nobody from the UI does
    on_pass: str | None = None
    on_fail: str | None = None


class Procedure(BaseModel):
    """The checklist for the PEOPLE of one kind of emergency (the playbook is the safing of the machine). Chosen by (kind,
    ``cause``, ``severity``): the one that names the cause wins over the generic one. ESTIMATE until the team reviews them."""

    model_config = ConfigDict(extra="forbid")

    id: str
    emergency: EmergencyKind
    cause: str | None = None
    severity: Severity | None = None
    title: str
    steps: list[ProcedureStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _steps_are_wired(self):
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError(f"procedure {self.id}: duplicate step ids")
        for s in self.steps:
            for ref in (s.on_pass, s.on_fail):
                if ref is not None and ref != "done" and ref not in ids:
                    raise ValueError(f"procedure {self.id}, step {s.id}: no step {ref!r}")
            if s.do == "action" and s.action is None:
                raise ValueError(f"procedure {self.id}, step {s.id}: an action step needs `action`")
            if s.do == "check" and (s.metric is None or (s.min is None and s.max is None)):
                raise ValueError(f"procedure {self.id}, step {s.id}: a check needs `metric` and `min` and/or `max`")
        return self


class CrewResponseConfig(BaseModel):
    """How the NPCs react to a confirmed emergency (ISS: Warn, Gather, Work). Roles and succession are by crew
    PROFILE (commander, engineer, ...), so they survive a change of crew ids. All timings are ESTIMATES."""

    model_config = ConfigDict(extra="forbid")

    roles: dict[str, CrewRole]  # profile -> role
    succession: list[str]  # profiles, in the order they take command when the commander is incapacitated
    # kinds that make the crew retreat; only CRITICAL ones do (a slow leak or a warning is handled at the desk)
    gather_on: list[EmergencyKind] = ["depressurization", "fire", "toxic"]
    react_delay_s: tuple[float, float] = (2.0, 6.0)  # each NPC notices the alarm after a delay drawn in this range
    asleep_extra_delay_s: float = Field(default=30.0, ge=0)  # added for a sleeping crew member
    # everyone enters the return vehicle when TRes falls below this: the ISS crew stops leak isolation and retreats at
    # 10 minutes of reserve time [ICES-2025-126]
    evacuate_tres_s: float = Field(default=600.0, gt=0)
    stand_down_delay_s: float = Field(default=120.0, ge=0)  # after the last emergency clears, schedules resume
    # the extinguisher was discharged and the fire still burns after this long: everyone goes to the return vehicle
    fire_evacuate_s: float = Field(default=45.0, gt=0)
    # once everyone capable is inside the return vehicle the crew closes its hatches, so the vehicle keeps its air while
    # the station loses its own ("close the appropriate hatch(es) to isolate the affected area" [ICES-2025-126])
    seal_vehicle: bool = True
    # the engineer (role ``systems``) goes to a module with a confirmed ``equipment`` emergency and needs this long to fix it
    repair_s: float = Field(default=600.0, gt=0)
    # same for a leak that is not an emergency yet (warning severity: fast/slow leak): they find it and patch it. ESTIMATE:
    # the ISS Zvezda leaks took days of checks and repeated sealing, and not all repairs held
    repair_leak_s: float = Field(default=1800.0, gt=0)
    gather_met: float = Field(default=2.0, gt=0)  # effort while moving to the safe haven
    # when true an NPC (the acting commander, once at the safe haven) approves pending actions after
    # ``approve_delay_s``; when false only the UI does, and life-saving steps run on their timeout
    npc_approves_actions: bool = False
    approve_delay_s: float = Field(default=5.0, ge=0)
    # the NPC with the step's role closes the ``instruction`` / ``question`` steps of a procedure after its ``duration_s`` when
    # nobody from the UI has: runs without a UI stay complete (and the decisions of the crew end up in the log)
    npc_follows_procedures: bool = True


class MonitorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classifier: ClassifierConfig = ClassifierConfig()
    detectors: list[DetectorSpec] = []
    playbooks: list[Playbook] = []
    procedures: list[Procedure] = []
    crew_response: CrewResponseConfig | None = None  # None: the NPCs ignore emergencies (schedule only)
    # faulty sensor -> the redundant sensors that see the same air, best first (``sensor substitute`` with ``value_id: auto``).
    # Generated for the station from the redundancy groups of the workbook (tools/build_station.py). An ML detector is just one
    # more entry in ``detectors``.
    substitutes: dict[str, list[str]] = {}
    diagnosis: dict[str, DiagnosisClass] = {}  # label of the fault catalog -> emergency (see ``DiagnosisClass``)
