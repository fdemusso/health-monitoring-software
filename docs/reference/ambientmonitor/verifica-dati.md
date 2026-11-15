# Verification of the simulation data against NASA sources

Date: 15 October 2026. Subject: constants and thresholds in `scenes/habitat.json`, `engine/simulation.js`, `engine/environment.js` and the values proposed in the initial plan (`docs/plan.md`, deleted after the implementation; see `git log -- docs/plan.md`).

Method: primary NASA documents (NTRS, NSSDC, NASA-STD-3001, GISS) read in full text when available. Where only a secondary source exists I say so. Where I did a calculation myself I say so and show the working.

Legend: ✅ confirmed · ⚠️ to correct or make configurable · ❌ wrong · ❓ no NASA source found (stays an estimate).

Sources cited as [S1]…[S19], list at the end.

---

## 1. The four flagged issues

### 1.1 Estimated values in `habitat.json`

| Parameter | Current value | Verdict | Verified value / proposal | Source |
|---|---|---|---|---|
| `gravity` | 3.71 m/s² | ✅ | 3.71 equatorial; 3.73 mean | [S1] |
| `atmosphere.P`, `O2` | 101.3 kPa, 20.9% | ⚠️ | Valid for transfer vehicles. For a surface habitat NASA foresees **70.3 kPa / 26.5% O₂** (contingency EVA) or **56.5 kPa / 34% O₂** (frequent EVAs), and the vehicle must be able to work at all three setpoints. The 2026 NASA scrubber study uses 10.2 psia (70.3 kPa) for the surface habitat on Mars | [S2] §4.1.1, [S11] |
| `atmosphere.CO2` | 600 ppm | ✅ | Reasonable initial value | — |
| `atmosphere.RH` | 40% | ✅ | BVAD nominal 40% (limits 25–75%) | [S2] Tab. 4-1 |
| `atmosphere.T` | 21 °C | ✅ | BVAD nominal 296 K (291–300 K) | [S2] Tab. 4-1 |
| `envelope.uWall` | 0.05 W/m²K | ⚠️ | Plausible but optimistic. With aerogel measured in CO₂ at 10 torr (0.0126 W/mK at −27 °C, 0.0089 at −80 °C) about 25 cm are needed. On Mars MLI is "almost useless" because the gas conducts. Make the parameter a sensitivity range 0.05–0.2 | [S14], NASA suit research cited in §3 |
| `envelope.uGlass` | 0.6 W/m²K | ❓ | No NASA data found for Martian habitat windows | — |
| `envelope.hIn` | 3.0 W/m²K | ⚠️ | The value is a terrestrial convective coefficient. With g = 3.71 and reduced pressure natural convection falls (my estimate: ×0.7 for gravity, ×0.8 at 70 kPa). Internal radiative exchange is missing (~5 W/m²K between surfaces at 295 K) | my calculation |
| `envelope.structCap` | 2.0e6 J/K | ❓ | Estimate. Equivalent to ~2 t of aluminium | — |
| `envelope.shgc` | 0.4 | ❓ | Estimate | — |
| `exterior.meanK/ampK` | 213 / 35 K → −95 / −25 °C | ⚠️ | See §1.4 | [S1], [S16], [S17] |
| `exterior.sunrise/sunset` | 6 / 18 fixed | ❌ | They depend on latitude and season: `cos ω_s = −tan φ · tan δ` | [S3] |
| `exterior.directWm2` | 350 on a vertical window | ❌ | Arbitrary `sqrt(sin)` shape. The direct beam depends on `τ` and the air mass: 590·e^(−τ/cos z) | [S3] |
| `exterior.diffuseWm2` | 40 | ❌ | On Mars the diffuse part is large: at τ = 0.5, z = 20° the horizontal diffuse is ~170 W/m² (global 495, direct 325). With high τ the diffuse dominates | [S3], calculation from the f(z,τ) table |
| `leakPerDay` | 0 | ⚠️ | BVAD: **0.02 kg/day per module** nominal (0.01 realistic, 0.09 maximum). For 66 m³ at 101 kPa (~79 kg of air) that is ~2.5e-4 per day | [S2] §4.1.1, Tab. 4-1 |
| `scrubber.onPpm/offPpm` | 1500 / 1000 ppm | ⚠️ | The NASA limits are on **partial pressure**: ppCO₂ ≤ **3 mmHg** (0.4 kPa) as a 1 h mean [V2 6004]; 7-day mean < 2.5 mmHg to keep the headache risk < 1%. 1500 ppm at 101 kPa = 1.14 mmHg, at 70 kPa = 0.79 mmHg: too conservative and it changes with pressure. Control in mmHg | [S6] |
| `dehum.onRH/offRH` | 58 / 48% (previously 55 / 45%) | ✅ | NASA comfort 30–60%, health 25–75% | [S6] [V2 6012/6013] |
| `hvac.setC` | 22 °C | ✅ | Comfort 20–25 °C, health 18–27 °C | [S6] |
| `o2gen` setpoint | initial pO₂ | ✅ | Nominal ppO₂ 20.7–50.6 kPa. At 70.3/26.5% you get 18.6 kPa, in the band "measurable impairment until acclimatization" (17.2–18.6) | [S2] Tab. 4-1 |

