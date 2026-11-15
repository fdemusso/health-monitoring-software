# Phase 2: crew stage A and the medical family of stage B

Branch `feat/crew-model` (from `feat/crew-dataset`). Data: waves 1 and 2 (677 runs) plus 40 nominal twins without jitter. All the numbers are
simulation time on synthetic data, not flight performance. The tuning (margins, thresholds, model choice) was done on the validation only
(seeds 131-138); the test (141-160) was opened **once**, on 15/11/2026 at 18:38, with the models frozen in
commit `6798982` (models and code).

## 1. What is there

| File | What |
|---|---|
| `src/ares3/plugins/monitor/ml/crew_baseline.py` | `CrewBaselineModel` + `CrewBaselineDetector` (`slow` and `fast` modes) |
| `tools/ml/train_crew.py`, `tools/ml/eval_crew.py` | offline training and evaluation with the same scoring code as the detector |
| `tools/ml/medical.py`, `train_diagnoser.py --families medical`, `sweep_diagnoser.py --medical`, `eval_medical.py` | medical family: twins, identity check, per-class thresholds, confusion matrix, A / B / A+B test |
| `tools/ml/make_crew_test_monitor.py`, `check_crew_parity.py` | test monitor (`output/ml/monitor_crew_test.yaml`, outside the generated files) and online = offline parity |
| `models/station_v2/` | `crew_baseline.joblib`, `diagnoser.joblib` (new medical family, the others from v1), cards, `eval_crew_{val,test}.json`, `eval_medical_test.json` |
| `tools/ml/classes.yaml` + `scenarios/station/monitor.yaml` (regenerated) | 4 new classes: `svt_suspected`, `bradycardia`, `respiratory_infection`, `abnormal_exertion` |

The live monitor moves to `station_v2` with A plus B gated by A (§3b).

## 2. Stage A: per-person baseline given the context

For each (person, quantity) one regressor (`HistGradientBoostingRegressor`, absolute error, depth 3, 200 iterations) predicts the expected value
from the schedule context alone (MET, activity, minutes since exercise and sleep, clock) plus a **schedule memory**
(exponential means of `ctx|met10` with constants of 30, 120 and 360 min, computed row by row: identical online and offline). The quantities are
the six 10-min means plus `hr|sd10`. The σ scale is per person, quantity and activity class (1.4826 × MAD of the validation residuals) and
a second small regressor raises it where the context says the body is in transition. Slow statistic = exponential mean (5 min) of
max(D²/L_D, z/L_z); fast statistic = |z| of HR (or of the irregularity) over the limit × `fast_factor`, **without** truncation at ±10.

Why the memory and the scale from the context: with the phase-1 context alone the validation false alarms came from two things: HR
stays high for hours after exercise while `min_since_ex` stops at 2 h, and in the first minutes of an activity change the 10-min mean
lags behind the context and z saturates at 10. The limits are therefore **margin × the highest level held for the confirmation time** (11 min for the
slow stage, 3 samples for the fast one), not the instantaneous maximum, and a limit cannot exceed 0.95 × the truncation (it would be unreachable).

**Regressor versus table** (same interface, table = median per activity class and MET band of 1, same detector), on the validation:

| | M val events detected | alarms outside the event | false-alarm checks (N1 val + half-half + outside) |
|---|---|---|---|
| regressor | **71/72** | 0 | 1 |
| table | 68/72 | 1 | 3 |

The regressor is kept (rule: fewer false alarms, then recall; on a tie the table). Margin chosen 2.0, `fast_factor` 1.5.

### Validation (N1 val 12 days, M val 72 events)

0 false alarms, 0 signals during exercise, recall 71/72 (0.99; Wilson 0.93-1.00); per type 8/8 except bradycardia 7/8.

### Test (N2 30 d + N3 15 d = 45 nominal days, 72 M events 141-148)

| | result |
|---|---|
| event recall (stage A) | **72/72** = 1.00 (Wilson 0.95-1.00); each type 8/8 [0.68-1.00] |
| median delay from visible (twin), minutes | AF 4.0; SVT 3.0; bradycardia 12.5; fever 17.5; resp. infection 14.0; stress 20.5; abnormal exertion 18.0; space sickness 16.5; dehydration 68.5 |
| false alarms | 6 in 45 d = 0.133/day (95 % upper limit 0.263) |
| signals during nominal exercise | 3 |

