# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ARES 3 (NASA Space Apps 2026): a deterministic tick-based simulator of a crewed habitat (4 astronauts) that exports labelled multivariate time series (environment + vital signs, with fault ground truth) for an ML alert model, plus a React dashboard. Team: 2 software engineers (core/SDK/export), a bioengineer (Luca: vital signs, physiology) and a physicist (Mario: sensors, actuators, environment physics). The user writes in Italian; `docs/USO-DOCKER.md` and the GitHub issues are in Italian.

## Commands

```
uv sync --extra dev                                   # install (Python >= 3.11)
uv run pytest -q                                      # tests, ~12 s
uv run pytest tests/test_engine.py::test_closed_system_conserves_every_species
uv run ruff check src tests
uv run ares3 validate scenarios/emergency.yaml        # loads scenario + builds every plugin, no run
uv run ares3 run scenarios/emergency.yaml --days 2 -o output/run1   # also --ticks N, --forever
docker compose run --rm ares3 run scenarios/nominal.yaml --days 1  # same CLI in Docker (scenarios/, src/, output/ are bind-mounted: no rebuild after edits)
uv run python tools/npc_report.py [--reuse]            # report for the bioengineer: HTML (figures as PNG) -> PDF via headless Chrome/Edge; normal day per NPC + 11 events (~10 min, needs --extra report)
cd dashboard && pnpm install && pnpm dev              # frontend, fully independent of the Python side
```

~1,900x real time (2 Mars sols in ~95 s). There is no build step for the engine.

## Architecture

**Package layering is enforced by `tests/test_architecture.py` (`LAYERS`)**: `schemas` imports nothing; `sdk` -> `schemas`; `core` and `plugins` -> `schemas`, `sdk`; `export` -> `core`. The only cross-imports below `core` are the leaves `core.constants/rng/clock`. A new package must be added to `LAYERS`. Plugin authors (Mario, Luca) must be able to work against `sdk` alone and never edit `core/`.

**One tick** (`core/engine.py`, phases are documented in the module docstring and order matters): faults active -> NPC schedule/MET -> crew exchange and physical faults applied to the world -> actuators (use the previous tick's snapshot, sensed readings and the agent's commands from the previous tick) -> world physics (hatch diffusion, heat, condensation) -> snapshot -> physiology -> sensors + sensor faults -> alarms, agent decides. The agent's commands take effect one tick later to avoid circular dependencies.

**Truth vs. measurement is a core rule.** `ModuleState`/`NPCState.vitals` are ground truth. Sensors return an `Observation` with `value` (noisy, lagged, fault-corrupted) and `value_true`; controllers and the agent read `ctx.reading(sensor_id)`, never the true state. Alarm rules evaluate the true state. Sensor faults (bias/drift/stuck/dropout/noise) are applied by the engine on top of the sensor's output; a sensor must model only the healthy device.

**Plugins return effects, they never mutate the world.** `BaseSensor.step -> Observation`, `BaseActuator.step -> list[ModuleFlow]` (rates in mol/s and W, so dt-independent), `PhysiologyModel.step -> VitalsUpdate`. The core applies them and books every mole in `World.ledger`; `tests/test_engine.py` checks conservation of O2/CO2/N2/H2O in a closed system.

