# Prompt fase 2: stadio A dell'equipaggio e famiglia medica dello stadio B (16:50-19:00)

Da dare a una sessione di Claude Code aperta nel **worktree** `C:\Users\flavi\Desktop\hms-fase2` (ramo `feat/crew-model`), mentre la
sessione della fase 1 continua a gestire le macchine nella cartella principale `C:\Users\flavi\Desktop\health-monitoring-software`.
Piano completo: `C:\Users\flavi\Desktop\health-monitoring-software\docs\piano-ml-equipaggio.md` (leggi i §2.1, §2.2, §3 e §7). La fase 1 è
fatta: `tools/ml/crew_plan.yaml`, `src/ares3/plugins/monitor/ml/crew.py` (`CrewFeatureExtractor`), `crew.parquet` in ogni run.

**Due sessioni in parallelo: le regole.**
- Lavori **solo nel worktree**. Nella cartella principale non cambi ramo, non modifichi file e non fai commit: da lì girano gli 8 worker
  dell'onda 2 e la sessione della fase 1.
- I dati stanno nella cartella principale (`output/` non è nel repository): leggili con percorsi assoluti, per esempio
  `C:\Users\flavi\Desktop\health-monitoring-software\output\ml\crew`. I modelli li scrivi nel worktree, in `models/station_v2/`.
- Prima di tutto, nel worktree: `uv sync --extra dev`, poi `uv run pytest -q -n 6` per avere il punto di partenza.
- Non lanci simulazioni lunghe e non tocchi le macchine remote: le gestisce la sessione della fase 1.

---

## Stato dei dati (verificato alle 16:45)

- **Onda 1 completa e integra: 405 run**, in tre cartelle, da leggere tutte insieme **in sola lettura** (non spostarle, non cancellarle):
  `output/ml/crew` (PC), `output/ml/crew_w1_m5pro`, `output/ml/crew_w1_m5`. Controllo: `output/ml/check_w1.py` → 0 difettose.
  Gruppi: N1 train 24 run + val 6 (2 d, con jitter); N2 test 10 (3 d, jitter); N3 test 5 (3 d, senza jitter); M1-M9 ciascuno 24 / 8 / 8
  (1,5 d, **senza** jitter). Righe con guasto attivo in train: M3 FA 851, M6 SVT 476, M9 1227, M7 1651, le altre ≥ 2700.
- `meta.json["job"]` contiene `group`, `split`, `npc`, `event`, `activity_at_start`, `start_fallback`, `drawn`, `faults`.
- Colonne di `crew.parquet` (formato lungo, una riga per `t_s` e `npc` ogni 60 s): `hr|lv10`, `hr|sd10`, ... per
  `hr, resp_rate, spo2, core_temp_c, skin_temp_c, hrv_rmssd`, `core_temp_c|sl1h`, `ctx|met10`, `ctx|met_max30`, `ctx|min_since_ex`,
  `ctx|act_*`, `ctx|min_since_sleep`, `clock|sin/cos`, e la verità `truth|...` (**solo per etichette e controlli, mai come ingresso**).
- **L'onda 2 (E, C, R1) gira ancora** fino alle 17:35 circa, su M5 Pro, M5 e **8 worker di questo PC**. Restano circa 8 thread liberi:
  **l'addestramento ne usa al massimo 6** (`OMP_NUM_THREADS=6`, nessun `n_jobs` più alto, nessuna generazione aggiuntiva sul PC).

## Un problema da risolvere per primo: mancano i gemelli dei malori

Le etichette "effetto visibile" dello stadio B vengono dal run gemello (stesso seed senza guasto). I run M sono **senza jitter, 1,5 d**,
mentre gli N1 con lo stesso seed hanno il jitter: **non sono gemelli** (il programma è diverso dal primo secondo). `train_diagnoser.py`
oggi prende come gemello il nominale con lo stesso seed e `days >= 2`: con questi dati sceglierebbe l'N1 sbagliato o salterebbe i run.

1. **I gemelli li genera la sessione della fase 1** (gruppo `T` di `crew_plan.yaml`: onda 3, nominale senza jitter, 1,5 d, seed 101-124,
   131-138, 141-148; 40 run), sul M5 o sul M5 Pro, e li copia in una cartella di `output/ml/` della cartella principale. Tu cerchi le cartelle
   `crew-T-*` in tutte le sottocartelle di `output/ml/`. Non modificare `crew_plan.yaml` nel tuo ramo: il gruppo `T` arriva dal ramo della fase 1.
