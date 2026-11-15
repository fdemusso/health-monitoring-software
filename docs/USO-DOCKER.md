# Come lanciare le simulazioni (senza installare Python)

Serve solo **Docker Desktop** installato e avviato. Tutti i comandi si danno da un terminale aperto nella
cartella del progetto (quella con `docker-compose.yml`).

## 1. La prima volta
```
docker compose build
```
Ci mette qualche minuto. Si rifà solo se cambiano `pyproject.toml` o le dipendenze: **modificare gli YAML o il codice
dei plugin non richiede di ricostruire nulla.**

## 2. Lanciare una simulazione
```
docker compose run --rm ares3 run scenarios/station/nominal.yaml --days 2 -o output/prova1
```
- `scenarios/station/nominal.yaml` è la stazione ufficiale (il modello ISS di Mario) senza guasti; in
  `scenarios/station/events/` c'è uno scenario per ognuno dei 26 guasti del catalogo (vedi `docs/station.md`).
  `scenarios/emergency.yaml` e `nominal.yaml` sono il piccolo habitat di prova.
- `--days 2` sono 2 giorni **dell'ambiente scelto** (su Marte un giorno dura 24 h 39 min).
- `-o output/prova1` è la cartella dei risultati: la trovi sul tuo computer in `output/prova1/`.
- Senza `--days` vale `duration_days` dello scenario. Per una corsa senza limite: `--forever` (si ferma con Ctrl+C
  e salva quello che ha fatto).

Ordine di grandezza: la stazione ISS (16 volumi, 186 sensori) va a circa 300x il tempo reale: 2 giorni simulati richiedono circa 10 minuti (il piccolo habitat circa 2).

## 3. Controllare gli YAML senza simulare
```
docker compose run --rm ares3 validate scenarios/station/nominal.yaml
```
Segnala subito errori di battitura, id inesistenti, orari che non coprono le 24 h, ecc.

## 4. Cosa si modifica
Tutto in `scenarios/`, con un editor di testo (VS Code, Blocco note...):

| File | Cosa contiene |
|---|---|
| `nominal.yaml`, `emergency.yaml` | scenario: seme, durata, quali file usare, ambiente, formato di export |
| `environments/*.yaml` | ambiente (Marte, orbita): atmosfera, gravità, durata del giorno, limiti di allarme |
| `base_layout.yaml`, `sensors_placeholder.yaml`, `actuators_placeholder.yaml` | moduli della stazione, sensori, attuatori |
| `crew.yaml` | i 4 astronauti e le loro giornate |
| `faults.yaml` | guasti ed emergenze e quando scattano |

Per cambiare ambiente basta una riga in `nominal.yaml`: `environment: environments/orbital_station.yaml`.
Per ritoccare un solo valore senza copiare il file: `environment_overrides: {atmosphere: {temperature_c: 23}}`.

**Prima di fidarti di un risultato, guarda le intestazioni `PLACEHOLDER`**: i file marcati così sono esempi in attesa di
revisione, non dati validati.

## 5. I risultati
In `output/<nome>/`:
- `long/part-*.parquet`: una riga per ogni misura (`value` = misurato, `value_true` = verità, `is_anomaly`,
  `anomaly_type`)
- `wide/part-*.parquet`: una colonna per ogni sensore
- `manifest.json` e `scenario.json`: con quale configurazione è stato generato (riproducibile con lo stesso seme)

Si leggono in Python con `pandas.read_parquet("output/prova1/long")`. Per ottenere CSV invece di Parquet, nello scenario:
`export: {format: csv}`.

## 6. Altri comandi utili
```
docker compose run --rm ares3 --help              # elenco comandi
docker compose run --rm --entrypoint pytest ares3 # test automatici (per chi sviluppa)
```

## Problemi comuni
- *"Cannot connect to the Docker daemon"*: Docker Desktop non è avviato.
- *Errore con una riga e un numero di riga YAML*: indentazione sbagliata (usa spazi, mai tab) o due punti dimenticati.
- *I file in `output/` non si cancellano* (Linux/Mac): sono creati dal container come root; usa `sudo rm -r output/prova1`.
