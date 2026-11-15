"""The medical family of the diagnoser on the crew dataset: the decision rule with per-class thresholds and the ``live`` flag, the choice
of the twin (by seed, length and programme, never by seed alone) and the identity check that stops the training when a run and its
twin differ before the fault. Synthetic, no engine."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ml"))
import medical
from crew_data import CrewRun

from ares3.plugins.monitor.ml.diagnoser import DiagnoserModel


class _Clf:
    classes_ = np.asarray(["abnormal_exertion", "bradycardia", "nominal", "svt_suspected"])


def _model(**kw) -> DiagnoserModel:
    return DiagnoserModel(keys=[], columns=[], clock_periods_s=(), mean=np.zeros(1), scale=np.ones(1), families={"medical": _Clf()},
                          signatures={}, sensor_info={}, **kw)


PROBA = np.asarray([[0.10, 0.20, 0.60, 0.10],    # nominal wins: the best class is bradycardia at 0.20, under any threshold
                    [0.05, 0.05, 0.10, 0.80],    # svt at 0.80
                    [0.70, 0.05, 0.20, 0.05]])   # abnormal_exertion at 0.70


def test_the_rule_applies_the_threshold_of_each_class():
    label, p = _model().decide("medical", PROBA, default=0.6)
    assert list(label) == ["nominal", "svt_suspected", "abnormal_exertion"] and p == pytest.approx([0.20, 0.80, 0.70])
    label, _ = _model(min_proba={"abnormal_exertion": 0.9, "svt_suspected": 0.5}).decide("medical", PROBA, default=0.6)
    assert list(label) == ["nominal", "svt_suspected", "nominal"]  # the class that asks for more stays quiet


def test_a_class_that_is_not_live_is_ignored_even_when_it_is_the_most_likely():
    model = _model(live={"svt_suspected": False})
    label, p = model.decide("medical", PROBA, default=0.6)
    assert list(label) == ["nominal", "nominal", "abnormal_exertion"] and p[1] == pytest.approx(0.05)  # the next live class, far under
    assert medical.best_live(model, PROBA)[0][1] != "svt_suspected"


def test_a_model_saved_before_the_fields_existed_has_every_class_live_and_the_default_threshold():
    model = _model()
    del model.live, model.min_proba  # what an unpickled v1 model looks like
    assert model.is_live("fever") and model.threshold("fever", 0.7) == 0.7


def _run(tmp_path: Path, name: str, seed: int, days: float, faults: dict | None, jitter: bool, group: str = "M3") -> CrewRun:
    d = tmp_path / name
    d.mkdir()
    job = {"seed": seed, "days": days, "group": group, **({"crew_schedule": {}} if jitter else {})}
    (d / "meta.json").write_text(json.dumps({"job": job, "faults": faults or {}}), encoding="utf-8")
    return CrewRun(d, {"job": job, "faults": faults or {}})


def test_the_twin_is_the_nominal_run_of_the_same_seed_without_jitter_and_long_enough(tmp_path):
    fault = {"f": {"label": "svt_suspected", "start_s": 7200.0, "duration_s": 600.0, "targets": ["cmd"]}}
    run = _run(tmp_path, "m", 101, 1.5, fault, jitter=False)
    n1 = _run(tmp_path, "n1", 101, 2.0, None, jitter=True, group="N1")  # same seed, other programme: NOT a twin
    short = _run(tmp_path, "short", 101, 1.0, None, jitter=False, group="T")
    ok = _run(tmp_path, "ok", 101, 1.5, None, jitter=False, group="T")
    longer = _run(tmp_path, "longer", 101, 3.0, None, jitter=False, group="")
    other = _run(tmp_path, "other", 102, 1.5, None, jitter=False, group="T")
    twins = medical.twin_index([run, n1, short, ok, longer, other])
    assert medical.find_twin(run, twins) is ok  # the shortest that is long enough
    assert medical.find_twin(_run(tmp_path, "m2", 103, 1.5, fault, jitter=False), twins) is None
    assert n1 not in twins[101] and run not in twins[101]


def _write(run: CrewRun, rows: int, shift_after: float | None = None, tiny: bool = False) -> None:
    t = np.arange(rows, dtype=float) * 60.0
    f = np.sin(t / 900.0).astype(np.float32)
    if shift_after is not None:
        f = np.where(t >= shift_after, f + (1e-6 if tiny else 5.0), f).astype(np.float32)
    pd.DataFrame({"t_s": t, "f": f}).to_parquet(run.path / "features.parquet", index=False)
    pd.DataFrame({"t_s": t, "npc": "cmd", "hr|lv10": f}).to_parquet(run.path / "crew.parquet", index=False)


def test_the_identity_check_passes_when_the_runs_agree_until_the_fault_and_stops_when_they_do_not(tmp_path):
    medical._checked.clear()
    fault = {"f": {"label": "svt_suspected", "start_s": 6000.0, "duration_s": 600.0, "targets": ["cmd"]}}
    run = _run(tmp_path, "run", 101, 1.5, fault, jitter=False)
    twin = _run(tmp_path, "twin", 101, 1.5, None, jitter=False, group="T")
    _write(twin, 200)
    _write(run, 200, shift_after=6000.0)  # different only from the start of the fault: the normal case
    medical.check_identity(run, twin)
    medical._checked.clear()
    _write(run, 200, shift_after=3000.0, tiny=True)  # a difference of 1e-6 BEFORE the fault: the determinism does not hold
    with pytest.raises(medical.TwinMismatch):
        medical.check_identity(run, twin)


def test_only_the_nominal_rows_are_thinned_and_the_dropped_ones_never_used():
    y = np.asarray(["nominal"] * 10 + ["fever"] * 7 + ["drop"] * 3 + ["nominal"] * 5, dtype=object)
    keep = medical.keep_rows(y, 5)
    assert keep[y == "fever"].all() and not keep[y == "drop"].any()
    assert keep[y == "nominal"].sum() == 3  # rows 0, 5 and 20 of the 25
