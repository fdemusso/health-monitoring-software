# Medical crew procedures: what they say, why, and what is still open

Procedures live in `scenarios/monitor_placeholder.yaml` (block `procedures:`; `tools/build_station.py` copies it into
`scenarios/station/monitor.yaml`). A procedure is picked by `(emergency, cause, severity)`; the `cause` is matched EXACTLY, so every
cause the monitor can name has its own (`tests/test_procedures_medical.py`). Everything here is **ESTIMATE until the bioengineer
(Luca) reviews it** and is a simulation checklist, not medical advice.

Rules followed: only objects of the ISS medical kit ([R12]) and phrases like "as the flight surgeon / the medical checklist says";
never a dose, never a diagnosis (the texts say "suspected", "assess", "report"). A treatment does not change the simulated
physiology, so each `check` is written on what the simulator can produce (the episode ends, clean air, the source is removed);
a check that fails goes to `escalate`. Checks read SENSED wearable values only. Sources: NASA / ISS where we found them;
terrestrial medicine is used only as support and is flagged `(terrestrial)`.

## Problem -> cause -> procedure (before and after)

| Problem | Cause the monitor emits | Emitted by | Before | After |
|---|---|---|---|---|
| Hypoxia | `hypoxia` | rule `low_spo2` | `med_hypoxia` | `med_hypoxia` |
| Carbon monoxide | `co_poisoning` | rules `cohb_*` | `med_co` | `med_co` |
| Heat / fever (core T) | `fever_or_heat` | rule `high_core_temp` | `med_heat` | `med_heat` |
| Fever | `fever` | stage B medical | `med_generic` | `med_fever` |
| Dehydration | `dehydration` | stage B medical | `med_generic` | `med_dehydration` |
| Atrial fibrillation (suspected) | `atrial_fibrillation_suspected` | stage B medical | `med_generic` | `med_afib` |
| Supraventricular tachycardia (suspected) | `svt_suspected` | stage B medical (phase 2) | `med_generic` | `med_svt` |
| Bradycardia | `bradycardia` | stage B medical (phase 2) | `med_generic` | `med_bradycardia` |
| Acute stress | `acute_stress` | stage B medical | `med_generic` | `med_stress` |
| Space motion sickness | `space_motion_sickness` | stage B medical | `med_generic` | `med_motion_sickness` |
| Respiratory infection | `respiratory_infection` | stage B medical (phase 2) | `med_generic` | `med_respiratory` |
| Abnormal exertion | `abnormal_exertion` | stage B medical (phase 2) | `med_generic` | `med_exertion` |
| Out of own baseline | `crew_baseline` | crew stage A (`crew_baseline.py`) | `med_generic` | `med_crew_baseline` |
| Hypoxia in the air (joint) | `hypoxia_crew` | stage B `crew_env` (phase 2) | `med_generic` | `med_hypoxia_crew` (= `med_hypoxia` steps) |
| CO in the air (joint) | `co_exposure_crew` | stage B `crew_env` (phase 2) | `med_generic` | `med_co_crew` (= `med_co` steps) |
| High CO2 in the air (joint) | `hypercapnia_crew` | stage B `crew_env` (phase 2) | `med_generic` | `med_hypercapnia_crew` (new) |
| Impaired / NEWS2 score, no cause | none | rules `impaired`, `news_*` | `med_generic` | `med_generic` |

"Before" was measured by choosing the procedure with the `monitor.yaml` of the starting commit. The `crew_env` causes and the phase 2
labels (`svt_suspected`, ...) are not emitted yet on the branch this work started from; the procedures are ready for when they are.

## Problems

Check thresholds are on SENSED values: `hr` [bpm], `spo2` [%], `core_temp_c`, `resp_rate`, `cohb_pct`. Thresholds without a
source are ESTIMATE.

