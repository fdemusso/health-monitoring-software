# Fase 2: stadio A dell'equipaggio e famiglia medica dello stadio B

Ramo `feat/crew-model` (da `feat/crew-dataset`). Dati: onde 1 e 2 (677 run) più 40 gemelli nominali senza jitter. Tutti i numeri sono
tempo simulato su dati sintetici, non prestazioni di volo. Le tarature (margini, soglie, scelta del modello) sono fatte solo sulla
validazione (seed 131-138); il test (141-160) è stato aperto **una volta**, il 15/11/2026 alle 18:38, con i modelli congelati nel
commit `6798982` (modelli e codice).

## 1. Cosa c'è

| File | Cosa |
|---|---|
| `src/ares3/plugins/monitor/ml/crew_baseline.py` | `CrewBaselineModel` + `CrewBaselineDetector` (modi `slow` e `fast`) |
| `tools/ml/train_crew.py`, `tools/ml/eval_crew.py` | addestramento e valutazione offline con lo stesso codice di punteggio del rilevatore |
| `tools/ml/medical.py`, `train_diagnoser.py --families medical`, `sweep_diagnoser.py --medical`, `eval_medical.py` | famiglia medica: gemelli, controllo di identità, soglie per classe, matrice di confusione, test A / B / A+B |
| `tools/ml/make_crew_test_monitor.py`, `check_crew_parity.py` | monitor di prova (`output/ml/monitor_crew_test.yaml`, fuori dai file generati) e parità online = offline |
| `models/station_v2/` | `crew_baseline.joblib`, `diagnoser.joblib` (famiglia medica nuova, le altre dal v1), schede, `eval_crew_{val,test}.json`, `eval_medical_test.json` |
| `tools/ml/classes.yaml` + `scenarios/station/monitor.yaml` (rigenerato) | 4 classi nuove: `svt_suspected`, `bradycardia`, `respiratory_infection`, `abnormal_exertion` |

Il monitor vivo resta su `station_v1` (fase 3).

## 2. Stadio A: baseline per persona dato il contesto

