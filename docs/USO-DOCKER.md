# How to run the simulations (without installing Python)

All you need is **Docker Desktop**, installed and running. Every command is typed in a terminal opened in the
project folder (the one with `docker-compose.yml`).

## 1. The first time
```
docker compose build
```
It takes a few minutes. It only needs to be redone when `pyproject.toml` or the dependencies change: **editing the YAML files or the
plugin code does not require rebuilding anything.**

## 2. Run a simulation
```
docker compose run --rm ares3 run scenarios/station/nominal.yaml --days 2 -o output/test1
```
- `scenarios/station/nominal.yaml` is the official station (Mario's ISS model) with no faults; `scenarios/station/events/` holds one
  scenario for each of the 26 faults in the catalog (see `docs/station.md`).
  `scenarios/emergency.yaml` and `nominal.yaml` are the small test habitat.
- `--days 2` is 2 days **of the chosen environment** (on Mars a day lasts 24 h 39 min).
- `-o output/test1` is the results folder: you will find it on your computer in `output/test1/`.
- Without `--days`, the scenario's `duration_days` applies. For an unbounded run: `--forever` (stop it with Ctrl+C;
  it saves what it has done).

Order of magnitude: the ISS station (16 volumes, 186 sensors) runs at about 300x real time: 2 simulated days take about 10 minutes (the small habitat about 2).

## 3. Check the YAML files without simulating
```
docker compose run --rm ares3 validate scenarios/station/nominal.yaml
```
It reports typos, nonexistent ids, schedules that do not cover 24 h, and so on, right away.

## 4. What to edit
Everything is in `scenarios/`, with a text editor (VS Code, Notepad...):

| File | What it holds |
|---|---|
| `nominal.yaml`, `emergency.yaml` | scenario: seed, duration, which files to use, environment, export format |
| `environments/*.yaml` | environment (Mars, orbit): atmosphere, gravity, day length, alarm limits |
| `base_layout.yaml`, `sensors_placeholder.yaml`, `actuators_placeholder.yaml` | station modules, sensors, actuators |
| `crew.yaml` | the 4 astronauts and their days |
| `faults.yaml` | faults and emergencies, and when they trigger |

To change environment, one line in `nominal.yaml` is enough: `environment: environments/orbital_station.yaml`.
To tweak a single value without copying the file: `environment_overrides: {atmosphere: {temperature_c: 23}}`.

**Before trusting a result, look at the `PLACEHOLDER` headers**: files marked that way are examples awaiting
review, not validated data.

## 5. The results
In `output/<name>/`:
- `long/part-*.parquet`: one row per measurement (`value` = measured, `value_true` = truth, `is_anomaly`,
  `anomaly_type`)
- `wide/part-*.parquet`: one column per sensor
- `manifest.json` and `scenario.json`: the configuration it was generated with (reproducible with the same seed)

Read them in Python with `pandas.read_parquet("output/test1/long")`. To get CSV instead of Parquet, in the scenario:
`export: {format: csv}`.

## 6. Other useful commands
```
docker compose run --rm ares3 --help              # list of commands
docker compose run --rm --entrypoint pytest ares3 # automated tests (for developers)
```

## Common problems
- *"Cannot connect to the Docker daemon"*: Docker Desktop is not running.
- *Error with a line and a YAML line number*: wrong indentation (use spaces, never tabs) or a forgotten colon.
- *Files in `output/` cannot be deleted* (Linux/Mac): they are created by the container as root; use `sudo rm -r output/test1`.
