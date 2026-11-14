"""Physical constants and moist-air thermodynamics (SI unless noted). Ported from ambientmonitor
``engine/shared/constants.js``. Imports nothing from the rest of the package."""

from __future__ import annotations

import math

R_UNIV = 8.314462618  # J/(mol K)

# Species handled by the engine. N2 stands for N2 plus inert gases.
SPECIES = ("o2", "co2", "n2", "h2o")
MOLAR_KG = {"o2": 0.031998, "co2": 0.04401, "n2": 0.0280134, "h2o": 0.01801528}  # kg/mol

CP_AIR = 1005.0  # J/(kg K)
L_VAP = 2.5e6  # J/kg
MMHG_PER_KPA = 7.50062
PH2O_LUNG_MMHG = 47.0  # water vapour pressure in the lungs at 37 degC [S20]
KELVIN = 273.15

# Energy equivalent of oxygen (~20.1 kJ per litre O2) and gas densities at STP, used by metabolism.
KJ_PER_L_O2 = 20.1
G_PER_L_O2 = 1.429
G_PER_L_CO2 = 1.977


def psat_kpa(temp_c: float) -> float:
    """Saturation vapour pressure of water in kPa (Magnus formula, over ice below 0 degC)."""
    if temp_c >= 0:
        pa = 610.94 * math.exp(17.625 * temp_c / (temp_c + 243.04))
    else:
        pa = 611.2 * math.exp(22.46 * temp_c / (temp_c + 272.62))
    return pa / 1000.0


def inspired_po2_mmhg(p_kpa: float, po2_kpa: float, ph2o_kpa: float) -> float:
    """PIO2 = (PB - 47 mmHg) * FO2 [S20], FO2 the dry O2 fraction ``pO2 / (P - pv)``."""
    return (p_kpa * MMHG_PER_KPA - PH2O_LUNG_MMHG) * (po2_kpa / (p_kpa - ph2o_kpa))