### 1.2 Horizontal flow and convection

Verdict: ⚠️ **real limit, to be modelled**.

- NASA-STD-3001 [V2 6107] requires ventilation "sufficient to prevent the formation of CO₂ pockets and thermal pockets" [S6]. The model today cannot assess them well because lateral convective motion is missing.
- Order of magnitude (my calculation): with g = 3.71 m/s², ΔT = 1 K and height 2.5 m, the buoyancy velocity scale √(g·β·ΔT·H) is ~0.18 m/s. With an efficiency factor of 0.2–0.5 you get 0.04–0.09 m/s, the same order as the velocities induced by F1/F2 (0.08 m³/s on a section of ~10 m² ≈ 0.01 m/s mean). So lateral convection is **not negligible**, especially near cold windows (cold air descent) and heaters.
- Solution adopted (Phase 0.6 of the initial plan): buoyancy flow computed from the hydrostatic pressure of each column and projected to zero divergence with the existing `solveFlow`.

### 1.3 Day length

Verdict: ❌ **must be corrected**. The mean solar sol lasts **88,775.244 s = 24 h 39 min 35.244 s** (1.027491251 Earth days) [S5], 24.6597 h according to NSSDC [S1]. With exactly 24 h the simulation accumulates 39.6 minutes of drift per day between the Sun and the crew.

NASA GISS Mars24 formulas [S5] useful for the implementation:

- Mean anomaly: `M = 19.3870° + 0.52402075° · Δt_J2000`
- Fictitious mean Sun angle: `α_FMS = 270.3863° + 0.52403840° · Δt_J2000`
- Solar longitude: `Ls = α_FMS + (10.691° + 3e-7°·Δt)·sin M + 0.623°·sin 2M + 0.050°·sin 3M + 0.005°·sin 4M + 0.0005°·sin 5M`
- Solar declination: `δ = asin(0.42565 · sin Ls) + 0.25° · sin Ls`
- Sun–Mars distance (AU): `r = 1.52367934 · (1.00436 − 0.09309·cos M − 0.004336·cos 2M − 0.00031·cos 3M − 0.00003·cos 4M)`
- Equation of time: `EOT = 2.861°·sin 2Ls − 0.071°·sin 4Ls + 0.002°·sin 6Ls − (ν − M)`

For a simulation of a few sols it is enough to fix `Ls` at the start (it varies by ~0.5° per sol) and compute local solar time as a fraction of a sol.

### 1.4 Exterior temperature

Verdict: ⚠️ **the minimum is not wrong, it is the site that is not defined**.

| Site | Minimum | Maximum | Source |
|---|---|---|---|
| Viking 1 (22° N) | 184 K (−89 °C) | 242 K (−31 °C) | [S1] primary |
| Mars Pathfinder | 10–12 K warmer than VL1 near the ground | | Schofield et al. 1997, Science 278 |
| InSight (Elysium, 2019) | −95 °C typical | −17 °C typical | [S17] secondary |
| Curiosity (Gale) | night/day swing > 55 °C; extremes −100 °C (winter) / +15.9 °C (summer) | | [S16] swing from NASA, extremes from a secondary source |
| Global mean | 214 K (−59 °C) | | [S1] |