2. Nel codice dell'addestramento il gemello si cerca per (seed, `days`, nessun jitter, nessun guasto), mai per seed soltanto. Prima di usarlo,
   **controlla che run e gemello abbiano caratteristiche identiche prima dell'inizio del guasto** (differenza massima 0 su `features.parquet`
   e su `crew.parquet`). Se non lo sono, fermati e segnalalo: vorrebbe dire che il determinismo non regge.
3. Finché i gemelli non ci sono (cioè fino alle 17:45 circa), lavora sullo stadio A, che non ne ha bisogno. Se alle 18:15 mancano ancora, ripiego
   dichiarato nella scheda: visibile = inizio + `ramp_s` (e per la disidratazione inizio + 1 h).

## Vincoli

- Non toccare `src/ares3/plugins/physiology/`, `src/ares3/core/`, i file generati `scenarios/station/*` a mano (si cambia
  `tools/build_station.py` e si rigenera), né i modelli in `models/station_v1/`. **I modelli nuovi vanno in `models/station_v2/`.**
- **Il monitor vivo non passa a v2 in questa fase** (è la fase 3). `scenarios/station/monitor.yaml` cambia solo se cambia `classes.yaml`
  (vedi B1), rigenerato con `uv run --with openpyxl python tools/build_station.py` e verificato con `--check`.
- Layering: i moduli in `src/ares3/plugins/monitor/ml/` importano solo `sdk`, `schemas`, numpy, sklearn. L'addestramento sta in `tools/ml/`.
- Il rilevatore legge solo valori **sensati** (le osservazioni) più `NPCState.met/activity` dal tick (come `EarlyWarningScore`). Mai `vitals`.
- **Split per seed**: train 101-124 (130 nel piano: qui ci sono 101-124), val 131-138, test 141-160. Ogni taratura (margini, soglie,
  scelta fra modelli) si fa **solo sulla validazione**. Il test si apre **una volta**, con i modelli congelati: la scheda registra l'ora.
- Ramo `feat/crew-model` (quello del worktree, creato da `feat/crew-dataset`). Commit senza righe di attribuzione. Si addestra
  **solo su questo PC** (le versioni di sklearn delle altre macchine non contano).
- I 180+ test esistenti restano verdi, `ruff` pulito su ciò che aggiungi.

## A. Stadio A dell'equipaggio (priorità 1, entro le 18:00)

### A1. `src/ares3/plugins/monitor/ml/crew_baseline.py`

- `CrewBaselineModel` (salvato con joblib): per ogni (npc, grandezza) un regressore del valore atteso dato il **solo contesto**
  (`ctx|*`, `clock|*`), la scala σ per classe di attività, la matrice di precisione robusta per npc, i limiti, la costante della media mobile,
  il verso clinico di ogni grandezza, la provenienza (come `train_anomaly.provenance`). Metodo `score(npc, row) -> (stat, z, spiegazione)`.