The 6 false alarms are **two situations repeated for three days** (the jitter is fixed per run), not six independent events, and the
Poisson limit assumes independent events: it underestimates. (1) N2 seed 144, person `med`: three times a work block at 7.5 MET (like an
extravehicular activity) with the respiratory rate at 10σ; it is also the only case of the 3 signals "during exercise". (2) N2 seed 149, person
`bot`: three 6 h sleeps with HR at 50 bpm, 10σ below expected. Probable cause: the test contains jitter combinations (MET higher than the one
seen in training, deeper sleep) outside the training range, and trees do not extrapolate. Nothing was adjusted.

## 3. Stage B: medical family

Trained with 351 runs (324 with a fault: M train and catalog; 27 nominal: N1 train and catalog; seeds 1-3 and 101-124), 139,002 rows (95,164 nominal, stride 5 on the nominal only), positives per class from 457
(SVT) to 13,644 (resp. infection); all 9 classes have ≥ 300 rows, so all are `live`. The other families are copied intact from v1
(same `mean`/`scale`, hence the same explanations). Per-class thresholds on the validation (≤ 0.05 false/day per class over 50 nominal validation days):
0.30 for all except respiratory infection (0.50): it is the bottom of the grid, i.e. the validation did not ask for more.

**Dehydration:** against the twin it never exceeds 3σ (peak 1.4-2.7σ on the station scale): its "visible effect" label uses
the declared fallback (start + `ramp_s` + 1 h), as the plan foresaw. The other 8 classes use the twin (k = 3).

### Test: event recall and confusion

| event | A | B right label + person | B right person | A+B | labels given by B |
|---|---|---|---|---|---|
| abnormal exertion | 8/8 | 3/8 | 4/8 | 8/8 | exertion 8, dehydr. 7 |
| acute stress | 8/8 | 3/8 | 3/8 | 8/8 | stress 3, fever 5 |
| atrial fibrillation | 8/8 | 6/8 | 6/8 | 8/8 | AF 7, resp. inf. 7 |
| bradycardia | 8/8 | 3/8 | 3/8 | 8/8 | bradycardia 4 |
| dehydration | 8/8 | 2/8 | 2/8 | 8/8 | dehydr. 8 (median delay 438 min) |
| fever | 8/8 | 5/8 | 7/8 | 8/8 | fever 8, dehydr. 4 |
| respiratory infection | 8/8 | 6/8 | 6/8 | 8/8 | resp. inf. 8 |
| space sickness | 8/8 | 0/8 | 2/8 | 8/8 | space sickness 5 |
| SVT | 8/8 | 4/8 | 5/8 | 8/8 | SVT 5 |
| **total** | **72/72** [0.95-1.00] | **32/72 = 0.44** [0.34-0.56] | 38/72 = 0.53 [0.41-0.64] | **72/72** | |

Stage B alone gives the right class in 56 events out of 72 (the "labels given" column), but the **subject** (the
person the explanation points at) is right only 53 % of the time: the class signature is the mean over all the people, and the feature closest to the
signature is not always the patient's. The A+B detection belongs entirely to stage A.

Stage B false alarms over the 43.1 nominal test days: 10 as opened by `eval_medical`, of which 8 without a person (`dehydration`,
subject `None`, 7 in the same N2 seed 148 run). The live detector discards a medical diagnosis without a person, so those would never
have reached the crew; **a-posteriori reading** (after the test was opened, without rerunning anything and without tuning, noted in the JSON):
2 alarms = 0.046/day (upper limit 0.146). Sum A + B ≤ 0.186/day (upper limit of the union, with no overlap).
`eval_medical.py` was fixed for the future (it discards diagnoses without a person).

### 3b. A and B combined in the live monitor (added after the test)

