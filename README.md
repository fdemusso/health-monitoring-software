# ARES 3

**A health monitor for crews too far from Earth to wait for an answer.**

ARES 3 (Autonomous Biomedical & Life-Support Digital Multi-Tool) watches two things at once: the vital signs of astronauts and the air they breathe. It runs in real time, onboard, and tells the crew what is wrong, where, and what to do next.

It started from two ISS references. [Tempus Pro](https://www.nasa.gov/glenn/glenn-expertise-space-exploration/human-health-performance/exploration-medical-technologies/multifunctional-integrated-medical-devices) is a multifunctional medical device with vital-sign monitoring, guided procedures and telemedicine. The [Crew Health Care System (CHeCS)](https://ntrs.nasa.gov/citations/20110022379) is the ISS medical hardware suite. ARES 3 keeps their job, monitoring crew health, and rebuilds it for missions where Earth cannot answer fast enough: Artemis, lunar gateways, Mars transits.

Labelled spaceflight data is rare, so ARES 3 also brings its own test bench: a deterministic, tick-based simulator of an ISS-like station with four astronauts, 16 connected volumes of air, heat and humidity, and a live web dashboard. Spring a leak. Foul a fan. Let CO build up in a cabin. Then watch the monitor catch it. Every run exports labelled time series for training and testing alert models.

Built by Team I Frappuccini for the NASA Space Apps Challenge 2026 in Rome, on the [Health Monitoring Software](https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/) challenge.

---

## Why ARES 3

Static monitors struggle on long-duration missions. Three problems keep coming back.

| The problem | What goes wrong | What ARES 3 does |
|---|---|---|
| Communication latency | On lunar and Mars missions the signal round trip is too long for an Earth flight surgeon to step in during an acute emergency. | Runs onboard. It detects, classifies and gives the crew a step-by-step procedure within seconds. |
| Fixed thresholds | A mandatory workout on the T2 treadmill, ARED or CEVIS looks like tachycardia. Rule-only systems either bury the crew in false alarms or miss subtle failures that cascade across systems. | Reads vitals in context (workout logs, cabin pressure). Rules carry the safety case. ML catches what nobody wrote a rule for. |
| Siloed data | Life-support streams (O₂, CO₂, pressure) and crew vital signs are rarely read together, so a heart rate or an SpO₂ value loses its meaning. | One pipeline reads both. Cabin air and the body are the same problem. |

## What it does

1. Monitors the crew and the habitat: rule-based detectors, a two-stage machine-learning pipeline, an ECG autoencoder, emergency playbooks and crew procedures, following the alert logic of ISS operations.
2. Simulates the station it monitors: gas, heat and humidity balance between 16 volumes (14 ISS modules, a docked Crew Dragon lifeboat and an EVA volume), the life-support hardware that controls them, the sensors that observe them, and the physiology of each astronaut.
3. Exports the data: labelled multivariate time series (environment and vital signs, with the fault ground truth) for training and evaluating alert models, plus a WebSocket stream that drives a React + TypeScript dashboard, where a body hologram highlights the affected organs in real time.

| At a glance | |
|---|---|
| Crew | 4 astronauts with different roles, each with their own physiology model |
| Station | 16 volumes, 62 environmental sensors, 23 life-support actuators |
| Faults | 26 catalogued, one scenario file each, plus combinations and crew medical events |
| Resolution | 1-second tick (1 Hz) |
| Orbit | 92.8 minutes, with eclipse and battery state of charge |
| Speed | about 300× real time: two simulated days in about 10 minutes |
| Output | Parquet or CSV, with `value` (sensed) and `value_true` (ground truth) |

| Results so far (simulation only) | |
|---|---|
| Tested | 16 simulated mission days, 1.38M+ samples (about 2 GB of telemetry) |
| Monitor specificity | 99.997% |
| False alerts | fewer than 2 per 24 hours across daily T2, ARED and CEVIS exercise schedules |

> **Scope.** Everything here is simulation time on synthetic data. Detection rates, delays and false-alarm figures describe the simulator, not flight hardware or clinical performance. See [Limitations](#limitations).

---

## Contents

- [Quick start](#quick-start)
- [Tutorial: running ARES 3 with Docker](#tutorial-running-ares-3-with-docker)
- [Monitoring system](#monitoring-system)
- [How it works](#how-it-works)
- [Why it is built this way](#why-it-is-built-this-way)
- [Beyond the station](#beyond-the-station)
- [Strengths](#strengths)
- [Limitations](#limitations)
- [Repository layout](#repository-layout)
- [Working on the project](#working-on-the-project)
- [Further documentation](#further-documentation)
- [Team](#team)
- [Licence notes](#licence-notes)

---

## Quick start

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/). The dashboard also needs Node and pnpm.

```bash
uv sync --extra dev
uv run ares3 validate scenarios/station/nominal.yaml            # load the scenario and build every plugin
uv run ares3 run scenarios/station/nominal.yaml --days 2 -o output/run1
uv run pytest -q -n auto

# Live: WebSocket bridge + dashboard
uv sync --extra serve
uv run ares3 serve scenarios/station/nominal.yaml --speed 10 --warmup-h 4
cd dashboard && pnpm install && pnpm dev
```

`--warmup-h 4` simulates four hours ahead, so the ML stages are primed and the charts start full.

Prefer containers? See `docs/USO-DOCKER.md`. Deploying for real? See `docs/deploy.md`.

**What you get** (`output/<run>/`): `long/` and `wide/` Parquet parts (one per simulated hour, so unbounded runs use bounded memory), plus `manifest.json` and `scenario.json`. Each observation carries `value` (what the sensor reports) and `value_true` (the ground truth), along with `is_anomaly`, `anomaly_type` and `anomaly_ids`.

---

## Tutorial: running ARES 3 with Docker

No Python installation. Just [Docker Desktop](https://www.docker.com/products/docker-desktop/), running. Run every command from the repository root, where `docker-compose.yml` lives.

There are two images:

| Image | Built from | Use |
|---|---|---|
| `ares3` | `Dockerfile` + `docker-compose.yml` | Batch work: validate scenarios, generate datasets, run tests |
| `ares3-serve` | `deploy/Dockerfile` | The live WebSocket backend for the dashboard (includes the ML models and the `serve` extra) |

### 1. Build the batch image (first time only)

```bash
docker compose build
```

It takes a few minutes, and you only repeat it when `pyproject.toml` or the dependencies change. `scenarios/`, `src/`, `tests/` and `output/` are bind-mounted, so **editing YAML or plugin code needs no rebuild**.

### 2. Check a scenario

```bash
docker compose run --rm ares3 validate scenarios/station/nominal.yaml
```

This loads the scenario and builds every plugin without simulating anything. Typos, unknown ids and schedules that do not cover 24 h are reported immediately.

### 3. Generate a dataset

```bash
docker compose run --rm ares3 run scenarios/station/nominal.yaml --days 2 -o output/run1
```

- Results land on your machine in `output/run1/` (`long/`, `wide/`, `manifest.json`, `scenario.json`).
- `scenarios/station/events/` holds one scenario per catalogued fault, for example `scenarios/station/events/F-ATT-CQFAN-FOD.yaml`.
- Add `--forever` for an unbounded run. Ctrl+C stops it and keeps everything written so far.
- Expect roughly 300× real time on the full station: two simulated days take about 10 minutes.

Read the output with `pandas.read_parquet("output/run1/long")`. For CSV, set `export: {format: csv}` in the scenario.

### 4. Run the tests

```bash
docker compose run --rm --entrypoint pytest ares3 -q
```

### 5. Run the live backend for the dashboard

```bash
docker build -f deploy/Dockerfile -t ares3-serve .
docker run --rm -p 8765:8765 ares3-serve serve scenarios/station/nominal.yaml \
    --host 0.0.0.0 --speed 10 --warmup-h 4
```

`--host 0.0.0.0` is required inside a container, otherwise the published port is unreachable. The WebSocket then listens at `ws://127.0.0.1:8765`. Start the dashboard on the host (`cd dashboard && pnpm install && pnpm dev`) and it connects on its own. The warm-up takes about a minute, and the ML stages are ready right after.

This image bakes in `scenarios/` and `models/`, so rebuild it after changing either. For a hardened production deployment (token, origin check, read-only container, Cloudflare tunnel), use `deploy/docker-compose.yml` and follow `docs/deploy.md`.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop is not running. |
| Error with a YAML line number | Wrong indentation (spaces only, never tabs) or a missing colon. |
| `output/` files cannot be deleted (Linux/macOS) | The container wrote them as root: `sudo rm -r output/run1`. |
| Dashboard cannot connect | Check that the port is published (`-p 8765:8765`) and that `--host 0.0.0.0` is set. |

The full Italian guide is `docs/USO-DOCKER.md`.

---

## Monitoring system

ARES 3 protects on two layers: the clinical stability of each astronaut, and the habitability of the habitat they share.

```
sensed observations
   │
   ├─ rule detectors (thresholds, pressure-drop time scales, variance, redundancy residual, early-warning score)
   ├─ stage A  anomaly detector   – "is something abnormal?"   (PCA per subsystem, nominal data only)
   ├─ stage B  diagnoser          – "which fault, where, why?" (gradient boosting per fault family)
   └─ ECG autoencoder             – "does this heartbeat look healthy?" (healthy beats only)
          │
          ▼
   debounce → Emergency (suspected / confirmed / cleared) → classifier (alert class, system mode)
          │
          ├─ playbook   (machine safing: isolate a module, stop gas, cut power, ...)
          └─ procedure  (checklist for the crew: instruction, check, question, escalate)
```

- Three system modes: `passive` (continuous ingestion of gas and heat balances, wearable vitals and crew schedules), `alert` (rules and ML detect the anomaly and classify fault family and location) and `reaction` (playbooks, crew checklists and organ status). The mode is the maximum over open emergencies. It rises immediately and falls only after a hold time, so it never flickers.
- Alert classes follow ISS levels: emergency, warning, caution, advisory.
- Stage A trains on nominal days only, so it can flag faults nobody catalogued. Stage B names catalogued faults and explains its decision (`Emergency.evidence` lists the largest contributors).
- Loss of cabin air is graded by time scale (breach, rapid, fast, slow, trend) with a time-to-pressure-floor estimate. A critical leak isolates the module and sends the crew to the return vehicle. A slow leak keeps make-up gas on and has the engineer patch it.
- Safety guard: no hatch is closed on someone cut off from a return vehicle. Actions that need judgement become pending requests that any crew member or the UI can approve, with an explicit timeout policy.
- Medical: wearable detectors open a `medical` emergency with a subject and an inferred cause (for example CO poisoning), and the medic is sent to the affected crew member.

### Sensors that cross-check each other

Two identical sensors drift the same way, fail together and make redundancy useless. ARES 3 combines different sensor technologies, whose drifts are independent. When their readings diverge, it is an instrument fault. When they move together, it is a real event. At one station node, three CO₂ sensors work as a team: two tell you that one is faulty, three tell you which one by voting.

### ECG autoencoder

- Trained on healthy beats only. A symmetric dense autoencoder (Python, TensorFlow/Keras) learns normal 140-sample cardiac waveforms, so no rare spaceflight arrhythmia labels are needed.
- Reconstruction-error scoring. The error on each incoming waveform flags structural cardiac anomalies in real time.
- Context-aware exercise filtering. ECG scores are cross-referenced with workout logs and cabin pressure, so healthy treadmill tachycardia is ignored while resting atrial fibrillation is caught.

The UI contract (modes, classes, evidence, procedures, the `ack_step` command) is in `docs/monitor-ui.md`.

---

## How it works

To test a monitor you need a station and a crew to watch. ARES 3 builds both.

### 1. The tick loop

The engine advances in fixed time steps. The order of the phases is part of the design:

```
faults active → crew schedule → crew gas exchange and physical faults applied to the world
→ actuators → world physics (hatch flow, heat, condensation) → snapshot
→ physiology → sensors and sensor faults → alarms, monitor and agent decisions
```

Commands issued in one tick take effect in the next. That removes every circular dependency between sensors, controllers and the world they act on.

### 2. Truth and measurement never mix

`ModuleState` and the crew vitals are the **truth**. Sensors turn truth into an `Observation`: noisy, lagged and, when a fault is active, corrupted. Controllers, detectors and the ML models see only observations. Alarm rules evaluate the true state.

Sensor faults (bias, drift, stuck, dropout, noise) are applied by the engine on top of a healthy device model, so a sensor plugin only ever models a working instrument.

### 3. Plugins propose, the core decides

Sensors return observations. Actuators return flows in mol/s and W, so they do not depend on the time step. Physiology returns vital-sign updates. The core applies all of it and books every mole in a ledger. The test suite checks conservation of O₂, CO₂, N₂ and H₂O in a closed system.

### 4. The station

The official model (`scenarios/station/`) is generated from the bioengineering and physics team's workbook by `tools/build_station.py`:

- 14 ISS volumes, a docked return vehicle (`lifeboat`, a Crew Dragon) and an `eva` volume
- 62 environmental sensors
- 23 life-support actuators
- a catalogue of 26 faults

Gas moves between modules by pressure difference through hatches and by concentration. Hatch flow uses exact exponential relaxation, so a 2 m³ cabin is as stable as a 70 m³ node. Fans and inter-module ventilation add to the exchange. Orbit effects (92.8-minute orbit, eclipse, battery state of charge) live in `core/orbit.py`.

Details, and every estimate that is ours rather than the workbook's, are in `docs/station.md`.

### 5. The crew

Each astronaut has a physiology model (`plugins/physiology/human.py`) with a health state from *ok* to *dead* (death is optional per scenario), driven by a dose of hypoxia, CO₂ and heat. The model includes:

- per-person parameters from sex, age and mass
- circadian rhythm and sleep stages
- core temperature and hydration
- microgravity adaptation
- a beat-to-beat RR series
- carbon-monoxide uptake (COHb, via a Coburn–Forster–Kane model)

Sources are tagged in `docs/reference/physiology-sources.md`. Unsourced numbers are marked ESTIMATE.

### 6. Sensors say everything is fine, the astronaut has a headache

In microgravity, CO₂ does not sink or dissolve. It floats around the face of a sleeping astronaut, while sensors on the walls read normal values. To catch it without paying for CFD, each crew cabin is modelled as a separate small air volume (2.1 m³) connected to the rest of the station only by its fan. The physical result is the same, CO₂ accumulates because air exchange is low, and the computing cost is close to zero.

### 7. Everything is configuration

Scenarios are YAML validated by Pydantic: environment profile, layout, crew, faults and a single root seed. Plugins are referenced as `package.module:Class` and need no registration. Sensors are written as rules ("metric X on all modules"), so defining 30 or 120 sensors costs the same. Time of day follows the profile's day length.

---

## Why it is built this way

| Decision | Reason |
|---|---|
| Deterministic and seeded | Every component draws its random stream from `(seed, kind, id)`. Runs reproduce exactly, and adding a sensor never changes another component's noise. That makes regression tests, ablations and paired comparisons possible. |
| Truth vs. measurement | A monitor that reads the true state looks perfect and proves nothing. Forcing every consumer through noisy, faulty sensors makes sensor failure a diagnosis problem from day one. |
| Effects, not mutation | One place applies changes and books every mole. Conservation is testable, and plugin authors cannot break the physics by accident. |
| Enforced package layering | `schemas` ← `sdk` ← `core`/`plugins` ← `export`, checked by `tests/test_architecture.py`. Domain experts write sensors, actuators and physiology against `sdk` alone and never touch `core`. |
| Lumped-parameter physics | Each module is a well-mixed volume with analytic flows. That gives about 300× real time for the 16-volume station, which is what makes multi-day labelled datasets and live demos affordable. A CFD model was ruled out on purpose. |
| ML beside the rules | Rules are auditable and carry the safety case. ML (two station stages plus the ECG autoencoder) covers what nobody wrote a rule for and diagnoses causes. ML never replaces a rule, and a rule that names a cause wins. |
| One feature extractor, online and offline | Training and inference run the same code, so there is no training/serving skew. Absolute levels are deliberately not features, because every sensor unit has its own fixed error per seed. |
| Ground-truth twin runs | "Fault active" is the label. The time the fault becomes *visible* is measured against a twin run (same seed, no fault), so detection delay has a real reference. |
| Python owns the UI contract | The UI has no threshold logic. Everything arrives computed in `SimulationTick` (`src/ares3/sdk/types.py`), mirrored by hand in `dashboard/src/telemetry/types.ts`. |

---

## Beyond the station

The monitor needs a crew, sensors and a closed environment. That describes more places than a spacecraft.

- Spaceflight: bridges the communication gap on lunar gateways, Mars transits and surface habitats, and turns 40+ telemetry streams into clear safing playbooks and crew checklists.
- Commercial deep-sea diving: real-time monitoring of hyperbaric gas mixtures, decompression risk and diver vital signs.
- High-altitude mountain rescue: early hypoxia detection, time of useful consciousness (TUC) estimation and cardiac arrhythmia alerts in remote alpine zones.
- Submarines and isolated outposts: closed-loop environmental and medical telemetry for polar stations and underground operations.

Plugins in YAML and Python adapt it to a new spacecraft or sensor suite without touching the core.

---

## Strengths

- Reproducible and testable: seeded, deterministic, with conservation checks and an architecture test.
- Labelled data at scale: randomised fault parameters drawn from the workbook's ranges, nominal days, medical events and fault combinations, exported in bounded memory.
- Honest evaluation: models see only sensed values, sensor faults are part of the problem, detection delay is measured against a no-fault twin, and model cards are committed next to the models.
- Defence in depth: deterministic rules stay as the safety net, with ML adding breadth and explanation on top.
- Explainable: alerts carry their evidence and a procedure the crew can follow.
- Replaceable parts: layout, sensors, actuators, environment (orbit or Mars), crew and monitor all swap through YAML or a plugin class.
- Fast: about 300× real time on the full station, so a multi-day scenario runs in minutes.
- Decoupled UI: the dashboard is a separate app that consumes one JSON protocol over WebSocket.

## Limitations

Read these before you trust a number.

- Synthetic data only. The ML metrics, including the figures in "Results so far", are simulation-time numbers, and sensor noise for several instruments is an estimate. They are not flight or clinical performance.
- Simulator-bound models. Both ML stages and the ECG autoencoder train on this simulator's faults, noise and waveforms. Real telemetry would need retraining and independent validation.
- Lumped physics. Each module is well mixed. Spatial effects (local CO₂ pockets, temperature gradients under a fouled fan, air velocity) are approximated with a mixing-efficiency parameter or a small separate volume, or not modelled. Radiation and acoustic noise are out of scope.
- Some inputs are our estimates, not the workbook's: 140 kW generation, CDRA efficiency 0.85, rack heat, the lifeboat, and wearable sensor characteristics. They are listed in `docs/station.md` and need confirmation.
- Compressed fault timescales. Drifts quoted per month run per day, so short runs show them.
- Partial toxicology and no launch phase. CO is modelled. FED (ISO 13571) and HCN/NH₃ toxicity are not, and the launch from Earth is not simulated.
- Limited leak localisation. With hatches open the station behaves as one volume, so pressure alone cannot localise a slow leak. Stage B ranks candidates, and a procedure step confirms by closing hatches.
- Fixed-step engine. Phenomena faster than the tick are not resolved.
- Models are pickled. `joblib` runs code on load, so load only the files committed in `models/`.
- Placeholder inputs remain for the small test habitat, some crew schedules and the monitor defaults. They exist to make the pipeline run and are marked `PLACEHOLDER` in their files.

---

## Repository layout

```
src/ares3/
  schemas/    Pydantic models for scenarios (imports nothing)
  sdk/        plugin base classes, data contract, ControlAPI (imports schemas)
  core/       engine, world, faults, monitor, responder, procedures, orbit
  plugins/    sensors, actuators, physiology, monitor detectors and ML
  export/     Parquet/CSV writers
  serve/      WebSocket session and server
scenarios/    YAML: environments, station (generated), events, crew, monitor
models/       trained ML artefacts and model cards
tools/        station generator, dataset builders, training and evaluation scripts, reports
dashboard/    React + Vite frontend
tests/        engine, station, monitor, architecture
docs/         station notes, UI contract, deployment, references and sources
```

## Working on the project

- Never edit the generated files in `scenarios/station/`. Change `tools/build_station.py` and regenerate (`uv run --with openpyxl python tools/build_station.py`; `--check` detects stale output).
- Respect the layering. A new package must be added to `LAYERS` in `tests/test_architecture.py`.
- Every physical constant needs a source tag or the word ESTIMATE.
- Machine-learning workflow:
  ```bash
  uv run python tools/ml/make_dataset.py --nominal --randomize --medical --combos --seeds 1-3,5 --days 2 --features --out output/ml/feat
  uv run python tools/ml/train_anomaly.py && uv run python tools/ml/train_diagnoser.py   # → models/station_v1/
  uv run python tools/ml/check_monitor.py --nominal --seeds 5 --days 1                   # false alarms and delays on whole runs
  ```
- Tests: `uv run pytest -q -n auto` (about 90 s on 16 cores). Lint: `uv run ruff check src tests`.

## Further documentation

| Topic | File |
|---|---|
| The official station, estimates and verified behaviour | `docs/station.md` |
| UI contract for the monitor | `docs/monitor-ui.md` |
| Crew medical procedures | `docs/procedure-mediche.md` |
| Crew ML plan | `docs/piano-ml-equipaggio.md` |
| Deployment | `docs/deploy.md`, `docs/USO-DOCKER.md` |
| Sources (physiology, toxicology, depressurisation, monitoring/ML) | `docs/reference/` |
| Monitoring design plan | `piano.md` |

## Team

Team I Frappuccini: Luca Pieralli, Mario D'Amore, Federico Attanasio, Flavio De Musso. NASA Space Apps Challenge 2026, Rome. Source code, simulation engine, trained models and documentation: [github.com/fdemusso/health-monitoring-software](https://github.com/fdemusso/health-monitoring-software).

## Licence notes

`dashboard/src/data/anatomy.json` is derived from gganatogram (GPL-2). Keep `dashboard/LICENSE` and `dashboard/THIRD_PARTY_NOTICES.md` with it.