Per ogni (persona, grandezza) un regressore (`HistGradientBoostingRegressor`, errore assoluto, profondità 3, 200 iterazioni) prevede il valore
atteso dal solo contesto del programma (MET, attività, minuti dall'esercizio e dal sonno, orologio) più una **memoria del programma**
(medie esponenziali di `ctx|met10` con costanti di 30, 120 e 360 min, calcolate riga per riga: identiche online e offline). Le grandezze sono
le sei medie a 10 min più `hr|sd10`. La scala σ è per persona, grandezza e classe di attività (1,4826 × MAD dei residui di validazione) e
un secondo piccolo regressore la alza dove il contesto dice che il corpo è in transizione. Statistica lenta = media esponenziale (5 min) di
max(D²/L_D, z/L_z); statistica veloce = |z| della FC (o dell'irregolarità) sul limite × `fast_factor`, **senza** troncamento a ±10.

Perché la memoria e la scala dal contesto: con il solo contesto della fase 1 i falsi allarmi di validazione venivano da due cose: la FC
resta alta per ore dopo l'esercizio mentre `min_since_ex` si ferma a 2 h, e nei primi minuti di un cambio di attività il valore medio a 10 min
ritarda sul contesto e z satura a 10. I limiti sono quindi **margine × il livello più alto mantenuto per il tempo di conferma** (11 min per lo
stadio lento, 3 campioni per il veloce), non il massimo istantaneo, e un limite non può superare 0,95 × il troncamento (sarebbe irraggiungibile).

**Regressore contro tabella** (stessa interfaccia, tabella = mediana per classe di attività e fascia di MET di 1, stesso rilevatore), sulla validazione:

| | eventi M val rilevati | allarmi fuori dall'evento | controlli di falsi allarmi (N1 val + metà-metà + fuori) |
|---|---|---|---|
| regressore | **71/72** | 0 | 1 |
| tabella | 68/72 | 1 | 3 |

Si tiene il regressore (regola: meno falsi allarmi, poi richiamo; a parità la tabella). Margine scelto 2,0, `fast_factor` 1,5.

### Validazione (N1 val 12 giorni, M val 72 eventi)

0 falsi allarmi, 0 segnali durante l'esercizio, richiamo 71/72 (0,99; Wilson 0,93-1,00); per tipo 8/8 salvo bradicardia 7/8.

### Test (N2 30 d + N3 15 d = 45 giorni nominali, 72 eventi M 141-148)

| | risultato |
|---|---|
| richiamo a evento (stadio A) | **72/72** = 1,00 (Wilson 0,95-1,00); ogni tipo 8/8 [0,68-1,00] |
| ritardo mediano dal visibile (gemello), minuti | AF 4,0; SVT 3,0; bradicardia 12,5; febbre 17,5; infezione resp. 14,0; stress 20,5; sforzo anomalo 18,0; mal di spazio 16,5; disidratazione 68,5 |
| falsi allarmi | 6 in 45 d = 0,133/giorno (limite sup. 95 % 0,263) |
| segnali durante l'esercizio nominale | 3 |

I 6 falsi allarmi sono **due situazioni ripetute per tre giorni** (il jitter è fisso per run), non sei eventi indipendenti, e il limite di
Poisson assume eventi indipendenti: lo sottostima. (1) N2 seed 144, persona `med`: tre volte un blocco di lavoro a 7,5 MET (come un'attività
extraveicolare) con la frequenza respiratoria a 10σ; è anche l'unico caso dei 3 segnali "durante l'esercizio". (2) N2 seed 149, persona
`bot`: tre sonni di 6 h con FC a 50 bpm, 10σ sotto l'atteso. Causa probabile: il test contiene combinazioni di jitter (MET più alto di quello
visto in addestramento, sonno più profondo) fuori dall'intervallo di addestramento, e gli alberi non estrapolano. Non si è ritoccato nulla.

## 3. Stadio B: famiglia medica

Addestrata con 351 run (324 con guasto: M train e catalogo; 27 nominali: N1 train e catalogo; seed 1-3 e 101-124), 139.002 righe (95.164 nominali, stride 5 solo sui nominali), positivi per classe da 457
(SVT) a 13.644 (infezione resp.); tutte le 9 classi hanno ≥ 300 righe, quindi tutte `live`. Le altre famiglie sono copiate intatte dal v1
(stessa `mean`/`scale`, quindi stesse spiegazioni). Soglie per classe sulla validazione (≤ 0,05 falsi/giorno per classe su 50 giorni nominali di validazione):
0,30 per tutte tranne l'infezione respiratoria (0,50): è il fondo della griglia, cioè la validazione non chiedeva di più.

**Disidratazione:** contro il gemello non supera mai 3σ (picco 1,4-2,7σ sulla scala della stazione): la sua etichetta "effetto visibile" usa
la ripiego dichiarato (inizio + `ramp_s` + 1 h), come previsto dal piano. Le altre 8 classi usano il gemello (k = 3).

### Test: richiamo a evento e confusione

| evento | A | B etichetta + persona giuste | B persona giusta | A+B | etichette date da B |
|---|---|---|---|---|---|
| sforzo anomalo | 8/8 | 3/8 | 4/8 | 8/8 | sforzo 8, disidr. 7 |
| stress acuto | 8/8 | 3/8 | 3/8 | 8/8 | stress 3, febbre 5 |
| fibrillazione atriale | 8/8 | 6/8 | 6/8 | 8/8 | FA 7, inf. resp. 7 |
| bradicardia | 8/8 | 3/8 | 3/8 | 8/8 | bradicardia 4 |
| disidratazione | 8/8 | 2/8 | 2/8 | 8/8 | disidr. 8 (ritardo mediano 438 min) |
| febbre | 8/8 | 5/8 | 7/8 | 8/8 | febbre 8, disidr. 4 |
| infezione respiratoria | 8/8 | 6/8 | 6/8 | 8/8 | inf. resp. 8 |
| mal di spazio | 8/8 | 0/8 | 2/8 | 8/8 | mal di spazio 5 |
| SVT | 8/8 | 4/8 | 5/8 | 8/8 | SVT 5 |
| **totale** | **72/72** [0,95-1,00] | **32/72 = 0,44** [0,34-0,56] | 38/72 = 0,53 [0,41-0,64] | **72/72** | |

Lo stadio B da solo dà la classe giusta in 56 eventi su 72 (la colonna "etichette date"), ma il **soggetto** (la
persona a cui punta la spiegazione) è giusto solo nel 53 % dei casi: la firma della classe è la media di tutte le persone, e la caratteristica più
vicina alla firma non è sempre quella del paziente. Il rilevamento A+B è interamente dello stadio A.

Falsi allarmi dello stadio B sui 43,1 giorni nominali di test: 10 come aperti da `eval_medical`, di cui 8 senza persona (`dehydration`,
soggetto `None`, 7 nello stesso run N2 seed 148). Il rilevatore vivo scarta una diagnosi medica senza persona, quindi quelli non sarebbero
mai arrivati all'equipaggio; **lettura a posteriori** (dopo l'apertura del test, senza rilanciare nulla e senza tarare, annotata nel JSON):
2 allarmi = 0,046/giorno (limite sup. 0,146). Somma A + B ≤ 0,186/giorno (limite superiore dell'unione, senza sovrapposizione).
`eval_medical.py` è stato corretto per il futuro (scarta le diagnosi senza persona).

## 4. Criteri di accettazione del §7 (test, una volta)

| criterio | esito | misura |
|---|---|---|
| falsi allarmi ≤ 0,2/giorno monitor completo | **non verificabile qui** | A+B letto a posteriori ≤ 0,186; il monitor completo (con le regole) è fase 3 |
| falsi allarmi ≤ 0,1/giorno solo equipaggio (45 d) | **non superato** | A: 0,133/giorno (6 in 45 d; due situazioni ripetute) |
| nessuna segnalazione durante l'esercizio nominale | **non superato** | A: 3 (stesso caso, MET 7,5 oltre l'addestramento); B: 0 |
| richiamo a evento ≥ 0,8 complessivo | **superato** | A 72/72; A+B 72/72; B da solo 0,44 (etichetta+persona) |
| per tipo ≥ 6/8 su FA, SVT, bradicardia, febbre | **superato** (A e A+B), B da solo no (SVT 4/8, bradicardia 3/8) | |
| anticipo mediano sulle regole ≥ 5 min su CO e ipercapnia | **non valutabile** | `crew_env` non fatto (fase 3) |
| costo medio per tick ≤ 4,7 ms | **superato** | 4,26 → 4,32 ms/tick con i due rilevatori dell'equipaggio (+0,06) |
| 180 test vecchi + nuovi, `ruff` pulito | 209 passed, 3 skipped (190 + 19 nuovi); `ruff` pulito sui file aggiunti | |
| stesso hash di un run su due macchine | **parziale** | vedi §5 |

