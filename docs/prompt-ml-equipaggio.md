# Prompt per un modello grande: pianificare l'ML sull'equipaggio e gli scenari, con 4 macchine, entro le 22-23 di stasera

Incolla tutto quello che segue (da "RUOLO" in giù) a un modello grande. Il documento è pensato per essere autosufficiente.

---

## RUOLO

Sei un ingegnere ML/simulazione senior. Devi **pianificare** (non scrivere ancora il codice) il lavoro che ci resta per un progetto
hackathon (NASA Space Apps 2026) con **consegna oggi alle 22:00-23:00**. Sono circa le 14:30: abbiamo circa 7-8 ore. Il piano deve essere
eseguibile da 2 ingegneri software più un assistente di codice (Claude Code) che lavora direttamente nel repository, con 4 computer a
disposizione per i calcoli. Voglio un piano **preciso, a fasi con orari, con criteri di accettazione misurabili e un piano B**.

## IL PROGETTO IN BREVE

ARES 3 è un simulatore deterministico, a passi di tempo (1 s), di una **stazione spaziale in stile ISS** con 4 astronauti. Esporta serie
temporali etichettate (ambiente + parametri vitali, con la verità sui guasti) per un modello di allerta ML. Tutto è in termini ISS, mai Marte.
L'obiettivo NON è un dottore onnisciente: è un **primo soccorritore** che agisce nella finestra tra l'inizio di un'emergenza e il momento in
cui uno staff medico può intervenire.