### Suspected atrial fibrillation (`med_afib`)
NASA recorded 11 cases of atrial fibrillation, flutter or SVT in active astronauts since 1959, mostly without symptoms [R16]. On the
ISS the crew medical officer is usually not a physician, so protocols must be executable alone [R11]. Steps: rest and ask about
palpitations, chest pain, dizziness or breathlessness [R16]; pulse by hand and an ECG with the kit device [R12]; report at once to the
flight surgeon, who decides any treatment [R16] (terrestrial: 2023 ACC/AHA/ACCP/HRS AF guideline, rate-control drugs are a physician's
choice [R23]). Check: `hr <= 110` within 900 s; else escalate. **Escalate** when the rhythm does not settle, or with chest pain /
fainting.

### Suspected supraventricular tachycardia (`med_svt`)
Same cases as above [R16]. Terrestrial: vagal manoeuvres and adenosine are the acute treatment of a regular SVT, cardioversion if
unstable [R22]; we do NOT put the manoeuvre in the steps, we say "manoeuvres and medication only as the flight surgeon says". Check
`hr <= 110` within 900 s; else escalate (defibrillator kept ready [R12]).

### Bradycardia (`med_bradycardia`)
No ISS-specific source found. Terrestrial reasoning: a slow rate matters when it comes with dizziness, fainting or chest pain, and
is normal in an athlete or while asleep (ESTIMATE). Check `hr >= 45` within 900 s; else escalate.

### Fever / heat (`med_fever`, `med_heat`, `med_exertion`)
Heat illness: cool first, fluids, no antipyretic for heat stroke [R15] (terrestrial, NHS heatstroke [R25]). Fever: rest, fluids,
medication from the kit only as the flight surgeon says [R12]. Checks: `core_temp_c <= 38.0` (fever) / `<= 38.5` (heat, existing
`med_heat`) within 3600 s. `med_exertion` also checks `hr <= 100` after the rest. **Escalate** if not falling.

### Dehydration (`med_dehydration`)
Terrestrial support [R24]: oral rehydration; signs of shock (confusion, fast breathing, cold skin) need urgent care. The galley and
the water supply of the module are ours (ESTIMATE). Check `hr <= 100` within 1800 s; else escalate.

### Acute stress (`med_stress`)
NASA HRP Behavioral Health & Performance covers monitoring and countermeasures [R26]; no step-by-step source found, so the steps (quiet
place, reduce workload, slow breathing, rule out a physical cause) are ESTIMATE, with the commander as the role. Check `hr <= 100`
within 900 s; else escalate to the flight surgeon and psychological support.

### Space motion sickness (`med_motion_sickness`)
Affects 67-75 % of astronauts in the first days [R17]. Steps: head still, bag at hand, fixed visual reference; medication from the
kit only as the checklist says [R17] [R12]. No check (a self-limiting advisory): the procedure ends when the instructions are done.

### Respiratory infection (`med_respiratory`)
Upper-respiratory symptoms are a leading in-flight event; confirmation on board is often not possible for lack of laboratory
equipment (ISS EMR studies, found via search, not opened: ESTIMATE). Mask to limit spread, measure T / breathing / SpO2 at rest,
report to the flight surgeon; oxygen with the Variable Oxygen System if SpO2 stays low (target 94-98 % [R13], terrestrial).
Checks `spo2 >= 94` then `core_temp_c <= 38.0`; fail -> escalate.

### Hypoxia, carbon monoxide (`med_hypoxia`, `med_co`, joint copies)
Unchanged content from the first version: oxygen with the Variable Oxygen System [R13]; 100 % oxygen for CO, COHb half-life
74 +- 25 min [R14]; isolate the module and measure before going back [R7]. The joint causes `hypoxia_crew` / `co_exposure_crew` reuse
the same steps (YAML anchor) because the treatment of the person is the same.

