"""Crew configuration: astronaut profiles, daily schedules and the metabolic activity catalog."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActivityClass(BaseModel):
    """Metabolic class. Gas exchange scales from ``met`` and body mass; the rest are per-person rates
    for the reference body mass."""

    model_config = ConfigDict(extra="forbid")

    met: float = Field(gt=0)
    heat_sensible_w: float = Field(ge=0)
    vapor_g_min: float = Field(ge=0)
    sweat_g_min: float = Field(default=0.0, ge=0)
    rq: float = Field(default=0.85, gt=0)  # respiratory quotient, VCO2 / VO2
    source: str = "ESTIMATE"


class ActivityBlock(BaseModel):
    """One block of a daily schedule, in local hours. ``met`` overrides the class value (rates scale)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_h: float = Field(alias="from", ge=0, le=24)
    to_h: float = Field(alias="to", gt=0, le=24)
    activity: str
    module: str
    met: float | None = Field(default=None, gt=0)


class PhysiologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    params: dict[str, Any] = {}


class CrewMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    profile: str  # free label: commander | engineer | medic | botanist | ...
    body_mass_kg: float = Field(default=82.0, gt=0)
    sex: Literal["M", "F"] | None = None
    alias: str | None = None  # name used in the bioengineer's brief (ASTRO_01 ...)
    schedule: list[ActivityBlock]
    physiology: PhysiologySpec | None = None  # None -> CrewConfig.physiology

    @model_validator(mode="after")
    def _schedule_covers_day(self) -> CrewMember:
        blocks = sorted(self.schedule, key=lambda b: b.from_h)
        cursor = 0.0
        for b in blocks:
            if b.to_h <= b.from_h:
                raise ValueError(f"{self.id}: block {b.activity} has to <= from")
            if abs(b.from_h - cursor) > 1e-9:
                raise ValueError(f"{self.id}: schedule has a gap or overlap at hour {cursor}")
            cursor = b.to_h
        if abs(cursor - 24.0) > 1e-9:
            raise ValueError(f"{self.id}: schedule must cover 0-24 h, ends at {cursor}")
        return self


class CrewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    physiology: PhysiologySpec = PhysiologySpec(kind="ares3.plugins.physiology.baseline:BaselineModel")
    activities: dict[str, ActivityClass] = {}  # merged over the built-in catalog
    members: list[CrewMember]
