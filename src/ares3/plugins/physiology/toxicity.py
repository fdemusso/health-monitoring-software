"""Carbon monoxide uptake: the Coburn-Forster-Kane (CFK) model of carboxyhaemoglobin (COHb).

Sources (docs/reference/toxicology-sources.md): CFK is "the best all-around model for carboxyhaemoglobin
prediction" [T1, WHO EHC 213 s.6.3]; its differential equation is Coburn, Forster & Kane 1965 [T2]:

    Vb * d[COHb]/dt = VCO + PICO / B - [COHb] * PcO2 / (M * [O2Hb] * B)        B = 1/DLCO + PL / VA

with [COHb], [O2Hb] in mL CO / O2 per mL of blood, PICO the inspired CO partial pressure and PL = PB - 47 mmHg.
Reference parameters of an adult non-smoker [T1, EHC 213 Fig. 6]: Haldane M = 218, blood volume 5.5 L, haemoglobin
15 g/100 mL, DLCO 30 mL/min/mmHg, endogenous production 0.007 mL/min. Per-person scaling (sex, mass), the BTPS->STPD
conversion, the alveolar-ventilation formula and PcO2 are ESTIMATES or textbook formulas, marked below.

Functional hypoxia: COHb removes haemoglobin from oxygen transport. ``effective_pio2`` returns the PIO2 that would
give the same functional saturation, so the existing hypoxia dose / tachycardia terms of the model can use it.
A pulse oximeter reads COHb as oxygenated haemoglobin: the ``spo2`` vital stays as it is and ``cohb_pct`` (SpCO,
co-oximetry) is the channel that sees the poisoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from ares3.core.constants import MMHG_PER_KPA

from .baseline import SPO2_VS_PIO2, spo2_from_pio2

HALDANE_M = 218.0  # [T1]
VCO_ML_MIN = 0.007  # endogenous CO production [T1]
HB_CAPACITY_ML_G = 1.38  # mL O2 bound per g of haemoglobin (textbook 1.34-1.39)
PH2O_MMHG = 47.0  # water vapour at 37 degC
FACO2 = 0.056  # alveolar CO2 fraction: VA(BTPS) = 0.863 * VCO2 / FACO2 (textbook)
BTPS_TO_STPD = 273.15 / 310.15  # x (PB - 47) / 760 for the pressure term
MIN_VA_ML_MIN = 100.0  # keeps the lung term finite for an apnoeic / dead subject


@dataclass(frozen=True)
class CFKPerson:
    """Per-person parameters. [T1] gives the adult-male reference; the female / mass scaling is ESTIMATE."""

    blood_volume_ml: float
    hb_g_dl: float
    dlco_ml_min_mmhg: float

    @classmethod
    def from_anthropometrics(cls, sex: str | None, mass_kg: float | None) -> CFKPerson:
        mass = mass_kg or 75.0
        female = sex == "F"
        return cls(blood_volume_ml=mass * (65.0 if female else 70.0),  # ESTIMATE: 70 / 65 mL/kg
                   hb_g_dl=13.5 if female else 15.0,  # 15 [T1]; female ESTIMATE
                   dlco_ml_min_mmhg=24.0 if female else 30.0)  # 30 [T1]; female ESTIMATE (~80 %)


def alveolar_ventilation_stpd_ml_min(vco2_l_min: float, pressure_kpa: float) -> float:
    """VA from the CO2 output: VA(BTPS) = 0.863 * VCO2 / FACO2, converted to STPD for the lung term of B."""
    pb = pressure_kpa * MMHG_PER_KPA
    va_btps_l = 0.863 * vco2_l_min / FACO2
    return max(MIN_VA_ML_MIN, 1000.0 * va_btps_l * BTPS_TO_STPD * (pb - PH2O_MMHG) / 760.0)


def _capacity(person: CFKPerson) -> float:
    return HB_CAPACITY_ML_G * person.hb_g_dl / 100.0  # mL O2 per mL blood at full saturation


def _terms(person: CFKPerson, va_ml_min: float, pressure_kpa: float, pio2_mmhg: float):
    pb = pressure_kpa * MMHG_PER_KPA
    pl = pb - PH2O_MMHG
    b = 1.0 / person.dlco_ml_min_mmhg + pl / va_ml_min  # mmHg min / mL
    pc_o2 = max(10.0, pio2_mmhg - PH2O_MMHG)  # mean capillary PO2 ~ alveolar PO2: ESTIMATE
    sat = spo2_from_pio2(pio2_mmhg) / 100.0
    return pl, b, pc_o2, sat


def cohb_step(cohb_pct: float, dt_s: float, *, co_ppm: float, pressure_kpa: float, pio2_mmhg: float,
              va_ml_min: float, person: CFKPerson) -> float:
    """One explicit step of the CFK equation (time constants are hours, so dt of seconds is stable). Returns COHb %."""
    pl, b, pc_o2, sat = _terms(person, va_ml_min, pressure_kpa, pio2_mmhg)
    cap = _capacity(person)
    c = cohb_pct / 100.0 * cap  # mL CO per mL blood
    o2hb = max(1e-4, cap * sat - c)
    pico = co_ppm * 1e-6 * pl
    dc_dt_ml_min = VCO_ML_MIN + pico / b - c * pc_o2 / (HALDANE_M * o2hb * b)
    c += dc_dt_ml_min / person.blood_volume_ml * (dt_s / 60.0)
    return min(90.0, max(0.0, 100.0 * c / cap))


def cohb_equilibrium(*, co_ppm: float, pressure_kpa: float, pio2_mmhg: float, va_ml_min: float,
                     person: CFKPerson) -> float:
    """Steady state (dc/dt = 0): [COHb]/[O2Hb] = M (VCO B + PICO) / PcO2 (the Haldane relation), so with
    [COHb] + [O2Hb] = capacity * SaO2 the COHb has a closed form. Used for the resting COHb at t=0 (~0.4 %)."""
    pl, b, pc_o2, sat = _terms(person, va_ml_min, pressure_kpa, pio2_mmhg)
    ratio = HALDANE_M * (VCO_ML_MIN * b + co_ppm * 1e-6 * pl) / pc_o2
    return min(90.0, 100.0 * sat * ratio / (1.0 + ratio))


def pio2_from_spo2(spo2_pct: float) -> float:
    """Inverse of the (monotonic) SpO2 curve of the baseline model."""
    pts = SPO2_VS_PIO2
    if spo2_pct <= pts[0][1]:
        return pts[0][0]
    for (x0, y0), (x1, y1) in pairwise(pts):
        if spo2_pct <= y1:
            return x0 + (x1 - x0) * (spo2_pct - y0) / (y1 - y0)
    return pts[-1][0]


def effective_pio2(pio2_mmhg: float, cohb_pct: float) -> float:
    """PIO2 giving the same functional saturation (SaO2 - COHb): ESTIMATE of the hypoxic equivalence of CO poisoning.
    Never above the real PIO2; equal to it when there is no COHb beyond what the air already allows."""
    sat = spo2_from_pio2(pio2_mmhg)
    functional = max(0.0, sat - cohb_pct)
    return min(pio2_mmhg, pio2_from_spo2(functional))
