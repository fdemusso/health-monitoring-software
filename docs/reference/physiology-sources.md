# Fonti dei parametri fisiologici (tag [P1]..[P22])

Raccolte con ricerca online il 2026-11-14. **Affidabilita**: A = fonte primaria o ufficiale letta direttamente;
B = fonte letta solo tramite il riassunto del motore di ricerca (da verificare sul testo); E = ESTIMATE, nessuna fonte
quantitativa trovata. Dove una fonte non dava un numero, nel codice c'e' la parola ESTIMATE.

| Tag | Cosa | Valore usato | Fonte | Aff. |
|---|---|---|---|---|
| P1 | SpO2 e tempo di coscienza utile contro PIO2 | tabella PIO2->SpO2 in `baseline.py` (99 mmHg: 85-95 %, 80: 70-85, 70: 60-70, 57: <70, 49: <65) | Hypoxic Hypoxia and Brain Function in Military Aviation, Tab. 2 - https://pmc.ncbi.nlm.nih.gov/articles/PMC8171399/ | A |
| P2 | Intensita allenamento ISS | sessioni T2 ~66-75 % del picco di FC (media 70 %) -> blocchi aerobici a 7.0 MET | NASA OCHMO-TB-031 https://www.nasa.gov/ochmo-tb-031-exercise-overview-2/ ; https://pmc.ncbi.nlm.nih.gov/articles/PMC7434884 | B |
| P3 | Relazione %HRR - %VO2R lineare | `effort = (MET-1)/(met_max-1)` | https://pubmed.ncbi.nlm.nih.gov/9502363/ | B |
| P4 | FC nel sonno | 20-30 % sotto il riposo diurno (Cleveland Clinic); altre fonti 10-30 % -> fattore 0.80 | https://health.clevelandclinic.org/sleeping-heart-rate | B |
| P5 | Valori normali a riposo | FR 12-20 /min, SpO2 96-100 % | OpenStax Clinical Nursing Skills 15.6 https://openstax.org/books/clinical-nursing-skills/pages/15-6-respiration | A |
| P6 | Temperatura cutanea nel sonno | sale col sonno profondo (studi di bed rest); entita' +0.6 C ESTIMATE | riassunto di ricerca, URL non verificato | E |
| P7 | Recupero FC dopo sforzo | tau esponenziale 65.5 +/- 12 s (40 uomini, sforzo massimale) | https://ijpp.com/exponential-modelling-of-heart-rate-recovery-after-a-maximal-exercise/ | B |
| P8 | Febbre -> FC | 7-10 bpm per C (8.5 bpm/C); +1.5 C -> +13 bpm | https://pubmed.ncbi.nlm.nih.gov/2424378/ ; https://journalfeed.org/?p=2902 | B |
| P9 | Fibrillazione atriale | RR irregolari, RMSSD piu' alto che in ritmo sinusale; FC ventricolare >100-110 | https://onlinelibrary.wiley.com/doi/full/10.1111/eci.13361 ; https://amboss.com/us/knowledge/Atrial_fibrillation_with_rapid_ventricular_response | B |
| P10 | FC durante EVA | media 131-135 bpm, picchi ~162 (Shuttle/ISS) | NASA NTRS 19910001262 https://ntrs.nasa.gov/api/citations/19910001262/downloads/19910001262.pdf ; valori letti dal riassunto | B |
| P11 | Pressione tuta | EMU 30 kPa (4.3 psia) O2 100 %; Mars/Artemis 8.2 psia con 34 % O2 (non validato) | https://www.nasa.gov/wp-content/uploads/2023/03/gernhardt-eva-ops-chp-5.4-2013.pdf ; OCHMO-TB-037 | A/B |
| P12 | CO2 | NASA-STD-3001: media 1 h <= 3 mmHg; sintomi (mal di testa) a 3.5 mmHg, stanchezza/nausea >4.5 mmHg | https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf | A |
| P13 | FC massima per eta' | HRmax = 208 - 0.7 x eta' (meta-analisi, 18712 soggetti, indipendente da sesso) | Tanaka et al. 2001 https://pubmed.ncbi.nlm.nih.gov/11153730/ | A |
| P14 | Differenze di sesso a riposo | FC a riposo ~4 bpm piu' alta nelle donne (mediana 59 contro 55, campione di sportivi); RMSSD +5 ms nelle donne di 20-45 anni, differenza ~2.5 ms a 45-59 anni | Altini https://medium.com/@altini_marco/what-is-behind-changes-in-resting-heart-rate-and-heart-rate-variability-ec3c02353373 (B) ; Lifelines https://lifelines.sites.kirra.nl/researcher/publications/reference-values-of-heart-rate-variability-from-10-second-resting-electrocardiograms-the-lifelines-cohort-study ; meta-analisi Koenig e Thayer 2016 | B |
| P15 | Ritmo circadiano | FC e temperatura centrale hanno ritmo circadiano; minimo di temperatura tra le 03 e le 05; ampiezze (FC +-3 bpm, temperatura +-0.4 C) ESTIMATE | https://pmc.ncbi.nlm.nih.gov/articles/PMC3825442 | B |
| P16 | Architettura del sonno | N1 ~5 %, N2 40-55 %, N3 10-20 % (piu' nei primi cicli), REM 20-25 % (piu' negli ultimi), cicli di 90-120 min; NREM = dominanza parasimpatica, REM = simpatica | https://www.sleepfoundation.org/how-sleep-works/deep-sleep ; https://pmc.ncbi.nlm.nih.gov/articles/PMC5886429 | B |
| P17 | Disidratazione | FC +3 bpm per 1 % di massa persa (3-5 in letteratura); temperatura centrale +0.12-0.25 C per 1 % | revisione sull'esercizio al caldo https://www.pubmed.gov/24736771/ | B |
| P18 | Microgravita' e cuore | FC +3.4 bpm in volo (meta-analisi 2024); spostamento di fluidi, calo del volume plasmatico 10-17 %; attivita' parasimpatica ridotta; gittata sistolica in calo nelle prime 2 settimane | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11310543/ ; https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8773383/ | B |
| P19 | Mal di spazio | incidenza 67 % al primo volo (Shuttle, 85 astronauti): 30 % lieve, 24 % moderato, 13 % severo; dura 2-3 giorni (fino a 3-5) | https://researchexperts.utmb.edu/en/publications/space-motion-sickness-during-24-flights-of-the-space-shuttle/ ; https://ntrs.nasa.gov/citations/20050000946 | B |
| P20 | Intervalli RR in fibrillazione atriale | modelli del nodo AV (AFVP, PhysioNet); RMSSD in AF 80-250 ms (tesi BioGears) | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1820785/ ; https://archive.physionet.org/physiotools/afvp | B |
| P21 | Tempo di coscienza utile (TUC) | tabella FAA a 18000-50000 ft (20-30 min a 18000 ft, 9 s a 50000 ft); dopo decompressione rapida ridotto a 1/3-1/2 sopra 30000 ft | https://www.faa.gov/pilots/training/airman_education/topics_of_interest/hypoxia ; tabella in https://en.wikipedia.org/wiki/Time_of_useful_consciousness (AC 61-107B da verificare) | B |
| P22 | CO2 ad alta concentrazione | 3 %: mal di testa e dispnea in ore; 4-6 %: mal di testa, vertigini in 15-30 min; 7-10 %: svenimento o quasi in pochi minuti | EPA appendice B https://19january2021snapshot.epa.gov/sites/static/files/2015-06/documents/co2appendixb.pdf (Schulte 1964, Lambertsen 1971) | B |

Non trovato (resta ESTIMATE): quantificazione di stress e nausea sui vitali; SpO2 in fibrillazione atriale; FC/SpO2 durante
decompressione esplosiva; risposta respiratoria quantitativa alla CO2; ampiezze circadiane di FC e temperatura; soglie di dose per
sintomi, perdita di coscienza e morte (derivate dalla tabella TUC [P21] con fattori nostri); VO2max per sesso/eta' dei membri dell'equipaggio;
eta' e altezza dei 4 astronauti (non nel brief). Mifflin-St Jeor (metabolismo basale) non e' usato: il nucleo calcola gli scambi gassosi da MET x massa.

Spaceflight: FC a riposo in orbita ~ uguale alla supina a terra, pressione sistolica piu' bassa (JACC 2023,
https://www.jacc.org/doi/10.1016/j.jacc.2023.05.058); risultati disomogenei, campioni piccoli.
