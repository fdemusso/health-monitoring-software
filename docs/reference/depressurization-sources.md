# Fonti della depressurizzazione (perdite d'aria, tempo di riserva, isolamento)

Tag usati nel codice (`plugins/monitor/detectors.py::PressureDrop`, `scenarios/monitor_placeholder.yaml`,
`schemas/monitor.py::CrewResponseConfig`). Tutto ciò che non ha un tag è `ESTIMATE`.
Aggiunto dal team software. Resta in termini ISS (mai Marte).

| Tag | Fonte | Cosa ne usiamo |
|---|---|---|
| `[ICES-2025-126]` | NASA, *ECLSS emergency operations* (ICES 2025, paper 126, Rev A), https://ntrs.nasa.gov/citations/20250003954 | tre livelli di perdita, formula del TRes, Pminimum, soglia dei 10 minuti, risposta del veicolo e dell'equipaggio |
| `[ISS-2020-PrK]` | cronaca della perdita nella camera intermedia del modulo Zvezda, ottobre 2020 (stampa: -52 mmHg in 11,5 h, poi 7-9 mmHg/h) | ordine di grandezza di una perdita lenta reale |

## Livelli di perdita (ISS)

Dal paper `[ICES-2025-126]`:

| Livello | Tasso | Nel codice |
|---|---|---|
| rapid depressurization | >= 0,87 mmHg/min | `leak_rapid` (critico) |
| fast leak | 0,4 - 0,87 mmHg/min | `leak_fast` (warning) |
| slow leak | < 0,4 mmHg/min (minimo rilevabile a bordo: 2 mmHg/giorno) | `leak_slow`, `leak_trend` (warning) |

`leak_breach` (>= 8 mmHg/min su 30 s) non è un livello ISS: serve a vedere subito le brecce grandi, perché una finestra
lunga sottostima il tasso di una perdita appena iniziata e quindi il TRes.

**Perché la finestra cambia con la soglia.** Il sensore di pressione ha 0,05 kPa di rumore (default portato dal simulatore
precedente, di Mario). Misurato su 24 h nominali della stazione, la pendenza su 60 s oscilla di +-1 mmHg/min, su 300 s di
+-0,26, su 30 min di +-0,11, su 1 h di +-0,06: la soglia ISS di 0,87 si può usare solo da 300 s in su. Le finestre scelte
(30 s, 300 s, 30 min, 2 h, 6 h) tengono almeno 3 volte di margine; 2 giorni simulati senza perdite non hanno acceso nessun
detector. Se Mario cambia il rumore del sensore le soglie vanno riverificate (`tests/test_depressurization.py`).

`leak_slow` (0,1 mmHg/min, ~6 mmHg/h) e `leak_trend` (0,03 mmHg/min, ~2 mmHg/h) sono `ESTIMATE`: il paper non dà una
soglia di allarme per le perdite lente (le vede il trend a terra); 6 mmHg/h è l'ordine di `[ISS-2020-PrK]`.

## Tempo di riserva (TRes)

`TRes = P * ln(490 mmHg / P) / (dP/dt)` (minuti, P in mmHg, dP/dt in mmHg/min, negativo) `[ICES-2025-126]`. È la soluzione
esatta per una perdita proporzionale alla pressione, cioè il flusso da orifizio che il motore modella
(`Engine`, fault `leak`: `rate_per_s * moli`). Prima il codice usava la formula lineare `(P - Pmin) / |dP/dt|`, che sottostima.

- Pminimum = 490 mmHg (9,5 psia = 65,3 kPa): sotto, le apparecchiature critiche smettono di funzionare e cresce il rischio
  di ipossia (`pressure_minimum`, critico).
- A TRes <= 10 minuti l'equipaggio smette di cercare la perdita e si ritira nel veicolo di rientro, chiudendo i portelli
  (`evacuate_tres_s: 600`; prima 120 s, che non era ISS).
- Un livello di pressione "bassa" (96,5 kPa, il limite inferiore della cabina ISS, 14,0 psia) è stato provato e tolto: con il
  make-up gas spento dal playbook non c'è modo di risalire e l'emergenza non si chiuderebbe più.

## Risposta

Veicolo `[ICES-2025-126]`: isola automaticamente i moduli, chiude le valvole verso l'esterno, **spegne i ventilatori**
(per sentire la perdita), **ferma le introduzioni di gas** (per misurare il tasso). È il playbook `critical`.
Per una perdita lenta (playbook `warning`) il make-up gas resta acceso e non scatta l'allarme di gruppo: l'equipaggio
fa un *leak check* chiudendo i portelli uno alla volta.

Equipaggio `[ICES-2025-126]`:
- nessun portello chiuso tra una persona e il suo veicolo di rientro (guardia `Engine._guard`);
- "retreat to a known safe location and close the appropriate hatch(es)": a equipaggio imbarcato il veicolo viene
  sigillato (`seal_vehicle`, evento `crew_sealed`), così tiene la sua aria mentre la stazione perde la propria;
- il portello del veicolo resta chiuso in operatività normale e si apre solo mentre qualcuno lo attraversa.

Non modellato: la maschera PBA (7 minuti di ossigeno), il fatto che un portello chiuso sotto grande differenza di pressione
si riapra con difficoltà, il ritrovamento della perdita con l'HDI (qui basta il leak check).

## ESTIMATE (da rivedere con Mario)

- `repair_leak_s: 1800` (tempo per trovare e tappare una perdita che non è ancora un'emergenza): le perdite reali di Zvezda
  hanno richiesto giorni e non tutte le riparazioni hanno tenuto. Un fault `leak` con `repairable: false` non si ripara.
- Le soglie `leak_slow` e `leak_trend` (sopra) e `leak_breach`.
- Una perdita in un modulo collegato da un portello aperto si propaga agli altri per diffusione: il motore lo fa già; il
  monitor può quindi aprire un'emergenza "eco" anche nei moduli vicini, finché il portello non viene chiuso.
