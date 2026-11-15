"""Stage A: a PCA trained on nominal features flags a sensor that stops following its redundant twin, and the detector
reports it from SENSED samples only. Synthetic two-sensor subsystem, no engine."""

import sys
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from ares3.plugins.monitor.ml.anomaly import AnomalyDetector, load_model
from ares3.plugins.monitor.ml.features import FeatureExtractor
from ares3.sdk import Observation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ml"))
import train_anomaly as ta

HOURS = 3600
KEYS = ["x_a", "x_b", "x_c"]


def _stream(seed, seconds, fault_at=None):
    """Three sensors of one place: a shared slow signal, their own noise; from ``fault_at`` x_a drifts away."""
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 0.002, seconds))
    for t in range(seconds):
        drift = 0.0 if fault_at is None or t < fault_at else 4e-5 * (t - fault_at)
        yield t, [("x_a", 5.0 + common[t] + rng.normal(0, 0.05) + drift), ("x_b", 5.2 + common[t] + rng.normal(0, 0.05)),
                  ("x_c", 4.9 + common[t] + rng.normal(0, 0.05))]


def _rows(seed, seconds=10 * HOURS):
    fx = FeatureExtractor(KEYS)
    rows = []
    for t, samples in _stream(seed, seconds):
        fx.push(float(t), samples)
        if fx.ready(float(t)) and t % 60 == 0:
            rows.append(fx.compute(float(t)))
    return fx, pd.DataFrame(rows, columns=fx.names)


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    fx, train = _rows(1)
    model = ta.fit_group("toy", KEYS, [train, _rows(2)[1]], fx.names, ())
    peaks = model.scores(_rows(3)[1][model.columns].to_numpy())
    model.t2_limit, model.spe_limit = 1.25 * peaks[0].max(), 1.25 * peaks[1].max()
    path = tmp_path_factory.mktemp("model") / "detector_toy.joblib"
    joblib.dump(model, path)
    return path


def _detector(path):
    d = AnomalyDetector.from_config("ml_toy", {"model": str(path)}, np.random.default_rng(0), metric=None, targets=[])
    d.reset()
    return d


def _run(det, seed, seconds, fault_at=None):
    fired = []
    for t, samples in _stream(seed, seconds, fault_at):
        obs = [Observation(tick=t, t_s=float(t), sensor_id=s, entity_id="m", metric="X", value=v, value_true=v)
               for s, v in samples]
        ctx = SimpleNamespace(tick=SimpleNamespace(t_sim_s=float(t), modules={"m": None}))
        sigs = det.detect(ctx, obs)
        if sigs:
            fired.append((t, sigs[0]))
    return fired


def test_the_model_saves_and_loads_with_its_limits(model_path):
    m = load_model(model_path)
    assert m.group == "toy" and m.keys == KEYS and m.t2_limit > 0 and m.spe_limit > 0
    assert m.components.shape[1] == len(m.columns)


def test_nominal_run_stays_quiet_and_a_drifting_sensor_is_flagged(model_path):
    assert not _run(_detector(model_path), seed=7, seconds=10 * HOURS)  # a seed the model never saw
    fault = 6 * HOURS
    fired = _run(_detector(model_path), seed=7, seconds=12 * HOURS, fault_at=fault)
    assert fired and fired[0][0] > fault  # never before the fault
    t, sig = fired[0]
    assert sig.emergency == "anomaly" and sig.module_id == "m" and "x_a" in sig.detail and "toy" in sig.detail
    assert t - fault < 4 * HOURS  # a few ppm of drift per hour is seen within hours


def test_same_stream_gives_the_same_signals(model_path):
    a = _run(_detector(model_path), seed=9, seconds=9 * HOURS, fault_at=5 * HOURS)
    b = _run(_detector(model_path), seed=9, seconds=9 * HOURS, fault_at=5 * HOURS)
    assert [(t, s.detail) for t, s in a] == [(t, s.detail) for t, s in b]
