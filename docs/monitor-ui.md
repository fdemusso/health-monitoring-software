# Monitor: contratto per la UI

La UI non ha logica di soglie: arriva tutto calcolato nel `SimulationTick` (`src/ares3/sdk/types.py` è la fonte di verità; lo
specchio a mano è `dashboard/src/telemetry/types.ts`).

## Stati del sistema (`tick.monitor_mode`)

| Valore | Quando | Banner suggerito |
|---|---|---|
| `passive` | nessuna emergenza aperta | verde, nessuna interruzione |
| `alert` | almeno un'emergenza `suspected`, oppure una `confirmed` di classe `caution`/`advisory` senza playbook | giallo |
| `reaction` | almeno un'emergenza `confirmed` di classe `emergency`/`warning`, o con un playbook in corso | rosso (emergency) o arancio (warning) |

Il modo è il massimo sulle emergenze aperte. Sale subito e scende solo dopo `classifier.mode_hold_s` (60 s) senza il livello
più alto, quindi non sfarfalla. Ogni cambio è un `MonitorEvent` con `kind: "mode_changed"` (`"monitoring: alert -> reaction"`).

## Classe di allerta (`Emergency.alert_class`)

`emergency` rosso, `warning` arancio, `caution` giallo, `advisory` blu. Viene da `classifier.classes` nel YAML del monitor
(chiavi `kind:severity:cause`, `kind:severity` o `kind`; senza voce: critical -> `emergency`, warning -> `warning`).
Livelli ISS: NASA, *CLD HSI Workshop - Alerts* (piano §11 [R1]).

## Spiegazione (`Emergency.evidence`, `tick.ml`)

