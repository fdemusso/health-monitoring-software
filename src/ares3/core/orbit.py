"""Low Earth orbit: sun / eclipse cycle, electrical bus and the heat that reaches the cabin through the insulation.

Formulas are Mario's (sheet 08_CICLO_ORBITALE, requests RC-2 and RC-3). Pure functions plus one small state holder:
the engine calls ``Orbit.step`` once per tick and gets a :class:`~ares3.sdk.types.StationState` back.

* period ``T = 2 pi sqrt((R+h)^3 / mu)`` (92.8 min at 420 km, the ISS flies 92.9)
* eclipse fraction ``f_ecl(beta) = arccos(sqrt(h^2 + 2 R h) / ((R + h) cos beta)) / pi``, zero beyond the critical beta
  (69.7 deg): 36 min of shadow at beta = 0
* battery: ``dSOC/dt = (P_gen - P_load) / E_bat``, clipped to [0, 1]; generation stops in eclipse
"""

from __future__ import annotations

import math

from ares3.schemas.environment import OrbitConfig
from ares3.sdk.types import StationState

SIGMA_SB = 5.670374e-8  # W/(m2 K4)
SKIN_K = 293.15  # ESTIMATE: reference skin temperature, 20 degC


def period_s(c: OrbitConfig) -> float:
    r = c.planet_radius_km + c.altitude_km
    return 2.0 * math.pi * math.sqrt(r**3 / c.mu_km3_s2)


def critical_beta_deg(c: OrbitConfig) -> float:
    r, h = c.planet_radius_km, c.altitude_km
    return math.degrees(math.acos(math.sqrt(h * h + 2.0 * r * h) / (r + h)))


def eclipse_fraction(c: OrbitConfig, beta_deg: float) -> float:
    r, h = c.planet_radius_km, c.altitude_km
    ratio = math.sqrt(h * h + 2.0 * r * h) / ((r + h) * math.cos(math.radians(beta_deg)))
    return 0.0 if ratio >= 1.0 else math.acos(ratio) / math.pi


def flux_absorbed_w_m2(c: OrbitConfig, sun: float) -> float:
    """Flux absorbed by the skin, minus nothing: in sunlight direct + albedo + Earth IR, in eclipse the IR only."""
    s = c.solar_const_w_m2
    return (c.absorptivity * s * sun + c.absorptivity * c.albedo * s * c.earth_view_factor * sun
            + c.emissivity * c.ir_earth_w_m2)


def flux_swing_w_m2(c: OrbitConfig, sun: float, f_ecl: float) -> float:
    """Absorbed flux now, minus its average over the orbit (the average is what the insulation and the cooling loop
    already balance): what the cabin sees as a periodic disturbance."""
    mean = flux_absorbed_w_m2(c, 1.0) * (1.0 - f_ecl) + flux_absorbed_w_m2(c, 0.0) * f_ecl
    return flux_absorbed_w_m2(c, sun) - mean


class Orbit:
    def __init__(self, cfg: OrbitConfig) -> None:
        self.cfg = cfg
        self.period_s = period_s(cfg)
        self.soc = cfg.soc0
        self.sun = 1.0
        self.beta_deg = cfg.beta0_deg
        self.f_ecl = 0.0

    def beta_at(self, t_s: float) -> float:
        c = self.cfg
        return c.beta0_deg + c.beta_max_deg * math.sin(2.0 * math.pi * t_s / (c.beta_period_d * 86400.0))

    def step(self, t_s: float, dt: float, load_w: float) -> StationState:
        """Sun state at ``t_s``; the battery integrates the load of the PREVIOUS tick (actuators run after this)."""
        c = self.cfg
        self.beta_deg = self.beta_at(t_s)
        self.f_ecl = eclipse_fraction(c, self.beta_deg)
        phase = (t_s / self.period_s) % 1.0
        # the eclipse is centred on the anti-solar point: the last ``f_ecl`` of the orbit is in shadow
        self.sun = 0.0 if phase >= 1.0 - self.f_ecl else 1.0
        p_gen = c.p_gen_kw * 1000.0 * self.sun
        total_load = c.base_load_kw * 1000.0 + load_w
        self.soc = min(1.0, max(0.0, self.soc + (p_gen - total_load) * dt / (c.battery_kwh * 3.6e6)))
        return StationState(sun=self.sun, beta_deg=self.beta_deg, orbit_phase=phase, soc=self.soc, p_gen_w=p_gen,
                            p_load_w=total_load)
