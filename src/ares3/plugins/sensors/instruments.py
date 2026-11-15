"""Instrument models of the ISS station (Mario's sheets 03_SENSORI and 05_TELEMETRIA_ATT).

A sensor here models only the HEALTHY device; the engine applies sensor faults (bias, drift, stuck, dropout, noise) on top.
What a healthy instrument does, in this order (guide, section 3.1):

1. first-order lag ``v += (truth - v) (1 - exp(-dt / tau))``; the datasheets give T90 = 2.303 tau
2. cross-sensitivities of the technology (an NDIR reads +0.15 % per hPa of pressure and -0.08 % per % of background O2)
3. a FIXED error of this particular unit, drawn once (``bias_sigma``): it does not average away, unlike the noise
4. slow healthy drift of the technology, back to zero at every calibration (``calibration_interval_d``)
5. Gaussian noise ``sigma``, quantisation to ``resolution``, and saturation at the range ends

``Instrument`` reads a module metric, ``ActuatorTelemetry`` a channel of an actuator (the same chain, aimed at a device
instead of the air), ``StationTelemetry`` the orbit / power bus, ``McaSensor`` is the shared slow mass spectrometer.
All numbers come from the workbook through ``tools/build_station.py``; ESTIMATE ones are marked there.
"""

from __future__ import annotations

import math
from collections import deque

from pydantic import BaseModel, ConfigDict, Field

from ares3.sdk import BaseSensor, Observation, StepContext, register
from ares3.sdk.metrics import actuator_metric, module_metric, station_metric

YEAR_S = 365.0 * 86400.0
STD_PRESSURE_HPA = 1013.25
STD_O2_PCT = 20.9
STD_TEMP_C = 22.0


