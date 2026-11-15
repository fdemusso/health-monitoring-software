"""The feature extractor is shared by the online detector and the dataset generator: check what each feature means."""

import numpy as np
import pytest

from ares3.plugins.monitor.ml.features import STATS, FeatureExtractor, select

HOURS = 7 * 3600  # long enough for the 6 h window to be mostly filled


def _run(gen, keys=("a",), seconds=HOURS, periods=()):
    fx = FeatureExtractor(keys, periods)
    for t in range(seconds):
        fx.push(float(t), gen(t))
    return fx, fx.compute(float(seconds))


def _stat(fx, row, key, stat):
    return row[fx.names.index(f"{key}|{stat}")]


def test_noise_count_and_level_independence():
    rng = np.random.default_rng(1)
    fx, row = _run(lambda t: [("a", 5.0 + rng.normal(0, 0.2))])
    assert _stat(fx, row, "a", "sd10") == pytest.approx(0.2, rel=0.1)
    assert _stat(fx, row, "a", "n10") == pytest.approx(600, abs=10)
    assert abs(_stat(fx, row, "a", "d10")) < 0.05 and abs(_stat(fx, row, "a", "sl6h")) < 0.01  # a flat signal
    assert np.isfinite(row).all()


def test_a_ramp_shows_in_the_slopes():
    fx, row = _run(lambda t: [("a", 1e-3 * t / 3600.0)])  # 1e-3 per hour
    assert _stat(fx, row, "a", "sl1h") == pytest.approx(1e-3, rel=0.02)
    assert _stat(fx, row, "a", "sl6h") == pytest.approx(1e-3, rel=0.02)


def test_a_stuck_sensor_has_no_noise_and_a_silent_one_no_samples():
    rng = np.random.default_rng(2)
    fx, row = _run(lambda t: [("ok", rng.normal()), ("stuck", 3.0)] + ([("half", 1.0)] if t % 2 else []),
                   keys=("ok", "stuck", "half"))
    assert _stat(fx, row, "stuck", "sd10") == 0.0 and _stat(fx, row, "ok", "sd10") > 0.5
    assert _stat(fx, row, "half", "n10") == pytest.approx(300, abs=10)


def test_not_ready_before_half_the_longest_window_and_unknown_keys_are_ignored():
    fx = FeatureExtractor(["a"])
    for t in range(3 * 3600 - 10):
        fx.push(float(t), [("a", 1.0), ("other", 9.0)])
    assert not fx.ready(3 * 3600 - 10)
    fx.push(3 * 3600.0, [])
    assert fx.ready(3 * 3600.0)


def test_chunking_does_not_change_the_row():
    """Pushing the same stream tick by tick or with a sensor split in two pushes gives the same numbers."""
    rng = np.random.default_rng(3)
    data = [(t, rng.normal(0, 1, 2)) for t in range(HOURS)]
    a, b = FeatureExtractor(["x", "y"], (86400.0, 5568.0)), FeatureExtractor(["x", "y"], (86400.0, 5568.0))
    for t, v in data:
        a.push(float(t), [("x", v[0]), ("y", v[1])])
        b.push(float(t), [("y", v[1])])
        b.push(float(t), [("x", v[0])])
    assert np.array_equal(a.compute(float(HOURS)), b.compute(float(HOURS)), equal_nan=True)


def test_select_takes_a_groups_slice_and_the_clock():
    fx = FeatureExtractor(["a", "b"], (86400.0,))
    cols = select(fx.names, ["b"])
    assert [fx.names[i].split("|")[0] for i in cols] == ["b"] * len(STATS) + ["clock"] * 2