**Everything is configured in YAML (`scenarios/`), validated by Pydantic (`schemas/`).** A plugin is referenced as `package.module:Class` (importable, no registration). A scenario file = environment profile + layout + crew + faults + seed. Details that are not obvious from one file:
- `layout:` can be a list of files, merged in order (modules/sensors/actuators are separate files). Sensors can be written as `sensor_sets` rules (expanded in `load_scenario`), so 30 or 120 sensors cost the same; default id is `{target}_{metric}` (case-sensitive: `hab_ppCO2`). Actuators and faults reference sensors **by id**, so changing the sensor set requires updating them.
- The environment (Mars / orbit) is a swappable profile (`scenarios/environments/`): gravity, `day_length_s`, atmosphere, exterior temperature and the alarm rules (NASA-STD-3001). Actuator setpoints left unset default to the environment's nominal values. Module microclimates (`atmosphere:` in a module) are partial overrides, never absolute values. `environment_overrides` in a scenario deep-merges over the profile.
- Time of day comes from `SimClock` using the profile's day length (a Mars sol is 88775.244 s); schedules are in local hours 0-24.
- Determinism: one root `seed`; every component gets `core/rng.derive(seed, kind, id)`, so adding a sensor does not change other components' random streams.
- Anomaly labels (`core/faults.py::label_row`, `Engine._row`): a row is anomalous when a fault targets the sensor, the thing measured, its module, or an actuator of that module. It means "fault active", not "effect visible". Highest `priority` wins `anomaly_type`; all ids go to `anomaly_ids`; non-anomalous rows are `nominal`.
- Export (`export/writers.py`) writes one Parquet/CSV part per simulated `chunk_hours` (long and wide), so unbounded runs use bounded memory.

## Conventions and gotchas

- Many files are marked `PLACEHOLDER - awaiting review by Mario/Luca` (layout, sensors, actuators, physiology, crew, faults). They exist to make the pipeline run; do not present them as validated. Keep the replaceable-pieces design: don't hard-wire anything to the example layout (tests do depend on the `hab` and `lab` module ids).
- Every physical constant needs a source tag (`[S1]..[S20]`, see `docs/reference/ambientmonitor/verifica-dati.md`) or the word ESTIMATE. `docs/reference/ambientmonitor/` documents the author's earlier JS simulator that the metabolism table, alarm limits and sensor noise defaults were ported from; don't reintroduce its 2.5D CFD (too slow, and ruled out by design).
- NPCs: the 4 members of `scenarios/crew.yaml` ARE Luca's ASTRO_01..04 (`alias`; mapping cmd/bot/eng/med is our proposal, to confirm). Physiology is `HumanModel` (`plugins/physiology/human.py`, on top of `ProfileModel` -> `BaselineModel`; sources [P1]-[P22] in `docs/reference/physiology-sources.md`; unsourced numbers say ESTIMATE). It keeps a health state (0 ok .. 3 unconscious, 4 dead; death is optional: `death_enabled`, set per scenario with `physiology_overrides:`) driven by a dose of hypoxia/CO2/heat, per-person parameters from sex/age/mass (`age_y`, `height_cm` in `crew.yaml`, our estimates), circadian rhythm and sleep stages, core temperature, hydration, microgravity adaptation and a beat-to-beat RR series. The vital `gas_scale` (0 dead, resting if unconscious) is read by the engine to scale the NPC's gas exchange. Reactive NPC behaviour is out of scope (the project monitors health). Event scenarios and the report's nominal day (`scenarios/events/day_nominal.yaml`) run in Luca's STATION atmosphere (orbital_station profile, 758 mmHg, 21 % O2): all his notebooks assume sea-level/ISS air; `nominal.yaml` and `events/day_mars.yaml` stay on Mars for comparison. The launch phase from Earth that Luca's notebooks consider is NOT simulated. The EVA volume uses 42 % O2 (our assumption, Luca's 28 % gives PIO2 85 mmHg). Event scenarios live in `scenarios/events/` (faults of category `medical` carry the episode params). A module with `alarm_mode: occupied` (the `eva` volume) only alarms while someone is inside.
- YAML 1.1 reads a bare `on:` key as boolean `true`; avoid `on`, `yes`, `no` as keys.
- Units: SI except partial pressures in kPa, ppCO2 and PIO2 in mmHg, temperatures in degC. The NASA oxygen limits are on PIO2 (not cabin pO2).
- `dashboard/` is a standalone Vite/React app. `dashboard/src/telemetry/types.ts` mirrors `sdk/types.py` by hand (Python is the source of truth); `VitalsAdapter`/`VitalsSource` are interfaces only. `dashboard/src/data/anatomy.json` is GPL-2 derived (gganatogram); keep `dashboard/LICENSE` and `THIRD_PARTY_NOTICES.md` with it.
- Git: commit messages and PR descriptions carry no attribution lines (`.claude/settings.json` disables them). Open issues for Mario are on GitHub (#1-#6).