The live monitor (`scenarios/station/monitor.yaml`, generated by `tools/build_station.py`) now has `ml_crew_slow` and `ml_crew_fast` after the rules and the
diagnoser on `station_v2` with `gate_board: crew`: the **medical** family speaks only while stage A flags someone and **the person it names is
the one flagged by A** (A knows who, B knows what). The other families (physical, actuators) are unchanged. A publishes the flagged people on a "board"
(`crew_baseline.BOARD`, by name) and its evidence (`EVIDENCE`); in the emergency the **first** evidence line is the person with the measured values against the expected ones,
the last is B's class. Emergency cause: that of the detector listed first (`crew_baseline`, or the rule that names a cause).

Measured **on the validation only** (`tools/ml/eval_gated.py`, ×2 confirmation as in the live monitor; the test is spent and is not opened here):

| | B alone | A+B gated |
|---|---|---|
| right class (person not required) | 56/72 = 0.78 | 56/72 = 0.78 |
| right class **and** right person | not measurable as now (right subject ~53 % on the test) | **56/72 = 0.78** [0.67-0.86] |
| right person, any class | | 63/72 = 0.88 [0.78-0.93] |
| false alarms over 50.1 nominal validation days | 1 (0.020/day) | **0** |

The gate loses no class recall and settles the person and the isolated alarms; the quality of the classes remains B's (stress/fever, space sickness, bradycardia,
AF/respiratory infection get confused). **Not certified on the test.**

Live-monitor checks on a whole run (`tools/ml/check_crew_live.py`, seed 5):
* nominal day: **0 emergencies**, 4.8 ms/tick (with other processes running);
* atrial fibrillation on `cmd` (25 min at 5 h): 1 emergency, right person, class `emergency`, opened at +2 min and confirmed at +4 min from the start;
* fever on `eng` (4 h at 7 h): right person, cause `fever_or_heat` (the existing temperature rule), opened at +17 min;
* in this last 1.2-day run `arresto_imv` also appeared (physical/actuator family, unchanged from v1) at 26 h without a fault: to look at in phase 3.

Known limit: in AF the class B names last can be "respiratory infection" (B confuses them: on the test it gives AF in 7 events and infection in 7 on the same 8). For this
reason the first evidence is the person with the numbers.

## 4. Acceptance criteria of §7 (test, once)

| criterion | outcome | measure |
|---|---|---|
| false alarms ≤ 0.2/day full monitor | **not verifiable here** | A+B read a posteriori ≤ 0.186; the full monitor (with the rules) is phase 3 |
| false alarms ≤ 0.1/day crew only (45 d) | **not met** | A: 0.133/day (6 in 45 d; two repeated situations) |
| no signal during nominal exercise | **not met** | A: 3 (same case, MET 7.5 beyond training); B: 0 |
| event recall ≥ 0.8 overall | **met** | A 72/72; A+B 72/72; B alone 0.44 (label+person) |
| per type ≥ 6/8 on AF, SVT, bradycardia, fever | **met** (A and A+B), B alone no (SVT 4/8, bradycardia 3/8) | |
| median lead over the rules ≥ 5 min on CO and hypercapnia | **not assessable** | `crew_env` not done (phase 3) |
| mean cost per tick ≤ 4.7 ms | **met** | 4.26 → 4.32 ms/tick with the two crew detectors (+0.06) |
| 180 old + new tests, clean `ruff` | 209 passed, 3 skipped (190 + 19 new); `ruff` clean on the added files | |
| same hash of a run on two machines | **partial** | see §5 |

## 5. Twins and determinism

The twins (group `T`) were not in the phase-1 plan nor had they been generated: I generated them with the existing generator (`make_dataset.py
--only nominal --days 1,5 --features`, seeds 101-124, 131-138, 141-148) in `crew_T_pc` (11, on the PC: **my mistake**, it blocked the PC for a while; the rest
was redistributed), `crew_T_m5pro` (15) and `crew_T_m5` (14). The identity check on all 360 M/twin pairs before the start of the fault:
**243 pairs on the same platform (12 Windows-Windows, 231 Mac-Mac): difference exactly 0; 117 pairs between Windows and macOS: 80 differ by
at most 1.04e-7 relative (one float32 ulp) in 1-8 cells out of 551,040** (variances that cancel, slopes). On the user's instruction the check is now two
rules (same platform: 0; different platforms: ≤ 2 relative ulp, 2.4e-7), recorded in the model card (`info.medical.twin_identity`: counts the pairs used in training and validation, 324). The
old catalog (`output/ml/feat`, generated with an earlier version of the code) has differences of 3.7e-9 in `eva_P|sd10` even on the same platform: absolute
tolerance 1e-6, only for those pairs.

