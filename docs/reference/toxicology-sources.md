# Toxicology sources (CO, smoke, ammonia)

Tags used in the code (`plugins/physiology/toxicity.py`, `scenarios/monitor_placeholder.yaml`). Anything without a tag is `ESTIMATE`.
Added by the software team, **to be reviewed with the bioengineer**: Luca's model (`human.py`) now reads CO through this module.

| Tag | Source | What we use from it |
|---|---|---|
| [T1] | WHO/IPCS, *Environmental Health Criteria 213: Carbon Monoxide* (2nd ed., 1999), ch. 6.3 and Fig. 6. https://www.inchem.org/documents/ehc/ehc/ehc213.htm | The CFK model is "the best overall model" for COHb. Parameters of a non-smoking adult: Haldane M = 218, blood volume 5.5 L, hemoglobin 15 g/100 mL, diffusing capacity 30 mL/min/mmHg, endogenous production 0.007 mL/min, alveolar ventilation 10 (rest) and 20 L/min (light activity) in their example. Elimination half-life 2-6.5 h |
| [T2] | Coburn RF, Forster RE, Kane PB. *J Clin Invest* 1965;44:1899. | Differential equation: `Vb d[COHb]/dt = VCO + PICO/B - [COHb] PcO2 / (M [O2Hb] B)`, `B = 1/DLCO + PL/VA`. The form is the one in the literature (the EHC 213 text does not give it: it is an image); the numbers are checked against known values (see `tests/test_toxicity.py`) |
| [T3] | NASA JSC 20584 Rev C, *Spacecraft Maximum Allowable Concentrations* (13/06/2024). https://www.nasa.gov/wp-content/uploads/2024/06/jsc-20584-smacs-rev-c-final.pdf | CO: 425 ppm (1 h), 100 (24 h), 55 (7 d), 15 (30 d, 180 d, 1000 d); target: central nervous system and arrhythmia (COHb). Ammonia: 30 / 20 / 3 / 3 / 3 ppm, irritation and headache. HCN and HCl: "Not Set" |
| [T4] | ISO 13571:2012 and SFPE Handbook, in the IFV/NIPV summary. https://archief.nipv.nl/documenten/appendix-1-comparison-between-the-iso-standard-sfpe-handbook-and-aegl | FED (not implemented yet): `FED = sum[CO*vCO2/35000 + HCN^2.36*vCO2/1.2e6] dt`, `vCO2 = exp(%CO2/5)`; SFPE CO `3.317e-5 CO^1.036 vE t / D` with D = 30 %COHb; low O2 `t/exp(8.13-0.54(20.9-%O2))`. Uncertainty ±35 % |
| [T5] | Purser DA, *Modelling Toxic and Physical Hazard in Fire*, Fire Safety Science 2 (1989). https://publications.iafss.org/publications/fss/2/391 | Origin of the FED method |
| [T6] | NASA, *Impacts of an ammonia leak on the cabin atmosphere of the ISS* (NTRS 20120007777) | Operational thresholds: 65 mg/m³ to take off the respirator once the concentration falls; 800 mg/m³ respirator limit |

## Our estimates (to be validated)

- Per-person scaling: blood volume 70 (M) / 65 (F) mL/kg; hemoglobin 13.5 g/dL (F); diffusing capacity 24 mL/min/mmHg (F, about 80 %).
- Alveolar ventilation from the engine's VCO2: `VA(BTPS) = 0.863 VCO2 / FACO2`, FACO2 = 0.056 (textbook formula), then BTPS→STPD.
- Capillary O2 pressure ≈ PIO2 − 47 mmHg.
- **Functional hypoxia**: the functional saturation is `SaO2 − COHb`; it is converted into an equivalent PIO2 with the base model's SpO2/PIO2 curve, which feeds the hypoxia dose and the tachycardia.
- **Pulse oximeter**: the pulse-ox reads COHb as oxygenated hemoglobin, so `spo2` does not drop with CO. The channel that sees it is `cohb_pct` (SpCO, co-oximetry). General physiology knowledge, not from these sources.
- Monitor thresholds: COHb 5 % (warning) and 15 % (critical), SpO2 < 90 %, core temperature > 38.5 °C.
- Not modelled: HCN (our fire does not produce it), myoglobin (10-50 % of body CO may be extravascular), the effects of altitude and maximal exercise on diffusion, high-concentration ammonia (no dose-response model found).