- Grandezze (7): i 6 `|lv10` più `hr|sd10` (l'irregolarità della FA si vede lì). Verso: `hr|lv10`, `resp_rate|lv10`, `skin_temp_c|lv10`,
  `hrv_rmssd|lv10` in entrambi i versi; `spo2|lv10` solo in basso; `core_temp_c|lv10` e `hr|sd10` solo in alto. z limitato a ±10.
- `CrewBaselineDetector(BaseDetector)`, sullo stesso schema di `AnomalyDetector` (stesso modo di pubblicare il punteggio in `tick.ml`,
  stesso rapporto con il debounce del classificatore). Parametri: `model`, `mode: slow | fast`, `eval_every_s: 60`. Tiene un
  `CrewFeatureExtractor`. **slow**: segnale quando la media mobile esponenziale (τ 5 min) di max(D²/L_D, max|z|/L_z) è ≥ 1 (nel YAML:
  `confirm_s: 600`). **fast**: segnale quando |z| di `hr|lv10` o di `hr|sd10` è ≥ `fast_factor` × L_z, senza media (nel YAML: `confirm_s: 120`).
  `Signal`: `emergency: medical`, `subject` = l'astronauta, `module_id` = dove si trova, `cause: crew_baseline`, `value` = il punteggio,
  `evidence` = le 3 grandezze con |z| più alto, in parole: "FC 105 bpm, attesi 68 a riposo (z 6,1)".

### A2. `tools/ml/train_crew.py`

- `--features` con più cartelle; righe di `crew.parquet` dei run N1 (train 101-124 per adattare, val 131-136 per scale e limiti).
- Regressore per (npc, grandezza): `HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, max_iter=200)`, ingressi = contesto
  e orologio. 4 × 7 = 28 regressori.
- σ per (npc, grandezza, classe di attività) = 1,4826 × MAD dei residui **di validazione**, con un minimo (0,5 × MAD di train) contro gli zeri.
  Precisione per npc con `MinCovDet` sugli z di validazione.
- Limiti: L = margine × massimo osservato sulla validazione (N1 val, 12 giorni × 4 persone) della statistica slow e di |z|. Margine scelto
  fra {1,25; 1,5; 2,0}: il **più basso con 0 falsi allarmi su N1 val**, poi si guarda il richiamo sui run M di validazione (131-138).
  `fast_factor` scelto allo stesso modo fra {1,5; 2,0; 3,0}.
- Opzione `--table` (piano B): al posto dei regressori, mediana e MAD per (npc, grandezza, classe di attività, fascia di MET larga 1).
  Stessa interfaccia, stesso rilevatore. **Addestra entrambi e confrontali sulla validazione**; si tiene il migliore (a parità, la tabella).
- Uscita: `models/station_v2/crew_baseline.joblib` e `model_card_crew.json` (split, margini, σ, limiti, metriche di validazione, provenienza).

### A3. `tools/ml/eval_crew.py`: valutazione offline con lo **stesso** codice di punteggio del rilevatore

`--split val|test`. Riproduce sulle righe di `crew.parquet` la statistica, la media mobile e il debounce (`metrics.episodes` con il
`confirm_s` del YAML). Metriche (§3 del piano):
- **falsi allarmi per giorno** sui nominali (val: N1 val; test: N2 30 d + N3 15 d), per persona, con il limite superiore al 95 %
  (regola del tre se 0, Poisson esatto altrimenti). E il conteggio dei segnali **durante l'esercizio nominale** (classe aerobica o resistiva,
  o `min_since_ex` < 30): l'obiettivo è 0 (il caso dei 126 bpm a 7 MET);
- **richiamo a evento** sui run M: rilevato se il segnale riguarda la persona colpita e si apre fra l'inizio e la fine + 30 min. Un segnale su
  un'altra persona conta come falso allarme. Per tipo di evento con intervallo di Wilson al 95 %, e complessivo;
- **ritardo** dal visibile (gemello) se c'è, altrimenti dall'inizio: mediana e p90, con un intervallo bootstrap sui run;
- la tabella dei criteri del §7 del piano, con l'esito di ciascuno.

## B. Famiglia medica dello stadio B (priorità 2, dalle 17:45 con i gemelli, entro le 18:45)

### B1. Etichette nuove in `tools/ml/classes.yaml`

Famiglia `medical`: `svt_suspected` (critical / emergency, `confirm_s` 120), `bradycardia` (warning / warning, 300), `respiratory_infection`
(warning / warning, 300), `abnormal_exertion` (warning / caution, 300), con `phrase` per l'equipaggio. Poi si rigenera con `build_station.py`,
si controlla con `--check` e si fanno girare i test. Il monitor resta su `station_v1`.

### B2. `tools/ml/train_diagnoser.py` (estensione compatibile: senza le opzioni nuove fa quello che fa oggi)

- `--features` accetta più cartelle; `--families medical`; `--base-model models/station_v1/diagnoser.joblib`: le altre famiglie (fisica,
  attuatori, sensori) si copiano intatte dal modello base, e si riusano `mean`/`scale` del base (le firme della famiglia nuova si calcolano con
  quella scala, così le spiegazioni restano coerenti); `--out models/station_v2`.
