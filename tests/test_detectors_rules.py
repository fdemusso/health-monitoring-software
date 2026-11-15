"""Rule detectors that double as features of the ML monitor: stuck / noisy sensor, redundant sensors that disagree,
early warning score. Synthetic streams, no engine."""

from types import SimpleNamespace

import numpy as np

from ares3.plugins.monitor.detectors import EarlyWarningScore, RedundancyResidual, Variance, news_points
from ares3.sdk import Observation

H = 3600


def _obs(t, sensor, entity, metric, value):
    return Observation(tick=int(t), t_s=float(t), sensor_id=sensor, entity_id=entity, metric=metric, value=value,
                       value_true=value)


def _make(cls, params, metric, targets):
    d = cls.from_config("d", params, np.random.default_rng(0), metric=metric, targets=targets)
    d.reset()
    return d


def _ctx(t, npcs=None):
    return SimpleNamespace(tick=SimpleNamespace(t_sim_s=float(t), npcs=npcs or {}))


def _fires(det, stream, seconds):
    """Seconds at which the detector fired. ``stream(t) -> list[Observation]``."""
    return [t for t in range(seconds) if det.detect(_ctx(t), stream(t))]


def test_variance_flags_stuck_and_noisy_sensors_but_not_healthy_ones():
    rng = np.random.default_rng(1)
    start = 5 * H
    det = _make(Variance, {}, "T", ["m"])
    seen = set()
    for t in range(8 * H):
        for s in det.detect(_ctx(t), [_obs(t, "ok", "m", "T", 21 + rng.normal(0, 0.05)),
                                         _obs(t, "stuck", "m", "T", 21.3 if t >= start else 21 + rng.normal(0, 0.05)),
                                         _obs(t, "noisy", "m", "T", 21 + rng.normal(0, 0.4 if t >= start else 0.05))]):
            seen.add(s.subject)
            assert s.emergency == "sensor_fault" and s.module_id == "m"
    assert seen == {"stuck", "noisy"}  # and never the healthy one, nor before the faults


def test_redundancy_residual_follows_the_change_not_the_fixed_offset():
    rng = np.random.default_rng(2)
    start = 4 * H

    def stream(bias):
        return lambda t: [_obs(t, "a", "m", "P", 101.0 + 0.05 + rng.normal(0, 0.05) + (bias if t >= start else 0.0)),
                          _obs(t, "b", "m", "P", 101.0 - 0.07 + rng.normal(0, 0.05))]  # the two units differ by 0.12 for good
    healthy = _make(RedundancyResidual, {"max_change": 0.15}, "P", ["m"])
    assert not _fires(healthy, stream(0.0), 7 * H)
    faulty = _make(RedundancyResidual, {"max_change": 0.15}, "P", ["m"])
    fires = _fires(faulty, stream(-0.3), 7 * H)
    assert fires and min(fires) >= start
    sig = faulty.detect(_ctx(7 * H), stream(-0.3)(7 * H))[0]
    assert sig.subject == "a~b" and sig.module_id == "m"  # two sensors: the pair, the culprit is not known


def test_redundancy_residual_names_the_culprit_among_three():
    rng = np.random.default_rng(3)
    det = _make(RedundancyResidual, {"max_change": 0.2}, "ppCO2", ["m"])
    culprits = set()
    for t in range(7 * H):
        obs = [_obs(t, s, "m", "ppCO2", 2.0 + off + rng.normal(0, 0.03) + (0.5 if s == "c" and t > 4 * H else 0.0))
               for s, off in (("a", 0.0), ("b", 0.05), ("c", -0.02))]
        culprits |= {s.subject for s in det.detect(_ctx(t), obs)}
    assert culprits == {"c"}


def test_news2_bands():
    assert news_points("spo2", 97) == 0 and news_points("spo2", 91) == 3 and news_points("hr", 120) == 2
    assert news_points("resp_rate", 12) == 0 and news_points("core_temp_c", 39.5) == 2


def _crew(t, hr=60.0, spo2=98.0, rr=14.0, temp=36.8, met=1.0, state=0.0):
    npcs = {"x": SimpleNamespace(module_id="USL", met=met)}
    obs = [_obs(t, f"x_{m}", "x", m, v) for m, v in
           (("hr", hr), ("spo2", spo2), ("resp_rate", rr), ("core_temp_c", temp), ("health_state", state))]
    return _ctx(t, npcs), obs


def _run_ews(det, seconds=600, **vitals):
    out = []
    for t in range(seconds):
        ctx, obs = _crew(t, **vitals)
        out += det.detect(ctx, obs)
    return out


def test_early_warning_score_resting_exercise_and_hypoxia():
    warn = lambda: _make(EarlyWarningScore, {"min_score": 5}, None, ["x"])
    assert not _run_ews(warn())  # a resting, healthy person
    assert not _run_ews(warn(), hr=150.0, rr=30.0, met=6.0)  # exercise: heart and breathing rates are not scored
    sigs = _run_ews(warn(), spo2=88.0)  # one parameter at 3 points
    assert sigs and sigs[0].subject == "x" and sigs[0].module_id == "USL" and sigs[0].emergency == "medical"
    crit = lambda: _make(EarlyWarningScore, {"min_score": 7, "single_3": False}, None, ["x"])
    assert not _run_ews(crit(), spo2=88.0)  # 3 points only
    assert _run_ews(crit(), spo2=88.0, hr=125.0, temp=39.5, rr=26.0)  # 3 + 2 + 2 + 3 = 10
    assert _run_ews(crit(), state=2.0, spo2=88.0, rr=7.0)  # consciousness 3 + 3 + 3


def test_early_warning_score_waits_for_the_recovery_after_exercise():
    det = _make(EarlyWarningScore, {"min_score": 5, "exercise_recovery_s": 600}, None, ["x"])
    fired = []
    for sec in range(2400):
        met = 6.0 if sec < 600 else 1.0  # exercise, then rest with the heart and breathing still fast
        ctx, obs = _crew(sec, hr=125.0, rr=23.0, temp=38.3, met=met)
        if det.detect(ctx, obs):
            fired.append(sec)
    assert fired and min(fired) >= 600 + 600 - 5  # blind while exercising and during the recovery, then it speaks
