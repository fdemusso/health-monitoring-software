# Prompt: procedure mediche dell'equipaggio (ricerca + implementazione), poi l'avviso nella UI

Da dare a una sessione di Claude Code aperta in un **worktree nuovo** (per esempio `C:\Users\flavi\Desktop\hms-procedure`, ramo
`feat/crew-procedures` creato da `main`). Il merge in `main` lo fa l'utente. Commit senza righe di attribuzione.

## Contesto

ARES 3 monitora la salute di 4 astronauti su una stazione ISS-like. Quando il monitor apre un'emergenza `medical` (con `subject`, `cause`,
`evidence`), la **procedura** (`src/ares3/core/procedures.py::ProcedureRunner`, YAML `procedures:` di `scenarios/station/monitor.yaml`) è la
checklist per le persone: passi `instruction` / `action` / `check` (su valori SENSATI) / `question` / `escalate`, scelta per (emergenza, causa,
severità): vince quella che nomina la causa (`procedures.py` riga ~127, confronto esatto), altrimenti la generica.

Oggi ci sono 4 procedure mediche: `med_hypoxia` (cause `hypoxia`), `med_co` (`co_poisoning`), `med_heat` (`fever_or_heat`), `med_generic`.
Le classi che il modello (stadio B, famiglia medical) sa riconoscere sono di più: `fever`, `dehydration`, `atrial_fibrillation_suspected`,
`acute_stress`, `space_motion_sickness` (in `tools/ml/classes.yaml`) e, in arrivo dalla fase 2, `svt_suspected`, `bradycardia`,
`respiratory_infection`, `abnormal_exertion`; più le cause congiunte persona + ambiente: `crew_baseline` (stadio A equipaggio),
`hypoxia_crew`, `co_exposure_crew`, `hypercapnia_crew`. **Quasi tutte ricadono su `med_generic`**, perché i nomi di causa non coincidono.
Il lavoro: dare a ogni problema la procedura giusta, con contenuto fondato su fonti pubbliche.

Letture iniziali: `CLAUDE.md` (sezioni Monitoring system, Three states), `src/ares3/core/procedures.py`, `tests/test_procedures.py`,
il blocco `procedures:` di `scenarios/station/monitor.yaml` (e dove nasce in `tools/build_station.py`), `tools/ml/classes.yaml`,
`docs/monitor-ui.md`, `docs/reference/monitoring-ml-sources.md`, `docs/reference/toxicology-sources.md`, `docs/reference/physiology-sources.md`,
`docs/piano-ml-equipaggio.md` (§2.2 e "Procedura per il nuovo allarme").

## Regole (non negoziabili)

- **Contenuto clinico = ESTIMATE finché non lo rivede Luca (bioingegnere).** Non presentarlo come validato. Ogni passo porta un tag di fonte
  (`[R7]`, `[R12]`... come nel file delle fonti, o una nuova voce aggiunta lì con titolo, ente, anno e URL) oppure la parola ESTIMATE.
  **Non inventare citazioni**: se non trovi la fonte di un passo, scrivi ESTIMATE e mettilo nella lista delle domande per Luca.
- **Mai dosi.** Solo oggetti del kit medico ISS e frasi del tipo "come da flight surgeon / checklist medica". Nessuna diagnosi: i testi
  dicono "sospetto", "valuta", "riferisci".
- Ragiona e testa in termini ISS, mai Marte (memoria di progetto). La stazione ufficiale è `scenarios/station/` (Mario): non si modificano i file
  generati a mano; si cambia `tools/build_station.py` e si rigenera con `uv run --with openpyxl python tools/build_station.py`, poi `--check`.
- **Non toccare** `src/ares3/plugins/physiology/` (Luca), `src/ares3/core/` (salvo un bisogno dimostrato: in tal caso fermati e chiedi), `dashboard/`
  (è di un altro sviluppatore), `tools/ml/classes.yaml` e il codice dei modelli (li sta cambiando la fase 2 sul ramo `feat/crew-model`).
- Il trattamento **non cambia la fisiologia simulata**: i `check` devono essere scritti su ciò che il simulatore può produrre (aria pulita,
  sorgente rimossa, episodio che finisce). Un check che non può mai passare va a `escalate`, non resta appeso.
- I `check` leggono solo valori sensati. Gli `instruction` hanno un `role` (`medical`, `systems`, `incident_commander`, `sensing`) esistente
  in `crew_response.roles`.
- Layering e test: `tests/test_architecture.py` resta verde; i test esistenti restano verdi; `ruff` pulito su ciò che aggiungi.
- Lavora solo nel tuo worktree. Non toccare le macchine remote né la cartella principale (da lì girano generazione dati e altre sessioni).

## Passo 0: verifica prima di scrivere

