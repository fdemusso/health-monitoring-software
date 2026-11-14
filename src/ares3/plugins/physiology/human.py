"""PLACEHOLDER - awaiting review by Luca (bioengineer). A crew member as an organism with a health state.

On top of ``ProfileModel`` (baseline + medical episodes) this adds, all deterministic and driven by the seed:

* HEALTH STATE: 0 ok, 1 symptomatic, 2 impaired, 3 unconscious, 4 dead. It follows a dose of insult that
  accumulates as 1 / (time of useful consciousness) per second: hypoxia from PIO2 [P21], CO2 from ppCO2 [P22],
  heat from core temperature (ESTIMATE). The dose decays with ``dose_recovery_tau_s`` when the exposure ends, so
  an unconscious crew member recovers. Death is OPTIONAL (``death_enabled``, default False: the state then stops
  at "unconscious"). The state feeds back: an unconscious NPC stops working (resting gas exchange, hr falls in
  severe hypoxia), a dead one stops exchanging gas and its vitals decay to zero (``gas_scale`` vital, read by the core).
* INDIVIDUAL PARAMETERS from sex, age, body mass (``crew.yaml``): HRmax [P13], resting hr and HRV by sex [P14],
  VO2max by sex and age (ESTIMATE). Values given explicitly in ``params`` always win.
* CIRCADIAN rhythm of hr and core temperature [P15] and a deterministic sleep hypnogram (90 min cycles, stage
  shares from [P16]) that modulates hr and respiration during sleep.
* CORE TEMPERATURE and HYDRATION as states: exercise heat storage, sweat loss from MET, ad-libitum drinking;
  dehydration raises hr 3 bpm per 1 % of body mass [P17], fever couples to hr [P8] (``core_temp_delta`` and
  ``fluid_loss_pct_per_h`` in a ``medical`` fault).
* MICROGRAVITY: small chronic hr rise and lower HRV [P18]; space motion sickness in the first days, with per-person
  severity drawn from the Shuttle distribution [P19] (``days_in_orbit`` sets the mission day at t=0; a medical fault
  with ``sms_severity`` / ``adaptation_day0`` forces an episode).
* CARBON MONOXIDE: carboxyhaemoglobin (``cohb_pct``, the SpCO channel) follows the Coburn-Forster-Kane model from the
  CO of the module (``plugins/physiology/toxicity.py``, sources [T1]-[T2]). COHb lowers the FUNCTIONAL oxygen
  saturation, which enters the hypoxia dose (so health state) and the tachycardia term. The ``spo2`` vital is the
  pulse-oximeter reading and does not see COHb. Added by the software team, to be reviewed by the bioengineer.
* BEAT-TO-BEAT RR series (``rr_interval_ms``) with irregular rhythm for ``arrhythmia: af`` faults [P20]; ``rhythm`` 1 = AF.

Not modelled: autonomic reflex or fainting without hypoxia, injury, bone and muscle loss, pharmacology.
"""

from __future__ import annotations

import math
from itertools import pairwise

from ares3.sdk import ModuleState, NPCState, StepContext, VitalsUpdate, register

from .profile import ProfileModel, ProfileParams
from .toxicity import CFKPerson, alveolar_ventilation_stpd_ml_min, cohb_equilibrium, cohb_step, effective_pio2

STATE_NAMES = ("ok", "symptomatic", "impaired", "unconscious", "dead")


def _pio2_at_ft(alt_ft: float) -> float:
    """PIO2 (mmHg) breathing air at a standard-atmosphere altitude (used only to place the FAA table on the PIO2 axis)."""
    p_kpa = 101.325 * (1.0 - 2.25577e-5 * alt_ft * 0.3048) ** 5.25588
    return (p_kpa * 7.50062 - 47.0) * 0.2095


# Time of useful consciousness after a normal ascent, seconds [P21] (FAA table, middle of each range).
_TUC_FAA = ((18000, 1500.0), (22000, 600.0), (25000, 240.0), (28000, 165.0), (30000, 90.0), (35000, 45.0),
            (40000, 17.5), (43000, 10.5), (50000, 9.0))