## 5. Gemelli e determinismo

I gemelli (gruppo `T`) non erano nel piano della fase 1 né erano stati generati: li ho generati con il generatore esistente (`make_dataset.py
--only nominal --days 1,5 --features`, seed 101-124, 131-138, 141-148) in `crew_T_pc` (11, sul PC: **errore mio**, ha bloccato per un po' il PC; il resto
è stato ridistribuito), `crew_T_m5pro` (15) e `crew_T_m5` (14). Il controllo di identità su tutte le 360 coppie M/gemello prima dell'inizio del guasto:
**243 coppie della stessa piattaforma (12 Windows-Windows, 231 Mac-Mac): differenza esattamente 0; 117 coppie fra Windows e macOS: 80 differiscono per
al massimo 1,04e-7 in relativo (un ulp float32) in 1-8 celle su 551.040** (varianze che si cancellano, pendenze). Su indicazione dell'utente il controllo è ora a
due regole (stessa piattaforma: 0; piattaforme diverse: ≤ 2 ulp relativi, 2,4e-7), registrate nella scheda del modello (`info.medical.twin_identity`: conta le coppie usate in addestramento e validazione, 324). Il
vecchio catalogo (`output/ml/feat`, generato con una versione precedente del codice) ha differenze di 3,7e-9 in `eva_P|sd10` anche sulla stessa piattaforma: tolleranza
assoluta 1e-6, solo per quelle coppie.

## 6. Verifica online (Parte C)

Monitor di prova `output/ml/monitor_crew_test.yaml` (generato da `tools/ml/make_crew_test_monitor.py`: il monitor della stazione più `ml_crew_slow` e
`ml_crew_fast` dopo le regole e il diagnosticatore su `station_v2`).

* **Parità** (`check_crew_parity.py`, seed 151 N3, 6 h): il punteggio che il rilevatore calcola online e quello che `eval_crew.py` calcola dalle righe di
  `crew.parquet` dello stesso run differiscono al massimo di 1,5e-13 (lento) e 1e-14 (veloce) su 330 confronti; nessuna emergenza aperta. Soglia 1e-6: **superato**.
  (Si legge il seed 151, un seed di test: ho visto solo il punteggio massimo dello stadio lento, 0,90, e non ho tarato nulla.)
