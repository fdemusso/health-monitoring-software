# Piano: riconoscimento ML dei problemi e sistema di monitoraggio a tre stati

Stato: PIANO DECISO (team software), 2026-11-15. Le domande che avremmo fatto a Mario e Luca sono chiuse nel §10, ricavandole
dal codice, dal workbook o da fonti pubbliche; ogni scelta nostra è marcata ESTIMATE ed è reversibile senza toccare il codice
di Luca né i file generati. Tutto in termini ISS, mai Marte.

---

## 1. Cosa c'è già e cosa manca

### Già fatto (non va rifatto)

| Pezzo | Dove | Cosa fa |
|---|---|---|
| Rilevatori a regole | `plugins/monitor/detectors.py` (`Threshold`, `NpcThreshold`, `PressureDrop`) | leggono valori MISURATI, emettono `Signal` |
| Classificatore (debounce) | `core/monitor.py` | `suspected` -> `confirmed` -> `cleared` per (tipo, modulo, soggetto), causa dal rilevatore più specifico |
| Playbook | `core/responder.py`, `scenarios/station/monitor.yaml` | passi `auto` (messa in sicurezza) e `confirm` (richiesta all'equipaggio, timeout `execute`/`discard`), guardia "nessuno tagliato fuori dal veicolo di rientro" |
| Reazione dell'equipaggio | `core/response.py` | Warn/Gather/Work, ruoli, evacuazione nel `lifeboat` con TRes basso, riparazioni |
| Superficie di comando | `sdk/control.py`, `serve/session.py`, `dashboard/src/telemetry/websocket.ts` | inject, approve/reject, dichiarazione manuale di un'emergenza |
| Dataset etichettato | `Engine._row`, `export/writers.py` | `value`, `value_true`, `is_anomaly`, `anomaly_type`, `anomaly_ids` (long + wide Parquet) |
| Catalogo guasti | `scenarios/station/faults/` (26 guasti), `scenarios/events/` (eventi medici sull'habitat piccolo) | etichette ML del foglio 06 di Mario |

`schemas/monitor.py::MonitorConfig` lo prevede già: *"an ML detector is just one more entry in `detectors`"*. Anche
`sdk/base.py::BaseAgent` cita `PASSIVE_MONITORING -> ALERT -> REACTION`, ma non è implementato.

### Cosa manca

1. **Nessun modello ML.** Le regole prendono i guasti NETTI (gradino, allarme in minuti). La guida di Mario (§6.1, foglio
   `06_GUASTI`) è esplicita: *"i guasti subdoli sono gli unici che giustificano un modello ML"*. Ce ne sono 12 su 26 (deriva del
   CO2, invecchiamento della cella O2, degrado CDRA/OGA/IMV/ventola di cabina, perdita del PrK, condensa RH, filamento MCA, ...),
   e oggi nessun rilevatore li vede prima che la grandezza vera esca dai limiti (o mai).
2. **Nessuna diagnosi né localizzazione.** `PressureDrop` apre un'emergenza in OGNI modulo che la perdita svuota
   (`docs/station.md`, "known limits"). Un CO senza fumo né calore (`co_source`) oggi viene chiamato `fire`. Un bias negativo su
   `usl_P_a` sembra l'inizio di una perdita.
3. **Gli stati del sistema non sono espliciti.** Monitoraggio passivo / allerta / reazione esistono solo implicitamente
   (`suspected` / `confirmed`). La UI non ha un unico "livello" da mostrare.
4. **La reazione è solo una lista di comandi.** Mancano le procedure a passi per l'equipaggio (istruzioni, controlli,
   biforcazioni, verifica dell'esito), in particolare quelle mediche. I tipi `toxic` e `sensor_fault` non hanno né rilevatori
   né playbook; `medical` ha solo un annuncio.
5. **Manca il comando "togli alimentazione a un modulo".** Esistono `actuator on/off` (OGA = spegnere l'ossigeno, PCA = gas di
   rabbocco), `hatch close`, `ventilation off`, `extinguish`; non esiste `power`. Sulla ISS la risposta automatica a un incendio
   toglie alimentazione ai rack per isolare le sorgenti d'innesco [R3].
6. **L'etichetta del dataset dice "guasto attivo", non "effetto visibile".** Per un degrado su 24 h le prime ore sono etichettate
   anomale ma sono indistinguibili dal nominale: addestrare un classificatore su quelle righe insegna rumore.

---

## 2. Decisioni di progetto (le raccomando, salvo obiezioni)

1. **Ibrido, non sostitutivo.** Le regole restano per i guasti netti e per tutto ciò che salva la vita in secondi (breccia,
   incendio, SpO2): sono verificabili e seguono NASA-STD-3001 / ICES-2025-126. L'ML aggiunge due rilevatori che producono gli
   stessi `Signal` e passano dallo stesso classificatore e dagli stessi playbook. Un guasto dell'ML non deve mai togliere una
   regola: le regole sono la rete di sicurezza (lo schema ibrido che la letteratura FDIR raccomanda [R10]).
2. **Due stadi ML.**
   * **A - Rilevamento (non supervisionato):** "c'è qualcosa di anomalo?", addestrato SOLO sul nominale. Vede anche guasti mai
     visti. Eredità NASA: l'Inductive Monitoring System, certificato nel Mission Control della ISS, fa proprio questo (distanza dal
     comportamento nominale appreso dai dati archiviati) [R4].
   * **B - Diagnosi (supervisionato):** "quale guasto, in quale modulo, con che probabilità, perché". Addestrato sul catalogo
     etichettato. Dà la `cause`, la severità e la localizzazione che scelgono il playbook e la procedura.
3. **Caratteristiche costruite a mano dalla fisica, non serie grezze.** Il foglio 06 di Mario ha una colonna "Come distinguerlo
   da altro" che è già una lista di caratteristiche (rapporto P/T, delta fra moduli, coppie ridondanti, varianza, tensione/corrente
   OGA, ...). Modelli piccoli su caratteristiche buone battono modelli grandi su dati grezzi con questa quantità di dati, sono
   spiegabili all'equipaggio e girano in tempo reale.
4. **Librerie:** `scikit-learn` (+ `joblib`) in un extra opzionale `ml`. Niente TensorFlow (i notebook di Luca lo usano, ma è
   pesante e non serve qui). LSTM alla Telemanom [R5] solo come estensione se resta tempo.
5. **Stessa estrazione di caratteristiche online e offline.** Un solo modulo `features.py` usato sia dal rilevatore nel
   simulatore sia dall'addestramento: niente divario addestramento/inferenza.