Le tre parti (visione originale):
1. **Persone**: 4 NPC con routine giornaliera, fisiologia (modello di Luca, bioingegnere), problemi interni (malori) ed esterni.
2. **Ambiente**: stazione ISS (16 volumi, 186 sensori, attuatori ECLSS, 26 tipi di guasto da un foglio di calcolo di Mario, fisico).
3. **Sistema di monitoraggio**, con 3 stati: **passivo** (dashboard e suggerimenti di salute), **allerta** (ML che combina sensori e dati delle
   persone), **reazione** (azioni per proteggere la vita: isolamento, spegnimento, estintore, evacuazione, procedure a passi per l'equipaggio).

Repository: `github.com/fdemusso/health-monitoring-software`, branch `main`. Backend Python (`uv`, pydantic, numpy, scikit-learn), dashboard React.
Online: dashboard `https://ares.daado.dev`, backend `wss://ares-api.daado.dev` (su un mini server Proxmox, Docker + tunnel Cloudflare).

## COSA È GIÀ FATTO (verificato)

- Stati `passive / alert / reaction` (`SimulationTick.monitor_mode`), classi di allerta ISS (emergency / warning / caution / advisory).
- Rilevatori a regole: perdita di pressione per scale temporali, fumo/incendio, CO, soglie sugli astronauti (`NpcThreshold`), `Variance`
  (sensore bloccato o rumoroso), `RedundancyResidual` (due sensori ridondanti che non concordano), `EarlyWarningScore` (tipo NEWS2 sulla media a 5 min,
  battito e respiro non valutati durante e 30 min dopo lo sforzo).
- **ML stadio A** (non supervisionato): una PCA per sottosistema (pressione, CO2, O2, termico/umidità, ventilazione; `tools/ml/groups.yaml`), addestrata
  solo su giorni nominali, punteggi T² e SPE sopra un limite. 0 falsi allarmi su 10 giorni nominali di test. **Non copre l'equipaggio.**
- **ML stadio B** (supervisionato): un `HistGradientBoostingClassifier` per famiglia (fisica / attuatori / sensori / medica), con classe `nominal`; dà
  l'etichetta del guasto, la spiegazione e la localizzazione. Tabella `diagnosis` (`tools/ml/classes.yaml`) = etichetta → tipo di emergenza.
  Addestrato su 140 run (guasti con parametri casuali dai range del foglio di Mario, combinazioni di due guasti, 5 eventi medici sull'equipaggio).
  Con soglia 0,90 e conferma doppia: 1 falso allarme su 10 giorni nominali, 26 guasti su 34 con l'etichetta giusta (un solo seed di test), ritardo mediano
  30 min dalla comparsa dell'effetto. Nel monitor vivo restano attive solo le famiglie fisica / attuatori / medica (le classi di sensore aprivano falsi
  `sensor_fault`, le coprono le regole).
- **Estrattore di caratteristiche unico** (`src/ares3/plugins/monitor/ml/features.py`), usato online e offline: bin da 10 s, finestre 10 min / 1 h / 6 h,
  per sensore `d10, d1h, sd10, n10, sl1h, sl6h` più orologio (seno/coseno del giorno e dell'orbita). **I livelli non sono caratteristiche**
  (ogni unità ha un errore fisso diverso per seed). I 186 sensori includono i dati vitali degli astronauti: `bot_/cmd_/eng_/med_` + `hr, spo2,
  resp_rate, core_temp_c, skin_temp_c, hrv_rmssd, rr_interval_ms, cohb_pct, health_state`.
- Etichetta "effetto visibile": corsa gemella (stesso seed senza guasto, identica fino all'azione del guasto), poi `visible_since_s` dove la differenza
  supera k sigma. Metriche a evento (stile ESA-ADB): allarmi veri/falsi, richiamo di evento, F0.5, ritardo (`tools/ml/metrics.py`).
- Eventi medici sulla stazione (`scenarios/events/*_faults.yaml`): `fever`, `dehydration`, `fibrillation`, `motion_sickness`, `stress`; esiste anche il CO
  (`co_source`) e la decompressione EVA. L'ipossia viene dall'ambiente (O2 basso). Il medico NPC va dal membro in difficoltà (`crew_response`).
- Reazione: playbook (`auto` o `confirm` con timeout), azioni `power` (taglio alimentazione) e `sensor substitute`, 7 procedure a passi
  (`med_hypoxia`, `med_co`, `med_heat`, `med_generic`, `sensor_check`, `anomaly_check`, `toxic_response`), comando UI `ack_step`.
- Server WebSocket con ruoli (token operatore, visitatori), storia di 6 h per i grafici, `--warmup-h`, `--pause-when-idle`. Test: 180 passati.

Costo: **4,4 ms per tick** con tutto attivo (circa 230x il tempo reale su un Ryzen 7 5800X3D). Un run di 2 giorni simulati ≈ 12 min di CPU a macchina libera.

## IL PROBLEMA DA RISOLVERE: "ML SULL'EQUIPAGGIO"

Oggi la parte persone è giudicata con **soglie fisse** e un punteggio tipo NEWS2: non impara niente. Esempio reale: la UI ha segnalato "fuori range"
un astronauta con 126 bpm mentre lavorava a 7 MET, che è normale. Voglio pianificare tre pezzi:

1. **Baseline per persona**: un modello per astronauta, addestrato su giorni sani, che conosce i valori normali di quella persona in funzione di cosa
   sta facendo (riposo, lavoro, esercizio, sonno; l'attività/MET è nota agli NPC) e segnala lo scostamento dal *proprio* normale (es. 105 bpm a riposo
   per un'ora). Stessa idea dello stadio A (PCA/robust z-score su caratteristiche) ma per persona, condizionata all'attività. Serve gestire sesso, età,
   massa diversi (sono nel file dell'equipaggio) e il fatto che 4 persone con la stessa routine hanno baseline diverse.
2. **Persona + ambiente insieme**: riconoscere quadri combinati (ppCO2 che sale piano e respiro/battito che salgono; O2 basso e SpO2 che scende; CO con
   COHb che sale senza che la SpO2 del pulsossimetro lo mostri) prima che scattino le soglie. Oggi le classi `hypoxia` e `co_poisoning` non sono
   nello stadio B (restano alle regole SpO2/SpCO) e il quadro congiunto non è un'etichetta.
3. **Più dati medici**: ora 5 eventi con pochissime righe positive (9 di fibrillazione, 32 di mal di spazio, 200 di febbre, 64 di stress) e la
   disidratazione quasi assente: i classificatori medici sono deboli. Servono molti più run per evento (intensità e istante d'inizio diversi,
   ampiezza ±30%) e idealmente altri malori.

## VINCOLI (da rispettare nel piano)

- **Non si modifica** `src/ares3/plugins/physiology/` (è di Luca). I file generati `scenarios/station/*` **non si editano a mano**: si cambia
  `tools/build_station.py` e si rigenera (`uv run --with openpyxl python tools/build_station.py`).
- La fisiologia è **sintetica**, in gran parte con numeri ESTIMATE; Luca deve ancora validare i dati generati sugli NPC. Ogni numero ML è tempo
  simulato su dati sintetici, mai prestazioni di volo.
- Niente GPU (HistGradientBoosting e PCA su CPU); inferenza online < 1 ms per tick. Modelli joblib: si caricano solo i nostri.
- Il layering dei pacchetti è imposto da `tests/test_architecture.py`; `ruff` pulito su ciò che si aggiunge (restano 2 avvisi vecchi).
- Un solo seed di test finora: serve una divisione train/validazione/test **per seed** con più seed, e il test non va mai usato per tarare.
- Trappole già incontrate: (a) un solo guasto sbagliato in un job fa cadere l'intero processo del generatore (un evento puntava a un modulo che
  non esiste: provare sempre la lista dei job con `--ticks 400`); (b) le calibrazioni periodiche dei sensori (dente di sega, -24 %/anno, azzeramento
  ogni 30 giorni) producono gradini sani che sembrano guasti; (c) un portello mosso dalla risposta stessa faceva scattare lo stadio A (ora escluso
  e i punteggi sono limitati a ±10 sigma); (d) le classi con pochi esempi danno diagnosi inaffidabili.

## RISORSE DI CALCOLO: LE 4 MACCHINE

Il generatore (`tools/ml/make_dataset.py`) lancia un processo per run ed è parallelo e deterministico per seed. Ogni run è indipendente, quindi si può
**dividere fra più computer**: l'opzione `--shard K1,K2/N` prende i job la cui posizione modulo N è in {K1,K2}; ogni macchina costruisce la stessa lista e
prende la sua parte; `--resume` salta i run già scritti. I risultati sono cartelle (`features.parquet` + `meta.json`) con nomi unici: si uniscono copiandole.

| Macchina | Core | Rendimento misurato | Come si raggiunge |
|---|---|---|---|
| PC principale, Ryzen 7 5800X3D (Windows) | 8 core / 16 thread | circa 1 run/min | locale |
| MacBook M5 | 10 | circa 1,2-1,3 run/min | SSH (Tailscale), `uv` già presente |
| MacBook M5 Pro (di un amico: chiedere sempre il permesso) | 18 | circa 2,6 run/min | SSH in LAN |
| Mini server Proxmox, i5-9500, container Docker | 6 | circa 0,2-0,4 run/min, a priorità bassa perché ospita servizi di casa | SSH al Proxmox e `pct exec` |

Procedura già collaudata: archivio del repository senza `output/` → copia → `uv sync --frozen --extra dev` (Python 3.12 gestito da `uv`) → prova breve
con `--ticks 400` → lancio con `nohup`/`caffeinate -i`/`nice` → recupero dei risultati via `tar` su SSH → pulizia. 140 run da 2 giorni sono stati fatti in circa 1 ora
con 4 macchine. Con questi rendimenti, l'insieme delle 4 macchine fa circa 5-6 run/min, cioè **300-350 run da 2 giorni all'ora**. Il collo di bottiglia
è il tempo di CPU, non la rete. Le versioni di numpy differiscono fra macchine (2,4 e 2,5) senza effetti sull'addestramento.
Il PC principale è anche quello che addestra, e il Proxmox ospita il sito pubblico: vanno protetti.

## COSA TI CHIEDO

Produci un **piano di lavoro** con questi capitoli, in italiano, senza codice (al più nomi di file e comandi):

1. **Matrice degli scenari** (molti, ma motivati): per ciascuno dì obiettivo, parametri variati (intensità, istante d'inizio, persona colpita, attività in
   corso, modulo), durata, seed, numero di ripetizioni e a cosa serve (addestramento, validazione, test, falsi allarmi). Copri: baseline sani per ognuno
   dei 4 astronauti in tutte le attività; i 5 eventi medici e nuovi malori; ipossia e CO con cause ambientali diverse; CO2 che sale piano; sforzo normale
   contro sforzo anomalo; combinazioni persona+ambiente; eventi con la risposta del sistema già attiva; giorni lunghi per i falsi allarmi.
2. **Progetto del modello per persona** (stadio A equipaggio) e delle classi congiunte persona+ambiente (stadio B): caratteristiche, condizionamento
   sull'attività, normalizzazione per persona, soglie e limiti (con il margine sul massimo di validazione), come evitare di imparare l'unità del sensore.
3. **Protocollo di valutazione**: divisione per seed, metriche a evento, falsi allarmi per giorno (obiettivo ≤ 0,2/giorno), richiamo per tipo di evento,
   ritardo dal momento visibile, intervalli di confidenza con campioni piccoli; come confrontare con le regole attuali (`EarlyWarningScore`, `NpcThreshold`).
4. **Piano di calcolo sulle 4 macchine** con orari: quanti run per macchina (usa i rendimenti di sopra), quali shard a chi, in che ordine, come non
   fermare il sito pubblico né il PC che addestra, checkpoint e recupero dei risultati, cosa fare se una macchina cade.
5. **Cronologia fino alle 22:00** (ora per ora): preparazione, generazione, addestramento, integrazione nel monitor (YAML generato da
   `tools/build_station.py`), controllo end to end con `tools/ml/check_monitor.py`, test, pubblicazione (backend su Docker, dashboard su Cloudflare
   Workers con `wrangler`), prova generale della demo. Indica cosa si può fare in parallelo.
6. **Piano B / versione minima** da avere pronta alle 19:00 se qualcosa slitta, e cosa tagliare per primo.
7. **Rischi** con probabilità e come ridurli, e **criteri di accettazione** misurabili per dire "il modello è sufficiente" (ad esempio falsi allarmi,
   richiamo, tempo di inferenza, nessuna regressione sui 180 test).
8. **Domande da chiarire** a Luca (bioingegnere) e Mario (fisico) prima di fidarsi dei numeri, ordinate per impatto.

Sii concreto: numeri, orari, nomi di file. Se un'ipotesi manca, scegli un default sensato, dichiaralo e dì come cambiarlo. Non proporre di cambiare il
modello fisiologico di Luca, di rimuovere la parte a regole (resta la rete di sicurezza) o di usare la GPU.
