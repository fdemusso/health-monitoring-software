"""MET -> O2 consumption, CO2 / vapour / heat production.

Activity table from BVAD Rev2, Tables 3-23 and 3-24 [S2] (ported from ambientmonitor
``crew/metabolism.js``): man of 82 kg, 101.3 kPa, 297.2 K. ``met`` is DERIVED from the BVAD O2 rate
(VO2 = met * 3.5 ml/kg/min), so the MET-based formulas reproduce BVAD at the reference mass (checked by
``tests/test_metabolism.py``). At reduced pressure the latent share grows (documented limit, not modelled).

``heat_sensible_w`` is SENSIBLE heat: the latent part is already in ``vapor_g_min`` and must not be
added to it. Sweat that drips and does not evaporate only goes to the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass

from ares3.schemas.crew import ActivityBlock, ActivityClass

from .constants import MOLAR_KG

_BVAD = "BVAD Rev2 Tab 3-23/3-24 [S2]; met derived from the O2 rate"

DEFAULT_ACTIVITIES: dict[str, ActivityClass] = {
    "sleep": ActivityClass(met=0.9, heat_sensible_w=44, vapor_g_min=1.08, rq=0.86, source=_BVAD),
    "nominal": ActivityClass(met=1.45, heat_sensible_w=85, vapor_g_min=1.33, rq=0.845, source=_BVAD),
    # 30 min at 75% VO2max: mean vapour 6.7-13.4 g/min [S2]; sweat 6.0 g/min tuned to 0.22 kg/day total
    "exercise_aerobic": ActivityClass(met=9.7, heat_sensible_w=131, vapor_g_min=10, sweat_g_min=6.0, rq=0.945, source=_BVAD),
    # 60 min: O2/CO2 from BVAD; heat (~200 W) and vapour (3 g/min) are ESTIMATES
    "exercise_resistive": ActivityClass(met=3.5, heat_sensible_w=200, vapor_g_min=3, rq=0.955, source=_BVAD + "; heat, vapour ESTIMATE"),
    # 60 min after exercise: mean vapour 6.9 -> 2.6 g/min
    "recovery": ActivityClass(met=1.45, heat_sensible_w=90, vapor_g_min=4.2, sweat_g_min=0.67, rq=0.845, source=_BVAD),
}

DEFAULT_ALIASES = {"work": "nominal", "rest": "nominal", "meal": "nominal", "exercise": "exercise_aerobic"}

_L_PER_MOL = 22.414  # molar volume at STP, L/mol
_ML_PER_KG_MIN_PER_MET = 3.5


@dataclass(frozen=True)
class MetabolicRates:
    met: float
    vo2_l_min: float
    vco2_l_min: float
    o2_mol_s: float  # consumed
    co2_mol_s: float  # produced
    h2o_mol_s: float  # vapour released into the air
    heat_sensible_w: float
    sweat_kg_s: float  # dripping sweat, not released into the air


def build_catalog(custom: dict[str, ActivityClass]) -> dict[str, ActivityClass]:
    return {**DEFAULT_ACTIVITIES, **custom}


def resolve_activity(name: str, catalog: dict[str, ActivityClass]) -> ActivityClass:
    if name in catalog:
        return catalog[name]
    alias = DEFAULT_ALIASES.get(name)
    if alias and alias in catalog:
        return catalog[alias]
    raise KeyError(f"unknown activity {name!r}; known: {sorted(catalog)} + aliases {sorted(DEFAULT_ALIASES)}")


def rates_for(block: ActivityBlock, catalog: dict[str, ActivityClass], body_mass_kg: float,
              ref_mass_kg: float = 82.0) -> MetabolicRates:
    """Rates for a schedule block. A block-level ``met`` rescales the class's latent/sensible rates."""
    act = resolve_activity(block.activity, catalog)
    met = block.met if block.met is not None else act.met
    scale = met / act.met
    mass_scale = body_mass_kg / ref_mass_kg
    vo2 = met * _ML_PER_KG_MIN_PER_MET * body_mass_kg / 1000.0
    vco2 = vo2 * act.rq
    return MetabolicRates(
        met=met,
        vo2_l_min=vo2,
        vco2_l_min=vco2,
        o2_mol_s=vo2 / _L_PER_MOL / 60.0,
        co2_mol_s=vco2 / _L_PER_MOL / 60.0,
        h2o_mol_s=act.vapor_g_min * scale * mass_scale / 60.0 / (MOLAR_KG["h2o"] * 1000.0),
        heat_sensible_w=act.heat_sensible_w * scale * mass_scale,
        sweat_kg_s=act.sweat_g_min * scale * mass_scale / 60.0 / 1000.0,
    )