* **Costo** (6000 tick, stessa sessione con e senza i due rilevatori dell'equipaggio, PC fermo): 4,26 → 4,32 ms/tick (+0,06). Prima delle ottimizzazioni
  era +2,6 ms (14 `predict` di scikit-learn per persona e per valutazione, doppi per i due modi). Nel giorno intero qui sotto il tick medio è 5,7 ms perché il
  PC faceva girare anche i test e la parità. **Soglia 4,7: superato** nella misura isolata.
* **`check_monitor.py` su seed 151, 1 giorno nominale** (test, una volta): 2 emergenze aperte, **nessuna dallo stadio A**:
  1. `medical:bot:1` a t = 42.220 s (11,7 h), regola esistente sulla temperatura interna 38,5 °C (il caso noto dell'esercizio, non nuovo);
  2. `medical:bot:2` a t = 83.520 s (23,2 h), diagnosi `respiratory_infection` (86 %) dello stadio B sulla persona `bot` mentre dorme.
  Il secondo è un falso allarme dello stadio B che i 43 giorni di `eval_medical` (2 allarmi con persona, 0,046/giorno) lasciavano prevedere come possibile: B va
  portato in fase 3 con la persona dallo stadio A e una soglia più alta per l'infezione respiratoria.

## 7. Scelte fatte senza indicazioni

* `CrewFeatureExtractor.register` (6 righe in `crew.py`): il rilevatore impara i sensori indossabili dalle osservazioni, non ha il layout.
* Memoria del programma e regressore di scala dal contesto, limiti sul livello mantenuto, tetto a 0,95 × troncamento, pavimenti dei limiti (z 3, D² 30, veloce 4: ESTIMATE),
  statistica veloce non troncata. Margine e `fast_factor` scelti con un controllo metà-metà sulla validazione oltre ai falsi allarmi su N1 val.
* L'evidenza è in italiano ("FC 105 bpm, attesi 68 a riposo (z 6,1)") e porta il segno di z.
* Il rilevatore arrotonda la riga a float32 prima di valutarla (la precisione del dataset): online = offline bit a bit.
* Costo: un solo modello condiviso fra `slow` e `fast`, z condiviso fra i due, e una valutazione numpy degli alberi (14 foreste per persona insieme, uguale a scikit-learn a 1e-12; ricade su `predict` per ciò che non riconosce); scikit-learn a 1 thread nel rilevatore.
* `DiagnoserModel` ha ora `live` e `min_proba` per classe (un modello v1 caricato ha tutte le classi vive e la soglia del rilevatore).
* La disidratazione si etichetta con il ripiego dichiarato, le altre classi con il gemello k = 3.

## 8. File che si sovrappongono al ramo della fase 1

`tools/ml/classes.yaml` (+4 classi), `scenarios/station/monitor.yaml` (rigenerato, +8 righe: classi di allerta e tabella `diagnosis`),
`src/ares3/plugins/monitor/ml/crew.py` (+6 righe, `register`). Nessun conflitto atteso se la fase 1 non li ha toccati dopo `68aa4fd`.

## 9. Cosa resta per la fase 3

1. `tools/build_station.py`: i rilevatori `ml_crew_slow` / `ml_crew_fast` dopo le regole, il diagnosticatore su `station_v2`, la procedura `crew_baseline` → `med_generic`; rigenerare e `--check`.
2. Confronto con le regole online (`check_monitor.py` R / R+A / R+A+B) su run di test, e i falsi allarmi del monitor completo.
3. Spiegazione dello stadio B: il soggetto è giusto nel 53 %; il minimo è prendere la persona dallo stadio A quando B e A sono d'accordo, o ri-addestrare B con le z dello stadio A.
4. Le classi congiunte `crew_env` (ipercapnia, ipossia, CO) sui dati dell'onda 2 (E, C, R1 già generati): non fatte.
5. Se l'utente vuole chiudere i due criteri non superati dello stadio A: ampliare il jitter di addestramento (MET fino a 8,5, sonno più profondo) e ri-addestrare; sul test si può solo rivalutare con modelli nuovi e un test nuovo.
