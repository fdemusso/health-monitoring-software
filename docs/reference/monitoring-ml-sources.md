# Fonti del monitoraggio a tre stati, dell'ML e delle procedure

Tag usati nel codice (`plugins/monitor/ml/`, `plugins/monitor/detectors.py`, `core/monitor.py`, `tools/ml/`,
`scenarios/monitor_placeholder.yaml`, `docs/monitor-ui.md`). Tutto ciò che non ha un tag è `ESTIMATE`.
Aggiunto dal team software; resta in termini ISS (mai Marte). Il piano di lavoro è `piano.md`.

| Tag | Fonte | Cosa ne usiamo |
|---|---|---|
| `[R1]` | NASA, *CLD HSI Workshop - Alerts*, https://ntrs.nasa.gov/api/citations/20240003565/downloads/CLD%20HSI%20Workshop%20Alerts.pdf ; ESA, blog della missione Principia (tre livelli più advisory, etichette FIRE / ΔP/Δt / ATM), https://blogs.esa.int/tim-peake/?p=945 | livelli Emergency / Warning / Caution / Advisory (`classifier.classes`, `Emergency.alert_class`) |
| `[R2]` | NASA, *Emergency Ops History*, SpaceOps 2023, https://ntrs.nasa.gov/citations/20220019247 ; `[ICES-2025-126]` in `depressurization-sources.md` | le tre emergenze (depressurizzazione rapida, incendio, atmosfera tossica); il medico è una categoria a parte |
| `[R3]` | NASA 2003, risposte automatiche al fumo/incendio, https://ntrs.nasa.gov/api/citations/20030053429/downloads/20030053429.pdf ; SAE 2003-01-2595, *ISS Automated Safing Responses to Fire Emergencies* | togliere alimentazione ai rack, ventilazione del modulo off, inibire O2/N2 (azione `power`, playbook incendio) |
| `[R4]` | NASA Ames, *Inductive Monitoring System*, https://technology.nasa.gov/patent/TOP2-175 , https://c3.ndc.nasa.gov/dashlink/static/media/publication/IMS_JACIC.pdf | monitoraggio guidato dai dati, certificato nel Mission Control della ISS: la base dello stadio A (`ml/anomaly.py`) |
| `[R5]` | Hundman et al., KDD 2018, *Detecting Spacecraft Anomalies Using LSTMs and Nonparametric Dynamic Thresholding*, https://arxiv.org/abs/1802.04431 | soglia dinamica sul punteggio di anomalia (estensione se la soglia statica non basta) |
| `[R6]` | Kotowski et al. 2024, *ESA Benchmark for Anomaly Detection in Satellite Telemetry*, https://arxiv.org/abs/2406.17826 | metriche a evento (F0.5, recall a evento, ritardo) in `tools/ml/metrics.py` |
| `[R7]` | Allarme ammoniaca ISS, gennaio 2015, https://spaceflightnow.com/2015/01/14/engineers-study-possible-coolant-leak-aboard-space-station/ , https://www.nasaspaceflight.com/2015/01/iss-ammonia-leak-alarm-false-indication/ | procedura `toxic`: maschere, ritiro, portello chiuso, verifica con tubi rivelatori |
| `[R8]` | Royal College of Physicians, NEWS2, riassunto NHS: https://www.nwas.nhs.uk/publications/news2-national-early-warning-score | fasce del punteggio di allerta (`EarlyWarningScore`); adattamento ai wearable = ESTIMATE |
| `[R9]` | NASA HRP / ExMC, *Clinical Decision Support*, https://ntrs.nasa.gov/citations/20220014306 | assistente di bordo che guida l'equipaggio senza la terra: modello delle procedure |
| `[R10]` | *On-board Telemetry Monitoring in Autonomous Satellites*, https://arxiv.org/abs/2604.08424 | FDIR ibrido regole + ML, spiegabilità nel ciclo decisionale: le regole restano la rete di sicurezza |
| `[R11]` | NASA 2011, riorganizzazione della ISS Medical Checklist, https://ntrs.nasa.gov/citations/20110003477 | procedure per apparato, emergenza / non emergenza |
| `[R12]` | NASA, *ISS Medical Kit Checklist*, https://www.nasa.gov/wp-content/uploads/2015/03/medical_kit_checklist_-_full_release.pdf | dotazioni citate nelle procedure mediche (mai dosi) |
| `[R13]` | British Thoracic Society 2017, *Guideline for oxygen use in adults*, https://pmc.ncbi.nlm.nih.gov/articles/PMC5531304 | bersaglio SpO2 94-98 % |
| `[R14]` | O2 al 100 % nel sospetto di intossicazione da CO; emivita COHb 74 ± 25 min, https://patient.info/doctor/emergency-medicine/carbon-monoxide-poisoning-pro , https://data.zhenzhi.com/details/1/902099600 | procedura `co_poisoning` |
| `[R15]` | Colpo di calore: raffreddare per primo, https://emergencycarebc.ca/clinical_resource/exertional-heat-illness , https://cgo.mod.uk/clinical-guidelines-for-operations/treatment-guidelines/environmental-injuries-exposure/heat-illness/ | procedura `fever_or_heat` |
| `[R16]` | NASA/TP-2010-216124, *Atrial Arrhythmias in Astronauts*, https://ntrs.nasa.gov/api/citations/20100021111/downloads/20100021111.pdf | procedura `atrial_fibrillation_suspected` |
| `[R17]` | Prometazina IM per la chinetosi spaziale, https://ntrs.nasa.gov/citations/19930046286 , https://ntrs.nasa.gov/citations/20110020471 | procedura `space_motion_sickness` |
| `[R18]` | Falsi positivi del NEWS2 da wearable in continuo, https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11459982/ , https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9941897/ | punteggio sulla MEDIA di 5 minuti, non sul campione |
| `[R19]` | Distribuzione elettrica ISS (DDCU, RPCM), https://spaceflight101.com/?p=4221 , https://ntrs.nasa.gov/citations/20050177179 | alimentazione per modulo (azione `power`) |

