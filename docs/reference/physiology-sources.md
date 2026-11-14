# Fonti dei parametri fisiologici (tag [P1]..[P12])

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

Non trovato (resta ESTIMATE): variazione di FC/HRV con disidratazione, stress e nausea; SpO2 in fibrillazione atriale; FC/SpO2 durante
decompressione esplosiva; risposta respiratoria quantitativa alla CO2; HRV di riferimento per sesso/eta' (tabelle Lifelines in
https://pmc.ncbi.nlm.nih.gov/articles/PMC7734556, non lette per intero).

Spaceflight: FC a riposo in orbita ~ uguale alla supina a terra, pressione sistolica piu' bassa (JACC 2023,
https://www.jacc.org/doi/10.1016/j.jacc.2023.05.058); risultati disomogenei, campioni piccoli.
