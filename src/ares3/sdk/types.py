"""Data contract between the engine, Mario's physics plugins and Luca's physiology models.

Everything here is a frozen snapshot: plugins read it and *return* effects, they never mutate world
state. Units are SI except where NASA-STD-3001 quotes another one: partial pressures in kPa,
ppCO2 and PIO2 in mmHg, temperatures in degC, volumes in m3, rates in mol/s and W.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ares3.core.constants import MMHG_PER_KPA, inspired_po2_mmhg, psat_kpa


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
    diffusion_coeff: float
    open: bool = True


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


class SimulationTick(_Frozen):
    tick: int
    t_sim_s: float
    dt_s: float
    day: int
    time_of_day_h: float
    modules: dict[str, ModuleState]
    npcs: dict[str, NPCState]
    hatches: tuple[HatchState, ...] = ()
    active_faults: tuple[str, ...] = ()
    alarms: tuple[AlarmEvent, ...] = ()


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
