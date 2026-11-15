# The official station (Mario's ISS model)

`scenarios/station/` is the station the project runs on: 14 ISS volumes + our lifeboat (a Crew Dragon) and the EVA volume,
62 environmental sensors, 8 MCA channels, 26 actuator-telemetry channels, 23 ECLSS actuators and the catalog of 26 faults.
The workbook `notebooks/mario/ARES3_Stazione_Sensori.xlsx` (and the guide PDF next to it) is the source of truth for every
number it contains; `tools/build_station.py` translates it into YAML. **Edit the tool, never the generated files.**

```
uv run --with openpyxl python tools/build_station.py            # regenerate scenarios/station/*
uv run --with openpyxl python tools/build_station.py --check    # CI: fails when the files are stale (tests/test_station.py does it)
uv run ares3 run scenarios/station/nominal.yaml --days 1 -o output/station
uv run ares3 run scenarios/station/events/F-ATT-CQFAN-FOD.yaml --days 3 -o output/cqfan
```

## What is where

| File | Origin |
|---|---|
| `modules.yaml`, `sensors.yaml`, `sensor_groups.csv`, `actuators.yaml`, `faults/`, `events/` | generated from the workbook |
| `crew.yaml`, `monitor.yaml` | generated from `scenarios/crew.yaml` (Luca's schedules, moved onto the station) and `scenarios/monitor_placeholder.yaml` |
| `extras.yaml` | ours: lifeboat, EVA volume, smoke/CO sensors, wearables, the lifeboat and suit life support |
| `scenarios/environments/iss_station.yaml` | profile: ISS atmosphere, the orbit, Mario's alarm table (sheet 07) |
| `scenarios/*.yaml`, `scenarios/events/` (old) | the small test habitat (`hab`, `lab`, ...), kept as the fixture of the engine tests and of Luca's physiology report |

## What the engine learned for it (Mario's requests)

* **RC-4** gas moves by PRESSURE difference through every hatch (`gp_open`, `gp_closed`; exact exponential relaxation, so a 2 m3
  cabin is as stable as a 70 m3 node). This is what makes the PrK leak and its isolation possible.
* **RC-6** hatches have ids, can be commanded and can fail (`hatch_stuck`); the crew-quarters vents are not closable.
  `isolate:<module>` in a playbook closes every closable hatch of the module through the safety guard.
* **RC-7** the CCAA condenses water on a wall at the cold-loop temperature (`m = max(0, w_in - w_sat(wall)) m_air`) and keeps a counter.
* **RC-8** the CDRA removes `R0 eta (pp/2)^0.8`, in 144-minute half-cycles with a 60 s dead time at the swap: a sawtooth on ppCO2.
* **RC-9** alarm rules are means (1 h; the 7-day criterion is decimated to ~3600 samples).
* **RC-2/RC-3** `core/orbit.py`: 92.8 min orbit, eclipse from the beta angle, battery state of charge, the heat swing through the
  insulation. The cabin does NOT oscillate (the CCAAs absorb it): the orbit shows on the bus, the radiators and the TCS.
* **RC-1** was already there (CO and smoke are contaminants of a module).
* Also: per-module structural leak, rack heat, a lumped thermal-control loop (`Tcs`, the CCAAs read its temperature), actuator
  telemetry (`BaseActuator.telemetry`, sensors with `target: actuator:<id>`), the new fault types (see `schemas/faults.py`).

## Decisions and estimates that are OURS (to confirm with Mario)

* **Generation 140 kW, not 100.** With 61 % of the orbit in sun, 100 kW gives 61 kW on average: an 80 kW load drains the
  battery for good (the workbook only checks one eclipse). 140 kW recharges it in the 57 minutes of sun.
* **CDRA eta 0.85, not 0.80.** With 0.80 the nominal day of our crew (exercise sessions included) crosses the 3 mmHg 1-hour
  limit; 0.85 keeps a nominal day clean and a 60 % scrubber still settles at 4.4 mmHg (Mario: 4.77). One CDRA is active (CDRA-B in standby).
* Rack heat per module (`RACK_HEAT_W`), insulation leak 0.04 W/m2K, the unit-to-unit bias and calibration interval of each sensor
  technology, TCS base load 32 kW and its loop capacity: ESTIMATE, tagged in the tool.
* F-ATT-CCAA-IDROFOBO hits all six CCAAs (a single unit is compensated by the others and shows nothing); RH rises 31 -> 61 % in two days with the liquid-water flag on. F-FIS-PORTELLO is a 40 kPa/min crack in PrK with the SM-PRK hatch stuck open.
* Fault timescales are compressed: a drift quoted per MONTH runs per DAY (`TIME_COMPRESSION = 30`) so a 3-day run shows it.
* **Crew-quarters CO2 pocket**: `mixing_efficiency: 0.07` on the vents (only 7 % of the fan flow washes the face; CO2 only). Without it a cabin sits 0.07 mmHg above the node whatever its fan does, and F-ATT-CQFAN-FOD cannot exist. Measured: a healthy cabin peaks ~3.2 mmHg at night, one with its fan at 20-24 CFM ~4 (the catalog quotes 5-7: not reached; the fault is still distinguishable from the node by ~1 mmHg and by the day/night cycle). The cabins have `alarm_mode: never` (the catalog: no station alarm for this fault); only `cq*_ppCO2_a` sees it.
* The workbook has no return vehicle: `lifeboat` is a Crew Dragon (9.3 m3 pressurised, 4 seats) docked to Harmony.
* The 7-day ppCO2 criterion (2.5 mmHg) is a warning that a one-CDRA station sits close to; ppCO2 sensors saturate softly up to 22.8 mmHg.
* `ppH2O` on the MCA is descoped on the real ISS; kept because the workbook lists it.

## Not modelled (and why)

IMV flow is not telemetered continuously on the ISS (the workbook warns): `imv_usl_fwd_Q` is sampled once a day. The velocity
limit of the cabin air is not a quantity of a well-mixed volume (sheet 07, row "not implementable"). The temperature difference
between the two T sensors of a module under a fouled CCAA fan needs a spatial model: the fan fault shows on the actuator telemetry
and on the humidity instead. Radiation and acoustic noise (RC-1, priority C) are not in the core.

## Verified over days (dt = 10 s diagnostic runs) and known limits for the monitoring work

* CDRA at 60 %: ppCO2 2.4 -> 3.7 mmHg in 4 days, still converging to ~4.4 (time constant ~30 h); both USL and NOD3 sensors follow.
* OGA stack: V_stack 45 -> 51 V, O2 output 2.6 -> 1.75 slpm in 4 days. O2 cell ageing: `usl_ppO2_a` 20.6 -> 19.8 while the paramagnetic `_b` reads 21.1 -> 21.8 and the true pO2 climbs to 22.1 (the controller trusts the aged cell).
* F-FIS-PORTELLO end to end (40 kPa/min crack in PrK, SM-PRK stuck open): the monitor proposes `isolate:PRK`, executes it after the timeout, the stuck hatch does not move, so SM drains with PRK (24 kPa); the monitor then isolates SM from NOD1 (the rest stays at 100.8 kPa), the crew evacuates to the lifeboat and seals it. Also unit-tested (`test_stuck_hatch_ignores_commands`).
* The pressure-drop detectors fire in EVERY module the leak drains (the open hatches equalise them); `classifier.group_by: connected` fuses the signals of modules joined by open hatches into ONE emergency in the module whose pressure falls fastest (right for a rapid leak; for a slow leak with the hatches open the station is one volume and the gradient cannot be measured: stage B ranks the candidates, and the `leak check` step closes the hatch of the candidate, as on the ISS).
* Not confirmed with Mario yet: 140 kW generation, CDRA eta 0.85, the cabin CO2 pocket, rack heat, the lifeboat.