- The current model (213 ± 35 K → −95 / −25 °C) is close to InSight and to Gale's winter, 6 K colder than Viking 1. The real problem is that mean, amplitude, sunrise and sunset are not tied to a site and a season.
- The symmetric cosine shape is not realistic: on Mars the temperature rises quickly in the morning and falls slowly at night. MEDA (Perseverance) describes the cycle with Fourier series and thermal tides [S19]. Proposal: per-site presets and a tabular profile loadable from PDS data (REMS/MEDA).
- **Two boundary temperatures are missing**:
  - **Sky**: there is no direct measurement. NASA tested radiators with simulated skies from 185 to 248 K [S7] and used a 210 K sink in sizings [S8]. It should be kept as an uncertain parameter with a sensitivity test.
  - **Ground**: thermal inertia measured at Gale 265–375 J m⁻² K⁻¹ s⁻½ (REMS) [S15]. It matters for the floor if the habitat rests on regolith.
- **External convection**: with CO₂ at 600 Pa and 220 K, a 1 m plate with wind from 2 to 10 m/s gives h ≈ 0.3–0.7 W/m²K (my calculation, Re 2,600–13,000, laminar regime). External radiative exchange is ~2 W/m²K and dominates. A "sol-air temperature" is needed for walls and windows.

---

## 2. Verification of the values of the initial plan

### 2.1 Crew (current code in `simulation.js`)

Reference: BVAD Rev2, Tab. 3-23 (man 82 kg, 1.75 m, 101.3 kPa, 297.2 K) [S2].

| Activity | Sensible heat | Vapour | O₂ | CO₂ |
|---|---|---|---|---|
| Sleep | 160 kJ/h = 44 W | 1.08 g/min | 0.37 g/min | 0.44 g/min |
| Nominal | 306 kJ/h = 85 W | 1.33 g/min | 0.59 g/min | 0.69 g/min |
| Aerobic exercise 75% VO₂max (0–30 min) | 465–479 kJ/h ≈ 131 W | 6.7–13.4 g/min (+ sweat 1.2–11.5 g/min) | 3.99 g/min | 5.22 g/min |
| Resistive exercise (long duration) | — | — | 1.43 g/min | 1.89 g/min |
| Recovery (1 h) | 311–339 kJ/h | 6.9 → 2.6 g/min | 0.59 g/min | 0.69 g/min |
| **Daily total** | **6.28 MJ** sensible, 5.51 MJ latent | **2.27 kg** (+0.22 sweat) | **0.84 kg** | **1.01 kg** |

Long missions (Tab. 4-1): O₂ 0.90 kg/day, CO₂ 1.08 kg/day (range 0.61–1.08 and 0.74–1.31) [S2].

Problems in the current code:

- ❌ **Latent heat counted twice.** `heat: 125 W` all goes into `sQ` (sensible heat to the air) and the vapour is added separately. The latent part is already in the vapour. The correct sensible figure is 85 W nominal and 44 W asleep, i.e. ~40–80 W per person less.
- ⚠️ Sleep: O₂ 0.63 kg/day against 0.53 BVAD; vapour 1.2 against 1.56.
- ⚠️ Exercise: the factor 3.2 for 1 h does not reproduce the BVAD profile (30 min at 6.8× nominal O₂, then 1 h of recovery with high vapour).
- ⚠️ "meal" does not exist in the BVAD: treat it as nominal, plus a galley vapour source if needed.
- Note: the BVAD tables are for 101.3 kPa. At reduced pressure the latent share grows. Keep the BVAD values and document the limit.

### 2.2 O₂ generator (electrolysis)

- ✅ `17.9 MJ/kg`: it is the enthalpy at the thermoneutral voltage of **1.48 V per cell**, cited in the NASA report on the ISS OGA [S10]. Working: 4F × 31.25 mol/kg × 1.48 V = 17.85 MJ/kg.
- ✅ `η ≈ 0.7`: the OGA cells work at ~1.75 V [S10] → 21.1 MJ/kg on the stack. With power supply and auxiliaries you get ~25 MJ/kg.
- For 2 people (1.68 kg/day): ~410 W on the stack, ~480–500 W mean electrical. The heat entering the loop or the cabin is `P_el − ṁ·17.85 MJ/kg`, ~130–150 W. The ISS OGA produces up to 9.25 kg/day at 46.9 A with a power supply of over 3800 W [S10].

### 2.3 CO₂ scrubber

