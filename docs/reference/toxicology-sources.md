# Fonti della tossicologia (CO, fumo, ammoniaca)

Tag usati nel codice (`plugins/physiology/toxicity.py`, `scenarios/monitor_placeholder.yaml`). Tutto ciò che non ha un tag è `ESTIMATE`.
Aggiunto dal team software, **da rivedere con la bioingegnere**: il modello di Luca (`human.py`) ora legge il CO attraverso questo modulo.

| Tag | Fonte | Cosa ne usiamo |
|---|---|---|
| [T1] | WHO/IPCS, *Environmental Health Criteria 213: Carbon Monoxide* (2a ed., 1999), cap. 6.3 e Fig. 6. https://www.inchem.org/documents/ehc/ehc/ehc213.htm | Il modello CFK è "il miglior modello complessivo" per la COHb. Parametri di un adulto non fumatore: Haldane M = 218, volume ematico 5,5 L, emoglobina 15 g/100 mL, capacità di diffusione 30 mL/min/mmHg, produzione endogena 0,007 mL/min, ventilazione alveolare 10 (riposo) e 20 L/min (attività leggera) nel loro esempio. Emivita di eliminazione 2-6,5 h |
| [T2] | Coburn RF, Forster RE, Kane PB. *J Clin Invest* 1965;44:1899. | Equazione differenziale: `Vb d[COHb]/dt = VCO + PICO/B - [COHb] PcO2 / (M [O2Hb] B)`, `B = 1/DLCO + PL/VA`. La forma è quella della letteratura (il testo di EHC 213 non la riporta: è un'immagine); i numeri sono verificati su valori noti (vedi `tests/test_toxicity.py`) |
| [T3] | NASA JSC 20584 Rev C, *Spacecraft Maximum Allowable Concentrations* (13/06/2024). https://www.nasa.gov/wp-content/uploads/2024/06/jsc-20584-smacs-rev-c-final.pdf | CO: 425 ppm (1 h), 100 (24 h), 55 (7 d), 15 (30 d, 180 d, 1000 d); bersaglio sistema nervoso centrale e aritmia (COHb). Ammoniaca: 30 / 20 / 3 / 3 / 3 ppm, irritazione e cefalea. HCN e HCl: "Not Set" |
| [T4] | ISO 13571:2012 e SFPE Handbook, nel riassunto IFV/NIPV. https://archief.nipv.nl/documenten/appendix-1-comparison-between-the-iso-standard-sfpe-handbook-and-aegl | FED (non ancora implementata): `FED = sum[CO*vCO2/35000 + HCN^2,36*vCO2/1,2e6] dt`, `vCO2 = exp(%CO2/5)`; CO SFPE `3,317e-5 CO^1,036 vE t / D` con D = 30 %COHb; O2 basso `t/exp(8,13-0,54(20,9-%O2))`. Incertezza ±35 % |
| [T5] | Purser DA, *Modelling Toxic and Physical Hazard in Fire*, Fire Safety Science 2 (1989). https://publications.iafss.org/publications/fss/2/391 | Origine del metodo FED |
| [T6] | NASA, *Impacts of an ammonia leak on the cabin atmosphere of the ISS* (NTRS 20120007777) | Soglie operative: 65 mg/m³ per togliere il respiratore se la concentrazione scende; 800 mg/m³ limite del respiratore |

## Stime nostre (da validare)

- Scalatura per persona: volume ematico 70 (M) / 65 (F) mL/kg; emoglobina 13,5 g/dL (F); capacità di diffusione 24 mL/min/mmHg (F, circa l'80 %).
- Ventilazione alveolare dal VCO2 del motore: `VA(BTPS) = 0,863 VCO2 / FACO2`, FACO2 = 0,056 (formula da manuale), poi BTPS→STPD.
- Pressione capillare di O2 ≈ PIO2 − 47 mmHg.
- **Ipossia funzionale**: la saturazione funzionale è `SaO2 − COHb`; la si converte in un PIO2 equivalente con la curva SpO2/PIO2 del modello base, che alimenta la dose di ipossia e la tachicardia.
- **Saturimetro**: il pulse-ox legge la COHb come emoglobina ossigenata, quindi `spo2` non cala per il CO. Il canale che lo vede è `cohb_pct` (SpCO, co-ossimetria). Conoscenza generale di fisiologia, non da queste fonti.
- Soglie del monitor: COHb 5 % (avviso) e 15 % (critico), SpO2 < 90 %, temperatura centrale > 38,5 °C.
- Non modellati: HCN (il nostro fuoco non lo produce), mioglobina (il 10-50 % del CO corporeo può essere extravascolare), effetti dell'altitudine e dell'esercizio massimale sulla diffusione, ammoniaca ad alta concentrazione (nessun modello dose-risposta trovato).