Fonti interne: `notebooks/mario/ARES3_Guida_implementazione.pdf` (§6 catalogo guasti, netto/subdolo; §8 l'orbita come orologio per
l'ML), `notebooks/mario/ARES3_Stazione_Sensori.xlsx` foglio `06_GUASTI` (firma osservabile, come distinguerlo, allarme atteso,
etichetta ML) e il notebook ECG di Luca (autoencoder con soglia sull'errore di ricostruzione).

## Cosa NON è validato

Il simulatore è nostro: rumori e bias dei sensori sono in gran parte `ESTIMATE` (`docs/station.md`). I modelli imparano il
simulatore, quindi le metriche dei report (falsi allarmi, ritardi) sono **tempi di simulazione su dati sintetici**, non
prestazioni di volo. Il tempo è compresso di 30x (`TIME_COMPRESSION` in `tools/build_station.py`): "24 h" simulate sono circa un
mese di deriva reale. I punteggi medici e le procedure sono ricostruiti da fonti pubbliche e vanno rivisti da Luca.
`joblib` esegue codice al caricamento: si caricano solo i modelli prodotti da noi (`models/`).

## Fonti delle procedure mediche (R20-R26)

Aggiunte con `docs/procedure-mediche.md`, dove stanno titolo, ente, anno e URL di ciascuna: `[R20]` NASA OCHMO-TB-004 (CO2),
`[R21]` NASA/TP-2010-216126 (CO2 in volo), `[R22]` linea guida SVT ACC/AHA/HRS 2015 (terrestre), `[R23]` linea guida FA
ACC/AHA/ACCP/HRS 2023 (terrestre, URL da verificare), `[R24]` NHS disidratazione, `[R25]` NHS colpo di calore, `[R26]` NASA HRP, rapporto
Behavioral Medicine 2025.