6. **Inferenza a cadenza propria** (`eval_every_s`, default 30-60 s): i guasti subdoli evolvono in ore, il budget del tick della
   stazione è 3-4 ms. Le finestre usano somme mobili O(1) come `_Window`.
7. **Strati rispettati (`tests/test_architecture.py`).** L'inferenza vive in `plugins/monitor/ml/` (importa solo `sdk`,
   `schemas`, numpy/sklearn). L'addestramento sta in `tools/ml/` (fuori dal pacchetto, legge il Parquet), come
   `tools/build_station.py`. Nessun nuovo pacchetto sotto `src/` -> `LAYERS` invariato.
8. **Il monitor non legge mai la verità.** Vale anche per l'ML: input = `Observation.value` (misurato). `value_true` serve solo a
   costruire etichette ed esperimenti offline.

---

## 3. I tre stati del sistema di monitoraggio

Mappati sui livelli di allarme della ISS: Emergency (tempo-critico: incendio, depressurizzazione rapida, atmosfera tossica),
Warning (richiede azione immediata), Caution (richiede attenzione ma non azione immediata), più gli Advisory [R1][R2]. Il medico
è una categoria a parte [R2], come nel nostro `medical`.

| Stato | Quando | Cosa fa il sistema | Cosa vede l'equipaggio |
|---|---|---|---|
| **MONITORAGGIO PASSIVO** | nessuna emergenza aperta, punteggi ML sotto soglia | registra, aggiorna le basi personali e le tendenze, eventuali `advisory` (es. "taratura usl_ppCO2_a fra 3 giorni") | pannello verde, nessuna interruzione |
| **ALLERTA** | almeno un'emergenza `suspected`, oppure una `warning`/`caution` confermata, oppure anomalia ML senza diagnosi certa | riconosce il problema: diagnosi, probabilità, modulo, spiegazione; propone CONTROLLI ("confronta usl_P_a con usl_P_b", "verifica il condensato della CCAA-NOD3") | banner giallo/ambra, scheda del problema, richieste non bloccanti |
| **REAZIONE** | almeno un'emergenza `confirmed` con playbook o procedura in corso | esegue i passi `auto`, presenta i passi `confirm` (staccare l'alimentazione di un modulo, spegnere l'OGA, chiudere un portello) con conto alla rovescia, guida la procedura a passi, verifica l'esito | banner rosso (emergency) o arancio (warning), checklist, richieste con timer |