`Emergency.evidence` è una lista di frasi per l'equipaggio: per le anomalie ML sono i 3 contributi più grandi alla decisione
("usl_ppCO2_a: slope over 6 h (+4.1 sigma)"), per gli altri rilevatori è vuota (c'è `detail`). Mostrarla nella scheda del problema,
sotto il titolo. `tick.ml` è il punteggio di ogni rilevatore ML sopra il suo limite (`ml_atmosphere_co2: 0.3`; >= 1 è un'anomalia):
utile per un indicatore per sottosistema, non serve per la logica di allerta.

## Tipi di emergenza nuovi

* `anomaly`: "qualcosa di anomalo nel sottosistema, senza causa nota" (stadio A, classe `caution`); `module_id` è il modulo del
  sensore che spiega di più, oppure `station` se è un canale di telemetria di un attuatore.
* `sensor_fault`: un sensore non va creduto. `subject` è l'id del SENSORE (o `a~b` se la coppia ridondante non dice quale dei due).

## Procedure (`tick.procedures`) e il comando `ack_step`

Una procedura è la checklist per le persone di un'emergenza confermata; parte da sola, il playbook resta la messa in sicurezza
della macchina. Ogni `ProcedureState` ha il titolo, lo stato (`running | done | escalated | closed`), il passo attivo (`current`) e
la lista dei passi con il loro stato (`pending | active | done | failed | skipped`, `by`, `answer`, `deadline_s`). Tipi di passo:

| `kind` | La UI mostra | Chi lo chiude |
|---|---|---|
| `instruction` | testo + pulsante "fatto" | comando `ack_step`, oppure un NPC del ruolo dopo qualche secondo |
| `question` | testo + sì / no | `ack_step` con `answer: "yes" \| "no"`, oppure un NPC (risposta di default) |
| `check` | "verifica in corso" con conto alla rovescia (`deadline_s`) | il sistema, sui valori misurati |
| `action` | come una `pending_action` (anche lì c'è il passo da approvare) | il sistema, quando l'azione è eseguita o scartata |
| `escalate` | avviso rosso: "chiama il chirurgo di volo / evacua" | la procedura finisce come `escalated` |

Comando WebSocket: `{"type": "command", "cmd": "ack_step", "args": {"procedure_id": "...", "step_id": "...", "by": "...", "answer": "yes"}}`
(`answer` solo per le domande). Chiunque può chiudere un passo: il monitor è aperto a tutti. Un'azione dell'equipaggio (`ack_step`)
su un passo non attivo risponde `ok: false`.

Eventi nuovi in `monitor_events`: `procedure_started`, `step_done`, `step_failed`, `procedure_done`, `procedure_escalated`.

## Procedure mediche e avviso

Contratto per la UI (solo documento: nessun campo nuovo in `sdk/types.py`, nessuna modifica a `dashboard/`). Il contenuto clinico è in
`docs/procedure-mediche.md`.

**Campi del tick che servono.** Dell'emergenza (`tick.emergencies`, `kind == "medical"`): `subject` (la persona), `module_id` (dove
si trova), `cause` (quale problema; sceglie la procedura), `evidence` (i valori che hanno fatto scattare l'allarme), `alert_class`
(il colore), `severity`. Della procedura (`tick.procedures`, si collega con `emergency_id`): `title`, `status`, `current`, `steps[]`
(`kind`, `text`, `status`, `by`, `answer`, `deadline_s`), `t_start_s`, `t_end_s`. Lo stesso `cause` può non avere una procedura
dedicata (allora c'è `med_generic`): la UI non deve presumere che il titolo dica la causa, lo dice `Emergency.cause`.

**Stati e transizioni dei passi.** `pending` -> `active` (uno solo alla volta, `current`) -> `done` | `failed`; i passi mai raggiunti
finiscono `skipped`. Un `check` che non passa entro `deadline_s` diventa `failed` e la procedura salta al ramo di fallimento
(quasi sempre un passo `escalate`). Un passo `escalate` è l'ultimo: diventa `done` e la procedura `escalated`. La procedura
`running` -> `done` (tutti i rami arrivati in fondo), `escalated` (arrivata a un passo `escalate`), `closed` (l'emergenza è finita
prima: i passi aperti diventano `skipped`). Resta nel tick 300 s dopo la fine, con l'esito.

**Avviso fisso, da mostrare in ogni procedura medica** (in alto, sempre visibile, non chiudibile):

> Simulation checklist, NOT medical advice. The steps are reconstructed from public sources and have not been reviewed by a flight
> surgeon. In a real emergency follow the ISS Medical Checklist and the instructions of the flight surgeon.

**Ordine di visualizzazione.** 1) avviso fisso; 2) titolo con la persona e il modulo, `alert_class` come colore, `evidence`
sotto (perché il monitor ha aperto l'allarme); 3) i passi nell'ordine della lista, quello `active` evidenziato con il suo pulsante
("fatto", sì / no) o il conto alla rovescia del `check`; i passi `skipped` attenuati; 4) se ci sono due procedure mediche aperte
(due persone), prima la più grave (`severity` poi `alert_class`) e l'altra in elenco.

**Quando una procedura va in `escalated`** l'equipaggio deve vedere, al posto della checklist, un riquadro rosso con il testo del
passo `escalate` (es. "chiama il chirurgo di volo"), l'elenco dei passi già fatti e quelli che non hanno funzionato (`failed`) per
riferirli a terra, e i valori attuali della persona. L'evacuazione o la chiamata a terra le decidono le persone: il sistema non le fa.
La procedura non si riapre da sola; se l'emergenza si riaccende, ne parte una nuova.

## Alimentazione e sensori sostitutivi

* `Action.kind = "power"` (`command: off | on`, `target` = modulo): togliere l'alimentazione a un modulo (risposta ISS al fumo). Quando è
  attiva, `tick.powered_off` elenca i moduli. Per i moduli vitali (USL, NOD3) è un passo `confirm` con il conto alla rovescia e
  `on_timeout: execute`; il ripristino viene solo PROPOSTO (`pending_actions`, `power on`) quando l'emergenza finisce: lo decide l'equipaggio.
  Il lifeboat e il volume EVA non si possono spegnere (l'azione è bloccata).
* `Action.kind = "sensor"` (`command: substitute`, `target` = sensore guasto, `value_id` = sostituto): da quel momento i controlli
  (CDRA, OGA...) leggono il sostituto. Passo `confirm` con `on_timeout: discard`; si annulla da solo a emergenza chiusa.

## Storia per i grafici (`history`) e avvio del backend

Subito dopo `hello` il backend manda UNA volta `{"type": "history", "samples": [{"t_sim_s", "npcs", "modules"}, ...]}`: le ultime 6 ore
simulate, un campione al minuto (stessi `npcs` e `modules` di un tick). La UI ci riempie i grafici subito invece di partire vuota (prima
li costruiva da sola, un punto al minuto SIMULATO dal momento della connessione: a 10x un punto ogni 6 s reali, a 1x uno ogni minuto).
Se la storia è vuota il messaggio non viene inviato. Un `reset` riparte da zero e svuota la storia.

`ares3 serve ... --warmup-h 4` fa avanzare la simulazione di 4 ore (circa un minuto reale) prima di andare in diretta: i rilevatori ML hanno
bisogno di 3 ore simulate di storia prima di giudicare, e la storia dei grafici parte già piena. La porta si apre SUBITO (dopo il
caricamento di scenario e modelli, qualche secondo): durante il warmup il server è nello stato `warming`.

- `hello` porta `"state": "warming" | "live"`.
- Mentre è `warming` arrivano circa 4 volte al secondo `{"type": "warming", "progress": 0..1, "sim_s", "total_s"}` (anche subito dopo
  `hello` per chi si connette a metà); NON arrivano `tick` né `history`, e ogni comando è rifiutato (`ok: false`, "warming up").
- A fine warmup: `history` a TUTTI i client, poi `{"type": "ready"}`, poi i tick. Un `hello` con `state: "live"` vale come `ready`.

La UI (`dashboard/src/app/WarmupScreen.tsx`, stato `warming` in `telemetry/store.ts`) mostra una schermata di caricamento con
percentuale e tempo stimato, e si dissolve su `ready`; l'app sotto è `inert` nel frattempo.

Un avviso "fuori range" della UI su un astronauta che lavora (es. 126 bpm a 7 MET) non viene dal backend: il monitor lo giudica con
l'`EarlyWarningScore`, che non valuta FC e frequenza respiratoria durante e 30 min dopo lo sforzo. Conviene che la UI usi
`tick.emergencies` / `tick.monitor_mode` per gli avvisi.

## Ancora da fare

La classificazione (stadio B) darà a `Emergency.cause` la diagnosi (quale guasto) con la sua probabilità; il tipo `crew` (ordini a un
NPC, es. spostare una persona) non esiste ancora: oggi lo spostamento è un passo `instruction`. Questa nota si aggiorna quando entrano.