- Gemelli come sopra (per seed, giorni e niente jitter, con il controllo di identità).
- Dati: positivi dai run M train (101-124). Negativi: righe prima dell'inizio dei run M, N1 train (con jitter: contengono l'esercizio) e i run
  del catalogo di `output/ml/feat` con i seed 1-3 (così un guasto di una macchina non sembra un malore; i loro 5 eventi medici valgono come
  positivi). **Tutte le righe positive, `--stride` solo sulle nominali** (con lo stride 5 di oggi la SVT scenderebbe a meno di 100 righe).
- Lezione (d): una classe con meno di 300 righe positive dopo i `drop` si addestra ma **non entra nel monitor vivo**: la scheda la marca
  `live: false` e il rilevatore la ignora.
- Soglie: estendi `sweep_diagnoser.py` (più cartelle, split val). Per classe, la `min_proba` più bassa con ≤ 0,05 FA/giorno sui nominali di
  validazione (N1 val e i tratti dei run M val prima dell'inizio), poi il richiamo migliore. Salvala nel modello o nella scheda, come oggi.
- Matrice di confusione sulla validazione, soprattutto febbre / infezione respiratoria e stress / sforzo anomalo / SVT / FA.

### B3. Valutazione sul test, una volta

Sugli stessi run di test dello stadio A (M 141-148, N2, N3): richiamo per evento con Wilson, falsi allarmi per giorno, ritardo dal visibile,
**etichetta giusta** (la classe) e **persona giusta** (`subject`). E la stessa tabella per lo stadio A e per A + B insieme (un evento è
rilevato se lo prende almeno uno dei due).

## C. Controllo online (priorità 3, se avanza tempo prima delle 19:00)

Un monitor di prova **fuori** dai file generati, `output/ml/monitor_crew_test.yaml`: il `monitor.yaml` della stazione più i due
`CrewBaselineDetector` (slow e fast) **dopo** le regole, e il diagnosticatore che punta a `station_v2`. Poi:
- **parità**: il seed 151 (N3) per 6 h simulate con questo monitor. Il punteggio online in `tick.ml` deve coincidere con quello che
  `eval_crew.py` calcola dal `crew.parquet` dello stesso run (differenza < 1e-6), purché non si apra un'emergenza;
- **costo**: ms per tick medi su 1 giorno, ≤ 4,7 (oggi 4,4), con al massimo 6 worker;
- `check_monitor.py --monitor output/ml/monitor_crew_test.yaml --nominal --seeds 151 --days 1`.

## Test (veloci) in `tests/test_crew_baseline.py`

Un modello sintetico piccolo, costruito nel test e non letto da joblib. A riposo, con valori nella norma, nessun segnale. Con la FC a +40 a
riposo c'è un segnale, con `subject` e `evidence` giusti. Con la FC a 140 e MET 7 nessun segnale. La modalità fast scatta prima della slow.
Il rilevatore non legge mai `vitals`. Più `test_architecture.py`.

## Ordine se il tempo non basta

A1+A2 (anche solo `--table`) → A3 su val e test → B1+B2 → B3 → C. Alle **19:00** c'è il cancello del piano B: deve esserci almeno lo stadio A
addestrato e valutato.

## Cosa consegnare (riporta l'output)

1. `uv run pytest -q -n auto` verde, `uv run ruff check src tests tools/ml` senza avvisi nuovi.
2. `models/station_v2/`: `crew_baseline.joblib`, `model_card_crew.json`, `diagnoser.joblib` (medica nuova, il resto dal v1),
   `model_card_diagnoser.json`.
3. Le tabelle di validazione e di test (stadio A, stadio B medico, A + B), con gli intervalli, e i criteri del §7 marcati superato / non
   superato. Per i criteri non superati, la causa probabile: **non si ritocca niente guardando il test**.
4. Il confronto regressore / tabella sulla validazione e quale si è tenuto.
5. Lo stato dei gemelli (gruppo T): quando sono arrivati e se il controllo di identità è passato.
6. Lo stato del ramo `feat/crew-model`: i commit, e i file che si sovrappongono al ramo della fase 1 (attesi solo `classes.yaml` e
   `monitor.yaml` rigenerato), così il merge lo fa l'utente senza sorprese.
6. Ogni scelta fatta senza indicazioni, e cosa resta per la fase 3: il rilevatore in `build_station.py`, il monitor su v2, il confronto con le
   regole online (`check_monitor.py` R / R+A / R+A+B) e le classi congiunte `crew_env` sui dati dell'onda 2.
