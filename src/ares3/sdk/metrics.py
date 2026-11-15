"""Named quantities that sensors and alarm rules can read from the true state."""

from __future__ import annotations

import math

from .types import ModuleState, NPCState, SimulationTick

MODULE_METRICS = ("T", "RH", "ppCO2", "pO2", "ppO2", "ppN2", "ppH2O", "PIO2", "P", "CO", "smoke", "dewpoint", "N2_fraction")
STATION_METRICS = ("sun", "beta", "soc", "p_gen", "p_load")


def module_metric(m: ModuleState, metric: str) -> float:
    """T [degC], RH [%], ppCO2 [mmHg], pO2 [kPa], PIO2 [mmHg], P [kPa], CO [ppm], smoke [mg/m3]."""
    if metric == "T":
        return m.temperature_c
    if metric == "RH":
        return m.rh_percent
    if metric == "ppCO2":
        return m.ppco2_mmhg
    if metric in ("pO2", "ppO2"):
        return m.gas.o2
    if metric == "ppN2":
        return m.gas.n2
    if metric == "ppH2O":
        return m.gas.h2o
    if metric == "N2_fraction":
        return 100.0 * m.gas.n2 / m.pressure_kpa
    if metric == "dewpoint":  # Magnus inverse of the vapour pressure
        pv = max(m.gas.h2o, 1e-6) * 1000.0
        g = math.log(pv / 611.2)
        return 243.12 * g / (17.62 - g)
    if metric == "PIO2":
        return m.pio2_mmhg
    if metric == "P":
        return m.pressure_kpa
    if metric == "CO":
        return m.co_ppm
    if metric == "smoke":
        return m.smoke_mg_m3
    raise KeyError(f"unknown module metric {metric!r}; known: {MODULE_METRICS}")


def npc_metric(n: NPCState, metric: str) -> float:
    """A vital sign (``hr``, ``spo2``, ...) or one of ``met``, ``vo2_l_min``, ``vco2_l_min``, ``heat_w``."""
    if metric in n.vitals:
        return n.vitals[metric]
    if metric in ("met", "vo2_l_min", "vco2_l_min", "heat_w"):
        return float(getattr(n, metric))
    raise KeyError(f"npc {n.id} has no metric {metric!r}; vitals: {sorted(n.vitals)}")


def station_metric(tick: SimulationTick, metric: str) -> float:
    st = tick.station
    if st is None:
        raise KeyError("this scenario has no orbit: no station metrics")
    table = {"sun": st.sun, "beta": st.beta_deg, "soc": 100.0 * st.soc, "p_gen": st.p_gen_w, "p_load": st.p_load_w}
    if metric not in table:
        raise KeyError(f"unknown station metric {metric!r}; known: {STATION_METRICS}")
    return table[metric]


def actuator_metric(tick: SimulationTick, actuator_id: str, channel: str) -> float:
    """A telemetry channel an actuator publishes (``BaseActuator.telemetry``)."""
    try:
        return tick.actuators[actuator_id][channel]
    except KeyError:
        raise KeyError(f"actuator {actuator_id} has no telemetry channel {channel!r}") from None
