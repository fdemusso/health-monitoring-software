# Monitor: contract for the UI

The UI has no threshold logic: everything arrives already computed in the `SimulationTick` (`src/ares3/sdk/types.py` is the source of
truth; the hand-kept mirror is `dashboard/src/telemetry/types.ts`).

## System states (`tick.monitor_mode`)

| Value | When | Suggested banner |
|---|---|---|
| `passive` | no emergency open | green, no interruption |
| `alert` | at least one `suspected` emergency, or a `confirmed` one of class `caution`/`advisory` without a playbook | yellow |
| `reaction` | at least one `confirmed` emergency of class `emergency`/`warning`, or with a playbook running | red (emergency) or orange (warning) |

The mode is the maximum over the open emergencies. It rises at once and falls only after `classifier.mode_hold_s` (60 s) without the
highest level, so it does not flicker. Every change is a `MonitorEvent` with `kind: "mode_changed"` (`"monitoring: alert -> reaction"`).

## Alert class (`Emergency.alert_class`)

`emergency` red, `warning` orange, `caution` yellow, `advisory` blue. It comes from `classifier.classes` in the monitor's YAML
(keys `kind:severity:cause`, `kind:severity` or `kind`; with no entry: critical -> `emergency`, warning -> `warning`).
ISS levels: NASA, *CLD HSI Workshop - Alerts* (plan §11 [R1]).

## Explanation (`Emergency.evidence`, `tick.ml`)

`Emergency.evidence` is a list of sentences for the crew: for ML anomalies they are the 3 largest contributions to the decision
("usl_ppCO2_a: slope over 6 h (+4.1 sigma)"), for the other detectors it is empty (there is `detail`). Show it on the problem card,
under the title. `tick.ml` is the score of every ML detector above its floor (`ml_atmosphere_co2: 0.3`; >= 1 is an anomaly):
useful for a per-subsystem indicator, not needed for the alert logic.

## New emergency types

* `anomaly`: "something anomalous in the subsystem, cause unknown" (stage A, class `caution`); `module_id` is the module of the
  sensor that explains the most, or `station` if it is an actuator telemetry channel.
* `sensor_fault`: a sensor must not be believed. `subject` is the id of the SENSOR (or `a~b` if the redundant pair does not say which of the two).

## Procedures (`tick.procedures`) and the `ack_step` command

A procedure is the checklist for the people of a confirmed emergency; it starts by itself, the playbook remains the safing of the
machine. Every `ProcedureState` has the title, the status (`running | done | escalated | closed`), the active step (`current`) and
the list of steps with their status (`pending | active | done | failed | skipped`, `by`, `answer`, `deadline_s`). Step types:

| `kind` | The UI shows | Who closes it |
|---|---|---|
| `instruction` | text + "done" button | `ack_step` command, or an NPC of the role after a few seconds |
| `question` | text + yes / no | `ack_step` with `answer: "yes" \| "no"`, or an NPC (default answer) |
| `check` | "check in progress" with a countdown (`deadline_s`) | the system, on the measured values |
| `action` | like a `pending_action` (there too is the step to approve) | the system, when the action is executed or discarded |
| `escalate` | red notice: "call the flight surgeon / evacuate" | the procedure ends as `escalated` |

WebSocket command: `{"type": "command", "cmd": "ack_step", "args": {"procedure_id": "...", "step_id": "...", "by": "...", "answer": "yes"}}`
(`answer` only for questions). Anyone can close a step: the monitor is open to everyone. A crew action (`ack_step`)
on a step that is not active answers `ok: false`.

New events in `monitor_events`: `procedure_started`, `step_done`, `step_failed`, `procedure_done`, `procedure_escalated`.

The right procedure for an emergency that is still only `suspected` (no procedure is running) is proposed by the UI from the CATALOG: `hello.procedures`
(`id, emergency, cause, severity, title, steps[{id, kind, text, role}]`, static, with `{subject}` and `{module}` still in the texts). The
choice replicates `ProcedureRunner._choose` (type, then cause, then severity; the one naming the cause beats the generic one):
`dashboard/src/domain/procedures.ts`. As soon as the emergency is confirmed the backend starts the real procedure (`tick.procedures`) and the UI
switches to the live checklist.

## Medical procedures and notice

Contract for the UI (document only: no new field in `sdk/types.py`, no change to `dashboard/`). The clinical content is in
`docs/procedure-mediche.md`.

**Tick fields that are needed.** From the emergency (`tick.emergencies`, `kind == "medical"`): `subject` (the person), `module_id` (where
they are), `cause` (which problem; it picks the procedure), `evidence` (the values that triggered the alarm), `alert_class`
(the colour), `severity`. From the procedure (`tick.procedures`, linked by `emergency_id`): `title`, `status`, `current`, `steps[]`
(`kind`, `text`, `status`, `by`, `answer`, `deadline_s`), `t_start_s`, `t_end_s`. The same `cause` may have no dedicated
procedure (then there is `med_generic`): the UI must not assume that the title says the cause, `Emergency.cause` does.

