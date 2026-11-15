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

from pydantic import BaseModel, ConfigDict, Field

EmergencyKind = Literal["depressurization", "fire", "toxic", "medical", "equipment", "sensor_fault"]
EmergencyState = Literal["suspected", "confirmed", "cleared"]
Severity = Literal["warning", "critical"]
CrewRole = Literal["incident_commander", "systems", "medical", "sensing"]
ActionKind = Literal["actuator", "hatch", "announce", "ventilation", "extinguish"]
ActionLevel = Literal["auto", "confirm"]
OnTimeout = Literal["execute", "discard"]

MODULE_TEMPLATE = "{module}"  # in a playbook target: the module where the emergency is


class ClassifierConfig(BaseModel):
    """Debounce: an emergency is ``confirmed`` after ``confirm_s`` of continuous signal and ``cleared``
    after ``clear_s`` without it. Stops a noise spike from opening an emergency."""

    model_config = ConfigDict(extra="forbid")

    confirm_s: float = Field(default=5.0, ge=0)
    clear_s: float = Field(default=60.0, ge=0)


class DetectorSpec(BaseModel):
    """One detector: a class ``package.module:Class`` (importable, like sensors) watching ``metric`` on ``targets``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    emergency: EmergencyKind  # what a firing of this detector is evidence of
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
    target: str
    command: str  # actuator: on/off/set, hatch: open/close, announce: free label (e.g. "evacuate")
    value: float | None = None
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


class MonitorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classifier: ClassifierConfig = ClassifierConfig()
    detectors: list[DetectorSpec] = []
    playbooks: list[Playbook] = []
    crew_response: CrewResponseConfig | None = None  # None: the NPCs ignore emergencies (schedule only)
    # reserved: an ML detector is just one more entry in ``detectors``
