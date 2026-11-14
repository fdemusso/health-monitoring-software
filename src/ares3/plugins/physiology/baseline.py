"""PLACEHOLDER - awaiting review by Luca (bioengineer). Baseline physiology model so the pipeline runs end to end.

EVERY number in ``BaselineParams`` is an unvalidated ESTIMATE. It is meant to be replaced or tuned by
the bioengineer (copy this file, change the params block in ``crew.yaml``, or subclass
``PhysiologyModel``). The structure is what matters:

    target(vital) = resting value + effort term (MET) + environment term (PIO2, ppCO2) + circadian term
    vital         = first-order lag towards the target + medical-fault deltas (not lagged)
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from ares3.sdk import ModuleState, NPCState, PhysiologyModel, StepContext, VitalsUpdate, register

_VITALS = ("hr", "spo2", "resp_rate")


class BaselineParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- resting values (ESTIMATE) ---
    hr_rest: float = 65.0
    hr_max: float = 185.0
    met_max: float = 10.0  # MET at which hr reaches hr_max
    spo2_rest: float = 98.0
    rr_rest: float = 14.0
    rr_per_met: float = 1.5
    hrv_rest: float = 45.0  # RMSSD, ms
    hrv_circadian_amp: float = 0.10
    hrv_circadian_peak_h: float = 3.0
    skin_temp_rest: float = 33.5
    skin_temp_per_met: float = 0.05
    # --- environment sensitivity (ESTIMATE) ---
    pio2_ref_mmhg: float = 127.0  # below this, hypoxia terms switch on [S20: mild hypoxia limit]
    spo2_per_mmhg_pio2: float = 0.15
    hr_per_mmhg_pio2: float = 0.5
    ppco2_ref_mmhg: float = 2.0
    rr_per_mmhg_co2: float = 1.5
    hr_per_mmhg_co2: float = 1.0
    # --- dynamics (ESTIMATE) ---
    tau_hr_s: float = 40.0
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
        hr = p.hr_rest + (p.hr_max - p.hr_rest) * effort + p.hr_per_mmhg_pio2 * d_pio2 + p.hr_per_mmhg_co2 * d_co2
        spo2 = p.spo2_rest - p.spo2_per_mmhg_pio2 * d_pio2
        rr = p.rr_rest + p.rr_per_met * (npc.met - 1.0) + p.rr_per_mmhg_co2 * d_co2
        return {"hr": hr, "spo2": min(100.0, max(50.0, spo2)), "resp_rate": rr}

    def _derived(self, vitals: dict[str, float], npc: NPCState, env: ModuleState, tod_h: float) -> dict[str, float]:
        p = self.params
        circ = 1.0 + p.hrv_circadian_amp * math.cos(2 * math.pi * (tod_h - p.hrv_circadian_peak_h) / 24.0)
        hrv = p.hrv_rest * (p.hr_rest / max(vitals["hr"], 1.0)) ** 1.5 * circ
        skin = p.skin_temp_rest + p.skin_temp_per_met * (npc.met - 1.0) + 0.03 * (env.temperature_c - 22.0)
        return {"hrv_rmssd": hrv, "skin_temp_c": skin}

    def initial_vitals(self, npc: NPCState, env: ModuleState) -> VitalsUpdate:
        latent = self._targets(npc, env, 0.0)
        vitals = {**latent, **self._derived(latent, npc, env, 0.0)}
        return VitalsUpdate(vitals=vitals, latent=latent)

    def step(self, dt: float, npc: NPCState, env: ModuleState, ctx: StepContext) -> VitalsUpdate:
        p = self.params
        targets = self._targets(npc, env, ctx.tick.time_of_day_h)
        taus = {"hr": p.tau_hr_s, "spo2": p.tau_spo2_s, "resp_rate": p.tau_rr_s}
        latent = {
            k: npc.latent.get(k, targets[k]) + (targets[k] - npc.latent.get(k, targets[k])) * (1.0 - math.exp(-dt / taus[k]))
            for k in _VITALS
        }
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