**Step states and transitions.** `pending` -> `active` (only one at a time, `current`) -> `done` | `failed`; steps never reached
end up `skipped`. A `check` that does not pass within `deadline_s` becomes `failed` and the procedure jumps to the failure branch
(almost always an `escalate` step). An `escalate` step is the last: it becomes `done` and the procedure `escalated`. The procedure
goes `running` -> `done` (all branches reached the end), `escalated` (reached an `escalate` step), `closed` (the emergency ended
first: the open steps become `skipped`). It stays in the tick for 300 s after the end, with the outcome.

**Fixed notice, to show in every medical procedure** (at the top, always visible, not dismissible):

> Simulation checklist, NOT medical advice. The steps are reconstructed from public sources and have not been reviewed by a flight
> surgeon. In a real emergency follow the ISS Medical Checklist and the instructions of the flight surgeon.

**Display order.** 1) fixed notice; 2) title with the person and the module, `alert_class` as the colour, `evidence`
below (why the monitor opened the alarm); 3) the steps in list order, the `active` one highlighted with its button
("done", yes / no) or the `check` countdown; `skipped` steps dimmed; 4) if two medical procedures are open
(two people), the more serious first (`severity` then `alert_class`) and the other in a list.

**When a procedure goes `escalated`** the crew must see, in place of the checklist, a red box with the text of the
`escalate` step (e.g. "call the flight surgeon"), the list of steps already done and those that did not work (`failed`) to
report them to the ground, and the person's current values. Evacuation or the call to the ground are decided by people: the system does not do them.
The procedure does not reopen by itself; if the emergency flares up again, a new one starts.

## Power and substitute sensors

* `Action.kind = "power"` (`command: off | on`, `target` = module): cut the power to a module (the ISS response to smoke). When it is
  active, `tick.powered_off` lists the modules. For vital modules (USL, NOD3) it is a `confirm` step with a countdown and
  `on_timeout: execute`; the restoration is only PROPOSED (`pending_actions`, `power on`) when the emergency ends, and runs on timeout if nobody answers.
  The lifeboat and the EVA volume cannot be switched off (the action is blocked).
* `Action.kind = "sensor"` (`command: substitute`, `target` = faulty sensor, `value_id` = substitute): from then on the control loops
  (CDRA, OGA...) read the substitute. `confirm` step with `on_timeout: discard`; it cancels itself when the emergency is closed.

## History for the charts (`history`) and backend start

Right after `hello` the backend sends ONCE `{"type": "history", "samples": [{"t_sim_s", "npcs", "modules"}, ...]}`: the last 6 simulated
hours, one sample per minute (same `npcs` and `modules` as a tick). The UI fills the charts with it at once instead of starting empty (it used to
build them itself, one point per SIMULATED minute from the moment of connection: at 10x one point every 6 real s, at 1x one every minute).
If the history is empty the message is not sent. A `reset` starts from zero and empties the history.

The crew's vital signs have a finer history: `"vitals": [{"t_sim_s", "w": {crew: {hr, spo2, resp_rate, core_temp_c, cohb_pct}}}, ...]`,
one point every 10 simulated s (2160 points = 6 h). They are the WEARABLE readings (measured: sensor noise and faults included, as the
monitor sees them), not the model's truth; `samples` (one point per minute) stays for modules and truth. Every `tick` also carries `"wearables"` (last
reading per person and metric): the UI draws them in the vital-signs chart. The time axis is on-board time (`time_of_day_h`).

`ares3 serve --vital-variability K` (default 0.3) adds to the physiology model (HumanModel, `variability`) a small short-term
wobble on hr / spo2 / resp_rate, because a real adult does not have a ruler-straight line (K=1: hr ±2.5 bpm, spo2 ±0.4 %, resp ±1/min). 0 = the earlier
smooth model (datasets and ML stay identical: the engine default is 0). With K >= 0.5 the `crew_baseline` ML (`models/station_v2`, trained on
smooth vitals) flags everyone: to use K=1 it must be retrained with data generated with the same variability.

`ares3 serve ... --warmup-h 4` advances the simulation by 4 hours (about a real minute) before going live: the ML detectors need
3 simulated hours of history before judging, and the charts' history starts already full. The port opens IMMEDIATELY (after
scenario and models load, a few seconds): during the warm-up the server is in the `warming` state.

- `hello` carries `"state": "warming" | "live"`.
- While `warming`, about 4 times a second `{"type": "warming", "progress": 0..1, "sim_s", "total_s"}` arrives (also right after
  `hello` for whoever connects midway); NO `tick` or `history` arrives, and every command is rejected (`ok: false`, "warming up").
- At the end of the warm-up: `history` to ALL clients, then `{"type": "ready"}`, then the ticks. A `hello` with `state: "live"` counts as `ready`.

The UI (`dashboard/src/app/WarmupScreen.tsx`, `warming` state in `telemetry/store.ts`) shows a loading screen with
percentage and estimated time, and dissolves on `ready`; the app underneath is `inert` meanwhile.

An "out of range" warning in the UI about an astronaut who is working (e.g. 126 bpm at 7 MET) does not come from the backend: the monitor judges it with
the `EarlyWarningScore`, which does not score HR and respiratory rate during and 30 min after exertion. The UI should use
`tick.emergencies` / `tick.monitor_mode` for its warnings.

## Still to do

The classification (stage B) will give `Emergency.cause` the diagnosis (which fault) with its probability; the `crew` type (orders to an
NPC, e.g. moving a person) does not exist yet: today moving is an `instruction` step. This note will be updated when they land.
