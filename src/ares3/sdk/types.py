"""Data contract between the engine, Mario's physics plugins and Luca's physiology models.

Everything here is a frozen snapshot: plugins read it and *return* effects, they never mutate world
state. Units are SI except where NASA-STD-3001 quotes another one: partial pressures in kPa,
ppCO2 and PIO2 in mmHg, temperatures in degC, volumes in m3, rates in mol/s and W.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ares3.core.constants import MMHG_PER_KPA, inspired_po2_mmhg, psat_kpa
from ares3.schemas.monitor import (
    ActionKind,
    ActionLevel,
    AlertClass,
    EmergencyKind,
    EmergencyState,
    MonitorMode,
    OnTimeout,
    Severity,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class GasComposition(_Frozen):
    """Partial pressures, kPa."""

    o2: float
    co2: float
    n2: float
    h2o: float


class ModuleState(_Frozen):
    id: str
    volume_m3: float
    temperature_c: float
    pressure_kpa: float
    gas: GasComposition
    heat_load_w: float  # heat released inside the module during this tick (crew, loads)
    # combustion products (fire): CO as a mole fraction in ppm, smoke as particulate mass concentration
    co_ppm: float = 0.0
    smoke_mg_m3: float = 0.0
    fans_on: bool = True  # ventilation; the ISS switches it off in a fire / depressurization
    occupants: tuple[str, ...] = ()

    @property
    def rh_percent(self) -> float:
        return 100.0 * self.gas.h2o / psat_kpa(self.temperature_c)

    @property
    def ppco2_mmhg(self) -> float:
        return self.gas.co2 * MMHG_PER_KPA

    @property
    def pio2_mmhg(self) -> float:
        return inspired_po2_mmhg(self.pressure_kpa, self.gas.o2, self.gas.h2o)


class HatchState(_Frozen):
    a: str
    b: str
    diffusion_coeff: float  # passive + fan flow now in effect, m3/s
    open: bool = True
    id: str = ""
    closable: bool = True


class StationState(_Frozen):
    """The station as a whole: orbit and electrical bus (``core/orbit.py``). The thermal-control loop is the ``TCS`` actuator."""

    sun: float  # 1 in sunlight, 0 in eclipse
    beta_deg: float
    orbit_phase: float  # 0..1
    soc: float  # battery state of charge, 0..1
    p_gen_w: float
    p_load_w: float


class NPCState(_Frozen):
    id: str
    profile: str
    module_id: str
    activity: str
    met: float
    # metabolic exchange of this tick (computed by the core from the schedule)
    vo2_l_min: float
    vco2_l_min: float
    heat_w: float
    # anthropometrics of the crew member (None = not given); read by physiology models
    sex: Literal["M", "F"] | None = None
    age_y: float | None = None
    height_cm: float | None = None
    body_mass_kg: float | None = None
    # true vital signs, written by the PhysiologyModel: hr, hrv_rmssd, spo2, resp_rate, skin_temp_c, ...
    vitals: dict[str, float] = Field(default_factory=dict)
    # emergency response (None outside an emergency): role in the crew and phase warn/gather/work/assist/evacuate/incapacitated
    role: str | None = None
    response_phase: str | None = None
    # persistent latent state of the model (fatigue, circadian drift, ...); opaque to the core
    latent: dict[str, float] = Field(default_factory=dict)


class AlarmEvent(_Frozen):
    code: str
    module_id: str
    metric: str
    value: float
    limit_min: float | None = None
    limit_max: float | None = None
    severity: Literal["warning", "alarm"] = "alarm"
    source: str = ""


class Signal(_Frozen):
    """What a detector reports for one tick: evidence of an emergency, before the classifier debounces it."""

    detector_id: str
    emergency: EmergencyKind
    module_id: str
    severity: Severity
    subject: str | None = None  # the crew member the evidence is about (medical emergencies); module_id is where they are
    value: float | None = None  # the quantity that tripped the rule, for the log
    tres_s: float | None = None  # time to reach the minimum safe pressure (depressurization only)
    detail: str = ""


class Emergency(_Frozen):
    """An emergency known to the monitor; lives in the tick from ``suspected`` until ``cleared``."""

    id: str
    kind: EmergencyKind
    module_id: str
    severity: Severity
    state: EmergencyState
    t_open_s: float
    t_update_s: float
    detectors: tuple[str, ...] = ()
    tres_s: float | None = None
    detail: str = ""
    subject: str | None = None  # crew member in trouble (medical emergencies)
    cause: str | None = None  # what the sensors say is wrong, e.g. co_poisoning, hypoxia
    alert_class: AlertClass = "warning"  # colour of the alert, from ``classifier.classes``: the UI has no rules of its own


class Action(_Frozen):
    """A concrete step the monitor takes or proposes. ``target`` is already resolved (no ``{module}``)."""

    id: str
    emergency_id: str
    kind: ActionKind
    target: str
    command: str
    value: float | None = None
    level: ActionLevel = "auto"
    reversible: bool = True
    reason: str = ""


class PendingAction(_Frozen):
    """A ``confirm`` action waiting for a human. Visible to every crew member and to the UI; anyone can
    approve it. At ``deadline_s`` it is executed or discarded according to ``on_timeout``."""

    action: Action
    t_proposed_s: float
    deadline_s: float
    on_timeout: OnTimeout = "discard"


class MonitorEvent(_Frozen):
    """One line of the monitor's log, for the UI and for the dataset of decisions."""

    t_s: float
    kind: Literal[
        "emergency_opened", "emergency_confirmed", "emergency_cleared",
        "action_executed", "action_proposed", "action_approved", "action_rejected",
        "action_expired_executed", "action_expired_discarded", "action_blocked",
        "crew_alerted", "crew_gathered", "crew_evacuating", "crew_assisting", "crew_command_passed",
        "crew_stood_down", "crew_repairing", "crew_repaired", "crew_sealed",
        "mode_changed",
    ]
    message: str
    emergency_id: str | None = None
    action_id: str | None = None
    by: str | None = None  # crew member / UI user that approved or rejected; None = the system