## 6. Online verification (Part C)

Test monitor `output/ml/monitor_crew_test.yaml` (generated by `tools/ml/make_crew_test_monitor.py`: the station monitor plus `ml_crew_slow` and
`ml_crew_fast` after the rules and the diagnoser on `station_v2`).

* **Parity** (`check_crew_parity.py`, seed 151 N3, 6 h): the score the detector computes online and the one `eval_crew.py` computes from the rows of
  `crew.parquet` of the same run differ by at most 1.5e-13 (slow) and 1e-14 (fast) over 330 comparisons; no emergency open. Threshold 1e-6: **met**.
  (Seed 151 is read, a test seed: I only saw the maximum score of the slow stage, 0.90, and tuned nothing.)
* **Cost** (6000 ticks, same session with and without the two crew detectors, PC idle): 4.26 → 4.32 ms/tick (+0.06). Before the optimizations
  it was +2.6 ms (14 scikit-learn `predict` calls per person and per evaluation, doubled for the two modes). In the whole day below the mean tick is 5.7 ms because the
  PC was also running the tests and the parity. **Threshold 4.7: met** in the isolated measure.
* **`check_monitor.py` on seed 151, 1 nominal day** (test, once): 2 emergencies opened, **none from stage A**:
  1. `medical:bot:1` at t = 42,220 s (11.7 h), existing rule on the core temperature 38.5 °C (the known exercise case, not new);
  2. `medical:bot:2` at t = 83,520 s (23.2 h), `respiratory_infection` diagnosis (86 %) from stage B on the person `bot` while asleep.
  The second is a stage B false alarm that the 43 days of `eval_medical` (2 alarms with a person, 0.046/day) made foreseeable as possible: B must be
  brought into phase 3 with the person from stage A and a higher threshold for respiratory infection.

## 7. Choices made without guidance

* `CrewFeatureExtractor.register` (6 lines in `crew.py`): the detector learns the wearable sensors from the observations, it does not have the layout.
* Schedule memory and scale regressor from the context, limits on the held level, cap at 0.95 × truncation, limit floors (z 3, D² 30, fast 4: ESTIMATE),
  untruncated fast statistic. Margin and `fast_factor` chosen with a half-half check on the validation besides the false alarms on N1 val.
* The evidence is in Italian ("FC 105 bpm, attesi 68 a riposo (z 6,1)") and carries the sign of z.
* The detector rounds the row to float32 before evaluating it (the dataset's precision): online = offline bit for bit.
* Cost: a single model shared between `slow` and `fast`, z shared between the two, and a numpy evaluation of the trees (14 forests per person together, equal to scikit-learn at 1e-12; falls back to `predict` for what it does not recognize); scikit-learn on 1 thread in the detector.
* `DiagnoserModel` now has `live` and `min_proba` per class (a loaded v1 model has all classes live and the detector's threshold).
* Dehydration is labelled with the declared fallback, the other classes with the twin k = 3.

## 8. Files that overlap with the phase-1 branch

`tools/ml/classes.yaml` (+4 classes), `scenarios/station/monitor.yaml` (regenerated, +8 lines: alert classes and `diagnosis` table),
`src/ares3/plugins/monitor/ml/crew.py` (+6 lines, `register`). No conflict expected if phase 1 did not touch them after `68aa4fd`.

## 9. What is left for phase 3

1. (done, §3b) crew detectors and gated medical diagnosis in the live monitor; still to check with the interface that it shows the evidence (the person with the values, then the class).
2. Comparison with the online rules (`check_monitor.py` R / R+A / R+A+B) on test runs, and the false alarms of the full monitor.
3. Quality of B's classes (stress/fever, AF/respiratory infection confusions): retrain B with stage A's z as inputs; the person is already settled by the gate.
4. The joint `crew_env` classes (hypercapnia, hypoxia, CO) on the wave-2 data (E, C, R1 already generated): not done.
5. If the user wants to close the two unmet stage-A criteria: widen the training jitter (MET up to 8.5, deeper sleep) and retrain; on the test one can only re-evaluate with new models and a new test.
