"""Crew stage A: the baseline model and its detector, on a SYNTHETIC model built here (no joblib file, no engine). A person who is
resting with ordinary vitals gives no signal; the heart rate 40 bpm too high at rest does; 140 bpm at 7 MET does not (the table of the
context says 132 is expected); the fast mode fires before the slow one; the detector never reads the true ``vitals``; and the
online score is the one the offline evaluation computes from the rows of the extractor."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ares3.plugins.monitor.ml import crew_baseline as cb
from ares3.plugins.monitor.ml.crew import ACT_NAMES, CLASSES, VITALS, CrewFeatureExtractor
from ares3.sdk import Observation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ml"))
import eval_crew as ec

NAMES = CrewFeatureExtractor(["a"], {}).names
EXPECTED = {"resp_rate": 15.0, "spo2": 98.0, "core_temp_c": 36.5, "skin_temp_c": 33.5, "hrv_rmssd": 40.0}
NOISE = {"hr": 1.0, "resp_rate": 0.5, "spo2": 0.5, "core_temp_c": 0.05, "skin_temp_c": 0.1, "hrv_rmssd": 2.0}
SIGMA = {"hr|lv10": 3.0, "resp_rate|lv10": 1.0, "spo2|lv10": 1.0, "core_temp_c|lv10": 0.1, "skin_temp_c|lv10": 0.3,
         "hrv_rmssd|lv10": 5.0, "hr|sd10": 0.3}


def hr_expected(met: float) -> float:
    return 60.0 + 12.0 * (met - 1.0)


class Toy:
    """The expected value of a quantity from the context: a straight line in the MET (what a fitted regressor would learn)."""

    def __init__(self, q: str) -> None:
        self.q = q

    def predict(self, ctx: np.ndarray) -> np.ndarray:
        met = np.nan_to_num(ctx[:, 0], nan=1.0)
        if self.q == "hr|lv10":
            return hr_expected(met)
        if self.q == "hr|sd10":
            return np.full(len(met), NOISE["hr"])
        return np.full(len(met), EXPECTED[self.q.split("|")[0]])


def toy_model(fast_factor: float = 1.0) -> cb.CrewBaselineModel:
    q = cb.QUANTITIES
    return cb.CrewBaselineModel(
        npc_ids=["a"], columns=list(NAMES), regressors={"a": {x: Toy(x) for x in q}},
        sigma={"a": np.repeat(np.asarray([[SIGMA[x]] for x in q]), len(CLASSES), axis=1)},
        precision={"a": np.eye(len(q))}, limit_d=40.0, limit_z=np.full(len(q), 4.0), fast_factor=fast_factor, limit_fast=np.full(2, 4.0), kind="table")


class _Npc:
    """A crew member as the tick shows him to a detector: the programme and the place. No ``vitals``: reading them is an error."""

    def __init__(self, met: float, activity: str) -> None:
        self.met, self.activity, self.module_id = met, activity, "NOD1"

    @property
    def vitals(self):
        raise AssertionError("the crew detector must not read the true vitals")


def stream(seconds, schedule, bias=None, seed=0):
    """(tick, observations) every second for one person; ``schedule(t) -> (met, activity)``; ``bias(t) -> {vital: offset}`` for the sensed values."""
    rng = np.random.default_rng(seed)
    for t in range(seconds):
        met, act = schedule(t)
        off = bias(t) if bias else {}
        obs = []
        for v in VITALS:
            mean = hr_expected(met) if v == "hr" else EXPECTED[v]
            val = mean + off.get(v, 0.0) + rng.normal(0.0, NOISE[v])
            obs.append(Observation(tick=t, t_s=float(t), sensor_id=f"a_{v}", entity_id="a", metric=v, value=val, value_true=val))
        tick = SimpleNamespace(t_sim_s=float(t), time_of_day_h=10.0, npcs={"a": _Npc(met, act)}, modules={"NOD1": None})
        yield SimpleNamespace(tick=tick), obs


def detector(monkeypatch, mode: str, model=None):
    model = model or toy_model()
    monkeypatch.setattr(cb, "load_model", lambda _path: model)
    d = cb.CrewBaselineDetector.from_config("crew_" + mode, {"model": "toy.joblib", "mode": mode}, np.random.default_rng(0),
                                            metric=None, targets=[])
    d.reset()
    return d


def first_signal(det, seconds, schedule, bias=None):
    for ctx, obs in stream(seconds, schedule, bias):
        sigs = det.detect(ctx, obs)
        if sigs:
            return ctx.tick.t_sim_s, sigs
    return None


REST = lambda t: (1.0, "work")


@pytest.mark.parametrize("mode", ["slow", "fast"])
def test_a_person_at_rest_with_ordinary_vitals_gives_no_signal(monkeypatch, mode):
    assert first_signal(detector(monkeypatch, mode), 2 * 3600, REST) is None


@pytest.mark.parametrize("mode", ["slow", "fast"])
def test_the_heart_rate_40_too_high_at_rest_is_a_signal_with_the_right_subject_and_evidence(monkeypatch, mode):
    t, sigs = first_signal(detector(monkeypatch, mode), 3600, REST, bias=lambda t: {"hr": 40.0})
    sig = sigs[0]
    assert t >= 1800.0  # the windows of the extractor are full after 30 min
    assert sig.emergency == "medical" and sig.subject == "a" and sig.module_id == "NOD1" and sig.cause == "crew_baseline"
    assert sig.evidence[0].startswith("FC 100 bpm, attesi 60 a riposo (z ")
    assert "a" in sig.detail and sig.value >= 1.0


def test_140_bpm_at_7_met_is_normal(monkeypatch):
    """The expected value at 7 MET is 132: 140 is 2.7 sigmas, under every limit. A fixed band would call it a fault."""
    exercise = lambda t: (7.0, "exercise_aerobic")
    for mode in ("slow", "fast"):
        assert first_signal(detector(monkeypatch, mode), 3 * 3600, exercise, bias=lambda t: {"hr": 8.0}) is None
    # and the same 140 bpm at rest is far out
    assert first_signal(detector(monkeypatch, "slow"), 3600, REST, bias=lambda t: {"hr": 80.0}) is not None


def test_fast_fires_before_slow_on_a_sudden_rise(monkeypatch):
    jump = lambda t: {"hr": 45.0 if t >= 2400 else 0.0}
    fast = first_signal(detector(monkeypatch, "fast"), 2 * 3600, REST, bias=jump)
    slow = first_signal(detector(monkeypatch, "slow"), 2 * 3600, REST, bias=jump)
    assert fast and slow and 2400 <= fast[0] < slow[0]


def test_only_the_clinical_direction_counts(monkeypatch):
    model = toy_model()
    row = np.asarray([0.0] * len(NAMES))
    pos = {c: i for i, c in enumerate(NAMES)}
    row[pos["ctx|met10"]] = row[pos["ctx|met_max30"]] = 1.0
    row[pos["ctx|act_nominal"]] = 1.0
    for q in cb.QUANTITIES:
        row[pos[q]] = float(Toy(q).predict(np.asarray([[1.0]]))[0])
    base = row.copy()
    high, low = row.copy(), row.copy()
    high[pos["spo2|lv10"]] += 3.0  # a better SpO2 than expected: nothing to say
    low[pos["spo2|lv10"]] -= 3.0
    assert model.score("a", high)[0] == pytest.approx(model.score("a", base)[0])
    stat, _z, text = model.score("a", low)
    assert stat > model.score("a", high)[0] and text.startswith("SpO2 95,0 %, attesi 98,0 a riposo (z -3,0)")
    cold = row.copy()
    cold[pos["core_temp_c|lv10"]] -= 0.5  # temperature only counts upwards
    assert model.score("a", cold)[0] == pytest.approx(model.score("a", base)[0])


def test_the_table_regressor_predicts_the_median_of_its_cell():
    rng = np.random.default_rng(0)
    n = 600
    ctx = np.zeros((n, len(cb.CTX_COLUMNS)))
    ctx[:, 0] = np.repeat([1.2, 6.5], n // 2)
    ctx[:, cb.CTX_COLUMNS.index("ctx|act_nominal")] = 1.0
    y = np.where(ctx[:, 0] > 5, 130.0, 62.0) + rng.normal(0, 1, n)
    reg = cb.TableRegressor.fit(ctx, y)
    probe = np.zeros((2, len(cb.CTX_COLUMNS)))
    probe[:, cb.CTX_COLUMNS.index("ctx|act_nominal")] = 1.0
    probe[:, 0] = [1.4, 6.9]
    assert reg.predict(probe) == pytest.approx([62.0, 130.0], abs=0.5)


def test_the_slow_score_online_is_the_offline_one(monkeypatch):
    """The detector and ``eval_crew`` run the same recursion: the score at every evaluation equals the offline exponential mean of the
    statistic of the extractor's rows."""
    model = toy_model()
    det = detector(monkeypatch, "slow", model)
    fx = CrewFeatureExtractor(["a"], {f"a_{v}": ("a", v) for v in VITALS})
    sched = lambda t: (1.0, "work")
    bias = lambda t: {"hr": 14.0 if t >= 2400 else 0.0}
    online, rows = [], []
    for ctx, obs in stream(2 * 3600, sched, bias, seed=3):
        det.detect(ctx, obs)
        fx.push(ctx.tick, obs)
        t = ctx.tick.t_sim_s
        if t % 60 == 0 and fx.ready(t):
            online.append(det.last_score)
            rows.append(fx.compute(t)["a"])
    z, _ = model.z_batch("a", np.asarray(rows, dtype=np.float32).astype(np.float64))  # as stored in crew.parquet
    stat, _, _ = model.stats("a", z)
    assert cb.ema(stat, 60.0, model.tau_s) == pytest.approx(online, abs=1e-9)
    # the offline alarm list built from the same series is the one the classifier would open
    ser = ec.NpcSeries("a", np.arange(len(rows)) * 60.0 + 1800.0, z, model._mask(z), np.zeros(len(rows), bool), np.zeros((len(rows), 7)), 60.0)
    assert ec.alarms_of(model, ser, "slow")