class SimulationTick(_Frozen):
    tick: int
    t_sim_s: float
    dt_s: float
    day: int
    time_of_day_h: float
    modules: dict[str, ModuleState]
    npcs: dict[str, NPCState]
    hatches: tuple[HatchState, ...] = ()
    station: StationState | None = None  # None for profiles without an orbit (Mars)
    actuators: dict[str, dict[str, float]] = Field(default_factory=dict)  # telemetry channels of each actuator
    active_faults: tuple[str, ...] = ()
    alarms: tuple[AlarmEvent, ...] = ()
    # TODO(dashboard): `emergencies`, `pending_actions`, `monitor_events` and NPCState `role` / `response_phase` must be mirrored by hand in
    # dashboard/src/telemetry/types.ts (Python is the source of truth); until then the UI cannot show them.
    # Same for ModuleState `co_ppm`, `smoke_mg_m3`, `fans_on`, Emergency `subject` / `cause`, and the vital `cohb_pct`.
    emergencies: tuple[Emergency, ...] = ()
    pending_actions: tuple[PendingAction, ...] = ()
    monitor_events: tuple[MonitorEvent, ...] = ()  # events produced during this tick only
    monitor_mode: MonitorMode = "passive"


class Observation(_Frozen):
    """What a sensor reports: ``value`` is sensed (noise, lag, faults), ``value_true`` is the truth."""

    tick: int
    t_s: float
    sensor_id: str
    entity_id: str  # id of the module / NPC measured
    metric: str
    value: float
    value_true: float
    quality: float = 1.0


class ModuleFlow(_Frozen):
    """An actuator's effect on a module, as RATES so it does not depend on dt."""

    module_id: str
    mol_s: dict[str, float] = Field(default_factory=dict)  # species -> mol/s (negative removes)
    heat_w: float = 0.0
    power_w: float = 0.0  # electrical draw (informational for now)


class VitalsUpdate(_Frozen):
    vitals: dict[str, float]
    latent: dict[str, float] = Field(default_factory=dict)


class Command(_Frozen):
    """Issued by the agent at tick N, applied by the actuator at tick N+1."""

    actuator_id: str
    action: str  # e.g. "on", "off", "set"
    value: float | None = None
