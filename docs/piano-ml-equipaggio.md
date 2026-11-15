# Piano: ML sull'equipaggio e scenari, 4 macchine, consegna alle 22:00

Risposta a `docs/prompt-ml-equipaggio.md`. Scritto il 15/11/2026 alle 14:40, dopo aver letto il codice (`tools/ml/make_dataset.py`,
`plugins/monitor/ml/features.py`, `tools/ml/train_*.py`, `classes.yaml`, `groups.yaml`, gli eventi medici, `WearableSensor`, `monitor.yaml`).
I numeri ML restano tempo simulato su dati sintetici: non sono prestazioni di volo.

## 0. Fatti verificati nel codice che cambiano il piano

1. **I sensori indossabili non hanno errore fisso per unità**: `WearableSensor` = verità + rumore bianco (`plugins/sensors/standard.py`).
   Quindi per i parametri vitali il **livello si può usare come caratteristica** (per i sensori ambientali no: hanno `bias_sigma`). È questo
   che rende possibile una baseline per persona. Se Mario/Luca aggiungono un bias al dispositivo indossabile, si passa al piano del §2.1-e.
2. **L'attività/MET non è nelle caratteristiche**: l'estrattore vede solo le osservazioni dei sensori. `EarlyWarningScore` legge già
   `npc.met` dal tick (il programma della giornata, come l'OSTPV sull'ISS): per il modello dell'equipaggio si usa la stessa fonte.
3. **Gli eventi medici sono legati a una persona e a una durata fisse** (`targets: [cmd]`, `duration_s` nel file); `make_dataset.py` cambia
   solo ampiezza (±30 %) e inizio (6-30 h), **una ripetizione per seed**. La fibrillazione dura 15 min: da qui le 9 righe positive.
4. **`SCALED` moltiplica i valori assoluti**: per `hr_to: 150` un'ampiezza di 1,3 darebbe 195 bpm. Va scalato lo scostamento dal basale, e
   `hr_to`, `spo2_to`, `spo2_delta`, `hrv_factor` oggi non sono scalati affatto.
5. Parametri medici che il modello di Luca accetta già (senza toccarlo): `hr_delta`, `hr_to`, `spo2_delta`, `spo2_to`, `resp_delta`,
   `skin_temp_delta`, `core_temp_delta`, `hrv_factor`, `ramp_s`, `fluid_loss_pct_per_h`, `arrhythmia: af`, `sms_severity`, `adaptation_day0`,
   `hr_init`, `spo2_init`. **I nuovi malori si compongono da questi.**
6. Guasti fisici disponibili: `leak`, `co2_source`, `co_source`, `heat_source`, `fire`. **Non esiste una sorgente che tolga O2**: l'ipossia
   oggi viene solo da perdita + reintegro, EVA, o incendio. Va verificata subito (§1, gruppo E).
7. Soglie a regole sull'equipaggio (`scenarios/station/monitor.yaml`): SpO2 < 90 %, COHb > 5 % e > 15 %, temperatura interna > 38,5 °C, più EWS.
   Sono il termine di confronto.
8. Le corse `--features` girano **senza monitor** (firma pura, gemella esatta). La risposta del sistema si valuta solo con `check_monitor.py`.

## 1. Matrice degli scenari

**Divisione per seed, nuova per tutto il lavoro di oggi** (non si sovrappone ai seed 1-15 già usati per i modelli `station_v1`):
addestramento **101-130**, validazione **131-140**, test **141-160**. Il test non si apre fino alle 19:30 (§3).

**Stratificazione deterministica per i malori** (così ogni astronauta e ogni attività è coperta senza estrazioni sbilanciate):
persona colpita = `seed mod 4` (cmd, eng, med, bot); attività all'inizio = `(seed div 4) mod 3` (sonno / lavoro-riposo / esercizio): l'inizio si
estrae dentro un blocco di quell'attività della persona. Ampiezza U(0,7-1,3) sullo **scostamento**, durata U(0,5-2) × nominale (con minimi
indicati), rampa U(0,5-2) × nominale. Durata del run **1,5 giorni** (36 h): 3 h di riscaldamento delle finestre, inizio fra 6 h e
`36 h - durata - 4 h`.

