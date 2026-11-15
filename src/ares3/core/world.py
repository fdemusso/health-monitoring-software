"""Mutable physical state: a topological graph of modules with gas inventories (mol) and temperature.

No geometry: a module is a well-mixed volume; hatches exchange gas and heat. The core is the only
writer; plugins get frozen snapshots and return flows. Every mole that enters or leaves is booked in
``ledger`` so conservation can be tested (see ``tests/test_world.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ares3.schemas.environment import Atmosphere
from ares3.schemas.layout import LayoutConfig, ModuleSpec
from ares3.sdk.types import GasComposition, HatchState, ModuleState

from .constants import KELVIN, R_UNIV, SPECIES, psat_kpa

CP_AIR_MOLAR = 29.1  # J/(mol K)
RHO_CP_STP = 1200.0  # J/(m3 K) of air at 101.3 kPa (scaled with pressure)
# Combustion products are removed by the air-revitalisation filters / catalytic oxidiser. ESTIMATES: first-order, owner Mario.
CONTAMINANT_TAU_S = {"co_mol": 900.0, "smoke_mg": 300.0}
FANS_OFF_DIFFUSION = 0.1  # with the fans off the modules only exchange air by slow diffusion. ESTIMATE


@dataclass
class ModuleRT:
    spec: ModuleSpec
    temp_c: float
    n: dict[str, float]  # mol per species
    heat_in_w: float = 0.0  # accumulated this tick, integrated by ``World.step``
    heat_load_w: float = 0.0  # reported in the snapshot
    occupants: list[str] = field(default_factory=list)
    co_mol: float = 0.0  # carbon monoxide from combustion
    smoke_mg: float = 0.0  # particulates from combustion
    fans_on: bool = True

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def n_total(self) -> float:
        return sum(self.n.values())

    def partial_kpa(self, species: str) -> float:
        return self.n[species] * R_UNIV * (self.temp_c + KELVIN) / self.spec.volume_m3 / 1000.0

    @property
    def pressure_kpa(self) -> float:
        return self.n_total * R_UNIV * (self.temp_c + KELVIN) / self.spec.volume_m3 / 1000.0


@dataclass
class HatchRT:
    a: str
    b: str
    diffusion_coeff: float  # passive exchange, m3/s
    open: bool = True
    id: str = ""
    gp_open: float = 0.0  # mol/(s kPa): bulk flow driven by the pressure difference
    gp_closed: float = 0.0
    conduction_w_k: float = 0.0
    closable: bool = True
    mixing: float = 1.0  # share of the exchange that washes the breathing zone (CO2 only)
    fan_flow_m3_s: float = 0.0  # IMV / vent fan flow, added to the exchange while open
    stuck: bool = False  # a fault: open/close commands are ignored

    @property
    def exchange_m3_s(self) -> float:
        """Gas exchange now: the passive term plus the fan, only while open."""
        return self.diffusion_coeff + self.fan_flow_m3_s if self.open else 0.0


def initial_inventory(volume_m3: float, atm: Atmosphere) -> tuple[dict[str, float], float]:
    t_k = atm.temperature_c + KELVIN
    n_total = atm.pressure_kpa * 1000.0 * volume_m3 / (R_UNIV * t_k)
    n_h2o = atm.rh_percent / 100.0 * psat_kpa(atm.temperature_c) * 1000.0 * volume_m3 / (R_UNIV * t_k)
    n_o2 = atm.o2_fraction * n_total
    n_co2 = atm.co2_ppm * 1e-6 * n_total
    n_n2 = n_total - n_o2 - n_co2 - n_h2o
    if n_n2 <= 0:
        raise ValueError("atmosphere is inconsistent: o2 + co2 + vapour exceed the total pressure")
    return {"o2": n_o2, "co2": n_co2, "n2": n_n2, "h2o": n_h2o}, atm.temperature_c


class World:
    def __init__(self, layout: LayoutConfig, default_atmosphere: Atmosphere, exterior_temp_c: float) -> None:
        self.exterior_temp_c = exterior_temp_c
        self.modules: dict[str, ModuleRT] = {}
        for spec in layout.modules:
            atm = default_atmosphere
            if spec.atmosphere is not None:
                atm = Atmosphere.model_validate({**atm.model_dump(), **spec.atmosphere.model_dump(exclude_none=True)})
            n, temp = initial_inventory(spec.volume_m3, atm)
            self.modules[spec.id] = ModuleRT(spec=spec, temp_c=temp, n=n)
        self.hatches = [HatchRT(h.a, h.b, h.diffusion_coeff, h.open, h.key, h.gp_open, h.gp_closed, h.conduction_w_k,
                                h.closable, h.mixing_efficiency) for h in layout.hatches]
        self.hatch_by_id = {h.id: h for h in self.hatches}
        # cumulative booking of every transfer, mol (species-keyed) or kg: "<source>:<species>"
        self.ledger: dict[str, float] = {}

    # ---- mutation (core only) -------------------------------------------------------------
    def book(self, source: str, species: str, dn: float) -> None:
        key = f"{source}:{species}"
        self.ledger[key] = self.ledger.get(key, 0.0) + dn

    def add_moles(self, module_id: str, species: str, dn: float, source: str) -> float:
        """Add (or remove, dn<0) moles; the inventory never goes negative. Returns the amount applied."""
        m = self.modules[module_id]
        applied = max(dn, -m.n[species])
        m.n[species] += applied
        self.book(source, species, applied)
        return applied

    def add_heat(self, module_id: str, watts: float) -> None:
        self.modules[module_id].heat_in_w += watts

    def add_contaminant(self, module_id: str, which: str, amount: float) -> None:
        """``which``: ``co_mol`` or ``smoke_mg``. Not booked in the ledger (not a conserved species)."""
        m = self.modules[module_id]
        setattr(m, which, getattr(m, which) + amount)

    def set_fans(self, module_id: str, on: bool) -> None:
        self.modules[module_id].fans_on = on

    def set_hatch(self, a: str, b: str, open_: bool) -> bool:
        """Open or close a hatch; returns False when it did not move (stuck, or not closable)."""
        for h in self.hatches:
            if {h.a, h.b} == {a, b}:
                if h.stuck or (not open_ and not h.closable):
                    return False
                h.open = open_
                return True
        raise KeyError(f"no hatch {a}:{b}")

    def begin_tick(self) -> None:
        for m in self.modules.values():
            m.heat_in_w = 0.0
            m.occupants = []

    # ---- physics ---------------------------------------------------------------------------
    def step(self, dt: float) -> None:
        self._bulk_flow(dt)
        self._conduct(dt)
        self._diffuse(dt)
        self._decay(dt)
        self._thermal(dt)
        self._condense()

    def _decay(self, dt: float) -> None:
        for m in self.modules.values():
            for key, tau in CONTAMINANT_TAU_S.items():
                setattr(m, key, getattr(m, key) * math.exp(-dt / tau))

    def _bulk_flow(self, dt: float) -> None:
        """Gas moves from the higher to the lower pressure through every hatch (RC-4). Two modules joined by a
        conductance G relax their pressure difference exponentially at the rate ``k = G (1/C1 + 1/C2)``, with
        ``C = n / P`` the moles per kPa: the exact solution is applied, so it is stable however small a module is.
        The mixture that moves has the composition of the module it leaves (it is booked nowhere: it stays inside)."""
        for h in self.hatches:
            g = h.gp_open if h.open else h.gp_closed
            if g <= 0.0:
                continue
            a, b = self.modules[h.a], self.modules[h.b]
            dp = a.pressure_kpa - b.pressure_kpa
            if dp == 0.0:
                continue
            ca = a.spec.volume_m3 * 1000.0 / (R_UNIV * (a.temp_c + KELVIN))
            cb = b.spec.volume_m3 * 1000.0 / (R_UNIV * (b.temp_c + KELVIN))
            series = 1.0 / (1.0 / ca + 1.0 / cb)
            k = g * (1.0 / ca + 1.0 / cb)
            dn = dp * series * (-math.expm1(-k * dt))  # mol from a to b (negative: b to a)
            src, dst = (a, b) if dn > 0 else (b, a)
            amount = abs(dn)
            total = src.n_total
            if total <= 0.0:
                continue
            for sp in SPECIES:
                moved = amount * src.n[sp] / total
                src.n[sp] -= moved
                dst.n[sp] += moved

    def _conduct(self, dt: float) -> None:
        for h in self.hatches:
            if h.conduction_w_k > 0.0:
                w = h.conduction_w_k * (self.modules[h.a].temp_c - self.modules[h.b].temp_c)
                self.modules[h.a].heat_in_w -= w
                self.modules[h.b].heat_in_w += w

    def _diffuse(self, dt: float) -> None:
        open_h = [h for h in self.hatches if h.open]
        if not open_h:
            return
        # explicit scheme: split dt so that D*dt/V stays well below 1
        worst = max(h.exchange_m3_s / min(self.modules[h.a].spec.volume_m3, self.modules[h.b].spec.volume_m3)
                    for h in open_h)
        nsub = max(1, math.ceil(worst * dt / 0.2))
        sub = dt / nsub
        for _ in range(nsub):
            for h in open_h:
                a, b = self.modules[h.a], self.modules[h.b]
                coeff = h.exchange_m3_s * (1.0 if a.fans_on and b.fans_on else FANS_OFF_DIFFUSION)
                for key in CONTAMINANT_TAU_S:
                    flux = coeff * (getattr(a, key) / a.spec.volume_m3 - getattr(b, key) / b.spec.volume_m3) * sub
                    setattr(a, key, getattr(a, key) - flux)
                    setattr(b, key, getattr(b, key) + flux)
                for sp in SPECIES:
                    k = coeff * h.mixing if sp == "co2" else coeff  # the pocket around the face is a CO2 pocket
                    flux = k * (a.n[sp] / a.spec.volume_m3 - b.n[sp] / b.spec.volume_m3) * sub
                    a.n[sp] -= flux
                    b.n[sp] += flux
                # heat carried by the exchanged air, weighted by the sub-step share of the tick
                p_ratio = 0.5 * (a.pressure_kpa + b.pressure_kpa) / 101.3
                w = coeff * RHO_CP_STP * p_ratio * (a.temp_c - b.temp_c) * sub / dt
                a.heat_in_w -= w
                b.heat_in_w += w

    def _thermal(self, dt: float) -> None:
        for m in self.modules.values():
            cap = m.spec.thermal_mass_j_k + m.n_total * CP_AIR_MOLAR
            loss = m.spec.ua_w_k * (m.temp_c - self.exterior_temp_c)
            m.temp_c += (m.heat_in_w - loss) * dt / cap
            m.heat_load_w = m.heat_in_w

    def _condense(self) -> None:
        """Vapour above saturation condenses and leaves the air (booked in the ledger)."""
        for m in self.modules.values():
            sat_mol = psat_kpa(m.temp_c) * 1000.0 * m.spec.volume_m3 / (R_UNIV * (m.temp_c + KELVIN))
            if m.n["h2o"] > sat_mol:
                excess = m.n["h2o"] - sat_mol
                m.n["h2o"] = sat_mol
                self.book("condensed", "h2o", -excess)

    # ---- views -------------------------------------------------------------------------------
    def snapshot_module(self, m: ModuleRT) -> ModuleState:
        return ModuleState(
            id=m.id,
            volume_m3=m.spec.volume_m3,
            temperature_c=m.temp_c,
            pressure_kpa=m.pressure_kpa,
            gas=GasComposition(**{sp: m.partial_kpa(sp) for sp in SPECIES}),
            heat_load_w=m.heat_load_w,
            occupants=tuple(m.occupants),
            co_ppm=1e6 * m.co_mol / m.n_total, smoke_mg_m3=m.smoke_mg / m.spec.volume_m3, fans_on=m.fans_on,
        )

    def snapshot_hatches(self) -> tuple[HatchState, ...]:
        return tuple(HatchState(a=h.a, b=h.b, diffusion_coeff=h.exchange_m3_s if h.open else h.diffusion_coeff, open=h.open,
                                id=h.id, closable=h.closable) for h in self.hatches)

    def total_moles(self, species: str) -> float:
        return sum(m.n[species] for m in self.modules.values())