# ascending PIO2; (0, 6 s) and (100 mmHg, 1e6 s) are ESTIMATE end points (no effect above ~100 mmHg)
HYPOXIA_TUC = ((0.0, 6.0), *sorted((_pio2_at_ft(ft), s) for ft, s in _TUC_FAA), (100.0, 1.0e6))
# ppCO2 (mmHg) -> time to loss of consciousness (s). 7-10 % CO2 (53-76 mmHg at 1 atm): unconscious within minutes [P22];
# values are ESTIMATE inside that statement. Below 50 mmHg (6.6 %): symptoms only.
CO2_TLOC = ((50.0, 7200.0), (53.0, 600.0), (76.0, 240.0), (150.0, 60.0))


def _log_interp(table, x: float) -> float:
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in pairwise(table):
        if x <= x1:
            return math.exp(math.log(y0) + (math.log(y1) - math.log(y0)) * (x - x0) / (x1 - x0))
    return table[-1][1]


def tuc_hypoxia_s(pio2_mmhg: float) -> float:
    return math.inf if pio2_mmhg >= HYPOXIA_TUC[-1][0] else _log_interp(HYPOXIA_TUC, pio2_mmhg)


def tloc_co2_s(ppco2_mmhg: float) -> float:
    return math.inf if ppco2_mmhg < CO2_TLOC[0][0] else _log_interp(CO2_TLOC, ppco2_mmhg)


_N3 = (0.30, 0.22, 0.14, 0.06, 0.0)  # share of each 90 min cycle spent in N3 (more in the first cycles) [P16]
_REM = (0.08, 0.18, 0.26, 0.30, 0.32)  # share in REM (more in the last cycles) [P16]


