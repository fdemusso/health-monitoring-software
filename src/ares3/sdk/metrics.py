"""Named quantities that sensors and alarm rules can read from the true state."""

from __future__ import annotations

from .types import ModuleState, NPCState

MODULE_METRICS = ("T", "RH", "ppCO2", "pO2", "PIO2", "P")


def module_metric(m: ModuleState, metric: str) -> float:
    """T [degC], RH [%], ppCO2 [mmHg], pO2 [kPa], PIO2 [mmHg], P [kPa]."""
    if metric == "T":
        return m.temperature_c
    if metric == "RH":
        return m.rh_percent
    if metric == "ppCO2":
        return m.ppco2_mmhg
    if metric == "pO2":
        return m.gas.o2
    if metric == "PIO2":
        return m.pio2_mmhg
    if metric == "P":
        return m.pressure_kpa
    raise KeyError(f"unknown module metric {metric!r}; known: {MODULE_METRICS}")


def npc_metric(n: NPCState, metric: str) -> float:
    """A vital sign (``hr``, ``spo2``, ...) or one of ``met``, ``vo2_l_min``, ``vco2_l_min``, ``heat_w``."""
    if metric in n.vitals:
        return n.vitals[metric]
    if metric in ("met", "vo2_l_min", "vco2_l_min", "heat_w"):
        return float(getattr(n, metric))
    raise KeyError(f"npc {n.id} has no metric {metric!r}; vitals: {sorted(n.vitals)}")
