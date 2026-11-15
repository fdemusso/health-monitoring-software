"""ECLSS of the ISS station model (Mario's sheet 04_ATTUATORI, guide section 4): CDRA, OGA, CCAA, PCA, IMV and
crew-quarters fans, and the thermal-control loop (TCS).

Same contract as the other actuators: they read SENSED values (``ctx.reading``) for control and the TRUE state of their own
module for the physics they perform (a scrubber breathes the real air), return rates, and never touch the world. Besides
the gas / heat flows each one publishes TELEMETRY (bed temperature, stack voltage, fan speed...): sensors with
``target: actuator:<id>`` turn those channels into observations, so a fault is visible in the device before the air changes.

Degradations arrive as ``actuator_degrade`` faults through ``ctx.capacity_factor``; ``actuator_offline`` stops the device
(the engine then asks ``telemetry_offline``). Numbers marked ESTIMATE are ours, the rest come from the workbook.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from ares3.core.constants import KELVIN, L_VAP, R_UNIV, psat_kpa
from ares3.sdk import BaseActuator, Command, ModuleFlow, StepContext, register

CFM_M3_S = 4.71947e-4
MMHG_PER_KPA = 7.50062
M_AIR = 0.02896  # kg/mol
CP_AIR = 1005.0  # J/(kg K)
WALL_C = 4.4  # coolant temperature of the low-temperature loop [F9]: the wall of the condensing exchanger


def _humidity_ratio(p_total_kpa: float, p_vapour_kpa: float) -> float:
    return 0.622 * p_vapour_kpa / max(p_total_kpa - p_vapour_kpa, 1e-6)


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- CDRA: CO2 scrubber -----------------------------------------------------------------------------------------
class _CdraParams(_P):
    sensor: str = ""  # command sensor (the CDRA runs continuously; kept for the record and for the data labels)
    r0_mol_s: float = 1.094e-3  # 4.16 kg CO2/day at 2.0 mmHg, 4 people, 26 CFM [F5]
    ref_mmhg: float = 2.0
    eta: float = 0.80  # ESTIMATE: only ~22 of the ~276 CFM of cabin air go through the scrubber [F28]
    exponent: float = 0.8  # fitted on 2 torr -> 4.6, 3 -> 6.8, 4 -> 7.9 kg/day [F31]
    saturation: float = 1.8  # the flow saturates at 1.8 R0 eta
    half_cycle_s: float = 8640.0  # 144 min [F22]
    swap_s: float = 60.0  # no removal while the beds swap
    power_w: float = 1000.0  # [F5]
    heat_w: float = 500.0  # into the cabin air; 620 W go to the TCS [F5]
    standby: bool = False  # True: the unit is not running until commanded ``on`` (one CDRA active is the realistic nominal)
    bed_regen_c: float = 200.0  # [F29]
    bed_cold_c: float = 20.0
    blower_a: float = 2.0  # ESTIMATE [F30]


@register("cdra")
class Cdra(BaseActuator):
    """Continuous scrubber with 144-minute half-cycles. ``R(pp) = R0 eta (pp / 2.0)^0.8``, saturated, zero during the bed
    swap: a sawtooth on ppCO2 whose period is the half-cycle. Command ``on`` wakes a standby unit, ``off`` stops it."""

    Params = _CdraParams

    def reset(self) -> None:
        self.active = not self.params.standby
        self._tele: dict[str, float] = self._idle()
        self._heater_fault: int | None = None

    def _idle(self) -> dict[str, float]:
        p = self.params
        return {"T_bed_1": p.bed_cold_c, "T_bed_2": p.bed_cold_c, "I_blower": 0.0, "pos_ASV": 0.0, "P_W": 0.0}

    def telemetry_offline(self) -> dict[str, float]:
        # the real failure of 2023: the selector valve stuck half-way, blower dead; the beds cool down
        return {**self._idle(), "pos_ASV": 0.5}

    def telemetry(self) -> dict[str, float]:
        return self._tele

    def _bed_temps(self, t: float, heater_ok: tuple[bool, bool]) -> tuple[float, float]:
        p = self.params
        k, frac = divmod(t, p.half_cycle_s)
        frac /= p.half_cycle_s
        # the bed that desorbs heats up over the first 60 % of the half-cycle and holds; the other one cools down
        heating = p.bed_cold_c + (p.bed_regen_c - p.bed_cold_c) * min(1.0, frac / 0.6)
        cooling = p.bed_cold_c + (p.bed_regen_c - p.bed_cold_c) * math.exp(-frac * 6.0)
        first_desorbs = int(k) % 2 == 0
        t1, t2 = (heating, cooling) if first_desorbs else (cooling, heating)
        if not heater_ok[0]:  # a shorted heater: that bed never gets hot
            t1 = min(t1, p.bed_cold_c + 0.35 * (p.bed_regen_c - p.bed_cold_c)) if first_desorbs else t1
        if not heater_ok[1]:
            t2 = min(t2, p.bed_cold_c + 0.35 * (p.bed_regen_c - p.bed_cold_c)) if not first_desorbs else t2
        return t1, t2

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        p = self.params
        if command is not None:
            if command.action == "on":
                self.active = True
            elif command.action == "off":
                self.active = False
            elif command.action == "auto":
                self.active = not p.standby
        t = ctx.tick.t_sim_s
        cap = ctx.capacity_factor(self.id)
        heater_ok = (True, True)
        for f in ctx.faults_for(self.id):
            if f.type == "actuator_degrade" and "heater_bed" in f.params:
                bed = int(f.params["heater_bed"])
                heater_ok = (bed != 1, bed != 2)
        t1, t2 = self._bed_temps(t, heater_ok)
        if not self.active:
            self._tele = self._idle()
            return []
        swapping = (t % p.half_cycle_s) < p.swap_s
        pp = ctx.tick.modules[self.module].ppco2_mmhg
        rate = 0.0 if swapping else p.r0_mol_s * p.eta * min(p.saturation, (max(pp, 0.0) / p.ref_mmhg) ** p.exponent) * cap
        self._tele = {"T_bed_1": t1, "T_bed_2": t2, "I_blower": p.blower_a, "P_W": p.power_w,
                      "pos_ASV": 0.5 if swapping else float(int(t // p.half_cycle_s) % 2)}
        return [ModuleFlow(module_id=self.module, mol_s={"co2": -rate}, heat_w=p.heat_w, power_w=p.power_w)]


# ---- OGA: oxygen generation (water electrolysis) ----------------------------------------------------------------
class _OgaParams(_P):
    sensor: str  # ppO2 sensor (kPa) that drives it
    on_kpa: float = 20.7
    off_kpa: float = 21.7
    rate_mol_s: float = 1.953e-3  # 5.4 kg O2/day, the nominal for 4 people [F6]
    start_delay_s: float = 900.0
    power_w: float = 3573.0
    standby_w: float = 382.0
    heat_w: float = 300.0  # into the cabin air
    i_nom_a: float = 24.0  # stack current at the nominal rate [F7]
    v_nom: float = 45.0  # ESTIMATE: split per cell [F7]
    h2_nom_pct: float = 0.02


@register("oga")
class Oga(BaseActuator):
    """Hysteresis on the sensed ppO2: ON below 20.7 kPa, OFF above 21.7, after a 900 s start-up. Production follows the
    stack current; an aged stack (``actuator_degrade``) needs more voltage for less oxygen."""

    Params = _OgaParams

    def reset(self) -> None:
        self.want = False
        self._since = 0.0
        self.mode = "auto"
        self._tele = {"V_stack": 0.0, "I_stack": 1.0, "H2_in_O2": self.params.h2_nom_pct, "Q_O2": 0.0}

    def telemetry(self) -> dict[str, float]:
        return self._tele

    def telemetry_offline(self) -> dict[str, float]:
        # the H2 sensor alarm trips and the unit shuts itself down: standby current, no oxygen
        return {"V_stack": 0.0, "I_stack": 1.0, "H2_in_O2": 3.0, "Q_O2": 0.0}

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        p = self.params
        if command is not None:
            self.mode = command.action
        r = ctx.reading(p.sensor)
        t = ctx.tick.t_sim_s
        if self.mode == "off":
            want = False
        elif self.mode == "on":
            want = True
        else:
            want = self.want if r is None else (True if r < p.on_kpa else False if r > p.off_kpa else self.want)
        if want and not self.want:
            self._since = t
        self.want = want
        if not want:
            self._tele = {"V_stack": 0.0, "I_stack": 1.0, "H2_in_O2": p.h2_nom_pct, "Q_O2": 0.0}
            return [ModuleFlow(module_id=self.module, power_w=p.standby_w)]
        if t - self._since < p.start_delay_s:  # starting up: standby power only
            self._tele = {"V_stack": 0.0, "I_stack": 1.0, "H2_in_O2": p.h2_nom_pct, "Q_O2": 0.0}
            return [ModuleFlow(module_id=self.module, power_w=p.standby_w)]
        f = ctx.capacity_factor(self.id)
        rate = p.rate_mol_s * f
        self._tele = {"V_stack": p.v_nom / math.sqrt(max(f, 0.2)), "I_stack": p.i_nom_a, "H2_in_O2": p.h2_nom_pct,
                      "Q_O2": rate * 22.414 * 60.0}  # slpm
        return [ModuleFlow(module_id=self.module, mol_s={"o2": rate}, heat_w=p.heat_w, power_w=p.power_w)]


# ---- CCAA: cabin air assembly (temperature and humidity) ----------------------------------------------------------
class _CcaaParams(_P):
    sensor: str  # T sensor (degC)
    setpoint_c: float = 22.0
    q_max_w: float = 2500.0  # sensible [F8]
    kp_w_k: float = 1000.0  # ESTIMATE: proportional gain
    deadband_k: float = 0.5
    fan_cfm: float = 300.0  # 200-400 CFM per module [F26][F33]
    fan_rpm: float = 5700.0
    fan_a: float = 1.2
    cond_max_kg_h: float = 1.2  # [F8]
    fan_power_w: float = 120.0
    power_w: float = 500.0


@register("ccaa")
class Ccaa(BaseActuator):
    """Proportional cooling of the cabin air plus a condensing exchanger. Condensate forms where the moist-air humidity
    ratio is above that of saturated air at the wall temperature of the cold loop: ``m = max(0, w_in - w_sat(wall)) m_air``
    (RC-7). A fouled fan (``component: fan``) moves less air; a hydrophobic coating (``component: chx``) condenses less and
    finally carries liquid water downstream. The cold loop temperature comes from the ``TCS`` actuator when there is one."""

    Params = _CcaaParams

    def reset(self) -> None:
        self.enabled = True
        self.setpoint = self.params.setpoint_c
        self._tele = {"rpm": self.params.fan_rpm, "I": self.params.fan_a, "T_out": 12.0, "cond_kg_h": 0.0, "liq": 0.0,
                      "q_removed_w": 0.0}

    def telemetry(self) -> dict[str, float]:
        return self._tele

    def telemetry_offline(self) -> dict[str, float]:
        return {"rpm": 0.0, "I": 0.0, "T_out": 22.0, "cond_kg_h": 0.0, "liq": 0.0, "q_removed_w": 0.0}

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        p = self.params
        if command is not None:
            if command.action == "set" and command.value is not None:
                self.setpoint = command.value
            elif command.action in ("on", "off"):
                self.enabled = command.action == "on"
        m = ctx.tick.modules[self.module]
        fan = ctx.capacity_factor(self.id, "fan")
        chx = ctx.capacity_factor(self.id, "chx")
        loop = ctx.tick.actuators.get("TCS", {}).get("T_loop", WALL_C)
        t_air = m.temperature_c
        flow_kg_s = p.fan_cfm * CFM_M3_S * fan * m.pressure_kpa * 1000.0 * M_AIR / (R_UNIV * (t_air + KELVIN))
        # sensible: proportional on the SENSED temperature; the exchanger works on the air-to-coolant difference
        r = ctx.reading(p.sensor)
        t_ctl = t_air if r is None else r
        exch = min(1.5, max(0.0, (t_air - loop) / (p.setpoint_c - WALL_C)))
        q_sens = 0.0
        if self.enabled:
            q_sens = min(p.q_max_w * fan * exch, max(0.0, p.kp_w_k * (t_ctl - self.setpoint + p.deadband_k)))
        # latent: condensation on the wall
        cond_kg_s = 0.0
        if self.enabled and flow_kg_s > 0:
            w_in = _humidity_ratio(m.pressure_kpa, m.gas.h2o)
            w_sat = _humidity_ratio(m.pressure_kpa, psat_kpa(loop))
            cond_kg_s = min(p.cond_max_kg_h / 3600.0, max(0.0, (w_in - w_sat) * flow_kg_s)) * chx
        q_lat = cond_kg_s * L_VAP
        self._tele = {
            "rpm": p.fan_rpm if self.enabled else 0.0,
            "I": p.fan_a * (0.55 + 0.45 * fan) if self.enabled else 0.0,  # less air, less aerodynamic load
            "T_out": t_air - (q_sens / (flow_kg_s * CP_AIR) if flow_kg_s > 0 else 0.0),
            "cond_kg_h": cond_kg_s * 3600.0,
            "liq": 1.0 if chx < 0.45 and w_in_wet(m) else 0.0,
            "q_removed_w": q_sens + q_lat,
        }
        if not self.enabled:
            return []
        return [ModuleFlow(module_id=self.module, mol_s={"h2o": -cond_kg_s / 0.01801528},
                           heat_w=p.fan_power_w - q_sens, power_w=p.power_w)]


def w_in_wet(m) -> bool:
    """Carry-over of liquid water downstream needs wet air at the exchanger: humid cabin (relative humidity above 55 %)."""
    return m.rh_percent > 55.0


# ---- PCA: N2 make-up and relief valve ---------------------------------------------------------------------------
class _PcaParams(_P):
    sensor: str  # total pressure sensor (kPa)
    on_kpa: float = 97.9  # [F2]
    off_kpa: float = 99.5
    relief_kpa: float = 102.7
    makeup_mol_s: float = 1.0e-2  # 24.2 kg N2/day: ESTIMATE
    relief_mol_s: float = 5.0e-3  # ESTIMATE
    tank_mol: float = 12000.0  # ESTIMATE: ~340 kg of N2 in the high-pressure tanks
    tank_kpa: float = 20000.0


@register("pca")
class Pca(BaseActuator):
    """Make-up N2 below 97.9 kPa (closing at 99.5) and a relief valve above 102.7. The signal to watch is how OFTEN the
    valve opens: it does not depend on the pressure sensors' bias or drift. Commands: ``off`` (stop gas introduction),
    ``on`` (valve forced open: the stuck-open failure), ``auto``."""

    Params = _PcaParams

    def reset(self) -> None:
        self.mode = "auto"
        self.open = False
        self.used_mol = 0.0
        self._tele = {"pos_N2": 0.0, "P_tank_N2": self.params.tank_kpa}

    def telemetry(self) -> dict[str, float]:
        return self._tele

    def telemetry_offline(self) -> dict[str, float]:
        return {"pos_N2": 0.0, "P_tank_N2": self._tele["P_tank_N2"]}  # a valve stuck closed

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        p = self.params
        if command is not None:
            self.mode = command.action
        r = ctx.reading(p.sensor)
        if self.mode == "off":
            self.open = False
        elif self.mode == "on":
            self.open = True
        elif r is not None:
            self.open = True if r < p.on_kpa else False if r > p.off_kpa else self.open
        flows: list[ModuleFlow] = []
        if self.open and self.used_mol < p.tank_mol:
            self.used_mol += p.makeup_mol_s * dt
            flows.append(ModuleFlow(module_id=self.module, mol_s={"n2": p.makeup_mol_s}))
        elif self.mode != "off" and r is not None and r > p.relief_kpa:
            g = ctx.tick.modules[self.module].gas
            total = g.o2 + g.co2 + g.n2 + g.h2o
            flows.append(ModuleFlow(module_id=self.module, mol_s={
                "o2": -p.relief_mol_s * g.o2 / total, "co2": -p.relief_mol_s * g.co2 / total,
                "n2": -p.relief_mol_s * g.n2 / total, "h2o": -p.relief_mol_s * g.h2o / total}))
        self._tele = {"pos_N2": 1.0 if self.open else 0.0,
                      "P_tank_N2": p.tank_kpa * max(0.0, 1.0 - self.used_mol / p.tank_mol)}
        return flows


# ---- IMV and crew-quarters fans ---------------------------------------------------------------------------------------
class _FanParams(_P):
    nominal_cfm: float = 140.0  # [F25]
    rpm: float = 8511.0  # fixed speed [F25]
    current_a: float = 0.8  # ESTIMATE
    power_w: float = 50.0  # ESTIMATE


@register("fan")
class Fan(BaseActuator):
    """Fixed-speed fan that sets the gas exchange of one hatch (the hatch lists it under ``imv``): ``hatch_flow_m3_s`` is
    its flow. Degraded (debris, ``actuator_degrade``) it keeps its speed and moves less air. ``off`` / ``on`` command it."""

    Params = _FanParams

    def reset(self) -> None:
        self.running = True
        self._k = 1.0

    def hatch_flow_m3_s(self) -> float | None:
        return self.params.nominal_cfm * CFM_M3_S * self._k if self.running else 0.0

    def telemetry(self) -> dict[str, float]:
        p = self.params
        if not self.running:
            return {"rpm": 0.0, "I": 0.0, "Q_cfm": 0.0}
        return {"rpm": p.rpm, "I": p.current_a * (0.75 + 0.25 * self._k), "Q_cfm": p.nominal_cfm * self._k}

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        if command is not None and command.action in ("on", "off"):
            self.running = command.action == "on"
        self._k = ctx.capacity_factor(self.id)
        if not self.running:
            return []
        return [ModuleFlow(module_id=self.module, power_w=self.params.power_w)]


# ---- TCS: thermal control (ammonia loops and radiators) -----------------------------------------------------------------
class _TcsParams(_P):
    capacity_w: float = 70000.0  # two loops of 35 kW [F9]
    base_load_w: float = 32000.0  # ESTIMATE: avionics and cold plates that are not a cabin heat exchanger
    loop_heat_capacity_j_k: float = 3.0e6  # ESTIMATE
    nominal_c: float = WALL_C  # temperature the mixing valves regulate [F9]
    radiator_gain_per_k: float = 0.03  # ESTIMATE: radiators reject more when the loop is warmer
    t_rad_out_c: float = 2.8  # [F9]


@register("tcs")
class Tcs(BaseActuator):
    """Lumped cold loop: it takes the heat the CCAAs remove plus a fixed base load and rejects at most ``capacity_w``
    (the radiators reject more when warmer). While it keeps up the loop is held at 4.4 degC; beyond its capacity (one ammonia
    loop lost: ``actuator_degrade`` fraction 0.5) the loop warms, the CCAAs lose their driving temperature difference
    and the whole station heats up slowly. The CCAAs read the loop temperature from this actuator's telemetry."""

    Params = _TcsParams

    def reset(self) -> None:
        self.t_loop = self.params.nominal_c
        self._tele = {"T_loop": self.t_loop, "Q_tot": 0.0, "T_rad_out": self.params.t_rad_out_c}

    def telemetry(self) -> dict[str, float]:
        return self._tele

    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]:
        p = self.params
        q_in = p.base_load_w + sum(ch.get("q_removed_w", 0.0) for ch in ctx.tick.actuators.values())
        cap = p.capacity_w * ctx.capacity_factor(self.id) * (1.0 + p.radiator_gain_per_k * (self.t_loop - p.nominal_c))
        if q_in > cap:
            self.t_loop += (q_in - cap) * dt / p.loop_heat_capacity_j_k
        elif self.t_loop > p.nominal_c:
            self.t_loop = max(p.nominal_c, self.t_loop - (cap - q_in) * dt / p.loop_heat_capacity_j_k)
        sun = ctx.tick.station.sun if ctx.tick.station is not None else 1.0
        # ESTIMATE: the outlet follows the heat load and dips in eclipse (the radiators see cold space and nothing else)
        t_out = p.t_rad_out_c + 6.0 * (q_in - 30000.0) / p.capacity_w - 3.0 * (1.0 - sun) + (self.t_loop - p.nominal_c)
        self._tele = {"T_loop": self.t_loop, "Q_tot": min(q_in, cap), "T_rad_out": t_out}
        return []
