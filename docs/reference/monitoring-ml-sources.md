# Sources for three-state monitoring, ML and procedures

Tags used in the code (`plugins/monitor/ml/`, `plugins/monitor/detectors.py`, `core/monitor.py`, `tools/ml/`,
`scenarios/monitor_placeholder.yaml`, `docs/monitor-ui.md`). Anything without a tag is `ESTIMATE`.
Added by the software team; stays in ISS terms (never Mars). The work plan is `piano.md`.

| Tag | Source | What we use from it |
|---|---|---|
| `[R1]` | NASA, *CLD HSI Workshop - Alerts*, https://ntrs.nasa.gov/api/citations/20240003565/downloads/CLD%20HSI%20Workshop%20Alerts.pdf ; ESA, Principia mission blog (three levels plus advisory, FIRE / ΔP/Δt / ATM labels), https://blogs.esa.int/tim-peake/?p=945 | Emergency / Warning / Caution / Advisory levels (`classifier.classes`, `Emergency.alert_class`) |
| `[R2]` | NASA, *Emergency Ops History*, SpaceOps 2023, https://ntrs.nasa.gov/citations/20220019247 ; `[ICES-2025-126]` in `depressurization-sources.md` | the three emergencies (rapid depressurization, fire, toxic atmosphere); medical is a separate category |
| `[R3]` | NASA 2003, automatic responses to smoke/fire, https://ntrs.nasa.gov/api/citations/20030053429/downloads/20030053429.pdf ; SAE 2003-01-2595, *ISS Automated Safing Responses to Fire Emergencies* | cutting power to racks, module ventilation off, inhibiting O2/N2 (`power` action, fire playbook) |
| `[R4]` | NASA Ames, *Inductive Monitoring System*, https://technology.nasa.gov/patent/TOP2-175 , https://c3.ndc.nasa.gov/dashlink/static/media/publication/IMS_JACIC.pdf | data-driven monitoring, certified in ISS Mission Control: the basis of stage A (`ml/anomaly.py`) |
| `[R5]` | Hundman et al., KDD 2018, *Detecting Spacecraft Anomalies Using LSTMs and Nonparametric Dynamic Thresholding*, https://arxiv.org/abs/1802.04431 | dynamic threshold on the anomaly score (an extension if the static threshold is not enough) |
| `[R6]` | Kotowski et al. 2024, *ESA Benchmark for Anomaly Detection in Satellite Telemetry*, https://arxiv.org/abs/2406.17826 | event-wise metrics (F0.5, event recall, delay) in `tools/ml/metrics.py` |
| `[R7]` | ISS ammonia alarm, January 2015, https://spaceflightnow.com/2015/01/14/engineers-study-possible-coolant-leak-aboard-space-station/ , https://www.nasaspaceflight.com/2015/01/iss-ammonia-leak-alarm-false-indication/ | `toxic` procedure: masks, retreat, closed hatch, verification with detector tubes |
| `[R8]` | Royal College of Physicians, NEWS2, NHS summary: https://www.nwas.nhs.uk/publications/news2-national-early-warning-score | early-warning score bands (`EarlyWarningScore`); adaptation to wearables = ESTIMATE |
| `[R9]` | NASA HRP / ExMC, *Clinical Decision Support*, https://ntrs.nasa.gov/citations/20220014306 | on-board assistant that guides the crew without Earth: procedure model |
| `[R10]` | *On-board Telemetry Monitoring in Autonomous Satellites*, https://arxiv.org/abs/2604.08424 | hybrid rules + ML FDIR, explainability in the decision loop: rules stay the safety net |
| `[R11]` | NASA 2011, reorganization of the ISS Medical Checklist, https://ntrs.nasa.gov/citations/20110003477 | procedures by body system, emergency / non-emergency |
| `[R12]` | NASA, *ISS Medical Kit Checklist*, https://www.nasa.gov/wp-content/uploads/2015/03/medical_kit_checklist_-_full_release.pdf | supplies cited in the medical procedures (never doses) |
| `[R13]` | British Thoracic Society 2017, *Guideline for oxygen use in adults*, https://pmc.ncbi.nlm.nih.gov/articles/PMC5531304 | SpO2 target 94-98 % |
| `[R14]` | 100 % O2 in suspected CO poisoning; COHb half-life 74 ± 25 min, https://patient.info/doctor/emergency-medicine/carbon-monoxide-poisoning-pro , https://data.zhenzhi.com/details/1/902099600 | `co_poisoning` procedure |
| `[R15]` | Heat stroke: cool first, https://emergencycarebc.ca/clinical_resource/exertional-heat-illness , https://cgo.mod.uk/clinical-guidelines-for-operations/treatment-guidelines/environmental-injuries-exposure/heat-illness/ | `fever_or_heat` procedure |
| `[R16]` | NASA/TP-2010-216124, *Atrial Arrhythmias in Astronauts*, https://ntrs.nasa.gov/api/citations/20100021111/downloads/20100021111.pdf | `atrial_fibrillation_suspected` procedure |
| `[R17]` | IM promethazine for space motion sickness, https://ntrs.nasa.gov/citations/19930046286 , https://ntrs.nasa.gov/citations/20110020471 | `space_motion_sickness` procedure |
| `[R18]` | NEWS2 false positives from continuous wearables, https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11459982/ , https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9941897/ | score on the 5-minute MEAN, not on the sample |
| `[R19]` | ISS electrical distribution (DDCU, RPCM), https://spaceflight101.com/?p=4221 , https://ntrs.nasa.gov/citations/20050177179 | per-module power (`power` action) |

Internal sources: `notebooks/mario/ARES3_Guida_implementazione.pdf` (§6 fault catalog, clear/subtle; §8 the orbit as a clock for
the ML), `notebooks/mario/ARES3_Stazione_Sensori.xlsx` sheet `06_GUASTI` (observable signature, how to tell it apart, expected alarm,
ML label) and Luca's ECG notebook (autoencoder with a threshold on the reconstruction error).

## What is NOT validated

The simulator is ours: sensor noise and bias are largely `ESTIMATE` (`docs/station.md`). The models learn the
simulator, so the report metrics (false alarms, delays) are **simulation times on synthetic data**, not
flight performance. Time is compressed by 30x (`TIME_COMPRESSION` in `tools/build_station.py`): "24 h" simulated is about a
month of real drift. The medical scores and procedures are rebuilt from public sources and must be reviewed by Luca.
`joblib` runs code on load: only load the models we produced (`models/`).

## Sources of the medical procedures (R20-R26)

Added with `docs/procedure-mediche.md`, which holds the title, body, year and URL of each: `[R20]` NASA OCHMO-TB-004 (CO2),
`[R21]` NASA/TP-2010-216126 (CO2 in flight), `[R22]` ACC/AHA/HRS 2015 SVT guideline (terrestrial), `[R23]` ACC/AHA/ACCP/HRS 2023 AF
guideline (terrestrial, URL to be verified), `[R24]` NHS dehydration, `[R25]` NHS heat stroke, `[R26]` NASA HRP, Behavioral Medicine
report 2025.