- ⚠️ `~150 W` is too low. The ISS CDRA is ~1000 W, of which 620 W is rejected to thermal control (NASA slide, secondary source [S12]). It removes 4.2 kg/day at 2 mmHg [S11]. For 2 people (~2 kg/day) a linear scale (my estimate) gives ~500 W.
- ⚠️ **Mars-specific (my deduction):** amine scrubbers regenerated "to vacuum" (Orion CHC) dump CO₂ to space [S11]. On Mars the exterior has ppCO₂ ≈ 0.95 × 636 Pa ≈ 4.5 mmHg, more than the cabin (2–3 mmHg), so passive dumping does not work without a pump or thermal regeneration. It is better to model a thermally regenerated sorbent system (4BMS/4BCO₂ type), with its electrical and thermal load.

### 2.4 Electrical bus and solar

| Item | Plan | Verification | Source |
|---|---|---|---|
| Irradiance at the top of the atmosphere | 590 W/m² | ✅ mean (586.2 NSSDC; 590 Appelbaum). Varies from **494 (aphelion) to 718 W/m² (perihelion)** | [S1], [S3], calculation from r(M) |
| `I_horiz = 590 · k · sin(a)` | | ❌ Ignores the atmosphere. NASA model: `G_h = G_0 · cos z · f(z,τ,al) / (1 − al)`, direct `G_b = G_0 · e^(−τ/cos z)`, diffuse = difference | [S3] |
| Noon, z = 20° | | τ 0.5 → ~495 W/m²; τ 1 → ~440; τ 2 → ~345 | [S3] Tab. I |
| Daily insolation | | 2–4 kWh/m²/sol in clear season (VL1) | [S3] |
| Optical depth | | VL1 minimum 0.35; global storms 3–9 | [S3] |
| `k_dust` = 0.6 fixed | | ❌ Mixes two phenomena. (a) Atmospheric opacity `τ`; (b) dust on the panels: typical loss **0.2% per sol** (0.05–2%), with episodic cleanings by the wind | [S13] |
| `efficiency` 0.22 | | ✅ if system-level. NASA reference: 20% cells → 15.4% system (packing 0.82, electrical losses 0.95, thermal 0.99). Modern 28–30% cells → system ~0.22 | [S8], [S2] |
| `areaM2` 50, battery 30 kWh | | ⚠️ Probably undersized (see estimate below) | my calculation |

**Loads added after the 16 October 2026 verification** (`power.loads`, estimates except the galley):

| Load | Value | Status | Source |
|---|---|---|---|
| `galley` | 960 W, 3 windows of 30 min (7:00, 12:00, 19:30 LTST), `modulable`, table position | ⚠️ power from the BVAD Shuttle galley (rehydration 0.540 kW + oven 0.360 kW + fans 0.060 kW = 0.960 kW maximum in use); the 30 min duration per meal is my ESTIMATE | [S2] §4.4.6 |
| `lighting-N`, `lighting-S` | 2 × 75 W (150 W in all), 7–23 LTST, `essential`, ceiling-mounted, one per zone | ❓ ESTIMATE: ~5 W/m² on ~27.6 m² of floor (LED). The BVAD only has crop lighting data, not habitat lighting | none |
| `water-N`, `water-S` | 140 + 60 W continuous (200 W in all), `modulable` | ❓ ESTIMATE: a forum cites a NASA article with 560 W mean (700 W in use) for ISS water recovery, **not verified on the primary** (NTRS PDF 20170008984 has only the abstract readable). Scaled to 2 people (~1/3 of the ISS crew) | not verified |

With these three loads a sol's consumption rises by ~8 kWh (galley 1.4 + lights 2.4 + water 4.8). Each load has a position (`pos`): without it, all the heat goes into the F1 supply air, which is in zone S, and zone S overheats (deviation from setpoint 1.42 K rms against 0.71, T max 27.0 °C in a test with lights and water without `pos`). The split of the water between zones was chosen in 2 sols of testing: all at N gives N 1.38 K / S 0.86 K; 100 + 100 W gives N 0.59 / S 1.50; 140 + 60 W gives N 0.77 / S 1.05 (T max 26.1 °C). The limit is per-zone cooling (F2's CHX for N, F1's for S), not the radiator: raising the area from 12 to 14 m² or the CHX UA to 100/70 W/K changes nothing. The two zones remain less accurate than before anyway (N 0.46 / S 0.71 K without the new loads).

