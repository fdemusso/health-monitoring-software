# ARES 3 - astronaut health & habitat simulation engine

NASA Space Apps Challenge 2026. A deterministic tick-based simulator of a crewed habitat (4 astronauts)
that produces labelled multivariate time series (environment + vital signs) in nominal and fault
conditions, for the ML alert model and the autonomous first-responder agent.

```
uv sync --extra dev
uv run ares3 validate scenarios/station/nominal.yaml
uv run ares3 run scenarios/station/nominal.yaml --days 2 -o output/run1     # or --forever (Ctrl-C to stop)
uv run pytest
```

Output (`output/<run>/`): `long/part-*.parquet` (`tick, timestamp, sensor_id, entity_id, metric, value,
value_true, is_anomaly, anomaly_type, anomaly_ids`), `wide/part-*.parquet` (one column per sensor),
`manifest.json`, `scenario.json`. One part file per simulated hour, so runs of any length stay in bounded memory.
`value` is what the sensor reports, `value_true` the ground truth. `is_anomaly` means "a fault is active on this
sensor, on what it measures, on its module, or on an actuator of that module" - not "the effect is already visible".

## Who edits what

Everything configurable lives in `scenarios/` (YAML) and `src/ares3/plugins/` (Python). `core/` is not
meant to be edited by Mario or Luca.

| Piece | File(s) | Status | Owner |
|---|---|---|---|
| Tick loop, world graph, gas/heat balance, faults, labels, export, CLI | `src/ares3/core`, `export` | solid | software |
| Data contract and plugin base classes | `src/ares3/sdk`, `schemas` | solid | software |
| MET -> O2/CO2/heat table (BVAD), NASA-STD-3001 limits | `core/metabolism.py`, `scenarios/environments/*.yaml` | ported from ambientmonitor, sources in `docs/reference/` | software |
| Environment (Mars / orbit), global rules | `scenarios/environments/` | swap with one line in the scenario; override single values with `environment_overrides` | team |
| Station: layout, sensors, actuators, telemetry, 26 faults | `scenarios/station/` (generated from `notebooks/mario/*.xlsx` by `tools/build_station.py`, see `docs/station.md`), `plugins/sensors/instruments.py`, `plugins/actuators/eclss.py` | **OFFICIAL** (Mario's ISS model); our additions marked ESTIMATE | Mario / software |
| Small test habitat (hab, lab, ...) | `scenarios/base_layout.yaml`, `sensors_placeholder.yaml`, `actuators_placeholder.yaml` | fixture of the engine tests and of Luca's report | software |
| Physiology | `plugins/physiology/baseline.py` | **PLACEHOLDER**, every number an ESTIMATE | Luca |
| Crew profiles and schedules | `scenarios/crew.yaml` | **PLACEHOLDER** | Luca |
| Faults | `scenarios/faults.yaml` | **PLACEHOLDER** examples | Mario / Luca |

### Replacing the layout / sensors without throwing work away
* `layout:` in a scenario takes one file or a list; they are merged. Modules, sensors and actuators are separate files.
* Sensors are **rules** (`sensor_sets`): "metrics X on all modules" is one entry, so 30 or 120 sensors cost the same.
* Actuators read sensors by id (`params.sensor`): when the sensor set changes, update those ids.
* A new component is any importable class, referenced as `package.module:Class`; no registration needed.

Every physical constant needs a source tag (`[S1]..[S20]`, see `docs/reference/ambientmonitor/verifica-dati.md`) or the
word ESTIMATE.

## Monitoring: three states, ML recognition, crew procedures

The station has a monitoring system that is ISS-like (never Mars): detectors -> classifier -> playbooks (the safing of the machine) and
**procedures** (the checklist for the crew). The whole system is always in one of three modes, `passive` / `alert` / `reaction`
(`tick.monitor_mode`), and every emergency has the ISS alert class the UI colours by (`alert_class`). The rule detectors stay the safety
net; two ML stages sit next to them (`src/ares3/plugins/monitor/ml/`, plan and decisions in `piano.md`):

* **Stage A** - "is something abnormal?": one PCA per subsystem, trained on nominal days only, so it also sees faults nobody has catalogued.
* **Stage B** - "which fault, where, how sure, why?": one classifier per family of faults (physical / actuator / sensor / medical),
  trained on the 26-fault catalog of Mario's workbook with parameters drawn from its ranges, plus Luca's medical events on the station crew.

```
uv run python tools/ml/make_dataset.py --nominal --randomize --medical --combos --seeds 1-3,5 --days 2 --features --out output/ml/feat
uv run python tools/ml/train_anomaly.py        # -> models/station_v1/detector_*.joblib
uv run python tools/ml/train_diagnoser.py      # -> models/station_v1/diagnoser.joblib
uv run python tools/ml/check_monitor.py --nominal --seeds 5 --days 1    # the real monitor on whole runs: false alarms, delays
```

Both stages read the SENSED values only, through the same feature extractor online and offline. Everything the ML measures is
simulation time on synthetic data (the noise of many sensors is an ESTIMATE): not flight performance. The UI contract (what to draw, the
`ack_step` command) is `docs/monitor-ui.md`; sources are `docs/reference/monitoring-ml-sources.md`. `joblib` runs code when it
loads a file: load only the models of `models/`.

## Dashboard (`dashboard/`)
React + Vite, independent of the Python engine (`cd dashboard && pnpm install && pnpm dev`). Contains the
`<BodyHologram />` component (organs coloured and pulsing from vital signs). `dashboard/src/telemetry/` holds the
TypeScript mirror of the engine's `SimulationTick` and two interfaces, `VitalsSource` (where ticks come from) and
`VitalsAdapter` (engine signals -> organs); neither is implemented yet. The thresholds in
`components/BodyHologram/vitals.ts` are generic resting-adult values: the engine should send them already computed.

**License note:** `dashboard/src/data/anatomy.json` is derived from gganatogram (GPL-2); see
`dashboard/THIRD_PARTY_NOTICES.md` and `dashboard/LICENSE`.
