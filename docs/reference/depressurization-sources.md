# Depressurization sources (air leaks, reserve time, isolation)

Tags used in the code (`plugins/monitor/detectors.py::PressureDrop`, `scenarios/monitor_placeholder.yaml`,
`schemas/monitor.py::CrewResponseConfig`). Anything without a tag is `ESTIMATE`.
Added by the software team. Stays in ISS terms (never Mars).

| Tag | Source | What we use from it |
|---|---|---|
| `[ICES-2025-126]` | NASA, *ECLSS emergency operations* (ICES 2025, paper 126, Rev A), https://ntrs.nasa.gov/citations/20250003954 | three leak levels, the TRes formula, Pminimum, the 10-minute threshold, vehicle and crew response |
| `[ISS-2020-PrK]` | account of the leak in the intermediate chamber of the Zvezda module, October 2020 (press: -52 mmHg in 11.5 h, then 7-9 mmHg/h) | order of magnitude of a real slow leak |

## Leak levels (ISS)

From the paper `[ICES-2025-126]`:

| Level | Rate | In the code |
|---|---|---|
| rapid depressurization | >= 0.87 mmHg/min | `leak_rapid` (critical) |
| fast leak | 0.4 - 0.87 mmHg/min | `leak_fast` (warning) |
| slow leak | < 0.4 mmHg/min (minimum detectable on board: 2 mmHg/day) | `leak_slow`, `leak_trend` (warning) |

`leak_breach` (>= 8 mmHg/min over 30 s) is not an ISS level: it exists to see big breaches at once, because a long window
underestimates the rate of a leak that has just started and therefore the TRes.

**Why the window changes with the threshold.** The pressure sensor has 0.05 kPa of noise (a default ported from the earlier
simulator, Mario's). Measured over 24 nominal hours of the station, the 60 s slope swings by +-1 mmHg/min, the 300 s one by
+-0.26, the 30 min one by +-0.11, the 1 h one by +-0.06: the ISS threshold of 0.87 can only be used from 300 s up. The chosen windows
(30 s, 300 s, 30 min, 2 h, 6 h) keep at least a 3x margin; 2 simulated days with no leaks did not trigger any
detector. If Mario changes the sensor noise the thresholds must be re-checked (`tests/test_depressurization.py`).

`leak_slow` (0.1 mmHg/min, ~6 mmHg/h) and `leak_trend` (0.03 mmHg/min, ~2 mmHg/h) are `ESTIMATE`: the paper gives no
alarm threshold for slow leaks (ground trending sees them); 6 mmHg/h is the order of `[ISS-2020-PrK]`.

## Reserve time (TRes)

`TRes = P * ln(490 mmHg / P) / (dP/dt)` (minutes, P in mmHg, dP/dt in mmHg/min, negative) `[ICES-2025-126]`. It is the exact solution
for a leak proportional to pressure, i.e. the orifice flow the engine models
(`Engine`, fault `leak`: `rate_per_s * moles`). The code used to use the linear formula `(P - Pmin) / |dP/dt|`, which underestimates.

- Pminimum = 490 mmHg (9.5 psia = 65.3 kPa): below it, critical equipment stops working and the risk
  of hypoxia grows (`pressure_minimum`, critical).
- At TRes <= 10 minutes the crew stops looking for the leak and retreats into the return vehicle, closing the hatches
  (`evacuate_tres_s: 600`; it used to be 120 s, which was not ISS).
- A "low" pressure level (96.5 kPa, the lower limit of the ISS cabin, 14.0 psia) was tried and removed: with the make-up gas
  turned off by the playbook there is no way to climb back and the emergency would never close.

## Response

Vehicle `[ICES-2025-126]`: automatically isolates the modules, closes the valves to the outside, **turns the fans off**
(to hear the leak), **stops gas introduction** (to measure the rate). This is the `critical` playbook.
For a slow leak (`warning` playbook) the make-up gas stays on and no group alarm is raised: the crew
does a *leak check*, closing the hatches one at a time.

Crew `[ICES-2025-126]`:
- no hatch closed between a person and their return vehicle (guard `Engine._guard`);
- "retreat to a known safe location and close the appropriate hatch(es)": once the crew is aboard, the vehicle is
  sealed (`seal_vehicle`, event `crew_sealed`), so it keeps its own air while the station loses its own;
- the vehicle hatch stays closed in normal operations and opens only while someone goes through it.

Not modelled: the PBA mask (7 minutes of oxygen), the fact that a hatch closed under a large pressure difference
is hard to reopen, locating the leak with the HDI (here the leak check is enough).

## ESTIMATE (to review with Mario)

- `repair_leak_s: 1800` (time to find and plug a leak that is not yet an emergency): the real Zvezda leaks
  took days and not every repair held. A `leak` fault with `repairable: false` is not repaired.
- The `leak_slow` and `leak_trend` thresholds (above) and `leak_breach`.
- A leak in a module joined by an open hatch spreads to the others by diffusion: the engine already does this; the
  monitor can therefore open an "echo" emergency in the neighbouring modules too, until the hatch is closed.