class _Cross(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pressure_pct_per_hpa: float = 0.0
    oxygen_pct_per_pct: float = 0.0
    temperature_pct_per_c: float = 0.0


class _AnalogParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sigma: float = 0.0
    tau_s: float = Field(default=1.0, gt=0)
    resolution: float = 0.0
    range_min: float = -1e30
    range_max: float = 1e30
    extend_factor: float = 1.0  # NDIR: beyond the range the reading degrades, valid up to range_max * extend_factor
    bias_sigma: float = 0.0  # 1-sigma of the fixed error of this unit, in the unit of the reading
    drift_abs_per_year: float = 0.0
    drift_rel_per_year: float = 0.0  # fraction of the reading per year (negative: reads low)
    calibration_interval_d: float = Field(default=365.0, gt=0)
    warmup_s: float = 0.0  # documented; the station is simulated already warm
    cross: _Cross = _Cross()


class _Analog(BaseSensor):
    """The shared chain; subclasses provide ``_truth``."""

    Params = _AnalogParams

    def reset(self) -> None:
        p = self.params
        self.sigma = p.sigma
        self._filt: float | None = None
        self._bias = p.bias_sigma * float(self.rng.standard_normal())
        # units are not calibrated on the same day: spread the sawtooth so redundant sensors do not reset together
        self._cal_phase = float(self.rng.random()) * p.calibration_interval_d * 86400.0

    def _truth(self, ctx: StepContext) -> float:
        raise NotImplementedError

    def _cross_factor(self, ctx: StepContext) -> float:
        c = self.params.cross
        if not (c.pressure_pct_per_hpa or c.oxygen_pct_per_pct or c.temperature_pct_per_c):
            return 1.0
        m = ctx.tick.modules[self.entity_id]
        o2_pct = 100.0 * m.gas.o2 / m.pressure_kpa
        return (1.0 + c.pressure_pct_per_hpa / 100.0 * (m.pressure_kpa * 10.0 - STD_PRESSURE_HPA)
                + c.oxygen_pct_per_pct / 100.0 * (o2_pct - STD_O2_PCT)
                + c.temperature_pct_per_c / 100.0 * (m.temperature_c - STD_TEMP_C))

    def _finish(self, y: float) -> float:
        """Noise, saturation and quantisation: the end of every chain."""
        p = self.params
        y += p.sigma * float(self.rng.standard_normal())
        if y > p.range_max:  # saturation: hard, or a degraded reading for the NDIR (valid up to 3x its range)
            y = p.range_max + 0.8 * (y - p.range_max) if p.extend_factor > 1.0 else p.range_max
            y = min(y, p.range_max * max(p.extend_factor, 1.0))
        y = max(y, p.range_min)
        if p.resolution > 0:
            y = round(y / p.resolution) * p.resolution
        return y

    def _drift(self, ctx: StepContext, y: float) -> float:
        p = self.params
        t_cal = (ctx.tick.t_sim_s + self._cal_phase) % (p.calibration_interval_d * 86400.0)
        return y + p.drift_abs_per_year * t_cal / YEAR_S + abs(y) * p.drift_rel_per_year * t_cal / YEAR_S

    def _measure(self, ctx: StepContext, truth: float, dt: float) -> float:
        self._filt = truth if self._filt is None else self._filt + (truth - self._filt) * (
            1.0 - math.exp(-dt / self.params.tau_s))
        return self._finish(self._drift(ctx, self._filt * self._cross_factor(ctx) + self._bias))

    def step(self, dt: float, ctx: StepContext) -> Observation | None:
        truth = self._truth(ctx)
        return Observation(tick=ctx.tick.tick, t_s=ctx.tick.t_sim_s, sensor_id=self.id, entity_id=self.entity_id,
                           metric=self.metric, value=self._measure(ctx, truth, dt), value_true=truth)


@register("instrument")
class Instrument(_Analog):
    """An ambient probe in a module: ``target: module:<id>``, metric from ``sdk.metrics.MODULE_METRICS``."""

    def _truth(self, ctx: StepContext) -> float:
        return module_metric(ctx.tick.modules[self.entity_id], self.metric)


class _TelemetryParams(_AnalogParams):
    channel: str = ""  # the telemetry channel of the actuator


@register("actuator_telemetry")
class ActuatorTelemetry(_Analog):
    """Reads a telemetry channel an actuator publishes (``BaseActuator.telemetry``): ``target: actuator:<id>``."""

    Params = _TelemetryParams

    def _truth(self, ctx: StepContext) -> float:
        return actuator_metric(ctx.tick, self.entity_id, self.params.channel)


@register("station_telemetry")
class StationTelemetry(_Analog):
    """Orbit / electrical bus: ``target: station:<any id>``, metric from ``sdk.metrics.STATION_METRICS``."""

    def _truth(self, ctx: StepContext) -> float:
        return station_metric(ctx.tick, self.metric)


@register("hatch_position")
class HatchPosition(BaseSensor):
    """Limit switch of a hatch: ``target: hatch:<id>``, 1 = open, 0 = closed. What the crew sees against what was commanded:
    a hatch that did not move (``hatch_stuck``) shows as a mismatch with the monitor's own log."""

    def step(self, dt: float, ctx: StepContext) -> Observation | None:
        state = next(h for h in ctx.tick.hatches if h.id == self.entity_id)
        v = 1.0 if state.open else 0.0
        return Observation(tick=ctx.tick.tick, t_s=ctx.tick.t_sim_s, sensor_id=self.id, entity_id=self.entity_id,
                           metric=self.metric, value=v, value_true=v)


class _McaParams(_AnalogParams):
    modules: list[str]  # sampled in rotation through the sample distribution assembly
    cycle_s: float = Field(default=1200.0, gt=0)  # one full rotation [F26]: each module about every 20 min
    delay_s: float = Field(default=45.0, ge=0)  # transport delay in the lines
    offset_s: float = 0.0  # lets the second instrument sample other modules at the same time


@register("mca")
class McaSensor(_Analog):
    """Major constituents analyser: one slow instrument shared by 8 modules, one channel per gas.

    Each tick it only advances its delay lines; every ``cycle_s / len(modules)`` it emits ONE sample, of the next module in
    the rotation, as it was ``delay_s`` ago. The observation's ``entity_id`` is that module, so the log shows which one it
    read. The four channels of an instrument (same params) sample the same module at the same instant, like the real one.
    The lag is the line transport itself: there is no extra first-order filter.
    """

    Params = _McaParams

    def reset(self) -> None:
        super().reset()
        self._slot_s = self.params.cycle_s / len(self.params.modules)
        self._hist: dict[str, deque[float]] = {}
        self._last_slot = -1

    def step(self, dt: float, ctx: StepContext) -> Observation | None:
        p = self.params
        n_delay = max(1, round(p.delay_s / dt)) if p.delay_s > 0 else 1
        for mid in p.modules:
            self._hist.setdefault(mid, deque(maxlen=n_delay + 1)).append(module_metric(ctx.tick.modules[mid], self.metric))
        slot = int((ctx.tick.t_sim_s + p.offset_s) // self._slot_s)
        if slot == self._last_slot:
            return None
        self._last_slot = slot
        mid = p.modules[slot % len(p.modules)]
        truth = self._hist[mid][0]  # the oldest value kept: delay_s ago
        return Observation(tick=ctx.tick.tick, t_s=ctx.tick.t_sim_s, sensor_id=self.id, entity_id=mid, metric=self.metric,
                           value=self._finish(self._drift(ctx, truth + self._bias)), value_true=truth)