Load estimate (mine, to tune in Phase 1): racks 300 + fans 60 + pump 60 + O₂ 500 + CO₂ ~500 + mean night heating ~500 W ≈ **1.9 kW mean ≈ 46 kWh/sol**, without lighting or water treatment. With 2–4 kWh/m²/sol × 0.22, **50–100 m²** are needed with a clear sky. With τ = 3 production falls to ~40% of the clear-sky level. In NASA's sizing (TM-106606) the habitat arrays were sized for the global storm (τ = 6) [S8].

### 2.5 Radiator

| Item | Plan | Verification | Source |
|---|---|---|---|
| ε | 0.85 | ✅ if clean. With dust at ~6 mg/cm², ε drops from ~0.9 to **~0.5** | [S7] |
| `T_sky` = T_ext − 20 K | | ❓ No measurement. NASA tests with skies between 185 and 248 K; sizings with a 210 K sink | [S7], [S8] |
| `h_conv` | 3 W/m²K | ⚠️ ~0.3–0.7 W/m²K with CO₂ at 600 Pa | my calculation |
| View factors | absent | ⚠️ The BVAD for Mars uses **vertical** radiators with silvered Teflon coating, sized for a moderate dust storm at the equator. A vertical radiator sees half sky and half ground; by day the ground is much warmer than the sky | [S2] §3.2.6 |
| Solar absorption | absent | ⚠️ Add `α · G` on the radiator face | [S9] |
| `antifreezeK` 255 K | | ⚠️ Holds for the internal water/glycol loop. In NASA's lunar habitat design the external loop uses NOVEC 7200, which freezes at 136 K and has an operating limit of 173 K. Keeping it above the limit requires continuous power (1.35–3.84 kW for 48 m² on the Moon) | [S9] |
| ~5 m² per 1 kW | | ✅ Calculation: ε 0.85, 280 K, sky 200 K → 219 W/m². With dust (ε 0.5) → 129 W/m², so ~8 m² per 1 kW | my calculation |

### 2.6 Setpoints and thermostats

- ⚠️ 18 °C at night coincides with NASA's lower health limit (18–27 °C) and is outside the comfort zone (20–25 °C) [S6]. Proposal: **20 °C at night, 22 °C by day**.

---

## 3. Values without a NASA source

These remain estimates and must be treated as sensitivity parameters, not as data: `uGlass`, `shgc`, `structCap`, `hMassGlass`, `mixing` coefficients, controller `kp`/`ki`, CHX UA, loop mass, actuator `τ`, fan power, battery efficiency, heat-pump COP (`η_carnot` 0.4), `heatPump.minLoopK` (275 K: below this loop temperature the pump does not start; previously 283 K), `external.capJK` (120 kJ/K: ~40 kg of glycol plus ~12 m² of aluminium radiant panel, previously 50 kJ/K without the panel mass). Electrical loads that a real habitat has are also missing: lighting, water treatment, galley, communications.

---

## 4. Sources

