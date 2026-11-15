"""The dataset generator runs independent simulations in parallel and must not change a single row."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ml"))  # spawned workers inherit sys.path and import the module by name
import make_dataset as md

TICKS = 300  # five minutes: enough rows to compare, cheap enough for four processes


def _jobs(out: Path) -> list[dict]:
    """Four different jobs: another seed, another fault, the fault-free run. The fault starts inside the window."""
    spec = [("F-SEN-DERIVA-CO2", 1), ("F-SEN-DERIVA-CO2", 2), ("F-FIS-PERDITA-PRK", 1), (None, 1)]
    jobs = []
    for fault, seed in spec:
        scenario = md.EVENTS / f"{fault}.yaml" if fault else md.NOMINAL
        job = {"scenario": str(scenario), "seed": seed, "days": 1.0, "ticks": TICKS,
               "fault_overrides": {"start_s": 60.0}}
        job["out"] = str(out / md.job_id(job))
        jobs.append(job)
    return jobs


def test_job_ids_are_unique_and_stable(tmp_path):
    ids = [md.job_id(j) for j in _jobs(tmp_path)]
    assert len(set(ids)) == 4 and ids[0] == f"F-SEN-DERIVA-CO2_s1_t{TICKS}"


def test_same_jobs_give_the_same_rows_with_1_and_4_workers(tmp_path):
    serial = md.run_jobs(_jobs(tmp_path / "w1"), workers=1, log=lambda *_: None)
    parallel = md.run_jobs(_jobs(tmp_path / "w4"), workers=4, log=lambda *_: None)
    assert serial.keys() == parallel.keys() and len(serial) == 4
    for jid in serial:
        assert md.rows_hash(serial[jid]) == md.rows_hash(parallel[jid]), jid
    assert len({md.rows_hash(d) for d in serial.values()}) == 4  # and the jobs really differ from each other


def test_fault_overrides_reach_the_engine(tmp_path):
    import pandas as pd

    (job,) = [j for j in _jobs(tmp_path) if "PERDITA-PRK" in j["scenario"]]
    plain = md.run_one({**job, "out": str(tmp_path / "a")})
    later = md.run_one({**job, "out": str(tmp_path / "b"), "fault_overrides": {"start_s": TICKS + 100.0}})
    a = pd.concat(pd.read_parquet(p) for p in sorted(Path(plain, "long").glob("part-*.parquet")))
    b = pd.concat(pd.read_parquet(p) for p in sorted(Path(later, "long").glob("part-*.parquet")))
    assert a["is_anomaly"].any() and not b["is_anomaly"].any()  # the label follows the overridden start


def test_resume_skips_what_is_written(tmp_path):
    jobs = _jobs(tmp_path)[:1]
    msgs: list[str] = []
    md.run_jobs(jobs, workers=1, log=msgs.append)
    out = Path(jobs[0]["out"])
    stamp = (out / "manifest.json").stat().st_mtime_ns
    md.run_jobs(jobs, workers=1, resume=True, log=msgs.append)
    assert (out / "manifest.json").stat().st_mtime_ns == stamp  # untouched
    assert any("already written" in m for m in msgs)
    assert not list(tmp_path.glob("*.tmp"))  # nothing half-written is left behind


def test_only_rejects_an_unknown_fault(tmp_path):
    with pytest.raises(SystemExit, match="unknown fault"):
        md.build_jobs([1], 1.0, ["F-NOPE"], tmp_path, nominal=False)


def test_parse_seeds():
    assert md.parse_seeds("1-3,7") == [1, 2, 3, 7]