### High CO2 in the air (`med_hypercapnia_crew`, new)
Symptoms: headache, breathlessness, fatigue; severity grows with exposure time [R20]; ISS limit 3 mmHg, 1 h average (NASA-STD-3001),
association with symptoms is not proven causal and microgravity fluid shifts cause similar headaches [R21]. Steps: assess the person;
move to a module with normal air (ESTIMATE); the engineer checks the module's CO2 on the MCA, the CDRA, and keeps the fans on [R20]; if
the CO2 is still high wake the standby scrubber (CDRA-B) and open hatches for the IMV exchange; check `resp_rate <= 20`; else escalate.
**Limitation**: a `check` reads `(subject, metric)`, so the module's ppCO2 cannot be a check while the emergency has a `subject`; it is a
`question` answered by the engineer. Letting a check read a module metric needs a change in `core/procedures.py` (not done).

### Generic / out of own baseline (`med_generic`, `med_crew_baseline`)
Assess, measure again at rest with the kit instruments [R12], report with the wearable data [R9]; `med_crew_baseline` adds a check
`hr <= 100` within 900 s, else escalate.

## Steps without a source (ESTIMATE)
Mask for infection spread; dehydration galley / water-supply step; stress steps (quiet place, workload, breathing); "move to a module
with normal air" for CO2; bradycardia reasoning; every numeric check threshold (`hr` 100 / 110 / 45, `core_temp_c` 38.0, `resp_rate` 20,
all `within_s`); the `duration_s` of every step; that the commander is the role for the stress procedure.

## Open questions for Luca
1. Thresholds: `hr` 100 at rest for "settled" (stress, dehydration, exertion, baseline), 110 for AF/SVT, 45 for bradycardia; `core_temp_c` 38.0 vs 38.5; `resp_rate` 20 for hypercapnia. Right for a trained astronaut at rest, with the wearable noise?
2. Does a 5-minute settle (`within_s` 900) make sense for an arrhythmia, or does the simulator's episode length decide it?
3. Is it right that SVT and AF end in "report to the flight surgeon" with no manoeuvre in the text?
4. Respiratory infection: which of the early signs should the crew look for in the ISS cabin (shared air, mask)?
5. Dehydration: is HR the right check, or HRV (`hrv_rmssd`) / skin temperature?
6. Acute stress: who should lead (commander, medic)? Is there an ISS behavioural-health procedure to follow?
7. Hypercapnia: is `resp_rate <= 20` a good proxy, or is a symptom question better?
8. Joint causes: should `co_exposure_crew` (exposure, COHb not yet high) ask for COHb measurement before oxygen?

## Sources (new in this work; the older ones are in `docs/reference/monitoring-ml-sources.md`)

| Tag | Source | Body | Year | URL |
|---|---|---|---|---|
| [R20] | OCHMO-TB-004, *Carbon dioxide* technical brief | NASA OCHMO | 2023 | https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf |
| [R21] | Law et al., NASA/TP-2010-216126, in-flight CO2 exposure (mirror copy found by search) | NASA | 2010 | https://inspectapedia.com/hazmat/In-Flight-CO2-Exposure-Implications-Law-NASA.pdf |
| [R22] | *2015 ACC/AHA/HRS Guideline for the Management of Adult Patients With Supraventricular Tachycardia* (terrestrial; summary page, guideline text not opened) | ACC / AHA / HRS | 2015 | https://cm.healio.com/cardiology/learn-the-heart/cardiology-review/cardiology-guidelines/2015-accahahrs-guideline-for-the-management-of-adult-patients-with-svt |
| [R23] | *2023 ACC/AHA/ACCP/HRS Guideline for the Diagnosis and Management of Atrial Fibrillation* (terrestrial; only known from search summaries, URL to add and verify) | ACC / AHA / ACCP / HRS | 2023 | to verify in Circulation / JACC |
| [R24] | *Dehydration* (terrestrial) | NHS | current | https://www.nhs.uk/conditions/dehydration/ |
| [R25] | *Heatstroke* (terrestrial) | NHS | current | https://www.nhs.uk/conditions/heatstroke/ |
| [R26] | *Behavioral Medicine evidence report* | NASA HRP | 2025 | https://ntrs.nasa.gov/citations/20250001454 (only the contents seen: not used for steps) |

Older tags reused: [R7] [R9] [R11] [R12] [R13] [R14] [R15] [R16] [R17].