- **[S1]** NASA NSSDC, *Mars Fact Sheet*. https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html
- **[S2]** Anderson, Ewert, Keener et al., *Life Support Baseline Values and Assumptions Document*, NASA/TP-2015-218570/REV2, February 2022. https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf
- **[S3]** Appelbaum & Flood, *Solar Radiation on Mars*, NASA TM-102299 (1989), https://ntrs.nasa.gov/citations/19890018252, and update NASA TM-103623 (1990), https://ntrs.nasa.gov/citations/19910005804
- **[S4]** Appelbaum, Flood & Crutchik, *Solar Radiation on Mars: Tracking Photovoltaic Array*, NASA TM-106700 (1994). https://ntrs.nasa.gov/citations/19950004977
- **[S5]** Allison & McEwen, *A post-Pathfinder evaluation of areocentric solar coordinates…*, Planet. Space Sci. 48 (2000). https://ntrs.nasa.gov/api/citations/20000097895/downloads/20000097895.pdf · NASA GISS Mars24, algorithm: https://www.giss.nasa.gov/tools/mars24/help/algorithm.html
- **[S6]** NASA OCHMO, NASA-STD-3001 Vol. 2 technical briefs: ECLSS https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-002-eclss.pdf · Habitable atmosphere https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-003-habitable-atmosphere.pdf · CO₂ https://nasa.gov/wp-content/uploads/2023/03/co2-technical-brief-ochmo.pdf
- **[S7]** *Final Report: Mars Radiator Characterization Experimental Program*, https://ntrs.nasa.gov/api/citations/20040161545/downloads/20040161545.pdf · *The Effect of Martian Dust on Radiator Performance*, https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20040161153.pdf
- **[S8]** Withrow & Morales, *Solar-Electrochemical Power System for a Mars Mission*, NASA TM-106606 (1994). https://ntrs.nasa.gov/api/citations/19950012155/downloads/19950012155.pdf
- **[S9]** *Surface Habitat Thermal Control System Architecture and Technical Challenges Update*, IEEE Aerospace 2022. https://ntrs.nasa.gov/api/citations/20210026557/downloads/IEEE%202022%20Paper%20SH%20TCS%20Architecture%20and%20Technical%20Challenges%20Update.pdf
- **[S10]** *ISS Oxygen Generation Assembly*, ICES-2018. https://ntrs.nasa.gov/api/citations/20180006335/downloads/20180006335.pdf · *AOGA Status*, ICES-2025. https://ntrs.nasa.gov/api/citations/20250005808/downloads/ICES_2025_345%20AOGA%20Status%205%2022%2025.pdf
- **[S11]** *CO₂ Removal Technologies ESM*, ICES-2026. https://ntrs.nasa.gov/api/citations/20260005251/downloads/ICES_CO2_ESM_2026.pdf
- **[S12]** NASA slides (hosted by USEA), backup on the CDRA. Secondary source. https://usea.org/sites/default/files/event-/JAN_NASA%20DCA%207-24-2019sW2.pdf
- **[S13]** Lorenz et al., *Lander and rover histories of dust accumulation on and removal from solar arrays on Mars* (2021). https://hal.sorbonne-universite.fr/hal-03369920 · NASA NTRS on the MER arrays: https://ntrs.nasa.gov/citations/20230007029
- **[S14]** Hickey et al., *Integrated Lightweight Structure and Thermal Insulation for Mars Rover*, SAE 951523 (1995). https://saemobilus.sae.org/papers/integrated-lightweight-structure-thermal-insulation-mars-rover-951523
- **[S15]** Hamilton et al. (2014) and Martínez et al. (2014), JGR Planets, thermal inertia from REMS. https://deepblue.lib.umich.edu/items/42b22b56-f48d-4815-aec2-17faec546aad
- **[S16]** NASA Photojournal, *Seasonal Cycles in Curiosity's First Two Martian Years*. https://science.nasa.gov/photojournal/seasonal-cycles-in-curiositys-first-two-martian-years/ · extremes reported by Sky & Telescope: https://skyandtelescope.org/astronomy-news/curiosity-sees-seasonal-trends-on-mars/
- **[S17]** InSight weather reports 2019 (secondary source). https://www.space.com/mars-weather-reports-from-insight-lander.html
- **[S18]** Schofield et al., *The Mars Pathfinder ASI/MET Experiment*, Science 278 (1997), pp. 1752–1758.
- **[S19]** Munguira et al., *One Martian Year of Near-Surface Temperatures at Jezero From MEDA*, JGR Planets (2024), DOI 10.1029/2024JE008385.
- **[S20]** NASA-STD-3001, Vol. 2, Rev F, §6.2 (Tab. 6.2-1, [V2 6003], [V2 6004]). https://standards.nasa.gov/system/files/tmp/NASA-STD-3001%20Vol%202%20Rev%20F.pdf · Rev C: https://www.nasa.gov/wp-content/uploads/2020/10/2022-04-08_nasa-std-3001_vol_2_rev_c_final.pdf · OCHMO-TB-003 brief: https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-003-habitable-atmosphere.pdf

## 5. Oxygen limits for the alarms (added after the strong storm)

Text extracted from the Rev F PDF (Rev D, cited by the OCHMO brief, was not found) [S20]. The NASA limit is not on the cabin ppO₂ but on the **partial pressure of inspired oxygen**, `PIO₂ = (PB − 47 mmHg) · FO₂`, with `PB` the total pressure in mmHg and `FO₂` the **dry** O₂ fraction (47 mmHg = vapour pressure at 37 °C, 6.27 kPa [S6]).

| Tab. 6.2-1, [V2 6003] | PIO₂ (mmHg) |
|---|---|
| Normoxia, reference range | 145–155 |
| Mild hypoxia, lower limit (undefined, with health monitoring) | **127** (1 h mean) |
| Absolute lower limit of mild hypoxia | **122** (2.36 psia) |
| Hyperoxia, undefined upper limit | 356 |
| Hyperoxia, short-term limit (6–9 h, prebreathe) | 791 |

