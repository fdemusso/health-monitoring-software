"""PLACEHOLDER - awaiting review by Luca (bioengineer). Baseline model + optional pins + lagged medical episodes.

``hr`` / ``spo2`` (params, optional) PIN that vital to a fixed value and switch its environment coupling off;
leave them unset to use the literature-based baseline. Per-astronaut resting values go in the baseline
params (``hr_rest``, ``rr_rest``, ``hrv_rest`` ...).

``medical`` faults are applied here, not in the baseline: each effect ramps in over ``ramp_s`` and is then
passed through a first-order lag (``tau_fault_s``), so it also RELEASES smoothly when the fault ends.
Params: ``hr_delta`` / ``spo2_delta`` / ``resp_delta`` / ``skin_temp_delta`` (additive), ``hrv_factor``
(multiplicative on RMSSD), ``hr_to`` / ``spo2_to`` (absolute targets, pull the vital to that value).
HRV is recomputed from the final hr, so it follows the episode without a step.
"""

from __future__ import annotations

import dataclasses
import math

from ares3.sdk import ModuleState, NPCState, StepContext, VitalsUpdate, register

from .baseline import BaselineModel, BaselineParams

_KEYS = ("hr", "spo2", "resp_rate", "skin_temp_c")


class ProfileParams(BaselineParams):
    hr: float | None = None  # pinned heart rate, bpm (None = baseline model)
    spo2: float | None = None  # pinned SpO2, % (None = baseline model)
    tau_fault_s: float = 30.0


@register("profile_physiology")
class ProfileModel(BaselineModel):
    Params = ProfileParams

    def _targets(self, npc: NPCState, env: ModuleState, tod_h: float) -> dict[str, float]:
        t = super()._targets(npc, env, tod_h)
        if self.params.hr is not None:
            t["hr"] = self.params.hr
        if self.params.spo2 is not None:
            t["spo2"] = self.params.spo2
        return t

    def step(self, dt: float, npc: NPCState, env: ModuleState, ctx: StepContext) -> VitalsUpdate:
        base = super().step(dt, npc, env, dataclasses.replace(ctx, _faults={}))  # healthy vitals
        vitals, latent = dict(base.vitals), dict(base.latent)
        want = dict.fromkeys(_KEYS, 0.0)
        hrv_want = 1.0
        for f in ctx.faults_for(npc.id):
            if f.type != "medical":
                continue
            ramp = float(f.params.get("ramp_s", 0.0))
            k = 1.0 if ramp <= 0 else min(1.0, max(0.0, (ctx.tick.t_sim_s - f.start_s) / ramp))
            for key, name in (("hr", "hr_delta"), ("spo2", "spo2_delta"), ("resp_rate", "resp_delta"),
                              ("skin_temp_c", "skin_temp_delta")):
                want[key] += k * float(f.params.get(name, 0.0))
            if "hr_to" in f.params:
                want["hr"] += k * (float(f.params["hr_to"]) - vitals["hr"])
            if "spo2_to" in f.params:
                want["spo2"] += k * (float(f.params["spo2_to"]) - vitals["spo2"])
            hrv_want *= 1.0 + k * (float(f.params.get("hrv_factor", 1.0)) - 1.0)
        a = 1.0 - math.exp(-dt / self.params.tau_fault_s)
        for key in _KEYS:
            off = npc.latent.get(f"off_{key}", 0.0)
            off += (want[key] - off) * a
            latent[f"off_{key}"] = off
            vitals[key] += off
        hrv_f = npc.latent.get("hrv_f", 1.0)
        hrv_f += (hrv_want - hrv_f) * a
        latent["hrv_f"] = hrv_f
        vitals["spo2"] = min(100.0, max(0.0, vitals["spo2"]))
        vitals["hrv_rmssd"] = self._derived(vitals, npc, env, ctx.tick.time_of_day_h)["hrv_rmssd"] * hrv_f
        return VitalsUpdate(vitals=vitals, latent=latent)
