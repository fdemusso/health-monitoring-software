"""PLACEHOLDER - awaiting review by Mario (sensor physics) and Luca (wearable metrics/noise).
Reference implementation so the pipeline runs; replace or subclass ``BaseSensor`` freely, nothing else
depends on these classes (they are only named in the sensors YAML).

Standard sensors: ambient probes (lag + Gaussian noise, ported from ambientmonitor
``monitoring/sensors.js``) and wearables on an NPC.

Sensor *faults* (bias, drift, stuck, dropout, noise) are NOT modelled here: the engine applies them
on top of the value returned by ``step``.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from ares3.sdk import BaseSensor, Observation, StepContext, register
from ares3.sdk.metrics import module_metric, npc_metric

# Defaults (noise = standard deviation in the metric's unit, tau = first-order lag in s).
# T, RH, ppCO2, pO2 come from ambientmonitor MEASURES; PIO2 and P are ESTIMATES.
MODULE_DEFAULTS: dict[str, tuple[float, float]] = {
    "T": (0.1, 30.0),
    "RH": (1.0, 20.0),
    "ppCO2": (0.02, 20.0),
    "pO2": (0.05, 10.0),
    "PIO2": (0.5, 10.0),
    "P": (0.05, 5.0),
}
# Wearable noise (std, unit of the vital). ESTIMATES: to be validated with the bioengineer.
WEARABLE_NOISE: dict[str, float] = {"hr": 1.0, "hrv_rmssd": 2.0, "spo2": 0.5, "resp_rate": 0.5, "skin_temp_c": 0.1}


class _SensorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    noise: float | None = None  # override the default std
    tau_s: float | None = None  # override the default lag


@register("module_probe")
class ModuleSensor(BaseSensor):
    """Ambient probe in a module: ``target: module:<id>``, metric one of T, RH, ppCO2, pO2, PIO2, P."""

    Params = _SensorParams

    def reset(self) -> None:
        noise, tau = MODULE_DEFAULTS[self.metric]
        self._noise = self.params.noise if self.params.noise is not None else noise
        self._tau = self.params.tau_s if self.params.tau_s is not None else tau
        self._filt: float | None = None

    def step(self, dt: float, ctx: StepContext) -> Observation | None:
        truth = module_metric(ctx.tick.modules[self.entity_id], self.metric)
        if self._filt is None:
            self._filt = truth
        else:
            self._filt += (truth - self._filt) * (1.0 - math.exp(-dt / self._tau))
        value = self._filt + self._noise * float(self.rng.standard_normal())
        return Observation(tick=ctx.tick.tick, t_s=ctx.tick.t_sim_s, sensor_id=self.id, entity_id=self.entity_id,
                           metric=self.metric, value=value, value_true=truth)


@register("wearable")
class WearableSensor(BaseSensor):
    """Wearable on an astronaut: ``target: npc:<id>``, metric a vital sign (hr, spo2, resp_rate, ...)."""

    Params = _SensorParams

    def reset(self) -> None:
        default = WEARABLE_NOISE.get(self.metric, 0.0)
        self._noise = self.params.noise if self.params.noise is not None else default

    def step(self, dt: float, ctx: StepContext) -> Observation | None:
        truth = npc_metric(ctx.tick.npcs[self.entity_id], self.metric)
        value = truth + self._noise * float(self.rng.standard_normal())
        return Observation(tick=ctx.tick.tick, t_s=ctx.tick.t_sim_s, sensor_id=self.id, entity_id=self.entity_id,
                           metric=self.metric, value=value, value_true=truth)