Other data from the same source: OSHA defines an atmosphere as deficient with less than 19.5% O₂ and enriched above 23.5% (normoxic PIO₂ 139–168 mmHg); the text notes that no microgravity data cover long missions with a PIO₂ of 127 mmHg, so a monitoring plan is needed. [V2 6004]: 1 h mean ppCO₂ ≤ **3 mmHg** (already used in the model). [V2 6022]: the crew must receive an alarm when pressure, humidity, temperature, ppO₂ and ppCO₂ go out of limits.

My calculations (formula above, vapour with Magnus, default scene 70.3 kPa):
- Design atmosphere (70.3 kPa, ppO₂ 18.63 kPa, 20 °C, RH 50%): PIO₂ ≈ **129 mmHg**, just above the 127 limit. With that pressure and RH the 127 mmHg threshold corresponds to ppO₂ ≈ 18.3 kPa, and the 122 mmHg one to ≈ 17.6 kPa.
- Storm screen (72.77 kPa, ppO₂ 17.72 kPa, 12.7 °C, RH 98%): PIO₂ ≈ **124 mmHg**, between 122 and 127.
- End of the 64-hour run (70.9 kPa, ppO₂ 15.6 kPa, 2 °C, RH 98%): PIO₂ ≈ **108 mmHg**, well below the absolute limit of 122.

**Alarms implemented** (`engine/monitoring/alarms.js`): `pio2_1h` if the 1 h mean of a probe's PIO₂ falls below 127 mmHg; `pio2_abs` if the instantaneous value falls below 122 mmHg; `pio2_hyper` (warning only) if it exceeds 356 mmHg, undefined upper limit. PIO₂ is computed by `inspiredPO2` (`engine/shared/constants.js`) with vapour from the probe's temperature and RH (`psat`, Magnus). The alarms read the true field, not the noisy readings, so sensor noise does not make them oscillate. With the design atmosphere the margin on the 127 mmHg limit is only ~2 mmHg: a rise in RH or a drop in ppO₂ of a few tenths of a kPa is enough to trigger the alarm.

**Values without a NASA source, to be declared as estimates in the code:** the battery reserve for life support (`lifeReserveSoc`) and the relief valve flow (`reliefKgS`).

**O₂ generator emergency setpoint (`o2gen.emergencySetpointKPa` = 18.15 kPa, ESTIMATE).** With the bus at `lifeSupportOnly` the generator aims at a lower pO₂ than the nominal one (18.63 kPa). The value corresponds to PIO₂ = 124 mmHg at 70.3 kPa, i.e. 2 mmHg above the absolute limit of 122 mmHg [S20]; the 2 mmHg margin is my choice. It is below the 127 mmHg alarm threshold (1 h mean): in an emergency the `pio2_1h` alarm fires, but not the absolute one. The reason: in a cold cabin the pO₂ falls for the same mass (13 °C against 22 °C ≈ −3%) and the PI saturated the generator at 1530 W (94% of the load) to bring it back to nominal, about 3.5 kWh of a 4.4 kWh battery left.

**Life-support reserve (`battery.lifeReserveSoc` = 0.22, ESTIMATE).** I did not find a rule in NASA-STD-3001 for the electrical reserve of life support: it is a design choice, sized on the load. Energy of a sol (default scene, τ 0.5, headless report): scrubber 0.71 kWh, O₂ generator 14.81, fan F1 0.51, fan F2 0.51, pump 1.48; sum **18.04 kWh/sol**, i.e. 0.75 kW mean. For ~12 hours: 8.8 kWh, equal to 0.22 of a 40 kWh battery. The value must be rechecked if loads or battery change. The bus serves in order `lifeSupport` > `essential` > `modulable`: life support may drain the battery down to 0, the essentials (racks, emergency heaters below 16 °C, external-loop antifreeze) stop at `lifeReserveSoc`, the modulables (heat pump, reheat, heaters above 16 °C) at `max(minSoc, lifeReserveSoc)`, because they must not eat into the reserve. Hysteresis of 5 percentage points above each threshold. `lifeSupport` priorities assigned in the scene to `scrubber`, `o2gen`, `fan:F1`, `fan:F2` (the fans' `priority` field) and `pump` (`thermal.loop.pumpPriority`).
