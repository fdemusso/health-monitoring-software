"""Habitat layout: a topological graph of modules joined by hatches, plus sensors and actuators.

Ids are unique across the whole scenario (modules, NPCs, sensors, actuators, faults) so a fault can
target any of them by plain id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .environment import AlarmRule, AtmosphereOverride


class ModuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    volume_m3: float = Field(gt=0)
    # ESTIMATE defaults, to be tuned by the physicist.
    thermal_mass_j_k: float = Field(default=2.0e5, gt=0)
    ua_w_k: float = Field(default=20.0, ge=0)  # heat loss to the exterior per kelvin
    atmosphere: AtmosphereOverride | None = None  # microclimate (e.g. greenhouse); unset fields = environment value
    # "never": not alarmed at all (the crew-quarters pockets: the catalog says a fouled cabin fan raises no station alarm).
    # "occupied": alarm rules are evaluated only while someone is inside (EVA suit / vehicle volumes, whose
    # atmosphere is not the habitat's and must not alarm when empty)
    alarm_mode: Literal["always", "occupied", "never"] = "always"
    # the escape vehicle (our Soyuz): a module the crew can retreat to. Emergency rules never close a hatch
    # between a crew member and a return vehicle (docs: NASA SpaceOps 2023, "Safe Haven and Safe Return").
    return_vehicle: bool = False
    # heat released by the racks / equipment of the module (W, always on). ESTIMATE unless a source says otherwise.
    base_heat_w: float = Field(default=0.0, ge=0)
    # limits of its own, instead of the environment profile's (the EVA suit lives at 47 kPa, far from the cabin band)
    alarm_rules: list[AlarmRule] | None = None
    # nominal structural leak to space (kg of air per day at 101.3 kPa, falling with the pressure): the floor the
    # make-up valve compensates and under which a real leak must stand out. ESTIMATE (Mario: ~0.1 kg/day for the station)
    leak_kg_day: float = Field(default=0.0, ge=0)
    # outer surface seen by the orbital heat cycle (m2); None -> 4.6 V^(2/3) (cylinder), ESTIMATE calibrated on the Lab
    surface_m2: float | None = Field(default=None, gt=0)


class HatchSpec(BaseModel):
    """An edge of the graph. ``diffusion_coeff`` is the passive gas exchange (m3/s, concentration driven). The optional
    fields add what the ISS station model needs: bulk flow driven by a PRESSURE difference (``gp_*``, mol/(s kPa)),
    heat conduction through the structure, an IMV fan whose flow adds to the exchange while the hatch is open, and
    openings that cannot be closed (the crew-quarters vents)."""

    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    diffusion_coeff: float = Field(gt=0)  # m3/s of air exchanged between the modules
    open: bool = True
    id: str | None = None  # defaults to ``H-<a>-<b>``; faults and commands can target it
    gp_open: float = Field(default=0.0, ge=0)  # mol/(s kPa) while open: 0 = no pressure-driven flow (legacy layouts)
    gp_closed: float = Field(default=0.0, ge=0)  # mol/(s kPa) while closed: the seal's leak-through
    conduction_w_k: float = Field(default=0.0, ge=0)  # structural heat conduction, open or closed
    imv: str | None = None  # id of the IMV / vent fan actuator: its flow (m3/s) is added to ``diffusion_coeff`` while open
    # share of the exchange flow that actually washes the breathing zone. 1 = a well-mixed volume; below 1 it models the CO2 pocket
    # that forms around the face in microgravity (no convection): the crew-quarters vents. Applies to CO2 only (the pocket), not to humidity, smoke or heat.
    mixing_efficiency: float = Field(default=1.0, gt=0, le=1.0)
    closable: bool = True  # False: a ventilated opening, never closed (and never part of "isolate the module")

    @property
    def key(self) -> str:
        return self.id or f"H-{self.a}-{self.b}"


class SensorSpec(BaseModel):
    """``target`` is ``module:<id>``, ``npc:<id>``, ``actuator:<id>`` (telemetry of an actuator), ``hatch:<id>`` (its position switch) or ``station:<id>``
    (the orbit / power / thermal-control state of the whole station)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str  # "package.module:Class" or a registered alias
    target: str
    metric: str
    rate_hz: float = Field(default=1.0, gt=0)
    params: dict[str, Any] = {}


class SensorSet(BaseModel):
    """A rule that expands into one sensor per (target, metric), so 120 sensors do not mean 120 YAML entries.

    ``targets`` are module / NPC ids, or ``all_modules`` / ``all_npcs``. ``id_template`` may use
    ``{target}`` and ``{metric}``. ``target_type`` decides the expanded ``target``:
    ``module:<id>`` or ``npc:<id>``.
    """

    model_config = ConfigDict(extra="forbid")

    target_type: Literal["module", "npc", "actuator", "station"]  # not `on`: YAML 1.1 reads a bare `on:` key as the boolean true
    kind: str
    targets: list[str]
    metrics: list[str]
    id_template: str = "{target}_{metric}"
    rate_hz: float = Field(default=1.0, gt=0)
    params: dict[str, Any] = {}


class ActuatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    module: str
    params: dict[str, Any] = {}


class LayoutConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: list[ModuleSpec]
    hatches: list[HatchSpec] = []
    sensors: list[SensorSpec] = []
    sensor_sets: list[SensorSet] = []  # expanded into ``sensors`` when the scenario is loaded
    actuators: list[ActuatorSpec] = []

    def expand_sensor_sets(self, npc_ids: list[str]) -> LayoutConfig:
        """Return a copy where every ``SensorSet`` has become plain ``SensorSpec`` entries."""
        module_ids = [m.id for m in self.modules]
        expanded = list(self.sensors)
        for ss in self.sensor_sets:
            pool = module_ids if ss.target_type == "module" else npc_ids
            targets = pool if ss.targets in (["all_modules"], ["all_npcs"]) else ss.targets
            for t in targets:
                for metric in ss.metrics:
                    expanded.append(SensorSpec(
                        id=ss.id_template.format(target=t, metric=metric), kind=ss.kind, target=f"{ss.target_type}:{t}",
                        metric=metric, rate_hz=ss.rate_hz, params=ss.params))
        return self.model_copy(update={"sensors": expanded, "sensor_sets": []})