**Jitter del programma** nei giorni nominali di addestramento: confini dei blocchi spostati di U(-30, +30) min, MET di ogni blocco × U(0,85-1,15),
modifica in memoria del `crew` nello scenario (il file dell'equipaggio è nostro, la fisiologia non si tocca). Serve a far imparare al modello
la dipendenza dal MET e non dall'ora del giorno.

| Gruppo | Scenario | Obiettivo | Parametri variati | Durata | Seed / ripetizioni | Uso |
|---|---|---|---|---|---|---|
| N1 | nominale con jitter | baseline per persona in tutte le attività | jitter programma | 2 d | 101-124 (24 run) + 131-136 (6) | train / val stadio A equipaggio |
| N2 | nominale lungo con jitter | falsi allarmi | jitter | 3 d | 141-150 (10 run = 30 d) | test FA |
| N3 | nominale **senza** jitter (il programma della demo) | FA sul programma vero, controllo che non si impari l'orologio | nessuno | 3 d | 151-155 (5 run = 15 d) | test FA |
| M1 | febbre (esistente) | | +0,8...+2,0 °C, 3-12 h | 1,5 d | 24 train / 8 val / 8 test | stadio B medico |
| M2 | disidratazione (esistente) | evento lento | 0,3-0,7 %/h, 6-10 h | 1,5 d | 24 / 8 / 8 | |
| M3 | fibrillazione atriale (esistente) | evento acuto raro | `hr_to` 130-170, `spo2_to` 91-95, **10-60 min** | 1,5 d | 24 / 8 / 8 | |
| M4 | mal di spazio (esistente) | | severità 2-3, 1-3 h | 1,5 d | 24 / 8 / 8 | |
| M5 | stress acuto (esistente) | confondente (simile allo sforzo) | `hr_delta` 6-15, 1-3 h | 1,5 d | 24 / 8 / 8 | |
| M6 | **tachicardia sopraventricolare** (nuovo) | ritmo veloce **regolare**: separarla dalla FA | `hr_to` 160-200, `hrv_factor` 0,3-0,6, 5-40 min | 1,5 d | 24 / 8 / 8 | |
| M7 | **bradicardia** (nuovo) | scostamento verso il basso | `hr_to` 38-46, 20-120 min | 1,5 d | 24 / 8 / 8 | |
| M8 | **infezione respiratoria** (nuovo) | quadro misto lento | `core_temp_delta` 0,6-1,4, `resp_delta` 4-8, `spo2_delta` -2...-5, 6-14 h | 1,5 d | 24 / 8 / 8 | |
| M9 | **sforzo anomalo** (nuovo) | "126 bpm a 7 MET è normale, 165 no" | inizio **dentro** l'esercizio, `hr_delta` 18-35, `core_temp_delta` 0,5-1,0, `fluid_loss` 1-2 %/h, 30-75 min | 1,5 d | 24 / 8 / 8 | |
| E1 | ipercapnia: `co2_source` in un modulo abitato (CQ1-4 di notte, COL/JPM/USL di giorno) | quadro congiunto CO2 ↑ + respiro/battito ↑ | 0,5-3 e-3 mol/s, 1-8 h, modulo | 1,5 d | 24 / 8 / 8 | stadio B `crew_env` |
| E2 | ipercapnia da macchina: CDRA-ARRESTO, CQFAN-FOD (catalogo, `--randomize`) | stessa classe, causa diversa | range del foglio 06 | 1,5 d | 12 + 12 / 4 + 4 / 4 + 4 | |
| E3 | CO: `co_source` in un modulo abitato | COHb ↑ con SpO2 piatta | 1e-5...1e-4 mol/s (ESTIMATE, da calibrare con la prova 400 tick), 1-6 h | 1,5 d | 24 / 8 / 8 | |
| E4 | ipossia: perdita PRK forte + OGA-STACK; EVA (`eva_decompression`) | O2 ↓ e SpO2 ↓ | scala della perdita, modulo | 1,5 d | 24 / 8 / 8 | solo se la prova del §5 (15:00) mostra PIO2 < 135 mmHg in < 12 h |
| C1 | combinazioni persona + ambiente: febbre durante CDRA-DEGRADO, stress durante perdita PRK, SVT durante CO lieve | due famiglie insieme, nessuna si deve mangiare l'altra | come sopra | 1,5 d | 4 tipi × 4 / 2 / 2 | validazione e test |
| R1 | **rigenerazione** del catalogo (26 guasti, `--randomize --combos`) con le nuove colonne | negativi e positivi per `crew_env` nei guasti esistenti | range del foglio 06 | 2 d | 101-104 (120 run) | train stadio B (onda 2, tagliabile) |
| V1 | con risposta attiva: test M/E/N con il monitor vivo | falsi allarmi indotti dalla risposta (medico che corre, esercizio interrotto) | | 1 d | test 141-148 | solo `check_monitor.py` |

Costo stimato (6 min di CPU per giorno simulato, misurato): N 105 d, M 9 × 40 × 1,5 = 540 d, E+C ≈ 200 d, R1 240 d, V1 ≈ 60 d:
**≈ 1.150 giorni simulati**, cioè ≈ 2 h 10 min della flotta (≈ 530 d/h con 3 macchine, §4). Ci sta, con R1 come primo taglio.

Default dichiarati (e dove si cambiano): soglie delle etichette precoci nel §2.2 (in `tools/ml/classes.yaml`); 24/8/8 run per evento
(minimo per avere ≥ 300 righe positive per classe in addestramento; con 3 macchine si scende a 16/6/6); 1,5 giorni per run.

## 2. Progetto dei modelli

### 2.1 Stadio A equipaggio: baseline per persona, condizionata all'attività

**a. Ingressi** (un vettore per astronauta ogni 60 s, nuovo modulo `src/ares3/plugins/monitor/ml/crew.py`, usato online e da
`make_dataset.py`, come `features.py`, quindi senza scarto fra addestramento e inferenza):
- livelli **sensati**: media a 10 min di `hr`, `resp_rate`, `spo2`, `core_temp_c`, `skin_temp_c`, `hrv_rmssd`; pendenza a 1 h di `core_temp_c`;
- contesto (dal tick, come fa `EarlyWarningScore`): MET medio 10 min, MET massimo degli ultimi 30 min, minuti dall'ultimo MET ≥ 4 (limite 120),
  classe di attività (sonno / nominale / aerobico / resistivo / recupero), minuti dall'inizio del sonno (limite 480), orologio seno/coseno del giorno.
- `cohb_pct` e `health_state` restano alle regole (non sono baseline).

**b. Modello**: per ogni coppia (persona, parametro vitale) un `HistGradientBoostingRegressor` con perdita `absolute_error` (mediana), profondità 3,
200 iterazioni, solo sul contesto → valore atteso. Residuo r = misura − atteso. Scala σ per (persona, parametro, classe di attività) = 1,4826 × MAD
dei residui **di validazione** (non di addestramento: include l'errore di generalizzazione). z = r/σ, limitato a ±10 (lezione c).
Punteggio multivariato: distanza di Mahalanobis dei 6 z con covarianza robusta (`MinCovDet`) stimata in validazione, più il massimo |z| per
parametro con verso clinico (FC e respiro in entrambi i versi, SpO2 solo verso il basso, temperature solo verso l'alto).
4 persone × 6 parametri = 24 regressori piccoli; inferenza ogni 60 s ≈ 2-3 ms, cioè < 0,05 ms per tick.

**c. Normalizzazione per persona**: un modello per astronauta assorbe sesso, età, massa e `hr_rest` diversi (sono già nei parametri dei 4 NPC).
Per un membro nuovo, ripiego documentato: un modello comune con sesso/età/massa/`hr_rest` come ingressi, addestrato sugli stessi dati (solo se avanza tempo).

**d. Soglie e allarme**: punteggio = max(D²/L_D, max|z|/L_z), media mobile esponenziale su 5 min. Limite L = **margine 1,5 × massimo osservato
sui 12 giorni-persona × 4 di validazione** (come lo stadio A, dove 2,0 ha dato 0 falsi allarmi: si parte da 1,5 e si sale a 2,0 se la validazione
supera 0,1 FA/giorno). Allarme se il punteggio ≥ 1 per 600 s (lento) oppure |z_hr| ≥ 2 L_z per 120 s (via rapida per FA/SVT/bradicardia).
Uscita: un `Signal` di tipo `medical` con `subject` = la persona, `cause` = `crew_baseline`, classe **caution** (ALERT, nessun playbook),
`evidence` = "FC 105 bpm contro 68 attesi a riposo (z 6,1)". Il caso dei 126 bpm a 7 MET si risolve per costruzione: l'atteso è ≈ 140.
Il rilevatore va **dopo** le regole nel YAML (una regola che dà la causa vince), generato da `tools/build_station.py`.

**e. Non imparare l'unità né l'orologio**: (1) gli indossabili non hanno bias (§0.1), quindi il livello è lecito; un test di architettura/unità
controlla che `WearableSensor` resti senza bias, e se un giorno lo avrà si usa z del residuo meno la sua mediana delle ultime 24 h di riposo
(auto-calibrazione: perde però gli eventi più lenti di un giorno); (2) jitter del programma in addestramento e test N3 senza jitter;
(3) divisione per seed, mai per riga.

### 2.2 Stadio B: classi congiunte persona + ambiente e famiglia medica più forte

**Nuova famiglia `crew_env`** in `tools/ml/classes.yaml` (un classificatore suo, così convive con `physical`/`actuator`/`medical`: un CDRA fermo
dà sia `arresto_cdra` sia `hypercapnia_crew`). Classi: `hypercapnia_crew`, `hypoxia_crew`, `co_exposure_crew`, `nominal`.

**Etichette dalla verità, non dal guasto**: `run_features` scrive accanto alle caratteristiche alcune colonne `truth|...` (solo per
l'etichetta, escluse dagli ingressi come oggi `faults`): ppCO2, PIO2 e CO veri nel modulo dove si trova ogni NPC, COHb vero. Una riga è
positiva quando un NPC supera una **soglia precoce**, prima delle regole: ppCO2 ≥ 4 mmHg, PIO2 ≤ 135 mmHg, COHb ≥ 2,5 % (ESTIMATE, da far
confermare a Luca, §8). Fascia grigia fra 0,8 e 1 × soglia = `drop` (non usata). `subject` = l'NPC più esposto, luogo = il suo modulo.
**Il volume `eva` è escluso dalle etichette** (controllo dell'onda 2, 15/11 ore 17:05): le uniche 107 righe nominali sopra 4 mmHg sono di `med`
durante l'EVA (MET 7,5 in un volume piccolo), e l'EVA ha per progetto PIO2 ≈ 130 mmHg. Senza l'esclusione, ogni EVA diventerebbe un esempio di
ipercapnia e di ipossia. Con l'esclusione, 0 righe nominali superano le soglie. `hypoxia_crew` non ha positivi (PIO2 minima in cabina 145,5 mmHg,
E4 spento): la classe cade e l'ipossia resta alla regola SpO2.

**Ingressi**: le caratteristiche attuali (ambiente + vitali, `d10/d1h/sd10/n10/sl1h/sl6h`) più i 24 z dello stadio A equipaggio. Le colonne vecchie
mantengono il nome, quindi i modelli `station_v1` già fatti restano validi finché non si ri-addestrano.

**Famiglia medica**: ri-addestrata con 24 run per evento (9 eventi). Regola della lezione (d): una classe con < 300 righe positive in addestramento
non entra nel modello vivo (resta nel rapporto). Etichetta "effetto visibile" dalla gemella (k = 3 sigma) come oggi; per la disidratazione
(lenta) si controlla quanti positivi restano con k = 3: se < 300, k = 2 solo per lei.

**Soglie**: per classe con `sweep_diagnoser.py` **sulla validazione**, obiettivo ≤ 0,05 FA/giorno per famiglia; `confirm_s` da `classes.yaml`
(medico 300 s, FA/SVT 120 s, `crew_env` 300 s).

## 3. Protocollo di valutazione

- **Divisione**: train 101-130, val 131-140 (tutte le tarature: margini, soglie, k), test 141-160 aperto **una sola volta** alle 19:30 con i
  modelli congelati. Lo scriviamo nella scheda del modello (`model_card_crew.json`) con l'ora.
- **Metriche a evento** (`tools/ml/metrics.py`, stile ESA-ADB): allarme vero = si apre durante il guasto (o entro `confirm_s` dopo); falso =
  fuori; richiamo per tipo; F0.5; ritardo dal `visible_since_s` della gemella (mediana e p90).
- **Falsi allarmi per giorno**: obiettivo ≤ 0,2/giorno sull'intero monitor, ≤ 0,1/giorno per il solo modello dell'equipaggio. Su 45 giorni
  di test (N2 + N3), 0 falsi allarmi danno un limite superiore al 95 % di 3/45 = 0,067/giorno (regola del tre); con k allarmi si riporta
  l'intervallo di Poisson esatto.
- **Campioni piccoli**: 8 eventi di test per tipo → richiamo con intervallo di Wilson al 95 % (6/8 = 0,75 [0,41-0,93]); si riporta anche il
  richiamo complessivo su 72 eventi medici e 32 congiunti, che ha un intervallo stretto. Ritardi: mediana con bootstrap su run (1000 ricampionamenti).
- **Confronto con le regole**, sugli stessi run di test e con il monitor vivo (`check_monitor.py` con `--monitor`): (R) regole sole =
  `monitor.yaml` di oggi; (R+A) + stadio A equipaggio; (R+A+B) completo. Misure accoppiate per run: anticipo = t_regola − t_ML (mediana, bootstrap),
  richiamo, FA/giorno; più il conteggio di segnalazioni di EWS/`NpcThreshold` durante l'esercizio nei giorni nominali contro quelle del modello
  (il caso dei 126 bpm).
- **Con la risposta attiva** (V1): falsi allarmi indotti dalla risposta (il medico che corre dal paziente cambia attività, l'esercizio interrotto).

## 4. Piano di calcolo sulle 4 macchine

**Flotta confermata (15/11, 14:35): M5 Pro, M5, PC Ryzen.** Il mini PC Proxmox **non si usa**: darebbe ≈ 0,3 run/min (≈ 6 % della flotta)
e ospita il sito pubblico e il backend della demo. Resta solo come riserva se cade una macchina, e anche allora solo lontano dalla demo.

Rendimento in run da 2 giorni al minuto, con le protezioni:

| Macchina | Impostazione | Rendimento | Shard (N = 16) | Quota |
|---|---|---|---|---|
| M5 Pro (amico, prenotato) | `--workers 17`, `caffeinate -i` | 2,6 | 0-9 | 10/16 |
| M5 | `--workers 9`, `caffeinate -i` | 1,25 | 10-13 | 4/16 |
| PC principale | `--workers 8` (gli altri core per addestramento, IDE, server di prova) | ≈ 0,55 | 14-15 | 2/16 |

Totale ≈ 4,4 run/min ≈ 530 giorni simulati all'ora. L'onda 1 dura ≈ 75 min, l'onda 2 ≈ 60 min: la cronologia del §5 regge senza cambiamenti.
Le quote sono proporzionali ai rendimenti, quindi le macchine finiscono insieme (lo shard alterna già run lunghi e corti).

**Una lista sola, in un file**: la matrice del §1 va in `tools/ml/crew_plan.yaml` (gruppi, seed, durate, range) e `make_dataset.py` riceve
`--plan tools/ml/crew_plan.yaml --wave 1|2`; ogni macchina costruisce la stessa lista dallo stesso commit e prende il suo `--shard`.
Prima del lancio su ogni macchina: `--ticks 400` sulla **lista intera** (trappola a: un modulo inesistente fa cadere tutto il processo) e
confronto dell'hash di un run fra PC e M5 Pro (determinismo fra numpy 2,4 e 2,5).

**Ordine**:
- **Onda 1** (≈ 650 d, ≈ 70 min): N1, N2, N3, poi M1-M9 con i seed di train e val **prima** di quelli di test (le posizioni della lista sono
  ordinate così: i primi risultati utili per addestrare arrivano per primi).
- **Onda 2** (≈ 500 d, ≈ 55 min): E1-E4, C1, R1 (R1 per ultimo: è il primo taglio).
- **Onda 3** (≈ 60 d, ≈ 10 min, solo M5 Pro e M5): V1 con il monitor vivo e i modelli nuovi copiati.

**Protezioni**: il PC non va mai sopra 8 worker (l'addestramento usa 6-8 core alle 17:00 e alle 18:30); il Proxmox non genera, così il sito
e il backend restano liberi. Sui Mac `caffeinate -i` e alimentatore collegato.

**Checkpoint e recupero**: ogni 30 min `tar` via SSH delle cartelle complete (solo quelle senza `.tmp`) verso il PC in `output/ml/crew/`.
Le cartelle si scrivono in `.tmp` e si rinominano a fine run, quindi una cartella presente è completa. **Se una macchina cade**: si copia sul
M5 Pro (o M5) ciò che il PC ha già recuperato di quello shard dentro la sua cartella di uscita e si rilancia lo stesso shard con `--resume`.

**Se l'M5 Pro cade a metà** (macchina dell'amico, da restituire o spenta): la flotta scende a ≈ 1,8 run/min. Si recupera ciò che ha scritto,
si rilanciano i suoi shard 0-9 divisi fra M5 (0-6) e PC (7-9) con `--resume`, si passa a 16/6/6 run per evento, si taglia R1 e N3 si riduce a 3 run.

## 5. Cronologia fino alle 22:00

Ing. A = generatore, scenari, calcolo. Ing. B = modelli, rilevatore, integrazione. Claude Code lavora con entrambi (due sessioni).

| Ora | Ing. A (+ Claude) | Ing. B (+ Claude) | Macchine |
|---|---|---|---|
| 14:45-15:00 | prova da 400 tick delle cause di ipossia/CO (E3, E4) con la verità stampata: decide se E4 resta | Bozza di `ml/crew.py` (estrattore equipaggio) | M5: copia del repository e `uv sync --frozen` |
| 15:00-15:45 | `make_dataset.py`: `--plan/--wave`, persona e attività stratificate, durata/rampa, scalatura sullo scostamento (§0.4), jitter del programma, colonne `truth|...` e `crew.parquet`; 4 nuovi file in `scenarios/events/` (M6-M9, PLACEHOLDER); `tools/ml/crew_plan.yaml` | estrattore equipaggio con test di parità online/offline; `CrewBaselineDetector` (scheletro) | M5 Pro: copia e `uv sync` |
| 15:45-16:00 | `--ticks 400` sulla lista intera dell'onda 1 su tutte le macchine; hash di determinismo; commit | rivede le modifiche al generatore | |
| **16:00** | **lancio onda 1** su 4 macchine | `tools/ml/train_crew.py` (regressori, MAD, MinCovDet, scheda del modello) | onda 1 |
| 16:30 | primo recupero; controlla righe positive per evento | primo addestramento dello stadio A equipaggio su N1 parziale (val su 131-136) | |
| 17:00 | prepara `--wave 2` (E, C, R1) con la prova 400 tick; **lancio onda 2** appena l'onda 1 libera core | stadio A equipaggio: taratura del margine sulla validazione; integrazione in `tools/build_station.py` (rilevatore dopo le regole) | onda 1 → 2 |
| 17:30 | `check_monitor.py`: aggiunge `--medical`, `--crew-env`, e il confronto (R)/(R+A)/(R+A+B) | `train_diagnoser.py`: famiglia `crew_env`, etichette dalla verità, ingressi z; addestramento su onda 1 | onda 2 |
| 18:15 | recupero finale onda 2 (taglio di R1 se non è finita) | | |
| 18:30-19:15 | test nuovi + i 180 vecchi (`pytest -n auto`), `ruff` | **addestramento finale** A equipaggio + B (medica, `crew_env`) su train, soglie su val; `sweep_diagnoser.py` | M5 Pro e M5: onda 3 pronta |
| **19:00** | **cancello del piano B** (§6) | | |
| 19:15-19:30 | rigenera i YAML con `build_station.py`, `ares3 validate` | modelli in `models/station_v2/` (v1 resta per tornare indietro), schede | |
| **19:30** | | **apertura del test** (una volta): metriche, intervalli, confronto con le regole | onda 3 (V1, `check_monitor.py`) su M5 Pro + M5 |
| 20:15 | correzioni solo se rompono i criteri del §7 (mai tarare sul test: si correggono difetti, non soglie) | scrive i numeri in `docs/` e nella scheda | |
| **20:45** | **congelamento**; immagine Docker nuova con tag, la vecchia tenuta per il ritorno indietro | `pnpm build` + `wrangler deploy` della dashboard (se servono modifiche ai tipi) | |
| 21:00 | pubblicazione backend sul Proxmox, prova `wss://ares-api.daado.dev` | prova dalla dashboard pubblica | |
| 21:15-21:45 | prova generale della demo: giorno nominale (nessun allarme a 7 MET), fibrillazione, CO con SpO2 piatta, ipercapnia in CQ di notte con `tools/demo_client.py` | | |
| 21:45-22:00 | margine | | |

In parallelo sempre: generazione (macchine) / codice dei modelli (Ing. B) / strumenti di valutazione (Ing. A dalle 17:30).

**Dettagli di integrazione da non dimenticare**:
- **Rami**: Ing. A su `feat/crew-dataset`, Ing. B su `feat/crew-model`. Il ramo del generatore va in `main` alle 15:50, prima del lancio, perché
  tutte le macchine devono costruire la lista dallo stesso commit. Il ramo dei modelli entra alle 19:15.
- **Modelli in `models/station_v2/`**: il generatore di `monitor.yaml` (`tools/build_station.py`) punta lì; `station_v1` resta intatto per
  tornare indietro con una riga.
- **Procedura per il nuovo allarme**: in `build_station.py` la causa `crew_baseline` apre `med_generic` (passi: andare dal membro, chiedere i
  sintomi, rimisurare). Le cause congiunte aprono le procedure esistenti: `hypoxia_crew` → `med_hypoxia`, `co_exposure_crew` → `med_co`,
  `hypercapnia_crew` → `med_generic` più il controllo della CO2 del modulo.
- **Dashboard**: si usano solo campi già presenti (`Emergency.subject`, `cause`, `evidence`, `alert_class`), quindi `types.ts` non cambia.
  Va verificato alle 19:30 che la UI mostri l'`evidence` del nuovo rilevatore. Se serve un campo nuovo, va prima in `sdk/types.py`, poi a mano in `types.ts`.
- **Layering**: `ml/crew.py` importa solo `sdk`/`schemas` più numpy/sklearn, come il resto di `plugins/monitor/ml/`; l'addestramento sta in
  `tools/ml/train_crew.py`, mai nel pacchetto.
- **Avvio del server**: lo stadio A dell'equipaggio è pronto dopo 30 min (finestre di 10 min più il MET massimo a 30 min). `--warmup-h 4`
  copre già le 3 h delle caratteristiche della stazione.

## 6. Piano B (deciso alle 19:00)

**Versione minima da avere comunque alle 19:00**: lo stadio A equipaggio integrato (anche solo con le tabelle, vedi sotto) addestrato su N1,
con 0 falsi allarmi sulla validazione e nessuna segnalazione durante l'esercizio nominale, più la famiglia medica ri-addestrata con i dati
dell'onda 1. Le classi congiunte restano alle regole (come oggi).

**Cosa tagliare, nell'ordine**:
1. R1 (rigenerazione del catalogo): `crew_env` si addestra solo su E/C, e le righe dei run vecchi valgono `drop` per quella famiglia.
2. E4 (ipossia) se la prova delle 14:45 non porta PIO2 sotto 135 mmHg: l'ipossia resta alla regola SpO2 < 90 %.
3. Nuovi malori oltre M6 e M9 (prima M7, poi M8).
4. Il regressore: si sostituisce con una tabella di mediana e MAD per (persona, parametro, classe di attività, fascia di MET di 1 unità), stesso
   rilevatore, stesse soglie. Si fa in 20 minuti e non può sbagliare l'inferenza.
5. La famiglia `crew_env` intera.

Mai tagliare: le regole, la divisione per seed, la prova da 400 tick, i 180 test.

## 7. Rischi e criteri di accettazione

| Rischio | Prob. | Come ridurlo |
|---|---|---|
| Le modifiche al generatore richiedono più di 45 min e la generazione parte tardi | alta | se alle 15:45 non è pronto, si lancia N1/N2/N3 (servono solo `crew.parquet` e il jitter) e i malori alle 16:30 |
| Nessuna causa porta all'ipossia in poche ore | media | prova alle 14:45; se no, E4 cade (piano B 2); un guasto `o2_sink` nel core sarebbe 20 righe + un test di conservazione, ma solo se tutto il resto è pronto |
| Il modello impara l'orologio o il programma | media | jitter, test N3 senza jitter, il MET massimo a 30 min come ingresso |
| Falsi allarmi indotti dalla risposta (medico che corre) | media | il contesto è il MET **reale** del tick, non quello del programma; V1 lo misura |
| Pochi positivi o fisiologia poco credibile per un evento | alta | ≥ 300 righe o la classe non entra nel monitor vivo; tutto marcato ESTIMATE; domande a Luca |
| L'M5 Pro cade o va restituito prima | bassa-media | checkpoint ogni 30 min; i suoi shard passano a M5 e PC con `--resume`; 16/6/6 run per evento, R1 tagliato |
| Versioni diverse di sklearn fra macchine | bassa | si addestra solo sul PC; le altre macchine generano dati, non modelli |
| La pubblicazione rompe la demo | media | congelamento alle 20:45, immagine vecchia con tag per tornare indietro in 2 minuti |

**Criteri di accettazione** (sul test, una volta):
- falsi allarmi ≤ 0,2/giorno per il monitor completo e ≤ 0,1/giorno per il solo modello dell'equipaggio su 45 giorni; nessun falso allarme di
  classe emergency;
- nessuna segnalazione del modello dell'equipaggio durante i blocchi di esercizio nominale nei giorni di test (il caso dei 126 bpm);
- richiamo a evento ≥ 0,8 complessivo sui malori; per tipo ≥ 6/8 su FA, SVT, bradicardia, febbre, CO, ipercapnia; gli altri si riportano col loro
  intervallo e, se < 5/8, si dichiarano deboli;
- anticipo mediano rispetto alle regole ≥ 5 min su CO e ipercapnia (e ipossia se c'è), mai peggio delle regole sugli altri;
- inferenza: costo medio per tick ≤ 4,7 ms (oggi 4,4), una valutazione completa < 5 ms;
- 180 test vecchi passati più i nuovi (parità dell'estrattore equipaggio, rilevatore, `test_architecture.py`), `ruff` pulito su ciò che si aggiunge;
- stesso hash di un run su due macchine.

## 8. Domande da chiarire, per impatto

**Luca**
1. I livelli per persona (FC a riposo 58/61/60, ≈ 140 a 7 MET) e il rumore dell'indossabile sono credibili? Un dispositivo vero ha un errore
   fisso per unità? (Se sì, il livello non si può usare: §2.1-e.)
2. Le soglie precoci delle etichette congiunte: ppCO2 ≥ 4 mmHg, PIO2 ≤ 135 mmHg, COHb ≥ 2,5 %. E il suo modello alza il respiro con la CO2?
   Se no, l'ipercapnia sarà "solo ambiente" e lo diremo.
3. Range di ampiezza e durata dei 9 eventi (§1), in particolare i 4 nuovi (SVT, bradicardia, infezione respiratoria, sforzo anomalo): vanno bene,
   o quali sostituire?
4. Il mal di spazio esiste solo nei giorni 1-3 di missione: va bene iniettarlo in qualunque giorno con `adaptation_day0` fisso?
5. È accettabile che il monitor conosca l'attività/MET dal programma (come l'OSTPV) o vuole un canale di attigrafia rumoroso?

**Mario**
1. Rumore e bias dei sensori indossabili e ambientali usati come ingressi (lo stadio A dipende da questi).
2. Cause realistiche di ipossia sull'ISS nell'arco di ore (perdita con reintegro di N2? OGA fermo?) e se un guasto "pozzo di O2" è fisicamente sensato.
3. Range di `co_source` e `co2_source` (mol/s) per modulo, e quali moduli occupa l'equipaggio di notte (CQ1-4).
4. Le calibrazioni periodiche (dente di sega) dei sensori di CO2/O2 entrano nelle caratteristiche congiunte: vanno tolte dal segnale o modellate?