def sleep_stage(minutes_asleep: float) -> int:
    """1 N1, 2 N2, 3 N3, 5 REM. Fixed template: N1, N2, N3, N2, REM in each 90 min cycle."""
    k = min(int(minutes_asleep // 90), 4)
    f = (minutes_asleep % 90) / 90.0
    n1, n3, rem = 0.05, _N3[k], _REM[k]
    n2 = (1.0 - n1 - n3 - rem) / 2.0
    for end, stage in ((n1, 1), (n1 + n2, 2), (n1 + n2 + n3, 3), (n1 + 2 * n2 + n3, 2)):
        if f < end:
            return stage
    return 5


_SLEEP_HR = {1: 1.05, 2: 1.0, 3: 0.93, 5: 1.07}  # NREM parasympathetic, REM sympathetic [P16]; magnitude ESTIMATE
_SLEEP_RR = {1: 0.0, 2: 0.0, 3: -1.0, 5: 1.0}  # ESTIMATE


def _sms_profile(day: float) -> float:
    """Space motion sickness over the mission day: onset within hours, plateau to day 2, gone by day 3.5 [P19]."""
    if day < 0:
        return 0.0
    if day < 0.5:
        return day / 0.5
    if day < 2.0:
        return 1.0
    return max(0.0, (3.5 - day) / 1.5)


class HumanParams(ProfileParams):
    death_enabled: bool = False
    # --- health state: dose thresholds on sum(dt / TUC) (ESTIMATE: TUC is "can no longer act", loss of consciousness follows)
    dose_symptomatic: float = 0.25
    dose_impaired: float = 1.0
    dose_unconscious: float = 1.5
    dose_death: float = 30.0
    dose_recovery_tau_s: float = 600.0
    rapid_decompression_factor: float = 0.5  # TUC shortened to 1/3-1/2 after a rapid decompression [P21]
    rapid_drop_mmhg: float = 20.0
    tau_pio2_ref_s: float = 60.0
    adrenergic_hr_bpm: float = 0.0  # >0: sympathetic surge, hr target floor while the air is hypoxic (PIO2 < pio2_ref_mmhg), state >= 1 and alive; 0 = off. Luca: 150-175 bpm
    heat_dose_core_c: float = 39.5  # heat dose starts here; 1/1800 s at +0.5 C (ESTIMATE)
    # --- individuals (used only when the matching base param was not given explicitly)
    hr_rest_m: float = 60.0  # ESTIMATE; women ~4 bpm higher [P14]
    hr_rest_f: float = 64.0
    vo2max_m: float = 44.0  # ml/kg/min at 30 y, fit adult (ESTIMATE)
    vo2max_f: float = 37.0
    vo2max_slope_per_y: float = 0.3  # ESTIMATE
    hrv_sex_delta_ms: float = 5.0  # women 20-45 y: +5 ms RMSSD [P14]
    hrv_age_slope: float = -0.4  # ms per year above 30 (ESTIMATE)
    # --- circadian
    hr_circ_amp: float = 3.0  # bpm, awake; peak in the afternoon (ESTIMATE amplitude) [P15]
    hr_circ_peak_h: float = 15.0
    core_temp_rest: float = 36.8
    core_circ_amp: float = 0.4  # nadir 03-05 h [P15]; amplitude ESTIMATE
    core_nadir_h: float = 4.5
    core_per_met: float = 0.15  # ESTIMATE
    tau_core_s: float = 600.0  # ESTIMATE
    hr_per_c: float = 8.5  # [P8]
    rr_per_c: float = 2.0  # ESTIMATE
    # --- hydration
    sweat_g_min_per_met: float = 5.0  # above sweat_met_threshold; 7 MET -> 1.5 L/h (Luca: right on target)
    sweat_met_threshold: float = 2.0
    drink_tau_s: float = 7200.0  # ad libitum: the deficit closes with this time constant (ESTIMATE)
    hr_per_pct_dehyd: float = 3.0  # [P17] 3-5 bpm per 1 % of body mass lost
    core_per_pct_dehyd: float = 0.2  # [P17] 0.12-0.25 C per 1 %
    rr_per_pct_dehyd: float = 0.25  # ESTIMATE
    hrv_per_pct_dehyd: float = 0.04  # ESTIMATE
    skin_per_pct_dehyd: float = -0.1  # ESTIMATE
    # --- microgravity
    days_in_orbit: float = 30.0  # mission day at t = 0 (microgravity only)
    micro_hr_delta: float = 3.4  # [P18] meta-analysis, mean difference in flight
    micro_hrv_factor: float = 0.90  # reduced parasympathetic activity [P18]; magnitude ESTIMATE
    micro_adapt_days: float = 10.0  # Luca: adapted from mission day 10
    sms_probs: tuple[float, float, float, float] = (0.33, 0.30, 0.24, 0.13)  # none/mild/moderate/severe [P19]
    sms_hr_per_level: float = 3.0  # ESTIMATE
    sms_rr_per_level: float = 0.5
    sms_hrv_per_level: float = 0.05
    sms_skin_per_level: float = -0.15
    # --- rhythm
    af_spo2_osc: float = 1.5  # AF: spo2 wanders +-1.5 around spo2_to (Luca: 91-94 %), slow noise
    af_sd_frac: float = 0.15  # AF: SD of RR / mean RR (RMSSD 80-250 ms is the usual AF range [P20])
    rr_min_ms: float = 250.0  # refractory limit


@register("human_physiology")
class HumanModel(ProfileModel):
    Params = HumanParams

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._individualized = False
        self._sms_level = 0
        self._cfk: CFKPerson | None = None

    # ---- individual parameters -----------------------------------------------------------------
    def _individualize(self, npc: NPCState) -> None:
        if self._individualized:
            return
        self._individualized = True
        p, given, upd = self.params, self.params.model_fields_set, {}
        sex, age = npc.sex, npc.age_y
        if "hr_rest" not in given:
            upd["hr_rest"] = {"M": p.hr_rest_m, "F": p.hr_rest_f}.get(sex, 0.5 * (p.hr_rest_m + p.hr_rest_f))
        if "hr_max" not in given and age is not None:
            upd["hr_max"] = 208.0 - 0.7 * age  # Tanaka [P13]
        if "met_max" not in given and (sex is not None or age is not None):
            vo2 = {"M": p.vo2max_m, "F": p.vo2max_f}.get(sex, 0.5 * (p.vo2max_m + p.vo2max_f))
            vo2 -= p.vo2max_slope_per_y * max(0.0, (age if age is not None else 30.0) - 30.0)
            upd["met_max"] = vo2 / 3.5
        if "hrv_rest" not in given:
            hrv = 45.0 + (p.hrv_sex_delta_ms if sex == "F" else 0.0)
            hrv += p.hrv_age_slope * ((age if age is not None else 30.0) - 30.0)
            upd["hrv_rest"] = max(15.0, hrv)
        self.params = p.model_copy(update=upd)
        self._sms_level = int(self.rng.choice(4, p=p.sms_probs))
        self._cfk = CFKPerson.from_anthropometrics(sex, npc.body_mass_kg)

    # ---- targets / derived with the extra terms --------------------------------------------------
    def _targets(self, npc: NPCState, env: ModuleState, tod_h: float) -> dict[str, float]:
        t = super()._targets(npc, env, tod_h)
        if self.params.hr is not None:  # pinned hr: leave it fixed
            return t
        p, lat = self.params, npc.latent
        dehyd, fever = lat.get("dehyd_pct", 0.0), lat.get("fever_c", 0.0)
        hr_add = (p.hr_per_pct_dehyd * dehyd + p.hr_per_c * fever + lat.get("micro_k", 0.0) * p.micro_hr_delta
                  + p.sms_hr_per_level * lat.get("sms_eff", 0.0))
        pio2_eff = lat.get("pio2_eff")  # carbon monoxide: functional hypoxia drives the heart like thin air would
        if pio2_eff is not None and pio2_eff < env.pio2_mmhg:
            extra = max(0.0, p.pio2_ref_mmhg - pio2_eff) - max(0.0, p.pio2_ref_mmhg - env.pio2_mmhg)
            hr_add += min(p.hr_hypoxia_cap, p.hr_per_mmhg_pio2 * extra)
        rr_add = p.rr_per_pct_dehyd * dehyd + p.rr_per_c * fever + p.sms_rr_per_level * lat.get("sms_eff", 0.0)
        if npc.activity == "sleep":
            stage = int(lat.get("sleep_stage", 2))
            t["hr"] *= _SLEEP_HR.get(stage, 1.0)
            rr_add += _SLEEP_RR.get(stage, 0.0)
        else:
            hr_add += p.hr_circ_amp * math.cos(2 * math.pi * (tod_h - p.hr_circ_peak_h) / 24.0)
        t["hr"] += hr_add
        if (p.adrenergic_hr_bpm > 0.0 and lat.get("health_state", 0.0) >= 1.0 and not lat.get("dead", 0.0)
                and env.pio2_mmhg < p.pio2_ref_mmhg):  # only while the air is hypoxic: it ends with the exposure
            t["hr"] = max(t["hr"], p.adrenergic_hr_bpm)
        t["resp_rate"] += rr_add
        return t

    def _derived(self, vitals: dict[str, float], npc: NPCState, env: ModuleState, tod_h: float) -> dict[str, float]:
        d = super()._derived(vitals, npc, env, tod_h)
        p, lat = self.params, npc.latent
        dehyd, sms = lat.get("dehyd_pct", 0.0), lat.get("sms_eff", 0.0)
        micro = 1.0 - lat.get("micro_k", 0.0) * (1.0 - p.micro_hrv_factor)
        d["hrv_rmssd"] *= max(0.2, 1.0 - p.hrv_per_pct_dehyd * dehyd) * micro * max(0.2, 1.0 - p.sms_hrv_per_level * sms)
        d["skin_temp_c"] += p.skin_per_pct_dehyd * dehyd + p.sms_skin_per_level * sms
        return d

    # ---- health state ----------------------------------------------------------------------------
    def _va_ml_min(self, npc: NPCState, env: ModuleState) -> float:
        """Alveolar ventilation (STPD) from the CO2 output; an unconscious / dead subject breathes less (gas_scale)."""
        return alveolar_ventilation_stpd_ml_min(npc.vco2_l_min * npc.vitals.get("gas_scale", 1.0), env.pressure_kpa)

    def _exposure(self, dt: float, env: ModuleState, lat: dict[str, float], npc: NPCState) -> dict[str, float]:
        p = self.params
        pio2 = env.pio2_mmhg
        cohb = cohb_step(lat.get("cohb_pct", lat.get("cohb_rest", 0.4)), dt, co_ppm=env.co_ppm,
                         pressure_kpa=env.pressure_kpa, pio2_mmhg=pio2, va_ml_min=self._va_ml_min(npc, env),
                         person=self._cfk)
        pio2_eff = effective_pio2(pio2, max(0.0, cohb - lat.get("cohb_rest", 0.0)))  # only the excess over the resting level
        ref = lat.get("pio2_ref", pio2)
        ref += (pio2 - ref) * (1.0 - math.exp(-dt / p.tau_pio2_ref_s))
        tuc = tuc_hypoxia_s(pio2_eff) * (p.rapid_decompression_factor if ref - pio2 > p.rapid_drop_mmhg else 1.0)
        rate = 1.0 / tuc + 1.0 / tloc_co2_s(env.ppco2_mmhg)  # per second
        core = lat.get("core_temp_c", 37.0)
        if core > p.heat_dose_core_c:
            rate += (core - p.heat_dose_core_c) / 0.5 / 1800.0
        dose, dead = lat.get("dose", 0.0), lat.get("dead", 0.0)
        if rate > 0.0:
            dose += rate * dt
        else:
            dose *= math.exp(-dt / p.dose_recovery_tau_s)
        if p.death_enabled and dose >= p.dose_death:
            dead = 1.0
        dose = min(dose, p.dose_death * (1.0 if p.death_enabled else 0.99))
        if dead:
            state = 4
        elif dose >= p.dose_unconscious:
            state = 3
        elif dose >= p.dose_impaired:
            state = 2
        elif dose >= p.dose_symptomatic:
            state = 1
        else:
            state = 0
        return {"pio2_ref": ref, "dose": dose, "dead": dead, "health_state": float(state), "cohb_pct": cohb,
                "pio2_eff": pio2_eff}

    # ---- model ------------------------------------------------------------------------------------
    def initial_vitals(self, npc: NPCState, env: ModuleState) -> VitalsUpdate:
        self._individualize(npc)
        upd = super().initial_vitals(npc, env)
        p = self.params
        cohb_rest = cohb_equilibrium(co_ppm=env.co_ppm, pressure_kpa=env.pressure_kpa, pio2_mmhg=env.pio2_mmhg,
                                     va_ml_min=self._va_ml_min(npc, env), person=self._cfk)
        extra = {"cohb_rest": cohb_rest, "cohb_pct": cohb_rest, "pio2_ref": env.pio2_mmhg, "dose": 0.0, "dead": 0.0, "health_state": 0.0, "core_act": 0.0,
                 "fever_c": 0.0, "dehyd_pct": 0.0, "sleep_t0": -1.0, "sleep_stage": 0.0, "micro_k": 0.0,
                 "sms_eff": 0.0, "af_w": 0.0, "core_temp_c": p.core_temp_rest, "next_beat_t": 0.0,
                 "rr_ms": 60000.0 / upd.vitals["hr"]}
        vitals = {**upd.vitals, "health_state": 0.0, "gas_scale": 1.0, "core_temp_c": p.core_temp_rest,
                  "sleep_stage": 0.0, "dehydration_pct": 0.0, "nausea": 0.0, "rr_interval_ms": extra["rr_ms"],
                  "rhythm": 0.0, "cohb_pct": cohb_rest}
        return VitalsUpdate(vitals=vitals, latent={**upd.latent, **extra})

    def step(self, dt: float, npc: NPCState, env: ModuleState, ctx: StepContext) -> VitalsUpdate:
        self._individualize(npc)
        p, lat = self.params, dict(npc.latent)
        t, tod = ctx.tick.t_sim_s, ctx.tick.time_of_day_h
        faults = [f for f in ctx.faults_for(npc.id) if f.type == "medical"]

        mine = self._exposure(dt, env, lat, npc)
        state = int(mine["health_state"])
        if mine["dead"]:
            return self._dead_step(dt, npc, env, lat, mine)

        unconscious = state >= 3
        sleeping = npc.activity == "sleep"
        met = 1.0 if unconscious else npc.met

        # sleep hypnogram
        t0 = lat.get("sleep_t0", -1.0)
        if sleeping and t0 < 0:
            t0 = t
        elif not sleeping:
            t0 = -1.0
        mine["sleep_t0"] = t0
        mine["sleep_stage"] = float(sleep_stage((t - t0) / 60.0)) if sleeping else 0.0

        # fault-carried parameters (ramped like the other medical effects)
        fever_want, fluid_loss, af_on, sms_fault = 0.0, 0.0, False, None
        for f in faults:
            ramp = float(f.params.get("ramp_s", 0.0))
            k = 1.0 if ramp <= 0 else min(1.0, max(0.0, (t - f.start_s) / ramp))
            fever_want += k * float(f.params.get("core_temp_delta", 0.0))
            fluid_loss += float(f.params.get("fluid_loss_pct_per_h", 0.0))
            af_on = af_on or f.params.get("arrhythmia") == "af"
            if "sms_severity" in f.params:
                day = float(f.params.get("adaptation_day0", 1.0)) + (t - f.start_s) / 86400.0
                sms_fault = float(f.params["sms_severity"]) * _sms_profile(day)

        # microgravity: chronic adaptation and space motion sickness of the mission day
        if ctx.env.gravity_m_s2 == 0.0:
            day = p.days_in_orbit + t / 86400.0
            mine["micro_k"] = min(1.0, max(0.0, day / p.micro_adapt_days))
            sms = self._sms_level * _sms_profile(day)
        else:
            mine["micro_k"], sms = 0.0, 0.0
        mine["sms_eff"] = max(sms, sms_fault or 0.0)

        # hydration
        mass = npc.body_mass_kg or 70.0
        sweat_g_min = p.sweat_g_min_per_met * max(0.0, met - p.sweat_met_threshold)
        loss = sweat_g_min / 60.0 / (mass * 10.0) + fluid_loss / 3600.0  # % of body mass per second
        dehyd = lat.get("dehyd_pct", 0.0)
        drink = 0.0 if fluid_loss > 0 else dehyd / p.drink_tau_s
        dehyd = max(0.0, dehyd + (loss - drink) * dt)
        mine["dehyd_pct"] = dehyd

        # core temperature
        a = 1.0 - math.exp(-dt / p.tau_core_s)
        core_act = lat.get("core_act", 0.0)
        core_act += ((0.0 if sleeping else p.core_per_met * (met - 1.0)) - core_act) * a
        fever = lat.get("fever_c", 0.0)
        fever += (fever_want - fever) * a
        circ = p.core_circ_amp * math.cos(2 * math.pi * (tod - (p.core_nadir_h + 12.0)) / 24.0)
        core = p.core_temp_rest + circ + core_act + fever + p.core_per_pct_dehyd * dehyd
        mine.update(core_act=core_act, fever_c=fever, core_temp_c=core)

        af_w = lat.get("af_w", 0.0)
        af_w += ((1.0 if af_on else 0.0) - af_w) * (1.0 - math.exp(-dt / p.tau_fault_s))
        mine["af_w"] = af_w

        # initial values right after an event (Luca: the brief's vitals are the START, no vertical crash): set once at fault start
        for f in faults:
            key = f"init_{f.id}"
            if ("hr_init" in f.params or "spo2_init" in f.params) and t >= f.start_s and not lat.get(key):
                lat["hr"], lat["spo2"] = float(f.params.get("hr_init", lat.get("hr", 0.0))), float(f.params.get("spo2_init", lat.get("spo2", 100.0)))
                mine[key] = 1.0

        # the vitals of the underlying (profile) model; an unconscious NPC does not exercise
        view = npc.model_copy(update={"met": met, "activity": "rest" if unconscious and not sleeping else npc.activity,
                                      "latent": {**lat, **mine}})
        vit = super().step(dt, view, env, ctx)
        v = dict(vit.vitals)
        if state == 3:  # severe hypoxia: bradycardia (unless the adrenergic floor holds hr up) and agonal breathing
            if p.adrenergic_hr_bpm <= 0.0:
                v["hr"] *= min(1.0, max(0.25, (v["spo2"] - 35.0) / 30.0))
            if v["spo2"] < 50.0:
                v["resp_rate"] *= 0.5
        if af_w > 0.0:
            osc = lat.get("spo2_osc", 0.0)
            osc += -osc * dt / 10.0 + 0.45 * math.sqrt(dt) * float(self.rng.standard_normal())
            osc = max(-p.af_spo2_osc, min(p.af_spo2_osc, osc))
            mine["spo2_osc"] = osc
            v["spo2"] = min(100.0, v["spo2"] + af_w * osc)
            af_hrv = math.sqrt(2.0) * p.af_sd_frac * 60000.0 / max(v["hr"], 20.0)
            v["hrv_rmssd"] = v["hrv_rmssd"] * (1.0 - af_w) + af_hrv * af_w

        # beat-to-beat series: RR drawn around 60000 / hr; sinus jitter reproduces the RMSSD, AF is irregular
        nb, rr_ms = lat.get("next_beat_t", t), lat.get("rr_ms", 60000.0 / max(v["hr"], 20.0))
        mean_rr = 60000.0 / max(v["hr"], 20.0)
        for _ in range(6):
            if nb > t:
                break
            sd = af_w * p.af_sd_frac * mean_rr + (1.0 - af_w) * v["hrv_rmssd"] / math.sqrt(2.0)
            rr_ms = max(p.rr_min_ms, mean_rr + sd * float(self.rng.standard_normal()))
            nb += rr_ms / 1000.0
        mine.update(next_beat_t=max(nb, t), rr_ms=rr_ms)

        v.update(health_state=float(state), core_temp_c=core, sleep_stage=mine["sleep_stage"], dehydration_pct=dehyd,
                 nausea=mine["sms_eff"], cohb_pct=mine["cohb_pct"], rr_interval_ms=rr_ms, rhythm=1.0 if af_w > 0.5 else 0.0,
                 gas_scale=min(1.0, 1.0 / max(npc.met, 1.0)) if unconscious else 1.0)
        return VitalsUpdate(vitals=v, latent={**lat, **vit.latent, **mine})

    def _dead_step(self, dt: float, npc: NPCState, env: ModuleState, lat: dict[str, float],
                   mine: dict[str, float]) -> VitalsUpdate:
        """Vitals are zero (hr, resp, spo2, hrv); skin and core temperature relax to the room temperature."""
        v = dict(npc.vitals)
        for key in ("hr", "resp_rate", "spo2", "hrv_rmssd"):  # Luca: after death the series is 0
            v[key] = 0.0
        for key, tau in (("skin_temp_c", 3600.0), ("core_temp_c", 18000.0)):
            v[key] = env.temperature_c + (v.get(key, env.temperature_c) - env.temperature_c) * math.exp(-dt / tau)
        v.update(health_state=4.0, gas_scale=0.0, sleep_stage=0.0, nausea=0.0, rr_interval_ms=0.0, rhythm=0.0,
                 dehydration_pct=lat.get("dehyd_pct", 0.0))
        return VitalsUpdate(vitals=v, latent={**lat, **mine, "core_temp_c": v["core_temp_c"]})
