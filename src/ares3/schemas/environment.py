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


AlarmMetric = Literal["ppCO2", "pO2", "PIO2", "T", "RH", "P"]


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
