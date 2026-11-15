# Sources of the physiological parameters (tags [P1]..[P22])

Collected with online research on 2026-11-14. **Reliability**: A = primary or official source read directly;
B = source read only through the search engine's summary (to be checked against the text); E = ESTIMATE, no
quantitative source found. Where a source gave no number, the code contains the word ESTIMATE.

| Tag | What | Value used | Source | Rel. |
|---|---|---|---|---|
| P1 | SpO2 and time of useful consciousness versus PIO2 | PIO2->SpO2 table in `baseline.py` (99 mmHg: 85-95 %, 80: 70-85, 70: 60-70, 57: <70, 49: <65) | Hypoxic Hypoxia and Brain Function in Military Aviation, Tab. 2 - https://pmc.ncbi.nlm.nih.gov/articles/PMC8171399/ | A |
| P2 | ISS training intensity | T2 sessions ~66-75 % of peak HR (mean 70 %) -> aerobic blocks at 7.0 MET | NASA OCHMO-TB-031 https://www.nasa.gov/ochmo-tb-031-exercise-overview-2/ ; https://pmc.ncbi.nlm.nih.gov/articles/PMC7434884 | B |
| P3 | Linear %HRR - %VO2R relation | `effort = (MET-1)/(met_max-1)` | https://pubmed.ncbi.nlm.nih.gov/9502363/ | B |
| P4 | HR during sleep | 20-30 % below daytime rest (Cleveland Clinic); other sources 10-30 % -> factor 0.80 | https://health.clevelandclinic.org/sleeping-heart-rate | B |
| P5 | Normal resting values | RR 12-20 /min, SpO2 96-100 % | OpenStax Clinical Nursing Skills 15.6 https://openstax.org/books/clinical-nursing-skills/pages/15-6-respiration | A |
| P6 | Skin temperature during sleep | rises with deep sleep (bed-rest studies); magnitude +0.6 C ESTIMATE | research summary, URL not verified | E |
| P7 | HR recovery after exertion | exponential tau 65.5 +/- 12 s (40 men, maximal exertion) | https://ijpp.com/exponential-modelling-of-heart-rate-recovery-after-a-maximal-exercise/ | B |
| P8 | Fever -> HR | 7-10 bpm per C (8.5 bpm/C); +1.5 C -> +13 bpm | https://pubmed.ncbi.nlm.nih.gov/2424378/ ; https://journalfeed.org/?p=2902 | B |
| P9 | Atrial fibrillation | irregular RR, RMSSD higher than in sinus rhythm; ventricular HR >100-110 | https://onlinelibrary.wiley.com/doi/full/10.1111/eci.13361 ; https://amboss.com/us/knowledge/Atrial_fibrillation_with_rapid_ventricular_response | B |
| P10 | HR during EVA | mean 131-135 bpm, peaks ~162 (Shuttle/ISS) | NASA NTRS 19910001262 https://ntrs.nasa.gov/api/citations/19910001262/downloads/19910001262.pdf ; values read from the summary | B |
| P11 | Suit pressure | EMU 30 kPa (4.3 psia) 100 % O2; Mars/Artemis 8.2 psia with 34 % O2 (not validated) | https://www.nasa.gov/wp-content/uploads/2023/03/gernhardt-eva-ops-chp-5.4-2013.pdf ; OCHMO-TB-037 | A/B |
| P12 | CO2 | NASA-STD-3001: 1 h mean <= 3 mmHg; symptoms (headache) at 3.5 mmHg, fatigue/nausea >4.5 mmHg | https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf | A |
| P13 | Maximum HR by age | HRmax = 208 - 0.7 x age (meta-analysis, 18712 subjects, independent of sex) | Tanaka et al. 2001 https://pubmed.ncbi.nlm.nih.gov/11153730/ | A |
| P14 | Sex differences at rest | resting HR ~4 bpm higher in women (median 59 versus 55, sample of athletes); RMSSD +5 ms in women aged 20-45, difference ~2.5 ms at 45-59 | Altini https://medium.com/@altini_marco/what-is-behind-changes-in-resting-heart-rate-and-heart-rate-variability-ec3c02353373 (B) ; Lifelines https://lifelines.sites.kirra.nl/researcher/publications/reference-values-of-heart-rate-variability-from-10-second-resting-electrocardiograms-the-lifelines-cohort-study ; Koenig and Thayer 2016 meta-analysis | B |
| P15 | Circadian rhythm | HR and core temperature have a circadian rhythm; temperature minimum between 03 and 05; amplitudes (HR +-3 bpm, temperature +-0.4 C) ESTIMATE | https://pmc.ncbi.nlm.nih.gov/articles/PMC3825442 | B |
| P16 | Sleep architecture | N1 ~5 %, N2 40-55 %, N3 10-20 % (more in the first cycles), REM 20-25 % (more in the last), cycles of 90-120 min; NREM = parasympathetic dominance, REM = sympathetic | https://www.sleepfoundation.org/how-sleep-works/deep-sleep ; https://pmc.ncbi.nlm.nih.gov/articles/PMC5886429 | B |
| P17 | Dehydration | HR +3 bpm per 1 % of mass lost (3-5 in the literature); core temperature +0.12-0.25 C per 1 % | review on exercise in the heat https://www.pubmed.gov/24736771/ | B |
| P18 | Microgravity and the heart | HR +3.4 bpm in flight (2024 meta-analysis); fluid shift, plasma volume drop 10-17 %; reduced parasympathetic activity; stroke volume falling in the first 2 weeks | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11310543/ ; https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8773383/ | B |
| P19 | Space sickness | incidence 67 % on the first flight (Shuttle, 85 astronauts): 30 % mild, 24 % moderate, 13 % severe; lasts 2-3 days (up to 3-5) | https://researchexperts.utmb.edu/en/publications/space-motion-sickness-during-24-flights-of-the-space-shuttle/ ; https://ntrs.nasa.gov/citations/20050000946 | B |
| P20 | RR intervals in atrial fibrillation | AV-node models (AFVP, PhysioNet); RMSSD in AF 80-250 ms (BioGears thesis) | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1820785/ ; https://archive.physionet.org/physiotools/afvp | B |
| P21 | Time of useful consciousness (TUC) | FAA table at 18000-50000 ft (20-30 min at 18000 ft, 9 s at 50000 ft); after rapid decompression reduced to 1/3-1/2 above 30000 ft | https://www.faa.gov/pilots/training/airman_education/topics_of_interest/hypoxia ; table in https://en.wikipedia.org/wiki/Time_of_useful_consciousness (AC 61-107B to be verified) | B |
| P22 | High-concentration CO2 | 3 %: headache and dyspnea within hours; 4-6 %: headache, dizziness within 15-30 min; 7-10 %: fainting or near-fainting within a few minutes | EPA appendix B https://19january2021snapshot.epa.gov/sites/static/files/2015-06/documents/co2appendixb.pdf (Schulte 1964, Lambertsen 1971) | B |

Not found (stays ESTIMATE): quantification of stress and nausea on the vitals; SpO2 in atrial fibrillation; HR/SpO2 during
explosive decompression; quantitative respiratory response to CO2; circadian amplitudes of HR and temperature; dose thresholds for
symptoms, loss of consciousness and death (derived from the TUC table [P21] with our own factors); VO2max by sex/age of the crew members;
age and height of the 4 astronauts (not in the brief). Mifflin-St Jeor (basal metabolism) is not used: the core computes gas exchange from MET x mass.

Spaceflight: resting HR in orbit ~ the same as supine on the ground, lower systolic pressure (JACC 2023,
https://www.jacc.org/doi/10.1016/j.jacc.2023.05.058); uneven results, small samples.
