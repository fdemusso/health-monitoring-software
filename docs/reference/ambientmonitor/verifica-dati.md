# Verifica dei dati della simulazione su fonti NASA

Data: 15 ottobre 2026. Oggetto: costanti e soglie in `scenes/habitat.json`, `engine/simulation.js`, `engine/environment.js` e i valori proposti nel piano iniziale (`docs/plan.md`, eliminato dopo l'implementazione; vedi `git log -- docs/plan.md`).

Metodo: documenti primari NASA (NTRS, NSSDC, NASA-STD-3001, GISS) letti nel testo integrale quando disponibile. Dove esiste solo una fonte secondaria lo dico. Dove ho fatto un calcolo mio lo dico e mostro il conto.

Legenda: ✅ confermato · ⚠️ da correggere o da rendere configurabile · ❌ errato · ❓ nessuna fonte NASA trovata (resta una stima).

Fonti citate come [S1]…[S19], elenco in fondo.

---

## 1. Le quattro criticità segnalate

### 1.1 Valori stimati in `habitat.json`

| Parametro | Valore attuale | Verdetto | Valore verificato / proposta | Fonte |
|---|---|---|---|---|
| `gravity` | 3,71 m/s² | ✅ | 3,71 equatoriale; 3,73 media | [S1] |
| `atmosphere.P`, `O2` | 101,3 kPa, 20,9% | ⚠️ | Valido per veicoli di trasferimento. Per un habitat di superficie la NASA prevede **70,3 kPa / 26,5% O₂** (EVA di contingenza) oppure **56,5 kPa / 34% O₂** (EVA frequenti), e il veicolo deve poter lavorare a tutti e tre i setpoint. Lo studio NASA 2026 sugli scrubber usa 10,2 psia (70,3 kPa) per l'habitat di superficie su Marte | [S2] §4.1.1, [S11] |
| `atmosphere.CO2` | 600 ppm | ✅ | Valore iniziale ragionevole | — |
| `atmosphere.RH` | 40% | ✅ | Nominale BVAD 40% (limiti 25–75%) | [S2] Tab. 4-1 |
| `atmosphere.T` | 21 °C | ✅ | BVAD nominale 296 K (291–300 K) | [S2] Tab. 4-1 |
| `envelope.uWall` | 0,05 W/m²K | ⚠️ | Plausibile ma ottimistico. Con aerogel misurato in CO₂ a 10 torr (0,0126 W/mK a −27 °C, 0,0089 a −80 °C) servono ~25 cm. Su Marte l'MLI è "quasi inutile" perché il gas conduce. Rendere il parametro un intervallo di sensibilità 0,05–0,2 | [S14], ricerca NASA tute citata in §3 |
| `envelope.uGlass` | 0,6 W/m²K | ❓ | Nessun dato NASA trovato per finestre di habitat marziano | — |
| `envelope.hIn` | 3,0 W/m²K | ⚠️ | Il valore è un coefficiente convettivo terrestre. Con g = 3,71 e pressione ridotta la convezione naturale scende (stima mia: ×0,7 per la gravità, ×0,8 a 70 kPa). Manca lo scambio radiativo interno (~5 W/m²K tra superfici a 295 K) | calcolo mio |
| `envelope.structCap` | 2,0e6 J/K | ❓ | Stima. Equivale a ~2 t di alluminio | — |
| `envelope.shgc` | 0,4 | ❓ | Stima | — |
| `exterior.meanK/ampK` | 213 / 35 K → −95 / −25 °C | ⚠️ | Vedi §1.4 | [S1], [S16], [S17] |
| `exterior.sunrise/sunset` | 6 / 18 fissi | ❌ | Dipendono da latitudine e stagione: `cos ω_s = −tan φ · tan δ` | [S3] |
| `exterior.directWm2` | 350 su finestra verticale | ❌ | Forma `sqrt(sin)` arbitraria. Il fascio diretto dipende da `τ` e dalla massa d'aria: 590·e^(−τ/cos z) | [S3] |
| `exterior.diffuseWm2` | 40 | ❌ | Su Marte il diffuso è grande: a τ = 0,5, z = 20° il diffuso orizzontale vale ~170 W/m² (globale 495, diretto 325). Con τ alto il diffuso domina | [S3], calcolo da tabella f(z,τ) |
| `leakPerDay` | 0 | ⚠️ | BVAD: **0,02 kg/giorno per modulo** nominale (0,01 realistico, 0,09 massimo). Per 66 m³ a 101 kPa (~79 kg d'aria) vale ~2,5e-4 al giorno | [S2] §4.1.1, Tab. 4-1 |
| `scrubber.onPpm/offPpm` | 1500 / 1000 ppm | ⚠️ | I limiti NASA sono su **pressione parziale**: ppCO₂ ≤ **3 mmHg** (0,4 kPa) come media su 1 h [V2 6004]; media su 7 giorni < 2,5 mmHg per tenere il rischio di cefalea < 1%. 1500 ppm a 101 kPa = 1,14 mmHg, a 70 kPa = 0,79 mmHg: troppo prudente e cambia con la pressione. Controllare in mmHg | [S6] |
| `dehum.onRH/offRH` | 58 / 48% (prima 55 / 45%) | ✅ | Comfort NASA 30–60%, salute 25–75% | [S6] [V2 6012/6013] |
| `hvac.setC` | 22 °C | ✅ | Comfort 20–25 °C, salute 18–27 °C | [S6] |
| `o2gen` setpoint | pO₂ iniziale | ✅ | ppO₂ nominale 20,7–50,6 kPa. A 70,3/26,5% si ottiene 18,6 kPa, nella fascia "impedimento misurabile fino all'acclimatazione" (17,2–18,6) | [S2] Tab. 4-1 |

### 1.2 Flusso e convezione orizzontale

Verdetto: ⚠️ **limite reale, da modellare**.

- NASA-STD-3001 [V2 6107] richiede una ventilazione "sufficiente a impedire la formazione di sacche di CO₂ e di sacche termiche" [S6]. Il modello oggi non le può valutare bene perché manca il moto convettivo laterale.
- Ordine di grandezza (calcolo mio): con g = 3,71 m/s², ΔT = 1 K e altezza 2,5 m, la scala di velocità di galleggiamento √(g·β·ΔT·H) vale ~0,18 m/s. Con un fattore di efficienza 0,2–0,5 si ottengono 0,04–0,09 m/s, lo stesso ordine delle velocità indotte da F1/F2 (0,08 m³/s su una sezione di ~10 m² ≈ 0,01 m/s medi). Quindi la convezione laterale **non è trascurabile**, soprattutto vicino alle finestre fredde (discesa d'aria fredda) e ai riscaldatori.
- Soluzione adottata (Fase 0.6 del piano iniziale): flusso di galleggiamento calcolato dalla pressione idrostatica di ogni colonna e proiettato a divergenza nulla con `solveFlow` già esistente.

### 1.3 Durata del giorno

Verdetto: ❌ **va corretto**. Il sol solare medio dura **88 775,244 s = 24 h 39 min 35,244 s** (1,027491251 giorni terrestri) [S5], 24,6597 h secondo NSSDC [S1]. Con 24 h esatte la simulazione accumula 39,6 minuti di sfasamento al giorno tra Sole ed equipaggio.

Formule NASA GISS Mars24 [S5] utili per l'implementazione:

- Anomalia media: `M = 19,3870° + 0,52402075° · Δt_J2000`
- Angolo del Sole medio fittizio: `α_FMS = 270,3863° + 0,52403840° · Δt_J2000`
- Longitudine solare: `Ls = α_FMS + (10,691° + 3e-7°·Δt)·sin M + 0,623°·sin 2M + 0,050°·sin 3M + 0,005°·sin 4M + 0,0005°·sin 5M`
- Declinazione solare: `δ = asin(0,42565 · sin Ls) + 0,25° · sin Ls`
- Distanza Sole–Marte (UA): `r = 1,52367934 · (1,00436 − 0,09309·cos M − 0,004336·cos 2M − 0,00031·cos 3M − 0,00003·cos 4M)`
- Equazione del tempo: `EOT = 2,861°·sin 2Ls − 0,071°·sin 4Ls + 0,002°·sin 6Ls − (ν − M)`

Per una simulazione di pochi sol basta fissare `Ls` all'inizio (varia di ~0,5° per sol) e calcolare l'ora solare locale come frazione di sol.

### 1.4 Temperatura esterna

Verdetto: ⚠️ **il minimo non è sbagliato, è il sito che non è definito**.

| Sito | Minimo | Massimo | Fonte |
|---|---|---|---|
| Viking 1 (22° N) | 184 K (−89 °C) | 242 K (−31 °C) | [S1] primaria |
| Mars Pathfinder | 10–12 K più caldo di VL1 vicino al suolo | | Schofield et al. 1997, Science 278 |
| InSight (Elysium, 2019) | −95 °C tipico | −17 °C tipico | [S17] secondaria |
| Curiosity (Gale) | escursione notte/giorno > 55 °C; estremi −100 °C (inverno) / +15,9 °C (estate) | | [S16] escursione da NASA, estremi da fonte secondaria |
| Media globale | 214 K (−59 °C) | | [S1] |

- Il modello attuale (213 ± 35 K → −95 / −25 °C) è vicino a InSight e all'inverno di Gale, 6 K più freddo di Viking 1. Il problema vero è che media, ampiezza, alba e tramonto non sono legati a un sito e a una stagione.
- La forma a coseno simmetrico non è realistica: su Marte la temperatura sale rapidamente al mattino e scende lentamente di notte. MEDA (Perseverance) descrive il ciclo con serie di Fourier e maree termiche [S19]. Proposta: preset per sito e un profilo tabellare caricabile da dati PDS (REMS/MEDA).
- **Mancano due temperature al contorno**:
  - **Cielo**: non esiste una misura diretta. NASA ha provato i radiatori con cieli simulati da 185 a 248 K [S7] e ha usato un pozzo a 210 K nei dimensionamenti [S8]. Va tenuto come parametro incerto con un test di sensibilità.
  - **Suolo**: inerzia termica misurata a Gale 265–375 J m⁻² K⁻¹ s⁻½ (REMS) [S15]. Conta per il pavimento se l'habitat poggia sulla regolite.
- **Convezione esterna**: con CO₂ a 600 Pa e 220 K, una lastra di 1 m con vento da 2 a 10 m/s dà h ≈ 0,3–0,7 W/m²K (calcolo mio, Re 2 600–13 000, regime laminare). Lo scambio radiativo esterno vale ~2 W/m²K e domina. Serve una "temperatura sole-aria" per pareti e finestre.

---

## 2. Verifica dei valori del piano iniziale

### 2.1 Equipaggio (codice attuale in `simulation.js`)

Riferimento: BVAD Rev2, Tab. 3-23 (uomo 82 kg, 1,75 m, 101,3 kPa, 297,2 K) [S2].

| Attività | Calore sensibile | Vapore | O₂ | CO₂ |
|---|---|---|---|---|
| Sonno | 160 kJ/h = 44 W | 1,08 g/min | 0,37 g/min | 0,44 g/min |
| Nominale | 306 kJ/h = 85 W | 1,33 g/min | 0,59 g/min | 0,69 g/min |
| Esercizio aerobico 75% VO₂max (0–30 min) | 465–479 kJ/h ≈ 131 W | 6,7–13,4 g/min (+ sudore 1,2–11,5 g/min) | 3,99 g/min | 5,22 g/min |
| Esercizio resistivo (lunga durata) | — | — | 1,43 g/min | 1,89 g/min |
| Recupero (1 h) | 311–339 kJ/h | 6,9 → 2,6 g/min | 0,59 g/min | 0,69 g/min |
| **Totale giornaliero** | **6,28 MJ** sensibile, 5,51 MJ latente | **2,27 kg** (+0,22 sudore) | **0,84 kg** | **1,01 kg** |

Missioni lunghe (Tab. 4-1): O₂ 0,90 kg/giorno, CO₂ 1,08 kg/giorno (fascia 0,61–1,08 e 0,74–1,31) [S2].

Problemi nel codice attuale:

- ❌ **Calore latente contato due volte.** `heat: 125 W` finisce tutto in `sQ` (calore sensibile all'aria) e il vapore viene aggiunto a parte. Il latente sta già nel vapore. Il sensibile corretto è 85 W nominale e 44 W nel sonno, cioè ~40–80 W per persona in meno.
- ⚠️ Sonno: O₂ 0,63 kg/giorno contro 0,53 BVAD; vapore 1,2 contro 1,56.
- ⚠️ Esercizio: il fattore 3,2 per 1 h non riproduce il profilo BVAD (30 min a 6,8× O₂ nominale, poi 1 h di recupero con vapore alto).
- ⚠️ "meal" non esiste nel BVAD: va trattato come nominale, più una sorgente di vapore della cucina se serve.
- Nota: le tabelle BVAD sono per 101,3 kPa. A pressione ridotta la quota latente cresce. Tenere i valori BVAD e documentare il limite.

### 2.2 Generatore di O₂ (elettrolisi)

- ✅ `17,9 MJ/kg`: è l'entalpia alla tensione termoneutra di **1,48 V per cella**, citata nel rapporto NASA sull'OGA della ISS [S10]. Conto: 4F × 31,25 mol/kg × 1,48 V = 17,85 MJ/kg.
- ✅ `η ≈ 0,7`: le celle OGA lavorano a ~1,75 V [S10] → 21,1 MJ/kg sullo stack. Con alimentatore e ausiliari si arriva a ~25 MJ/kg.
- Per 2 persone (1,68 kg/giorno): ~410 W sullo stack, ~480–500 W elettrici medi. Il calore che entra nell'anello o in cabina è `P_el − ṁ·17,85 MJ/kg`, ~130–150 W. L'OGA della ISS produce fino a 9,25 kg/giorno a 46,9 A con un alimentatore da oltre 3800 W [S10].

### 2.3 Scrubber CO₂

- ⚠️ `~150 W` è troppo basso. Il CDRA della ISS vale ~1000 W, di cui 620 W rigettati al controllo termico (slide NASA, fonte secondaria [S12]). Rimuove 4,2 kg/giorno a 2 mmHg [S11]. Per 2 persone (~2 kg/giorno) una scala lineare (stima mia) dà ~500 W.
- ⚠️ **Specifico per Marte (deduzione mia):** gli scrubber a ammina rigenerati "a vuoto" (Orion CHC) scaricano CO₂ verso lo spazio [S11]. Su Marte l'esterno ha ppCO₂ ≈ 0,95 × 636 Pa ≈ 4,5 mmHg, più della cabina (2–3 mmHg), quindi lo scarico passivo non funziona senza pompa o rigenerazione termica. Conviene modellare un sistema a sorbente rigenerato termicamente (tipo 4BMS/4BCO₂), con il suo carico elettrico e termico.

### 2.4 Bus elettrico e solare

| Voce | Piano | Verifica | Fonte |
|---|---|---|---|
| Irraggiamento in cima all'atmosfera | 590 W/m² | ✅ media (586,2 NSSDC; 590 Appelbaum). Varia da **494 (afelio) a 718 W/m² (perielio)** | [S1], [S3], calcolo da r(M) |
| `I_horiz = 590 · k · sin(a)` | | ❌ Ignora l'atmosfera. Modello NASA: `G_h = G_0 · cos z · f(z,τ,al) / (1 − al)`, diretto `G_b = G_0 · e^(−τ/cos z)`, diffuso = differenza | [S3] |
| Mezzogiorno, z = 20° | | τ 0,5 → ~495 W/m²; τ 1 → ~440; τ 2 → ~345 | [S3] Tab. I |
| Insolazione giornaliera | | 2–4 kWh/m²/sol in stagione limpida (VL1) | [S3] |
| Profondità ottica | | minimo VL1 0,35; tempeste globali 3–9 | [S3] |
| `k_polvere` = 0,6 fisso | | ❌ Mescola due fenomeni. (a) Opacità atmosferica `τ`; (b) polvere sui pannelli: perdita tipica **0,2% per sol** (0,05–2%), con pulizie episodiche dal vento | [S13] |
| `efficiency` 0,22 | | ✅ se è di sistema. Riferimento NASA: celle al 20% → sistema al 15,4% (impaccamento 0,82, perdite elettriche 0,95, termiche 0,99). Celle moderne al 28–30% → sistema ~0,22 | [S8], [S2] |
| `areaM2` 50, batteria 30 kWh | | ⚠️ Probabilmente sottodimensionati (vedi stima sotto) | calcolo mio |

**Carichi aggiunti dopo la verifica del 16 ottobre 2026** (`power.loads`, stime tranne il galley):

| Carico | Valore | Stato | Fonte |
|---|---|---|---|
| `galley` | 960 W, 3 finestre da 30 min (7:00, 12:00, 19:30 LTST), `modulable`, posizione del tavolo | ⚠️ potenza dal galley Shuttle del BVAD (reidratazione 0,540 kW + forno 0,360 kW + ventole 0,060 kW = 0,960 kW massimi in uso); la durata di 30 min per pasto è STIMA mia | [S2] §4.4.6 |
| `lighting-N`, `lighting-S` | 2 × 75 W (150 W in tutto), 7–23 LTST, `essential`, a soffitto, una per zona | ❓ STIMA: ~5 W/m² su ~27,6 m² di pavimento (LED). Nel BVAD ci sono solo i dati dell'illuminazione per colture, non quella dell'habitat | nessuna |
| `water-N`, `water-S` | 140 + 60 W continui (200 W in tutto), `modulable` | ❓ STIMA: un forum cita un articolo NASA con 560 W medi (700 W in uso) per il recupero acqua ISS, **non verificato sul primario** (il PDF NTRS 20170008984 ha solo l'abstract leggibile). Scalato a 2 persone (~1/3 dell'equipaggio ISS) | non verificata |

Con questi tre carichi il consumo di un sol sale di ~8 kWh (galley 1,4 + luci 2,4 + acqua 4,8). Ogni carico ha una posizione (`pos`): senza, il calore va tutto nell'aria della mandata di F1, che è nella zona S, e la zona S si surriscalda (scarto dal setpoint 1,42 K rms contro 0,71, T max 27,0 °C in una prova con luci e acqua senza `pos`). La ripartizione dell'acqua tra le zone è stata scelta in 2 sol di prova: tutta a N dà N 1,38 K / S 0,86 K; 100 + 100 W dà N 0,59 / S 1,50; 140 + 60 W dà N 0,77 / S 1,05 (T max 26,1 °C). Il limite è il raffreddamento per zona (CHX di F2 per N, F1 per S), non il radiatore: portare l'area da 12 a 14 m² o l'UA dei CHX a 100/70 W/K non cambia nulla. Le due zone restano comunque meno precise di prima (N 0,46 / S 0,71 K senza i carichi nuovi).

Stima di carico (mia, da tarare in Fase 1): rack 300 + ventole 60 + pompa 60 + O₂ 500 + CO₂ ~500 + riscaldamento notturno medio ~500 W ≈ **1,9 kW medi ≈ 46 kWh/sol**, senza illuminazione né trattamento acqua. Con 2–4 kWh/m²/sol × 0,22 servono **50–100 m²** con cielo limpido. Con τ = 3 la produzione cade al ~40% di quella limpida. Nel dimensionamento NASA (TM-106606) gli array dell'habitat erano dimensionati per la tempesta globale (τ = 6) [S8].

### 2.5 Radiatore

| Voce | Piano | Verifica | Fonte |
|---|---|---|---|
| ε | 0,85 | ✅ se pulito. Con polvere a ~6 mg/cm², ε cala da ~0,9 a **~0,5** | [S7] |
| `T_cielo` = T_ext − 20 K | | ❓ Nessuna misura. Test NASA con cieli tra 185 e 248 K; dimensionamenti con pozzo a 210 K | [S7], [S8] |
| `h_conv` | 3 W/m²K | ⚠️ ~0,3–0,7 W/m²K con CO₂ a 600 Pa | calcolo mio |
| Fattori di vista | assenti | ⚠️ BVAD per Marte usa radiatori **verticali** con rivestimento Teflon argentato, dimensionati per una tempesta di polvere moderata all'equatore. Un radiatore verticale vede metà cielo e metà suolo; di giorno il suolo è molto più caldo del cielo | [S2] §3.2.6 |
| Assorbimento solare | assente | ⚠️ Aggiungere `α · G` sulla faccia del radiatore | [S9] |
| `antifreezeK` 255 K | | ⚠️ Vale per l'anello interno ad acqua/glicole. Nel progetto dell'habitat lunare NASA l'anello esterno usa NOVEC 7200, che congela a 136 K e ha limite di esercizio a 173 K. Tenerlo sopra il limite richiede potenza continua (1,35–3,84 kW per 48 m² sulla Luna) | [S9] |
| ~5 m² per 1 kW | | ✅ Calcolo: ε 0,85, 280 K, cielo 200 K → 219 W/m². Con polvere (ε 0,5) → 129 W/m², quindi ~8 m² per 1 kW | calcolo mio |

### 2.6 Setpoint e termostati

- ⚠️ 18 °C di notte coincide con il limite inferiore di salute NASA (18–27 °C) ed è fuori dalla zona comfort (20–25 °C) [S6]. Proposta: **20 °C di notte, 22 °C di giorno**.

---

## 3. Valori senza fonte NASA

Questi restano stime e vanno trattati come parametri di sensibilità, non come dati: `uGlass`, `shgc`, `structCap`, `hMassGlass`, coefficienti di `mixing`, `kp`/`ki` dei controllori, UA del CHX, massa dell'anello, `τ` degli attuatori, potenza delle ventole, rendimento della batteria, COP della pompa di calore (`η_carnot` 0,4), `heatPump.minLoopK` (275 K: sotto questa temperatura dell'anello la pompa non parte; prima 283 K), `external.capJK` (120 kJ/K: ~40 kg di glicole più ~12 m² di pannello radiante in alluminio, prima 50 kJ/K senza la massa del pannello). Mancano inoltre carichi elettrici che un habitat reale ha: illuminazione, trattamento acqua, cucina, comunicazioni.

---

## 4. Fonti

- **[S1]** NASA NSSDC, *Mars Fact Sheet*. https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html
- **[S2]** Anderson, Ewert, Keener et al., *Life Support Baseline Values and Assumptions Document*, NASA/TP-2015-218570/REV2, febbraio 2022. https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf
- **[S3]** Appelbaum & Flood, *Solar Radiation on Mars*, NASA TM-102299 (1989), https://ntrs.nasa.gov/citations/19890018252, e aggiornamento NASA TM-103623 (1990), https://ntrs.nasa.gov/citations/19910005804
- **[S4]** Appelbaum, Flood & Crutchik, *Solar Radiation on Mars: Tracking Photovoltaic Array*, NASA TM-106700 (1994). https://ntrs.nasa.gov/citations/19950004977
- **[S5]** Allison & McEwen, *A post-Pathfinder evaluation of areocentric solar coordinates…*, Planet. Space Sci. 48 (2000). https://ntrs.nasa.gov/api/citations/20000097895/downloads/20000097895.pdf · NASA GISS Mars24, algoritmo: https://www.giss.nasa.gov/tools/mars24/help/algorithm.html
- **[S6]** NASA OCHMO, schede tecniche NASA-STD-3001 Vol. 2: ECLSS https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-002-eclss.pdf · Atmosfera abitabile https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-003-habitable-atmosphere.pdf · CO₂ https://nasa.gov/wp-content/uploads/2023/03/co2-technical-brief-ochmo.pdf
- **[S7]** *Final Report: Mars Radiator Characterization Experimental Program*, https://ntrs.nasa.gov/api/citations/20040161545/downloads/20040161545.pdf · *The Effect of Martian Dust on Radiator Performance*, https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20040161153.pdf
- **[S8]** Withrow & Morales, *Solar-Electrochemical Power System for a Mars Mission*, NASA TM-106606 (1994). https://ntrs.nasa.gov/api/citations/19950012155/downloads/19950012155.pdf
- **[S9]** *Surface Habitat Thermal Control System Architecture and Technical Challenges Update*, IEEE Aerospace 2022. https://ntrs.nasa.gov/api/citations/20210026557/downloads/IEEE%202022%20Paper%20SH%20TCS%20Architecture%20and%20Technical%20Challenges%20Update.pdf
- **[S10]** *ISS Oxygen Generation Assembly*, ICES-2018. https://ntrs.nasa.gov/api/citations/20180006335/downloads/20180006335.pdf · *AOGA Status*, ICES-2025. https://ntrs.nasa.gov/api/citations/20250005808/downloads/ICES_2025_345%20AOGA%20Status%205%2022%2025.pdf
- **[S11]** *CO₂ Removal Technologies ESM*, ICES-2026. https://ntrs.nasa.gov/api/citations/20260005251/downloads/ICES_CO2_ESM_2026.pdf
- **[S12]** Slide NASA (ospitate da USEA), backup sul CDRA. Fonte secondaria. https://usea.org/sites/default/files/event-/JAN_NASA%20DCA%207-24-2019sW2.pdf
- **[S13]** Lorenz et al., *Lander and rover histories of dust accumulation on and removal from solar arrays on Mars* (2021). https://hal.sorbonne-universite.fr/hal-03369920 · NASA NTRS sugli array MER: https://ntrs.nasa.gov/citations/20230007029
- **[S14]** Hickey et al., *Integrated Lightweight Structure and Thermal Insulation for Mars Rover*, SAE 951523 (1995). https://saemobilus.sae.org/papers/integrated-lightweight-structure-thermal-insulation-mars-rover-951523
- **[S15]** Hamilton et al. (2014) e Martínez et al. (2014), JGR Planets, inerzia termica da REMS. https://deepblue.lib.umich.edu/items/42b22b56-f48d-4815-aec2-17faec546aad
- **[S16]** NASA Photojournal, *Seasonal Cycles in Curiosity's First Two Martian Years*. https://science.nasa.gov/photojournal/seasonal-cycles-in-curiositys-first-two-martian-years/ · estremi riportati da Sky & Telescope: https://skyandtelescope.org/astronomy-news/curiosity-sees-seasonal-trends-on-mars/
- **[S17]** Rapporti meteo InSight 2019 (fonte secondaria). https://www.space.com/mars-weather-reports-from-insight-lander.html
- **[S18]** Schofield et al., *The Mars Pathfinder ASI/MET Experiment*, Science 278 (1997), pp. 1752–1758.
- **[S19]** Munguira et al., *One Martian Year of Near-Surface Temperatures at Jezero From MEDA*, JGR Planets (2024), DOI 10.1029/2024JE008385.
- **[S20]** NASA-STD-3001, Vol. 2, Rev F, §6.2 (Tab. 6.2-1, [V2 6003], [V2 6004]). https://standards.nasa.gov/system/files/tmp/NASA-STD-3001%20Vol%202%20Rev%20F.pdf · Rev C: https://www.nasa.gov/wp-content/uploads/2020/10/2022-04-08_nasa-std-3001_vol_2_rev_c_final.pdf · scheda OCHMO-TB-003: https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-003-habitable-atmosphere.pdf

## 5. Limiti di ossigeno per gli allarmi (aggiunto dopo la tempesta forte)

Testo estratto dal PDF Rev F (la Rev D citata dalla scheda OCHMO non è stata trovata) [S20]. Il limite NASA non è sulla ppO₂ della cabina ma sulla **pressione parziale dell'ossigeno inspirato**, `PIO₂ = (PB − 47 mmHg) · FO₂`, con `PB` pressione totale in mmHg e `FO₂` frazione di O₂ **a secco** (47 mmHg = pressione di vapore a 37 °C, 6,27 kPa [S6]).

| Tab. 6.2-1, [V2 6003] | PIO₂ (mmHg) |
|---|---|
| Normossia, intervallo di riferimento | 145–155 |
| Ipossia lieve, limite inferiore (indefinito, con monitoraggio sanitario) | **127** (media su 1 h) |
| Limite inferiore assoluto dell'ipossia lieve | **122** (2,36 psia) |
| Iperossia, limite superiore indefinito | 356 |
| Iperossia, limite a breve termine (6–9 h, prebreathe) | 791 |

Altri dati dalla stessa fonte: OSHA definisce carente un'atmosfera con meno del 19,5% di O₂ e arricchita sopra il 23,5% (PIO₂ normossico 139–168 mmHg); il testo osserva che nessun dato in microgravità copre le missioni lunghe con PIO₂ di 127 mmHg, per cui serve un piano di monitoraggio. [V2 6004]: media su 1 h della ppCO₂ ≤ **3 mmHg** (già usata nel modello). [V2 6022]: l'equipaggio deve ricevere un allarme quando pressione, umidità, temperatura, ppO₂ e ppCO₂ escono dai limiti.

Calcoli miei (formula sopra, vapore con Magnus, scena di default 70,3 kPa):
- Atmosfera di progetto (70,3 kPa, ppO₂ 18,63 kPa, 20 °C, UR 50%): PIO₂ ≈ **129 mmHg**, cioè appena sopra il limite di 127. Con quella pressione e UR la soglia di 127 mmHg corrisponde a ppO₂ ≈ 18,3 kPa, e quella di 122 mmHg a ≈ 17,6 kPa.
- Schermata della tempesta (72,77 kPa, ppO₂ 17,72 kPa, 12,7 °C, UR 98%): PIO₂ ≈ **124 mmHg**, tra 122 e 127.
- Fine della corsa di 64 ore (70,9 kPa, ppO₂ 15,6 kPa, 2 °C, UR 98%): PIO₂ ≈ **108 mmHg**, ben sotto il limite assoluto di 122.

**Allarmi implementati** (`engine/monitoring/alarms.js`): `pio2_1h` se la media su 1 h della PIO₂ di una sonda scende sotto 127 mmHg; `pio2_abs` se il valore istantaneo scende sotto 122 mmHg; `pio2_hyper` (solo avviso) se supera 356 mmHg, limite superiore indefinito. La PIO₂ è calcolata da `inspiredPO2` (`engine/shared/constants.js`) con vapore dalla temperatura e dall'UR della sonda (`psat`, Magnus). Gli allarmi leggono il campo vero, non le letture con rumore, quindi il rumore dei sensori non li fa oscillare. Con l'atmosfera di progetto il margine sul limite di 127 mmHg è di soli ~2 mmHg: un aumento dell'UR o un calo della ppO₂ di pochi decimi di kPa basta ad attivare l'allarme.

**Valori senza fonte NASA, da dichiarare come stime nel codice:** la riserva di batteria per il supporto vitale (`lifeReserveSoc`) e la portata della valvola di sfiato (`reliefKgS`).

**Setpoint di emergenza del generatore di O₂ (`o2gen.emergencySetpointKPa` = 18,15 kPa, STIMA).** Con il bus a `lifeSupportOnly` il generatore punta a una pO₂ più bassa di quella nominale (18,63 kPa). Il valore corrisponde a PIO₂ = 124 mmHg a 70,3 kPa, cioè 2 mmHg sopra il limite assoluto di 122 mmHg [S20]; il margine di 2 mmHg è una scelta mia. È sotto la soglia di allarme di 127 mmHg (media 1 h): in emergenza l'allarme `pio2_1h` scatta, ma non quello assoluto. Il motivo: a cabina fredda la pO₂ cala a parità di massa (13 °C contro 22 °C ≈ −3%) e il PI saturava il generatore a 1530 W (94% del carico) per riportarla al nominale, circa 3,5 kWh di una batteria da 4,4 kWh rimasti.

**Riserva per il supporto vitale (`battery.lifeReserveSoc` = 0,22, STIMA).** Non ho trovato in NASA-STD-3001 una regola per la riserva elettrica del supporto vitale: è una scelta di progetto, dimensionata sul carico. Energia di un sol (scena di default, τ 0,5, report headless): scrubber 0,71 kWh, generatore di O₂ 14,81, ventola F1 0,51, ventola F2 0,51, pompa 1,48; somma **18,04 kWh/sol**, cioè 0,75 kW medi. Per ~12 ore: 8,8 kWh, pari a 0,22 di una batteria da 40 kWh. Il valore va riverificato se cambiano carichi o batteria. Il bus serve in ordine `lifeSupport` > `essential` > `modulable`: il supporto vitale può scaricare la batteria fino a 0, gli essenziali (rack, riscaldatori di emergenza sotto 16 °C, antigelo dell'anello esterno) si fermano a `lifeReserveSoc`, i modulabili (pompa di calore, post-riscaldo, riscaldatori sopra 16 °C) a `max(minSoc, lifeReserveSoc)`, perché non devono intaccare la riserva. Isteresi di 5 punti percentuali sopra ogni soglia. Priorità `lifeSupport` assegnate nella scena a `scrubber`, `o2gen`, `fan:F1`, `fan:F2` (campo `priority` delle ventole) e `pump` (`thermal.loop.pumpPriority`).