def test_the_detector_reads_no_vitals_and_forgets_a_repaired_person(monkeypatch):
    det = detector(monkeypatch, "slow")
    out = first_signal(det, 3600, REST, bias=lambda t: {"hr": 40.0})
    assert out is not None  # (the _Npc above raises if ``vitals`` is read)
    det.forget("a")
    assert not det._latched and "a" not in det._ema


def test_the_act_names_and_classes_the_model_relies_on_exist():
    assert len(ACT_NAMES) == len(CLASSES) == 5 and all(f"ctx|{a}" in NAMES for a in ACT_NAMES)


def test_the_memory_of_the_programme_is_the_same_batch_or_step_by_step():
    """The detector steps the memory one row at a time, the offline evaluation runs it down a column: the same numbers, bit for bit."""
    model = toy_model()
    mets = np.concatenate([np.full(40, 1.2), np.full(30, 7.0), np.full(120, 1.5)])
    X = np.zeros((len(mets), len(NAMES)))
    X[:, NAMES.index("ctx|met10")] = mets
    batch = model.memory(X)
    state = None
    for i, met in enumerate(mets):
        state = model.memory_step(state, float(met), 60.0)
        assert state == pytest.approx(batch[i], rel=0, abs=1e-12)
    assert batch[0] == pytest.approx([1.2, 1.2, 1.2])
    assert batch[-1][0] < batch[-1][1]  # two hours after the 7 MET the 30 min memory has forgotten it, the 120 min one has not


