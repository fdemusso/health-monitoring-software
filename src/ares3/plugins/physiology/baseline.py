"""PLACEHOLDER - awaiting review by Luca (bioengineer). Baseline physiology model, literature-based where a source exists.

Every number carries a source tag [P1..P7] or the word ESTIMATE (list with URLs: docs/reference/physiology-sources.md).
It is meant to be replaced or tuned by the bioengineer (copy this file, change the params block in
``crew.yaml``, or subclass ``PhysiologyModel``). The structure is what matters:

    target(vital) = resting value (x sleep factor) + effort term (MET) + environment term (PIO2, ppCO2)
    vital         = first-order lag towards the target (hr: faster up than down) + medical-fault deltas

Not modelled: loss of consciousness (time of useful consciousness), beat-to-beat arrhythmia, exercise
desaturation, circadian drift of hr.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from ares3.sdk import ModuleState, NPCState, PhysiologyModel, StepContext, VitalsUpdate, register

_VITALS = ("hr", "spo2", "resp_rate")

# Steady-state SpO2 (%) against inspired PO2 (mmHg). 70-99 mmHg: midpoints of the ranges in Table 2 of
# "Hypoxic Hypoxia and Brain Function in Military Aviation" [P1]; below 70 mmHg the source only gives upper
# bounds, the rest of the curve is ESTIMATE. 127 / 149 mmHg: ESTIMATE (mild hypoxia limit / sea level).
SPO2_VS_PIO2 = ((0.0, 10.0), (16.0, 30.0), (28.0, 45.0), (49.0, 55.0), (57.0, 60.0), (70.0, 65.0),
                (80.0, 77.5), (99.0, 90.0), (127.0, 96.0), (149.0, 98.0))


def spo2_from_pio2(pio2_mmhg: float) -> float:
    pts = SPO2_VS_PIO2
    if pio2_mmhg <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if pio2_mmhg <= x1:
            return y0 + (y1 - y0) * (pio2_mmhg - x0) / (x1 - x0)
    return pts[-1][1]


class BaselineParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- resting values (ESTIMATE) ---
    hr_rest: float = 65.0
    hr_max: float = 185.0  # ESTIMATE; a cosmonaut study reports a 180 bpm in-flight exercise cap (not verified)
    met_max: float = 10.0  # MET at which hr reaches hr_max; HR reserve and VO2 reserve are linear [P3]
    hr_sleep_factor: float = 0.80  # sleeping hr = rest x factor; 20-30 % lower [P4]
    spo2_rest: float = 98.0  # healthy 95/96-100 % [P5]
    rr_rest: float = 14.0  # adult 12-20 /min [P5]
    rr_sleep: float = 12.0  # ESTIMATE
    rr_per_met: float = 1.5
    hrv_rest: float = 45.0  # RMSSD, ms
    hrv_circadian_amp: float = 0.10
    hrv_circadian_peak_h: float = 3.0
    skin_temp_rest: float = 33.5
    skin_temp_per_met: float = 0.05
    skin_temp_sleep_delta: float = 0.6  # wrist skin temperature rises in sleep [P6]; magnitude ESTIMATE
    # --- environment sensitivity (ESTIMATE) ---
    pio2_ref_mmhg: float = 127.0  # below this, hypoxia terms switch on [S20: mild hypoxia limit]
    hr_per_mmhg_pio2: float = 0.5  # ESTIMATE
    hr_hypoxia_cap: float = 40.0  # ESTIMATE: tachycardia saturates; no bradycardia / syncope modelled
    ppco2_ref_mmhg: float = 2.0
    rr_per_mmhg_co2: float = 1.5
    hr_per_mmhg_co2: float = 1.0
    # --- dynamics (ESTIMATE) ---
    tau_hr_s: float = 40.0  # onset, ESTIMATE
    tau_hr_down_s: float = 65.0  # recovery: single-exponential tau 65.5 +/- 12 s after maximal exercise [P7]
    tau_spo2_s: float = 15.0
    tau_rr_s: float = 20.0


@register("baseline_physiology")
class BaselineModel(PhysiologyModel):
    Params = BaselineParams

    # ---- model --------------------------------------------------------------------------------
    def _targets(self, npc: NPCState, env: ModuleState, tod_h: float) -> dict[str, float]:
        p = self.params
        effort = min(1.0, max(0.0, (npc.met - 1.0) / (p.met_max - 1.0)))
        d_pio2 = max(0.0, p.pio2_ref_mmhg - env.pio2_mmhg)
        d_co2 = max(0.0, env.ppco2_mmhg - p.ppco2_ref_mmhg)
        sleeping = npc.activity == "sleep"
        hr_base = p.hr_rest * (p.hr_sleep_factor if sleeping else 1.0)
        hr = (hr_base + (p.hr_max - p.hr_rest) * effort + min(p.hr_hypoxia_cap, p.hr_per_mmhg_pio2 * d_pio2)
              + p.hr_per_mmhg_co2 * d_co2)
        spo2 = min(p.spo2_rest, spo2_from_pio2(env.pio2_mmhg))
        rr = (p.rr_sleep if sleeping else p.rr_rest) + p.rr_per_met * (npc.met - 1.0) + p.rr_per_mmhg_co2 * d_co2
        return {"hr": hr, "spo2": min(100.0, max(0.0, spo2)), "resp_rate": rr}

    def _derived(self, vitals: dict[str, float], npc: NPCState, env: ModuleState, tod_h: float) -> dict[str, float]:
        p = self.params
        circ = 1.0 + p.hrv_circadian_amp * math.cos(2 * math.pi * (tod_h - p.hrv_circadian_peak_h) / 24.0)
        hrv = p.hrv_rest * (p.hr_rest / max(vitals["hr"], 1.0)) ** 1.5 * circ
        skin = p.skin_temp_rest + p.skin_temp_per_met * (npc.met - 1.0) + 0.03 * (env.temperature_c - 22.0)
        if npc.activity == "sleep":
            skin += p.skin_temp_sleep_delta
        return {"hrv_rmssd": hrv, "skin_temp_c": skin}

    def initial_vitals(self, npc: NPCState, env: ModuleState) -> VitalsUpdate:
        latent = self._targets(npc, env, 0.0)
        vitals = {**latent, **self._derived(latent, npc, env, 0.0)}
        return VitalsUpdate(vitals=vitals, latent=latent)

    def step(self, dt: float, npc: NPCState, env: ModuleState, ctx: StepContext) -> VitalsUpdate:
        p = self.params
        targets = self._targets(npc, env, ctx.tick.time_of_day_h)
        taus = {"hr": p.tau_hr_s, "spo2": p.tau_spo2_s, "resp_rate": p.tau_rr_s}
        latent = {}
        for k in _VITALS:
            cur = npc.latent.get(k, targets[k])
            tau = p.tau_hr_down_s if k == "hr" and targets[k] < cur else taus[k]
            latent[k] = cur + (targets[k] - cur) * (1.0 - math.exp(-dt / tau))
        vitals = {**latent, **self._derived(latent, npc, env, ctx.tick.time_of_day_h)}
        for f in ctx.faults_for(npc.id):
            if f.type != "medical":
                continue
            ramp = float(f.params.get("ramp_s", 0.0))
            k = 1.0 if ramp <= 0 else min(1.0, max(0.0, (ctx.tick.t_sim_s - f.start_s) / ramp))
            vitals["hr"] += k * float(f.params.get("hr_delta", 0.0))
            vitals["spo2"] = min(100.0, vitals["spo2"] + k * float(f.params.get("spo2_delta", 0.0)))
            vitals["resp_rate"] += k * float(f.params.get("resp_delta", 0.0))
            vitals["skin_temp_c"] += k * float(f.params.get("skin_temp_delta", 0.0))
            vitals["hrv_rmssd"] *= 1.0 + k * (float(f.params.get("hrv_factor", 1.0)) - 1.0)
        return VitalsUpdate(vitals=vitals, latent=latent)