Regole di transizione (in `core/monitor.py`, nuova classe piccola `ModeTracker` o metodo della `Monitor`):
* lo stato è il MASSIMO sulle emergenze aperte (`reaction` > `alert` > `passive`);
* si torna a `passive` solo quando tutte sono `cleared` e le procedure sono chiuse (o dopo `stand_down_delay_s`, come
  l'equipaggio): isteresi, niente sfarfallio;
* ogni cambio genera un `MonitorEvent(kind="mode_changed")`.

Ogni `Emergency` riceve anche `alert_class: emergency | warning | caution | advisory`, derivata da (tipo, severità) con una
tabella in YAML (`classifier.classes`), così la UI colora senza logica propria.

---

## 4. Stadio A: rilevamento delle anomalie (non supervisionato)

**Modelli per sottosistema**, non uno solo per tutta la stazione (spiegabile: "anomalia nel sottosistema CO2", e un guasto in un
gruppo non diluisce l'altro):

| Gruppo | Ingressi principali |
|---|---|
| `atmosphere_pressure` | P per modulo, rapporto P/T, PCA (apertura, conteggio aperture), stato portelli |
| `atmosphere_co2` | ppCO2 per modulo e cabina, CDRA (potenza, ASV, T letti, delta ingresso-uscita), MCA |
| `atmosphere_o2` | ppO2 (celle galvaniche e paramagnetiche), OGA (V, I, portata, duty cycle), MCA |
| `thermal_humidity` | T, RH, condensato CCAA, TCS, sensore acqua liquida |
| `ventilation` | IMV/CCAA/ventole di cabina (giri, corrente), delta fra moduli a valle |
| `crew_<id>` | parametri vitali del singolo, normalizzati sulla SUA base personale |

**Metodo (in ordine, si passa al successivo solo se serve):**
1. *PCA con T² di Hotelling + SPE* su caratteristiche standardizzate: lineare, veloce, deterministica, si spiega con i contributi
   per variabile. Buon punto di partenza per ventilazione e CO2 (fenomeni coerenti fra moduli).
2. *Isolation Forest* (scikit-learn) dove i dati non sono lineari (pressione con ciclo orbitale e turni dell'equipaggio).
3. *Autoencoder piccolo* (MLP di scikit-learn) per i parametri vitali: è l'idea dei notebook ECG di Luca (errore di ricostruzione
   con soglia), applicata alle finestre di FC/HRV/SpO2/FR/temperature; la usiamo senza toccare il suo codice.

**Soglia:** sul punteggio di anomalia, dinamica e non parametrica come in Telemanom [R5] (media + k deviazioni di una finestra di
errori recenti, con riduzione dei falsi positivi), tarata sui giorni nominali per avere ZERO falsi allarmi per giorno simulato.

**Uscita:** sopra soglia per il sottosistema -> `Signal(emergency="anomaly", severity="warning", detail=<top-3 contributi>)`.
Nuovo tipo di emergenza `anomaly` ("anomalia senza causa nota", classe `caution`): stato ALLERTA, playbook = annuncio + procedura
di controllo. Se lo stadio B riconosce il guasto, la sua emergenza specifica prende il posto di quella generica.

---

## 5. Stadio B: diagnosi, localizzazione, spiegazione (supervisionato)

**Classi:** le 26 `anomaly_type` del catalogo della stazione + le classi mediche (`fever`, `dehydration`,
`atrial_fibrillation_suspected`, `acute_stress`, `space_motion_sickness`, `hypoxia`, `co_poisoning`) + `nominal`. Le etichette
restano quelle che ci sono; una tabella di corrispondenza le rende indipendenti dal nome (§10 D1).

**Modello:** `HistGradientBoostingClassifier` (scikit-learn) su finestre di caratteristiche, probabilità calibrate, UN
classificatore per famiglia (fisico / attuatore / sensore / medico), ognuno con la sua classe `nominal`: così due guasti di
famiglie diverse sovrapposti vengono riconosciuti entrambi (§10 D10).

**Caratteristiche (`plugins/monitor/ml/features.py`), dalla colonna "Come distinguerlo" di Mario:**

| Caratteristica | Guasto che separa |
|---|---|
| media, deviazione standard, pendenza su 10 min / 1 h / 6 h / 24 h per sensore | tutti; varianza ~0 = `sensore_bloccato`, deviazione alta con media ferma = `rumore_sensore` |
| frazione di campioni mancanti | `dropout_sensore`, `guasto_mca_linea` (mancano SOLO alcuni moduli) |
| residuo fra sensori ridondanti (`_a - _b`) e verso l'MCA (lento ma stabile) | `bias_sensore_P`, `deriva_sensore_CO2`, `deriva_sensore_O2`, `offset_sensore_RH`, `deriva_mca` (tutti i canali di UNO strumento insieme) |
| modo comune su tutti i moduli (media fra moduli) contro scarto del singolo modulo | `degrado_cdra` (tutti i ppCO2 salgono insieme) contro deriva di un sensore |
| delta fra moduli a valle e a monte di una ventola | `degrado_imv`, `arresto_imv` |
| `n ∝ P/T` (moli d'aria), sua pendenza su ore | `perdita_prk` (0.16 kPa/giorno < effetto di 1 K) |
| P in salita E ppO2 in calo | `guasto_pca_aperta` |
| comandato contro misurato (portelli, PCA, attuatori) | `portello_bloccato`, `guasto_pca_chiusa` |
| telemetria attuatori: V/I stack OGA, T letti CDRA, potenza, corrente/giri ventole, delta ppCO2 ingresso-uscita CDRA | `degrado_oga`, `guasto_riscaldatore_cdra`, `degrado_ventola_ccaa`, `degrado_cdra` (il segnale più precoce) |
| RH alta CON raffreddamento sensibile normale | `guasto_chx` |
| fase giorno/notte e occupazione della cabina | `degrado_ventola_cabina` (la CO2 di CQ4 sale quando l'astronauta dorme) |
| fase orbitale, stato di carica | "orologio" per separare il ciclo orbitale dagli eventi (guida §8) |
| fumo + CO + T locale contro CO da solo | `incendio` contro `co_source` (-> `toxic`, non `fire`) |
| vitali: z-score sulla base personale (FC, HRV, SpO2, FR, T cute/centrale, COHb), punteggio tipo NEWS2 | classi mediche |

**Localizzazione:** per i guasti di modulo, il classificatore lavora su caratteristiche per modulo e sceglie il modulo con la
probabilità più alta; per le perdite si aggiunge un'euristica fisica (il modulo che scende per primo / più in fretta, e dopo
l'isolamento il lato che continua a scendere), così il playbook isola il modulo giusto e non tutti quelli drenati.

**Spiegazione per l'equipaggio:** le 3 caratteristiche che contano di più per quella previsione (importanza per permutazione
locale o contributi dell'albero) tradotte in frase con una tabella `features.yaml` ("delta ppCO2 ingresso-uscita CDRA -40 % in
6 h; potenza CDRA nominale"). La spiegabilità va dentro la decisione, non dopo [R10]. Il testo è nel `detail` del `Signal` e nel
nuovo campo `Emergency.evidence`.

**Uscita:** `Signal(emergency=<tipo da tabella classe->tipo>, severity=..., module_id=..., subject=..., detail=...)` con la
`cause` = la classe. Si apre/conferma col classificatore esistente; soglia di probabilità e `confirm_s` per classe nel YAML.
Classi -> tipo di emergenza (tabella in `monitor.yaml`, non nel codice): degradi/arresti -> `equipment`, guasti di sensore ->
`sensor_fault`, perdite -> `depressurization` (warning), CO senza fumo -> `toxic`, medico -> `medical`.

---

## 6. Dati: generazione, etichette, valutazione

### 6.1 Generatore di dataset (`tools/ml/make_dataset.py`)
* Corre in parallelo (multiprocessing) le simulazioni della stazione:
  * giorni nominali con semi diversi (base del rilevatore A e misura dei falsi allarmi);
  * i 26 guasti con **parametri estratti a caso nell'intervallo [min, max] del foglio 06** e istante d'inizio casuale;
  * eventi medici iniettati sulla stazione (stessi `medical` fault di `scenarios/events/*_faults.yaml`, ma programmatici, senza
    nuovi file di scenario);
  * **combinazioni di due guasti** (deriva CO2 su degrado CDRA, perdita PrK durante PCA chiusa): secondo Mario è dove l'ML batte
    in modo evidente qualunque soglia.
* Gli intervalli dei parametri escono dal workbook: **`tools/build_station.py` genera `scenarios/station/fault_ranges.yaml`**
  (i file generati non si toccano a mano).
* Scrive direttamente le caratteristiche (una riga ogni `eval_every_s`) con `features.py`, oltre al Parquet grezzo se richiesto:
  dataset piccolo, nessun divario fra addestramento e inferenza.
* Dimensioni, semi, `dt_s` e costo: decisi in §10 (D9).

### 6.2 Etichetta "effetto visibile" con la corsa gemella
Il motore è deterministico e ogni componente ha il suo flusso casuale (`core/rng.derive`): la stessa corsa SENZA il guasto
(stesso seme) è identica fino all'effetto. Confrontando `value_true` fra corsa con guasto e corsa gemella si ottiene, per ogni
guasto, l'istante `visible_since_s` in cui almeno un sensore si discosta più di k·sigma. Serve a:
* addestrare la diagnosi solo dove il guasto è osservabile (o pesare le righe);
* misurare il ritardo di rilevamento da quando era POSSIBILE vederlo, non da quando è iniziato.
(Prima della risposta dell'equipaggio le due corse coincidono; dopo divergono, ed è giusto così.)

### 6.3 Suddivisione e metriche
* Suddivisione **per corsa / seme**, mai per riga (le righe consecutive sono quasi uguali: fuga di informazione). Combinazioni e
  alcuni semi tenuti solo per il test.
* Metriche a evento come ESA-ADB [R6]: F0.5 a evento (penalizza i falsi allarmi), recall a evento, **ritardo di rilevamento**
  (da `visible_since_s`), falsi allarmi per giorno nominale; per la diagnosi matrice di confusione e accuratezza della
  localizzazione.
* **Criteri di accettazione** = colonne "Firma osservabile" e "Allarme atteso" del foglio 06, più:
  * 0 emergenze aperte dall'ML su 10 giorni nominali (estende `test_nominal_day_opens_no_emergency`);
  * i guasti subdoli riconosciuti PRIMA della regola corrispondente (es. `degrado_cdra` prima che la media oraria di ppCO2
    superi 3 mmHg; `arresto_cdra` dalla telemetria ore prima dell'ambiente);
  * nessun guasto netto rilevato più tardi di oggi (le regole restano);
  * stesso seme -> stesso registro del monitor anche con l'ML (estende `test_same_seed_gives_the_same_monitor_log`);
  * costo medio dell'ML < 1 ms per tick sulla stazione.
* Report `tools/ml/report.py` (HTML come `tools/npc_report.py`): curve, matrice di confusione, ritardi per guasto, esempi
  spiegati.

### 6.4 Artefatti del modello
`models/station_v1/` con `detector_<gruppo>.joblib`, `diagnoser.joblib` e `model_card.json` (elenco caratteristiche, hash del
dataset, semi, versione di ares3 e del workbook, metriche). Il rilevatore li carica da `params.model`. `joblib` esegue codice al
caricamento: si caricano solo modelli prodotti da noi (scritto nella model card e nel docstring).

---

## 7. Reazione: procedure a passi e richieste a schermo

### 7.1 Procedure (nuovo concetto accanto ai playbook)
Un playbook resta la messa in sicurezza della macchina; una **procedura** è la checklist per le persone, selezionata da
(tipo di emergenza, `cause`). Schema in `schemas/monitor.py`:

```yaml
procedures:
  - id: med_hypoxia
    emergency: medical
    cause: hypoxia
    title: "Ipossia: SpO2 sotto 90 %"
    steps:
      - {id: s1, do: instruction, text: "Raggiungi {subject} e verifica che sia cosciente", role: medical}
      - {id: s2, do: action, action: {do: crew, target: "{subject}", command: relocate, value_module: safest}, level: confirm,
         confirm_timeout_s: 60, on_timeout: execute, reason: "portare in un modulo con PIO2 nominale"}
      - {id: s3, do: instruction, text: "Maschera O2 / ossigeno supplementare", role: medical}
      - {id: s4, do: check, metric: spo2, subject: "{subject}", min: 94, within_s: 300,
         on_fail: s5, on_pass: done}          # verifica AUTOMATICA dell'esito sui valori misurati
      - {id: s5, do: escalate, text: "SpO2 non migliora: contatta il chirurgo di volo, prepara l'evacuazione nel lifeboat"}
```

Tipi di passo:
* `instruction`: testo per l'equipaggio, chiuso con "fatto" (dalla UI o dall'NPC con quel `role` dopo `duration_s`);
* `action`: un `ActionSpec` esistente (`auto` / `confirm`, stessa guardia di sicurezza, stesso timeout);
* `check`: verifica automatica su valori MISURATI entro un tempo, con biforcazione `on_pass` / `on_fail`;
* `question`: domanda sì/no all'equipaggio ("vedi fumo?") con biforcazione;
* `escalate`: passa al livello successivo (procedura più grave, evacuazione, terra).

Esecuzione: `core/procedures.py::ProcedureRunner`, chiamato accanto al `Responder` nella fase 9; stato in
`SimulationTick.procedures` (passo corrente, stato di ogni passo, chi l'ha chiuso). Nuovo comando
`ControlAPI.ack_step(procedure_id, step_id, by, answer=None)`; chiunque può chiudere un passo (memoria del progetto: il monitor
è aperto a tutti). Gli NPC con `npc_approves_actions` eseguono i passi del loro ruolo, così le corse senza UI restano complete
e il dataset delle decisioni si genera da solo.

**Fuori perimetro (per non toccare il codice di Luca):** un trattamento non cambia direttamente la fisiologia. Ha effetto solo
attraverso l'ambiente (spostare la persona, ventilare, togliere la sorgente di CO). Le verifiche automatiche delle procedure
sono quindi scritte su ciò che il simulatore può produrre (§10 D3).

### 7.2 Nuova azione `power` (staccare l'alimentazione a un modulo)
* `ActionKind` + `power`; `target: <modulo>`, `command: off|on`.
* Motore: modulo senza alimentazione -> i suoi attuatori come `actuator_offline` (telemetria a zero), calore dei rack
  (`base_heat_w`) a zero, ventole del modulo ferme, carico del bus ridotto; un `fire` con `params.electrical: true`
  (predefinito) perde la sorgente d'innesco e si spegne in fretta (parametro `unpowered_factor`, ESTIMATE). Fonte della
  sequenza: la risposta automatica ISS al fumo toglie alimentazione ai rack, ferma la ventilazione del modulo e inibisce
  l'immissione di O2/N2 [R3].
* Granularità, livelli e ripristino: decisi in §10 (D5).

### 7.3 Playbook e procedure da scrivere (contenuto, tutto ESTIMATE finché non lo rivede il team)

| Emergenza / causa | Messa in sicurezza (playbook) | Procedura (persone) |
|---|---|---|
| `fire` | ventilazione off, **power off modulo (confirm)**, OGA/PCA off (esiste) | localizzare (CSA-CP / fumo), estintore, maschere, verifica CO, evacuazione se dopo `fire_evacuate_s` brucia ancora (esiste) |
| `toxic` (CO senza fumo, nuovo) | ventilazione del modulo off, isolamento (confirm) | maschere, ritiro in un modulo pulito, chiusura portello, misura (come la risposta ISS all'allarme ammoniaca del 2015: maschere, ritiro, portello chiuso, verifica con tubi rivelatori [R7]) |
| `depressurization` warning | esiste | ricerca della perdita: chiusura portello per portello e verifica del lato che scende (il classificatore B indica il candidato) |
| `equipment` per classe (CDRA, OGA, IMV, CCAA, TCS, ventola cabina) | dove ha senso: unità di riserva (CDRA-B, già), carico ridotto | controlli specifici (ispezione ventola, filtro, condensato), riparazione (`repair_s`, esiste) |
| `sensor_fault` (nuovo) | nessun comando forzato | "non fidarti di X, usa Y": avviso; passo `confirm` "passa il controllo al sensore ridondante" (azione `sensor substitute`, §10 D6) |
| `anomaly` (nuovo, senza causa) | nessuna | controlli guidati dai contributi (confronto sensori, ispezione del sottosistema) |
| `medical` per causa: ipossia, CO, febbre/calore, disidratazione, aritmia, stress, chinetosi | per CO/ipossia: come `toxic` sul modulo del soggetto | il medico va dal soggetto (esiste); procedure della tabella §10 D3; verifica automatica dell'esito; escalation |

Per il medico come base di regole (e caratteristica per lo stadio B): un punteggio aggregato **tipo NEWS2** (FR, SpO2, FC,
temperatura; coscienza ≈ `health_state` >= 2; pressione arteriosa non c'è) con fasce 0-4 / 5-6 / >=7 e "un parametro a 3" come
allerta [R8]. È uno strumento ospedaliero terrestre: adattamento ESTIMATE da confermare con Luca. Il riferimento per il
contenuto è il progetto NASA Clinical Decision Support (assistente di bordo che guida l'equipaggio nelle presentazioni cliniche
senza la terra, carico cognitivo ridotto) [R9]; la checklist medica della ISS è organizzata per apparato e per
emergenza/non emergenza [R11]: usiamo la stessa organizzazione.

---

## 8. Protocollo e UI (la UI è di un altro sviluppatore: noi diamo il contratto)

* `SimulationTick`: + `monitor_mode`, + `procedures`, + `ml` (punteggio per sottosistema, prime 3 diagnosi con probabilità e
  spiegazione); `Emergency`: + `alert_class`, + `evidence`; `MonitorEvent.kind`: + `mode_changed`, `step_done`, `step_failed`,
  `procedure_started`, `procedure_done`, `ml_anomaly`.
* `ActionKind`: + `power`, + `sensor` (`substitute`), + `crew` (ordini a un NPC: `relocate`). `EmergencyKind`: + `anomaly`.
  `ActionSpec`/`Action`: + `value_id` (id di un sensore o di un modulo, accanto al `value` numerico).
* Colori per `alert_class`: emergency rosso, warning arancio, caution giallo, advisory blu; `passive` verde.
* Comando WebSocket `ack_step {procedure_id, step_id, by?, answer?}` in `serve/session.py`.
* Specchio a mano in `dashboard/src/telemetry/types.ts` e comando in `websocket.ts` (`WebSocketBackend`).
* Nota per lo sviluppatore UI (`docs/monitor-ui.md`): banner per stato (verde/giallo/arancio/rosso), scheda del problema con
  spiegazione, carte delle richieste con conto alla rovescia e chi ha approvato, checklist con passo corrente, nessuna logica di
  soglie nella UI (arriva tutto calcolato).

---

## 9. Fasi di lavoro

Due filoni paralleli fra i due ingegneri software: **ML** (F0, F2, F3) e **stati + reazione** (F1, F4, F5).

| Fase | Contenuto | File principali | Prova di fine fase | Taglia |
|---|---|---|---|---|
| **F0 Dati** | `fault_ranges.yaml` e `substitutes.yaml` dal workbook; `classes.yaml`; `features.py`; generatore (D9) con parametri casuali, combinazioni, eventi medici sulla stazione; corsa gemella e `visible_since_s`; etichette `hypoxia`/`co_poisoning`; metriche a evento | `tools/build_station.py`, `tools/ml/classes.yaml`, `plugins/monitor/ml/features.py`, `tools/ml/make_dataset.py`, `tools/ml/metrics.py` | dataset generato; `build_station.py --check` pulito; test: stessa caratteristica online e offline sullo stesso seme | M |
| **F1 Stati** | `monitor_mode`, `alert_class`, `mode_changed`, isteresi; tabella classi in YAML | `core/monitor.py`, `schemas/monitor.py`, `sdk/types.py` | test: nominale = `passive` tutto il giorno; perdita: passive -> alert -> reaction -> passive | S |
| **F2 Stadio A** | rilevatori di base che sono anche caratteristiche (`Variance` per sensore bloccato/rumore, `RedundancyResidual` per coppie `_a/_b` e MCA, `EarlyWarningScore` tipo NEWS2); PCA/IForest per sottosistema; soglia dinamica; tipo `anomaly` | `plugins/monitor/detectors.py`, `plugins/monitor/ml/anomaly.py`, `tools/ml/train_anomaly.py` | 0 falsi allarmi su 10 giorni nominali; i guasti di sensore del catalogo rilevati | M |
| **F3 Stadio B** | 4 classificatori per famiglia (D10), localizzazione (D11, `group_by: connected`), spiegazione, mappa da `classes.yaml`; `CombustionSignature` e CO -> `toxic` (D12) | `plugins/monitor/ml/diagnoser.py`, `tools/ml/train_diagnoser.py`, `core/monitor.py`, `scenarios/monitor_placeholder.yaml` + tool | matrice di confusione sul test; subdoli prima delle regole; una sola emergenza nel modulo giusto per F-FIS-PERDITA-RAPIDA; report HTML | L |
| **F4 Reazione** | `ProcedureRunner`, `ack_step`, passi NPC (D14); azione `power` con livelli e ripristino (D5); azione `sensor substitute` (D6); playbook/procedure di §7.3 e D3; punteggio medico (D4) | `core/procedures.py`, `core/engine.py`, `core/responder.py`, `sdk/context.py`, `sdk/control.py`, `scenarios/monitor_placeholder.yaml` + tool | test: incendio in COL -> power off auto -> fuoco più debole; incendio in USL -> power off solo dopo confirm/timeout + CDRA-B sveglio; F-SEN-DERIVA-CO2 -> CDRA-A segue `usl_ppCO2_b`; ipossia -> procedura completa con verifica; guardia `power` sul lifeboat | L |
| **F5 Contratto UI** | campi nuovi, comando WebSocket, mirror TS, nota UI | `sdk/types.py`, `serve/session.py`, `dashboard/src/telemetry/*` | `tests/test_serve.py` esteso; `pnpm build` passa | S |
| **F6 Chiusura** | fonti, documentazione, CLAUDE.md, model card, demo (combinazione di due guasti in diretta con `ares3 serve`) | `docs/reference/monitoring-ml-sources.md`, `docs/station.md`, `README.md` | demo registrata | S |

Ordine consigliato se il tempo è poco: F1 -> F2 (solo rilevatori di base + PCA) -> F4 (procedure + `power`) -> F3 -> F5 -> F6.
Già dopo F1+F2+F4 i tre stati sono completi end to end; F3 è dove sta il valore ML vero (subdoli e combinazioni).

---

## 10. Decisioni prese al posto del team

Ogni decisione dice da dove viene (codice, workbook, fonte) e come si cambia se Mario o Luca dicono altro. Nessuna richiede di
modificare `plugins/physiology/` né i file generati a mano.

### D1 - Etichette (era: "da concordare con Luca")
* **Si tengono i nomi che ci sono**: `anomaly_type` dei 26 guasti generati dal workbook (italiano: `degrado_cdra`, ...) e quelli
  degli eventi medici di Luca (inglese: `fever`, `atrial_fibrillation_suspected`, ...). Rinominarli vorrebbe dire cambiare il tool
  e i suoi notebook per niente.
* **`tools/ml/classes.yaml`** fa da unico punto di corrispondenza: etichetta -> `family` (fisico / attuatore / sensore /
  medico), `emergency`, `severity`, `cause`, `alert_class`, frase per l'equipaggio. Se un nome cambia si tocca solo questa riga.
* Due classi mediche **ambientali** che il catalogo non ha come guasto, derivate OFFLINE dalla verità sulle righe dei wearable:
  `hypoxia` (SpO2 vera < 90 % per >= 60 s) e `co_poisoning` (COHb vera >= 5 %, la soglia di avviso già nel monitor
  [toxicology-sources]). Sulle righe del soggetto prevalgono sull'etichetta del modulo: si diagnostica la persona, non la stanza.
  `dead` resta com'è (`Engine._row`).

### D2 - Eventi medici sulla stazione (era: eventi solo sull'habitat piccolo)
I 7 eventi di `scenarios/events/*_faults.yaml` vengono iniettati dal generatore sugli id della stazione (`cmd`, `eng`, `med`,
`bot`, stessi profili) con gli STESSI nomi di parametro di Luca, ampiezze estratte in ±30 % del suo valore (ESTIMATE). Nessun
nuovo file di scenario, nessuna modifica a `human.py`.

### D3 - Contenuto delle procedure mediche (era: "da rivedere con Luca")
Regole fisse: si usano solo dotazioni presenti nella lista ufficiale del kit medico ISS [R12] (Variable Oxygen System,
prometazina orale e IM, metoprololo orale, paracetamolo, ibuprofene, flebo 1 L, impacco caldo/freddo, AMBU, kit ALS con
adrenalina/atropina, termometro); **mai dosi** nel testo ("secondo checklist medica / chirurgo di volo"); verifica dell'esito
scritta su ciò che il simulatore può davvero produrre (un trattamento non cambia la fisiologia: conta lo spostamento in aria
sana, §7.1). Ruolo esecutore: `medical` (il `med`); se è lui il soggetto o è incapacitato, il successivo in `succession`.

| Causa (rilevata da) | Passi | Verifica automatica / escalation |
|---|---|---|
| `hypoxia` (SpO2 < 90 %) | 1 controlla PIO2 del modulo del soggetto; 2 se è basso: `relocate` nel modulo sano più vicino (confirm, timeout execute); 3 ossigeno con il VOS, bersaglio SpO2 94-98 % [R13] | SpO2 >= 94 % entro 5 min, altrimenti critico -> evacuazione nel lifeboat se il problema è il modulo, terra |
| `co_poisoning` (COHb >= 5 / 15 %) | 1 fuori dal modulo con CO (`relocate`); 2 O2 al 100 % subito (VOS, maschera senza rirespirazione) [R14]; 3 apre `toxic` sul modulo se il CO è ancora lì | COHb in CALO su 15 min (in aria il tempo di dimezzamento è di ore, con O2 al 100 % ~74 min [R14]: il simulatore produce il primo); COHb >= 15 % o stato >= 2 -> critico |
| `fever_or_heat` (T centrale > 38,5 °C) | 1 distingue: modulo caldo o esercizio recente -> **colpo di calore**: stop esercizio, raffreddamento attivo (impacco freddo), liquidi orali, NIENTE antipiretici [R15]; altrimenti **febbre**: riposo, liquidi, antipiretico solo su indicazione del chirurgo | T centrale in calo entro 60 min; > 40 °C o stato >= 2 -> critico |
| `dehydration` (FC e T centrale su, HRV giù sulla base personale; il wearable non ha un canale idratazione) | 1 liquidi orali, riposo; 2 se non beve o non migliora: flebo 1 L (passo del medico) | FC verso la base personale entro 2 h; altrimenti escalation |
| `atrial_fibrillation_suspected` (RR irregolare: SD/RR ~0,15, FC ~150 [physiology-sources P20]) | 1 stabilità: cosciente? SpO2 >= 90 %? 2 instabile -> critico: kit ALS / AED, terra; 3 stabile -> riposo, ECG, chiama il chirurgo (controllo della frequenza con metoprololo solo su sua indicazione); nei casi NASA erano quasi tutti parossistici [R16] | FC < 110 entro 30 min o ritorno del ritmo regolare -> chiusa; altrimenti escalation |
| `acute_stress` | riposo, riduzione del carico di lavoro, respirazione guidata (`caution`) | FC/HRV verso la base entro 30 min |
| `space_motion_sickness` | movimenti della testa limitati; prometazina (l'IM è la via più efficace nei dati NASA [R17]) su indicazione del chirurgo; `advisory` | FC/T cute verso la base entro 2 h |

Severità e classi: ipossia, CO, aritmia instabile `emergency`/`warning`; febbre, disidratazione, aritmia stabile `warning`;
stress `caution`; chinetosi `advisory`.

### D4 - Punteggio di allerta medico tipo NEWS2 (era: "adattamento da confermare")
* 4 parametri NEWS2 con le sue fasce [R8]: FR, SpO2 (scala 1), FC, temperatura (`core_temp_c`). Coscienza: `health_state >= 2`
  vale 3 punti (equivale a "non vigile"). Pressione arteriosa: il wearable non la misura, termine assente. "+2 se in ossigeno":
  aggiunto quando la procedura ha attivato il VOS.
* Su MEDIA di 5 min, non sul campione: con i wearable in continuo il NEWS2 dà molti falsi positivi (86 % degli allarmi >= 5 nello
  studio COSMIC-19 [R18]). Totale 5-6 o un singolo parametro a 3 -> `medical` warning (`confirm_s` 300); >= 7 -> critico
  (`confirm_s` 60). Una versione senza pressione arteriosa non risulta validata: ESTIMATE, e serve anche come caratteristica
  per lo stadio B.

### D5 - Alimentazione elettrica (era: "chiedere a Mario i canali")
* **Per modulo.** Sulla ISS l'ultimo stadio sono gli RPCM, interruttori remoti da cui l'alimentazione va alle apparecchiature
  [R19]; il workbook non ha la mappa rack/canale, quindi un "bus di modulo" = tutti gli attuatori con `module:` quel modulo in
  `actuators.yaml`, più il calore dei rack (`RACK_HEAT_W`). Se Mario darà i canali, un campo opzionale `power_group` per
  attuatore sostituisce il modulo senza cambiare altro.
* **Moduli vitali, ricavati da `actuators.yaml`:** USL (CDRA-A, PCA, CCAA-USL, IMV-USL-FWD/AFT) e NOD3 (CDRA-B, OGA, TCS,
  CCAA-NOD3, IMV-CUP). Togliere loro corrente è `confirm` con il conto delle conseguenze a schermo; nel playbook incendio
  `on_timeout: execute`, perché con un solo scrubber la ppCO2 sale ~1 mmHg ogni 6-8 h (foglio 06, F-ATT-CDRA-ARRESTO) mentre un
  incendio si misura in minuti; il playbook `equipment` sveglia l'altro CDRA (esiste). Tutti gli altri moduli: `auto` nel playbook
  incendio, come la risposta automatica ISS [R3]. `lifeboat` ed `eva` (alimentazione propria): mai, lo blocca la guardia.
* **Incendio:** `params.electrical: true` predefinito; senza corrente l'intensità si moltiplica per `unpowered_factor = 0.2`
  (ESTIMATE), che si somma a ventole spente (0.15): ~3 %, il fuoco si spegne o lo spegne l'estintore. `electrical: false`
  permette di provare un incendio che non dipende dalla corrente.
* **Ripristino:** mai automatico (come i portelli: è una decisione dell'equipaggio). Quando l'emergenza si chiude viene proposto
  il passo `confirm` "ripristina alimentazione <modulo>" con `on_timeout: discard`.

### D6 - Sensore sostitutivo per i guasti di sensore (era: "dopo")
* Nuova azione `sensor` (`command: substitute`, `target` = sensore guasto, `value_id` = sostituto). La sostituzione la fa il
  motore nello `StepContext` che dà agli attuatori (`ctx.reading(a)` restituisce `b`): nessuna modifica ai plugin degli attuatori.
  Livello `confirm`, `on_timeout: discard`, annullata alla chiusura dell'emergenza.
* I candidati li genera `tools/build_station.py` in `scenarios/station/substitutes.yaml` dalla colonna **"Gruppo di
  ridondanza"** del foglio 03: stesso gruppo e stesso modulo, ESCLUSI i sensori montati su un ingresso/uscita di un apparato
  (nelle note: uscita CDRA-B, diffusore IMV, vicino all'uscita OGA), che misurano un'altra aria. Risultato atteso:
  `usl_ppCO2_a -> usl_ppCO2_b` (CDRA-A), `usl_P_a -> usl_P_b` (PCA), `usl_ppO2_a -> usl_ppO2_b`, `*_T_a -> *_T_b` (CCAA), e
  NESSUN sostituto per `nod3_ppCO2_a` (il `_b` è l'uscita del CDRA-B: la differenza è il segnale di degrado, non una ridondanza) e
  per `nod3_ppO2_a` (il `_b` vede l'O2 appena immesso): lì la procedura dice di usare l'MCA.

### D7 - Soglie e cadenze ML (era: "da tarare")
* Stadio A: soglia per gruppo = 1,25 x il punteggio massimo sui giorni nominali di validazione (0 falsi allarmi per costruzione
  sulla validazione, misurati sul test); la soglia dinamica alla Telemanom [R5] solo se questa non basta.
* Stadio B: `suspected` con probabilità >= 0,6; `confirm_s` per famiglia: sensore 900 s, attuatore e perdite lente 1800 s,
  medico 300 s; `clear_s` = 2 x `confirm_s`. Si cambiano nel YAML.
* `eval_every_s`: 60 s per l'ambiente, 30 s per l'equipaggio. Finestre: 10 min, 1 h, 6 h, 24 h.

### D8 - Tempi compressi
`TIME_COMPRESSION = 30` resta (`tools/build_station.py`): senza, le derive mensili non si vedono in 3 giorni. Le pendenze sono
in unità per giorno simulato; la model card dichiara che "24 h" corrispondono a ~1 mese di deriva reale e che i ritardi di
rilevamento sono tempi di simulazione.

### D9 - Dimensioni del dataset e costo
* Sempre `dt_s: 1` (quello della stazione): generare a 10 s cambierebbe la statistica delle finestre (divario con l'inferenza).
* Corse SENZA `monitor:` (come i file in `scenarios/station/events/`): firme pure e corsa gemella esatta. La valutazione end to
  end si fa a parte, CON il monitor.
* Semi 1-3 addestramento, 4 validazione, 5 test. Guasti: 26 x 5 semi, 3 giorni, inizio uniforme fra 6 e 30 h, parametri
  uniformi in [min, max] del foglio 06 (scalati da `TIME_COMPRESSION`) da `fault_ranges.yaml`. Gemelle: UNA corsa nominale per
  seme è la gemella di tutti i guasti con quel seme (i flussi casuali dei guasti sono indipendenti, `core/rng.derive`). Più 10
  giorni nominali (semi 6-15) per i falsi allarmi, 7 eventi medici x 5 semi (1 giorno), 4 combinazioni x semi 4-5 (solo test).
* Costo stimato: ~145 corse da 3 giorni (~15 min l'una a 3-4 ms per tick) + ~45 corse da 1 giorno ≈ 40 h di CPU ≈ 2,5 h sui
  16 core di questa macchina.

### D10 - Combinazioni e più guasti insieme
Le due di Mario (deriva CO2 su degrado CDRA; perdita PrK con PCA chiusa) + due nostre (cella O2 che invecchia con stack OGA
degradato; IMV FOD con ventola CQ4 degradata). Un classificatore per famiglia riconosce le coppie di famiglie diverse; due guasti
della STESSA famiglia (IMV + ventola cabina, entrambi attuatori) danno solo il più forte: limite dichiarato nel report.

### D11 - Localizzazione della perdita
* Perdita rapida: il gradiente basta (foglio 06): nel classificatore le emergenze `depressurization` di moduli collegati da
  portelli aperti vengono fuse in una sola, intestata al modulo con la caduta più veloce (`classifier.group_by: connected`).
* Perdita lenta: con i portelli aperti la stazione è un volume unico e il gradiente non si misura; lo stadio B dà la classifica
  dei candidati, il passo `confirm` "chiudi il portello del candidato" (playbook warning, esiste) fa la prova come sulla ISS, e il
  lato che continua a scendere conferma.

### D12 - Rilevatore di CO senza fumo
Dal foglio 06 ("fumo + CO + T locale è univoca"): `combustion_co` diventa un rilevatore `CombustionSignature` (CO > 25 ppm E
(fumo > 0,25 mg/m³ O salita di T locale)) -> `fire`; CO da solo -> `toxic` warning, media di 1 h sopra lo SMAC di 1 h (425 ppm
[toxicology-sources T3]) -> `toxic` critico. Si cambia in `scenarios/monitor_placeholder.yaml` e nel tool che ne deriva
`scenarios/station/monitor.yaml`.

### D13 - Dipendenze e artefatti
`scikit-learn>=1.5` nell'extra `ml` e in `dev` (così i test girano); `joblib` arriva con lui. I modelli (`models/station_v1/`,
pochi MB) si committano, così la demo funziona senza riaddestrare; si caricano solo i nostri.

### D14 - Chi chiude i passi
Chiunque, dalla UI o da un NPC (il monitor è aperto a tutti). Le corse senza UI restano complete: i passi `instruction` /
`question` li chiude l'NPC del ruolo dopo `duration_s` (risposta alle domande: la verità del simulatore, perché l'NPC "vede");
i passi `confirm` seguono il flag esistente `npc_approves_actions`.

### Rischi che restano
* **Il modello impara il simulatore.** Rumori e bias sono in gran parte ESTIMATE ([F19] copre 46 sensori su 62). Mitigazione:
  semi diversi, parametri casuali, combinazioni mai viste al test; le metriche non vanno presentate come prestazioni di volo.
* **Contenuto medico**: ricostruito da fonti pubbliche (la checklist medica ISS non è pubblica), marcato ESTIMATE.
* **Costo di calcolo**: se l'ML supera 1 ms per tick si allunga `eval_every_s`; il profilo si misura su
  `scenarios/station/nominal.yaml` all'inizio di F2.

---

## 11. Fonti (da trasformare in `docs/reference/monitoring-ml-sources.md`, tag `[R1]..`)

* [R1] NASA, *CLD HSI Workshop - Alerts* (livelli Emergency / Warning / Caution, toni):
  https://ntrs.nasa.gov/api/citations/20240003565/downloads/CLD%20HSI%20Workshop%20Alerts.pdf ; ESA, blog della missione Principia
  (tre livelli più advisory, etichette FIRE / ΔP/Δt / ATM): https://blogs.esa.int/tim-peake/?p=945
* [R2] NASA, *Emergency Ops History*, SpaceOps 2023 (tre emergenze: depressurizzazione rapida, incendio, atmosfera tossica; medico
  a parte): https://ntrs.nasa.gov/citations/20220019247 ; e `[ICES-2025-126]` già in `docs/reference/depressurization-sources.md`
* [R3] NASA 2003, risposte automatiche al fumo/incendio: togliere alimentazione ai rack, ventilazione del modulo off, inibire
  O2/N2: https://ntrs.nasa.gov/api/citations/20030053429/downloads/20030053429.pdf ; SAE 2003-01-2595, *ISS Automated Safing
  Responses to Fire Emergencies*: https://saemobilus.sae.org/papers/international-space-station-iss-automated-safing-responses-fire-emergencies-2003-01-2595
* [R4] NASA Ames, *Inductive Monitoring System* (monitoraggio dati-guidato, certificato nel MCC della ISS):
  https://technology.nasa.gov/patent/TOP2-175 , https://c3.ndc.nasa.gov/dashlink/static/media/publication/IMS_JACIC.pdf
* [R5] Hundman et al., KDD 2018, *Detecting Spacecraft Anomalies Using LSTMs and Nonparametric Dynamic Thresholding*:
  https://arxiv.org/abs/1802.04431 (codice: https://github.com/khundman/telemanom)
* [R6] Kotowski et al. 2024, *European Space Agency Benchmark for Anomaly Detection in Satellite Telemetry* (metriche a evento,
  F0.5): https://arxiv.org/abs/2406.17826
* [R7] Allarme ammoniaca ISS, gennaio 2015 (maschere, ritiro nel segmento russo, portello chiuso, circuito di raffreddamento
  spento, verifica con tubi Draeger): https://spaceflightnow.com/2015/01/14/engineers-study-possible-coolant-leak-aboard-space-station/ ,
  https://www.nasaspaceflight.com/2015/01/iss-ammonia-leak-alarm-false-indication/
* [R8] Royal College of Physicians, NEWS2 (tabella dei punteggi e fasce di rischio), riassunto NHS:
  https://www.nwas.nhs.uk/publications/news2-national-early-warning-score
* [R9] NASA HRP / ExMC, progetto *Clinical Decision Support*: https://ntrs.nasa.gov/citations/20220014306
* [R10] FDIR ibrido regole + ML e spiegabilità nel ciclo decisionale: *On-board Telemetry Monitoring in Autonomous Satellites*,
  https://arxiv.org/abs/2604.08424
* [R11] NASA 2011, riorganizzazione della ISS Medical Checklist (per apparato, emergenza / non emergenza, CMO non medico):
  https://ntrs.nasa.gov/citations/20110003477
* [R12] NASA, *ISS Medical Kit Checklist* (contenuto dei pack del kit medico, 2015):
  https://www.nasa.gov/wp-content/uploads/2015/03/medical_kit_checklist_-_full_release.pdf
* [R13] British Thoracic Society 2017, *Guideline for oxygen use in adults in healthcare and emergency settings* (bersaglio SpO2
  94-98 %): https://pmc.ncbi.nlm.nih.gov/articles/PMC5531304
* [R14] Ossigeno al 100 % subito nel sospetto di intossicazione da CO; COHb con O2 al 100 % a pressione ambiente: emivita
  74 ± 25 min (93 pazienti): https://patient.info/doctor/emergency-medicine/carbon-monoxide-poisoning-pro ,
  https://data.zhenzhi.com/details/1/902099600
* [R15] Colpo di calore: raffreddare per primo, fermarsi intorno a 39 °C, nessun ruolo per gli antipiretici:
  https://emergencycarebc.ca/clinical_resource/exertional-heat-illness ,
  https://cgo.mod.uk/clinical-guidelines-for-operations/treatment-guidelines/environmental-injuries-exposure/heat-illness/
* [R16] NASA, *Atrial Arrhythmias in Astronauts - Summary of a NASA Summit* (NASA/TP-2010-216124):
  https://ntrs.nasa.gov/api/citations/20100021111/downloads/20100021111.pdf
* [R17] Prometazina IM per la chinetosi spaziale (sollievo quasi immediato nel 90 %, la più efficace nei debriefing):
  https://ntrs.nasa.gov/citations/19930046286 , https://ntrs.nasa.gov/citations/20110020471
* [R18] Falsi positivi del NEWS2 da wearable in continuo (COSMIC-19 e studi con wearable):
  https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11459982/ , https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9941897/
* [R19] Distribuzione elettrica ISS: DDCU da ~160 a ~120 V, RPCM come ultimo stadio verso le apparecchiature:
  https://spaceflight101.com/?p=4221 , https://ntrs.nasa.gov/citations/20050177179
* Interne: `notebooks/mario/ARES3_Guida_implementazione.pdf` (§6 catalogo guasti, netto/subdolo, §8 orbita come orologio per
  l'ML), `notebooks/mario/ARES3_Stazione_Sensori.xlsx` foglio `06_GUASTI` (firma, come distinguerlo, allarme atteso, etichetta
  ML), notebook ECG di Luca (autoencoder con soglia sull'errore di ricostruzione).