def test_the_stacked_forest_gives_what_scikit_learn_predicts():
    """The numpy walk of the live detector is the fitted model, to the rounding of the sum, with and without a missing value."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    rng = np.random.default_rng(1)
    X = rng.normal(size=(600, 6))
    X[rng.random(X.shape) < 0.03] = np.nan
    models = [HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, max_iter=40, early_stopping=False, random_state=k)
              .fit(X, np.nan_to_num(X[:, 0]) * (k + 1) + rng.normal(size=600)) for k in range(3)]
    stack = cb._StackedForest.try_build(models)
    assert stack is not None
    for row in np.vstack([X[:25], np.full((1, 6), np.nan)]):
        want = [m.predict(row[None, :])[0] for m in models]
        assert stack.predict(row) == pytest.approx(want, abs=1e-9)
    assert cb._StackedForest.try_build([cb.TableRegressor({}, {}, 0.0)]) is None  # anything it does not know falls back


class _FeverClf:
    classes_ = np.asarray(["fever", "nominal"])

    def predict_proba(self, row):
        return np.asarray([[0.9, 0.1]])


def _gated_detector(monkeypatch, gate: str | None):
    """A real ``DiagnosisDetector`` with a model that always says fever, whose explanation points to ``cmd``."""
    import joblib

    from ares3.plugins.monitor.ml.diagnoser import DiagnoserModel, DiagnosisDetector
    from ares3.plugins.monitor.ml.features import FeatureExtractor

    fx = FeatureExtractor(["s1"])
    model = DiagnoserModel(keys=["s1"], columns=list(fx.names), clock_periods_s=(), mean=np.zeros(len(fx.names)), scale=np.ones(len(fx.names)),
                           families={"medical": _FeverClf()}, signatures={"fever": np.ones(len(fx.names))}, sensor_info={"s1": ("npc", "cmd")},
                           phrases={"fever": "Raised core temperature"})
    monkeypatch.setattr(joblib, "load", lambda _p: model)
    params = {"model": "x.joblib", "min_proba": 0.6, **({"gate_board": gate} if gate else {})}
    det = DiagnosisDetector.from_config("diag", params, np.random.default_rng(0), metric=None, targets=[])
    det.reset()
    return det


def _run_diagnosis(det, seconds=11000):
    last = []
    npcs = {"cmd": SimpleNamespace(module_id="NOD1"), "eng": SimpleNamespace(module_id="USL")}
    for t in range(seconds):
        obs = [Observation(tick=t, t_s=float(t), sensor_id="s1", entity_id="m", metric="X", value=5.0, value_true=5.0)]
        last = det.detect(SimpleNamespace(tick=SimpleNamespace(t_sim_s=float(t), npcs=npcs, modules={"NOD1": None, "USL": None})), obs)
    return last


def test_the_medical_diagnosis_speaks_only_while_the_baseline_flags_somebody_and_names_that_person(monkeypatch):
    cb.BOARD.clear()
    alone = _run_diagnosis(_gated_detector(monkeypatch, None))
    assert alone and alone[0].subject == "cmd" and alone[0].cause == "fever"  # without the gate: the person the explanation points to

    cb.BOARD["crew"] = {"ml_crew_slow": {}, "ml_crew_fast": {}}
    assert _run_diagnosis(_gated_detector(monkeypatch, "crew")) == []  # the baseline sees nobody: no diagnosis of its own

    cb.BOARD["crew"] = {"ml_crew_slow": {"eng": 1.4}, "ml_crew_fast": {"cmd": 1.1, "eng": 2.5}}
    cb.EVIDENCE["crew"] = {"eng": ("FC 150 bpm, attesi 63 a riposo (z 10,0)",)}
    gated = _run_diagnosis(_gated_detector(monkeypatch, "crew"))
    assert gated[0].evidence == ("FC 150 bpm, attesi 63 a riposo (z 10,0)", "Raised core temperature")  # the person's values first, the class last
    assert gated and gated[0].subject == "eng" and gated[0].module_id == "USL" and gated[0].cause == "fever"  # the person the baseline flags most
    assert cb.flagged("crew") == {"eng": 2.5, "cmd": 1.1}
    cb.BOARD.clear()
    cb.EVIDENCE.clear()


def test_the_crew_detector_publishes_who_it_flags_on_its_board(monkeypatch):
    cb.BOARD.clear()
    model = toy_model()
    monkeypatch.setattr(cb, "load_model", lambda _path: model)
    det = cb.CrewBaselineDetector.from_config("crew_slow", {"model": "x", "mode": "slow", "board": "b"}, np.random.default_rng(0), metric=None, targets=[])
    det.reset()
    assert cb.flagged("b") == {}
    first_signal(det, 3600, REST, bias=lambda t: {"hr": 40.0})
    assert set(cb.flagged("b")) == {"a"} and cb.flagged("b")["a"] >= 1.0
    det.forget("a")
    assert cb.flagged("b") == {}
    cb.BOARD.clear()
