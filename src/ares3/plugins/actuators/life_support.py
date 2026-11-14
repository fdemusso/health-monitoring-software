"""PLACEHOLDER - awaiting review by Mario (actuator physics and control).
Minimal controllers ported in spirit from ambientmonitor so the example station stays stable; replace
or subclass ``BaseActuator`` freely, nothing else depends on these classes (named only in the YAML).

Environmental actuators. Controllers read the SENSED value (``ctx.reading``), never the truth, so a
faulty sensor degrades the control loop exactly as it would on a real station.

Setpoints left unset default to the environment profile's nominal values (``ctx.env``), so swapping
``mars_surface`` for ``orbital_station`` needs no layout change.

Thresholds, rates and powers are ESTIMATES (owner: physicist). ambientmonitor used 1500/1000 ppm for
the scrubber, 58/48 % RH for dehumidification [S6] and a pressure band of 1.0 kPa.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ares3.sdk import BaseActuator, Command, ModuleFlow, StepContext, register


class _Hysteresis(BaseActuator):
    """Shared on/off logic: ``on`` / ``off`` commands force the state, ``auto`` returns to control."""

    def reset(self) -> None:
        self.running = False
        self.mode = "auto"

    def _apply_command(self, command: Command | None) -> None:
        if command is not None:
            self.mode = command.action

    def _decide(self, want_on: bool | None) -> bool:
        """``want_on``: True/False to switch, None to keep the current state."""
        if self.mode == "on":
            self.running = True
        elif self.mode == "off":
            self.running = False
        elif want_on is not None:
            self.running = want_on
        return self.running


# ---- CO2 scrubber -------------------------------------------------------------------------------
class _ScrubberParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor: str  # id of the ppCO2 sensor that drives it (mmHg)
    on_mmhg: float = 2.0
    off_mmhg: float = 1.0
    removal_mol_s: float = 1.0e-3  # ~4 crew at nominal activity produce ~1e-3 mol/s
    power_w: float = 150.0


@register("co2_scrubber")
class CO2Scrubber(_Hysteresis):
    Params = _ScrubberParams

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        self._apply_command(command)
        r = ctx.reading(self.params.sensor)
        want = None if r is None else (True if r > self.params.on_mmhg else False if r < self.params.off_mmhg else None)
        if not self._decide(want):
            return []
        return [ModuleFlow(module_id=self.module, mol_s={"co2": -self.params.removal_mol_s}, power_w=self.params.power_w)]


# ---- O2 generator ---------------------------------------------------------------------------------
class _O2GenParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor: str  # id of the pO2 sensor (kPa)
    setpoint_kpa: float | None = None  # None -> environment pO2 (o2_fraction * pressure)
    band_kpa: float = 0.2
    rate_mol_s: float = 5.0e-4
    power_w: float = 300.0


@register("o2_generator")
class O2Generator(_Hysteresis):
    Params = _O2GenParams

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        self._apply_command(command)
        sp = self.params.setpoint_kpa
        if sp is None:
            sp = ctx.env.atmosphere.o2_fraction * ctx.env.atmosphere.pressure_kpa
        r = ctx.reading(self.params.sensor)
        want = None if r is None else (True if r < sp - self.params.band_kpa else False if r > sp + self.params.band_kpa else None)
        if not self._decide(want):
            return []
        return [ModuleFlow(module_id=self.module, mol_s={"o2": self.params.rate_mol_s}, power_w=self.params.power_w)]


# ---- dehumidifier (condensing heat exchanger) --------------------------------------------------------
class _DehumParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor: str  # id of the RH sensor (%)
    on_rh: float = 58.0  # [S6] comfort 30-60 %
    off_rh: float = 48.0
    removal_mol_s: float = 0.01  # ~10 g/min of vapour
    power_w: float = 200.0


@register("dehumidifier")
class Dehumidifier(_Hysteresis):
    Params = _DehumParams

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        self._apply_command(command)
        r = ctx.reading(self.params.sensor)
        want = None if r is None else (True if r > self.params.on_rh else False if r < self.params.off_rh else None)
        if not self._decide(want):
            return []
        return [ModuleFlow(module_id=self.module, mol_s={"h2o": -self.params.removal_mol_s}, power_w=self.params.power_w)]


# ---- thermostat (heater / cooler) --------------------------------------------------------------------
class _ThermostatParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor: str  # id of the T sensor (degC)
    setpoint_c: float | None = None  # None -> environment temperature
    kp_w_k: float = 500.0  # proportional gain
    max_heat_w: float = 1500.0
    max_cool_w: float = 1500.0


@register("thermostat")
class Thermostat(BaseActuator):
    """Proportional heater/cooler. Command ``set`` with ``value`` changes the setpoint; ``off`` disables."""

    Params = _ThermostatParams

    def reset(self) -> None:
        self.setpoint = self.params.setpoint_c
        self.enabled = True

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        if command is not None:
            if command.action == "set" and command.value is not None:
                self.setpoint = command.value
            elif command.action in ("on", "off"):
                self.enabled = command.action == "on"
        if self.setpoint is None:
            self.setpoint = ctx.env.atmosphere.temperature_c
        r = ctx.reading(self.params.sensor)
        if not self.enabled or r is None:
            return []
        w = max(-self.params.max_cool_w, min(self.params.max_heat_w, self.params.kp_w_k * (self.setpoint - r)))
        return [ModuleFlow(module_id=self.module, heat_w=w, power_w=abs(w))]


# ---- pressure regulator (N2 make-up / relief valve) --------------------------------------------------
class _PressureParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor: str  # id of the P sensor (kPa)
    setpoint_kpa: float | None = None  # None -> environment pressure
    band_kpa: float = 0.5
    makeup_mol_s: float = 2.0e-3  # N2 added below the band
    relief_mol_s: float = 2.0e-3  # mixture vented above the band


@register("pressure_regulator")
class PressureRegulator(BaseActuator):
    Params = _PressureParams

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        sp = self.params.setpoint_kpa if self.params.setpoint_kpa is not None else ctx.env.atmosphere.pressure_kpa
        r = ctx.reading(self.params.sensor)
        if r is None:
            return []
        if r < sp - self.params.band_kpa:
            return [ModuleFlow(module_id=self.module, mol_s={"n2": self.params.makeup_mol_s})]
        if r > sp + self.params.band_kpa:
            gas = ctx.tick.modules[self.module].gas
            total = gas.o2 + gas.co2 + gas.n2 + gas.h2o
            rate = self.params.relief_mol_s
            return [ModuleFlow(module_id=self.module, mol_s={
                "o2": -rate * gas.o2 / total, "co2": -rate * gas.co2 / total,
                "n2": -rate * gas.n2 / total, "h2o": -rate * gas.h2o / total})]
        return []
