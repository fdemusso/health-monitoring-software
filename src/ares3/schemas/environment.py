"""Environment profile: every global variable and rule that defines *where* the crew lives.

Swapping the profile (``mars_surface.yaml`` -> ``orbital_station.yaml``) changes gravity, day length,
atmosphere and alarm limits without touching code. A scenario can also patch single values through
``environment_overrides``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Atmosphere(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pressure_kpa: float = Field(gt=0)
    o2_fraction: float = Field(gt=0, lt=1)
    co2_ppm: float = Field(ge=0)
    temperature_c: float
    rh_percent: float = Field(ge=0, le=100)


class AtmosphereOverride(BaseModel):
    """Partial microclimate of one module (e.g. a greenhouse); unset fields keep the environment value."""

    model_config = ConfigDict(extra="forbid")

    pressure_kpa: float | None = Field(default=None, gt=0)
    o2_fraction: float | None = Field(default=None, gt=0, lt=1)
    co2_ppm: float | None = Field(default=None, ge=0)
    temperature_c: float | None = None
    rh_percent: float | None = Field(default=None, ge=0, le=100)


AlarmMetric = Literal["ppCO2", "pO2", "PIO2", "T", "RH", "P", "dewpoint", "N2_fraction"]


class AlarmRule(BaseModel):
    """A limit on a true (not sensed) module quantity. ``window_s > 0`` evaluates the mean over that window."""

    model_config = ConfigDict(extra="forbid")

    code: str
    metric: AlarmMetric
    min: float | None = None
    max: float | None = None
    window_s: float = Field(default=0.0, ge=0)
    severity: Literal["warning", "alarm"] = "alarm"
    source: str = "ESTIMATE"


class OrbitConfig(BaseModel):
    """Sun / eclipse cycle, electrical bus and the heat the orbit pushes through the insulation (``core/orbit.py``).
    Values of the ISS station model are Mario's (sheet 08_CICLO_ORBITALE); ESTIMATE marks his own estimates."""

    model_config = ConfigDict(extra="forbid")

    altitude_km: float = Field(default=420.0, gt=0)  # [F1]
    planet_radius_km: float = Field(default=6371.0, gt=0)
    mu_km3_s2: float = Field(default=398600.4, gt=0)
    beta0_deg: float = 0.0  # sun angle at t = 0
    beta_max_deg: float = Field(default=75.0, ge=0, le=90)  # ISS reaches about +-75 deg
    beta_period_d: float = Field(default=63.0, gt=0)  # ESTIMATE: beta(t) = beta_max sin(2 pi t / period)
    # electrical bus (RC-3)
    p_gen_kw: float = Field(default=140.0, gt=0)  # ESTIMATE, ours: array output in sunlight. Mario's 100 kW cannot carry an 80 kW load (61 % of the orbit in sun = 61 kW on average)
    base_load_kw: float = Field(default=70.8, ge=0)  # ESTIMATE: everything that is not an ECLSS actuator (80 kW total)
    battery_kwh: float = Field(default=200.0, gt=0)  # ESTIMATE: usable energy
    soc0: float = Field(default=1.0, ge=0, le=1)
    # heat through the multilayer insulation (RC-2)
    solar_const_w_m2: float = 1361.0  # [F10]
    albedo: float = 0.3  # [F10]
    ir_earth_w_m2: float = 237.0  # [F10]
    absorptivity: float = 0.3  # ESTIMATE (white paint)
    emissivity: float = 0.8  # ESTIMATE (white paint)
    earth_view_factor: float = 0.3  # ESTIMATE
    mli_attenuation: float = 0.01  # ESTIMATE: the decisive parameter of the block (50-200x insulation)


class EnvironmentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    gravity_m_s2: float = Field(ge=0)  # 0 = microgravity
    day_length_s: float = Field(default=86400.0, gt=0)
    exterior_temp_c: float
    reference_body_mass_kg: float = 82.0  # BVAD reference crew member [S2]
    atmosphere: Atmosphere
    alarm_rules: list[AlarmRule] = []
    orbit: OrbitConfig | None = None  # None: constant exterior (Mars profile)