1. Quale `cause` emettono davvero le emergenze mediche? Leggi `plugins/monitor/ml/diagnoser.py` e i detector (`NpcThreshold`,
   `EarlyWarningScore`, `CrewBaselineDetector` se già presente su `feat/crew-model`) e scrivi una **tabella problema → emergenza → cause emessa →
   procedura scelta oggi**. Conferma o smentisci l'ipotesi "ricade su `med_generic`" con un test che apre l'emergenza e legge `tick.procedures`.
2. Come la UI legge una procedura: `SimulationTick.procedures` e `docs/monitor-ui.md` (campi, stati `escalated`/`done`).

## A. Ricerca (documento, prima del codice)

Crea `docs/procedure-mediche.md`, in inglese come gli altri documenti di fonti (i testi dei passi sono in inglese, come quelli esistenti), con
una sezione per problema: **fibrillazione atriale sospetta, tachicardia sopraventricolare, bradicardia, febbre / calore, disidratazione,
stress acuto, mal di spazio, infezione respiratoria, sforzo anomalo, ipossia, monossido di carbonio, ipercapnia** (e il malore generico).
Per ognuna: cosa fa l'equipaggio sulla ISS secondo fonti pubbliche (NASA Human Research Program, manuali e checklist mediche ISS pubblici,
articoli peer-reviewed di medicina spaziale, linee guida di medicina terrestre solo come appoggio, dichiarandolo), i passi proposti, quali
valori sensati si possono controllare (`hr`, `resp_rate`, `spo2`, `core_temp_c`, `skin_temp_c`, `hrv_rmssd`, `cohb_pct`, ppCO2 del modulo) e
con che soglia, **quando si escala** al flight surgeon, e le **domande aperte per Luca**. Una tabella finale: fonte, ente, anno, URL.

## B. Implementazione

1. In `tools/build_station.py` una procedura per problema (o una per famiglia dove i passi sono davvero gli stessi), con il `cause` esatto che
   emette il rilevatore. Per le cause congiunte: `hypoxia_crew` → `med_hypoxia`, `co_exposure_crew` → `med_co`, `crew_baseline` → `med_generic`,
   `hypercapnia_crew` → una procedura nuova (spostare la persona in un modulo con aria normale, ventilazione, controllo della CO2 del modulo,
   `escalate` se non scende). Titoli e testi con `{subject}` e `{module}` come quelli esistenti.
2. Passi `question` con `auto_answer` quando l'equipaggio simulato non può rispondere; `check` con `within_s` ragionevoli; ogni ramo termina in
   `done` o `escalate`.
3. Rigenera i YAML, `--check` pulito. **Coordinamento con la fase 2**: lei modifica `tools/ml/classes.yaml` e rigenera `monitor.yaml`.
   Tu tocchi solo il blocco delle procedure di `build_station.py`; rigenera `monitor.yaml` per ultimo e, se `main` o `feat/crew-model` sono
   avanzati, fai `git rebase` (o chiedi all'utente quale ramo ha la precedenza) prima di consegnare. Elenca i file che si sovrappongono.
4. Test in `tests/test_procedures.py` o in un file nuovo: per ogni procedura, (a) viene scelta con la causa giusta, (b) il percorso felice
   arriva a `done`, (c) il ramo di escalation arriva a `escalated`, (d) deterministico a parità di seed. Usa il fixture `station` (habitat
   piccolo) dove basta e `scenarios/events/debug_station.yaml`.
5. `uv run pytest -q -n auto` verde (circa 90 s su 16 core), `uv run ruff check src tests tools/ml`.

## C. Contratto per l'avviso nella UI (solo documento: la UI NON si tocca ora)

L'avviso nella dashboard lo facciamo più avanti, quando arriva l'ultima versione dalla persona che la sviluppa. Ora prepara in `docs/monitor-ui.md`
una sezione "Procedure mediche e avviso" con: quali campi del tick servono (`Emergency.subject/cause/evidence/alert_class`, `tick.procedures`),
gli stati e le transizioni dei passi, il testo di **avviso fisso** da mostrare (la procedura è una checklist di simulazione, non un consiglio
medico, e va rivista dal flight surgeon), l'ordine di visualizzazione e che cosa deve vedere l'equipaggio quando una procedura va in `escalated`.
Nessun campo nuovo in `sdk/types.py` se non strettamente necessario (se serve, prima lì, poi a mano in `dashboard/src/telemetry/types.ts`,
ma **solo dopo l'ok dell'utente**).

## Consegna (riporta l'output)

1. La tabella problema → causa emessa → procedura (prima e dopo).
2. `docs/procedure-mediche.md` con le fonti e le domande per Luca; l'elenco dei passi senza fonte (ESTIMATE).
3. `pytest -n auto` e `ruff` (output), `build_station.py --check` pulito.
4. Lo stato del ramo: commit, file toccati, sovrapposizioni con `feat/crew-model` / `main`, così il merge lo fa l'utente senza sorprese.
5. Ogni scelta fatta senza indicazioni, e cosa resta per l'avviso nella UI.
