"""The crew dataset: the job list of ``tools/ml/crew_plan.yaml`` (the same on every machine) and the crew features (online = offline)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ml"))  # spawned workers inherit sys.path and import the module by name
import crew_plan as cp
import make_dataset as md

from ares3.plugins.monitor.ml.crew import CrewFeatureExtractor, activity_class, crew_sensor_map
from ares3.schemas.crew import CrewMember

PLAN = ROOT / "tools" / "ml" / "crew_plan.yaml"


@pytest.fixture(scope="module")
def plan() -> dict:
    p = cp.load_plan(PLAN)
    for g in p["groups"].values():  # E4 may be switched off by the probe: its jobs must be valid anyway
        g.pop("enabled", None)
    return p


@pytest.fixture(scope="module")
def waves(plan) -> dict[int, list[dict]]:
    return {w: cp.build_plan_jobs(plan, w, Path("out")) for w in (1, 2)}


def test_the_list_is_deterministic_and_the_ids_unique(plan, waves):
    for w, jobs in waves.items():
        assert jobs == cp.build_plan_jobs(plan, w, Path("out"))
        assert cp.jobs_hash(jobs) == cp.jobs_hash(cp.build_plan_jobs(plan, w, Path("out")))
        ids = [md.job_id(j) for j in jobs]
        assert len(set(ids)) == len(ids) and all(i.startswith("crew-") and i.endswith("_f") for i in ids)
        assert all(j["out"].endswith(md.job_id(j)) for j in jobs)


def test_the_order_is_train_then_val_then_test_and_r1_is_last(waves):
    for jobs in waves.values():
        rank = [cp.SPLIT_ORDER.index(j["split"]) for j in jobs if j["group"] != "R1"]
        assert rank == sorted(rank)
    r1 = [i for i, j in enumerate(waves[2]) if j["group"] == "R1"]
    assert r1 == list(range(len(waves[2]) - len(r1), len(waves[2])))


def test_the_shards_of_the_three_machines_partition_the_list(waves):
    for jobs in waves.values():
        shards = [md.shard_jobs(jobs, s) for s in ("0,1,2,3,4,5,6,7,8,9/16", "10,11,12,13/16", "14,15/16")]
        got = sorted(md.job_id(j) for s in shards for j in s)
        assert got == sorted(md.job_id(j) for j in jobs)  # nobody twice, nobody missing


def test_every_module_npc_and_file_of_every_job_exists(plan, waves):
    """The trap: one unknown module drops the whole process, so every name is checked against the station before the launch."""
    sc = cp._scenario(str(md.NOMINAL))
    modules, npcs = {m.id for m in sc.layout.modules}, {m.id for m in sc.crew.members}
    for g in plan["groups"].values():
        for spec in [g, *g.get("variants", [])]:
            med = cp._medical_spec(spec, plan)
            if med:
                assert (ROOT / med["faults_file"]).is_file()
            for fid in spec.get("catalog", []):
                assert (md.FAULTS / f"{fid}.yaml").is_file() and (md.EVENTS / f"{fid}.yaml").is_file()
    for jobs in waves.values():
        for j in jobs:
            assert Path(j["scenario"]).is_file() and j["npc"] in npcs | {None}
            for f in j.get("faults", []):
                assert set(f["targets"]) <= modules | npcs, (md.job_id(j), f["targets"])
            assert j["module"] in modules | {None}
            assert set(j.get("crew_schedule", {})) <= npcs
            for fid in j.get("extra_faults", []):
                assert (md.FAULTS / f"{fid}.yaml").is_file()


def test_the_jitter_keeps_a_valid_programme():
    sc = cp._scenario(str(md.NOMINAL))
    catalog = cp._metabolic_catalog(sc)
    for seed in range(50):
        rng = np.random.default_rng([seed, 1])
        for m in sc.crew.members:
            blocks = cp.schedule_of(m)
            moved = cp.jitter_schedule(blocks, rng, 30.0, (0.85, 1.15), catalog)
            CrewMember.model_validate({**m.model_dump(by_alias=True), "schedule": moved})  # covers 0-24, no gap, no overlap
            assert moved[0]["from"] == 0.0 and moved[-1]["to"] == 24.0
            assert [b["activity"] for b in moved] == [b["activity"] for b in blocks]  # same blocks, same order
            assert all((b["to"] - b["from"]) * 60 >= 10.0 for b in moved)  # every block keeps 10 min
            assert all(abs(b["to"] - o["to"]) <= 0.5 + 1e-6 for b, o in zip(moved[:-1], blocks, strict=False))  # +-30 min
            assert all(b["met"] > 0 for b in moved)


def test_the_drawn_start_is_inside_a_block_of_the_requested_activity(waves):
    """Checked with the ``SimClock`` of the engine, not with the arithmetic of the plan: t = 0 is 06:00, not midnight."""
    from ares3.core.clock import SimClock

    sc = cp._scenario(str(md.NOMINAL))
    sched = {m.id: cp.schedule_of(m) for m in sc.crew.members}
    checked = 0
    for jobs in waves.values():
        for j in jobs:
            if not j.get("npc"):
                continue
            checked += 1
            assert not j["start_fallback"], md.job_id(j)
            start = j["drawn"]["start_s"]
            dur = max(j["drawn"]["durations_s"].values())
            assert 6 * 3600 <= start <= j["days"] * 86400 - dur - 4 * 3600
            clock = SimClock(dt_s=1.0, day_length_s=86400.0, start_tod_h=sc.file.start_time_of_day_h, tick=int(start))
            tod = clock.time_of_day_h
            blocks = j.get("crew_schedule", sched)[j["npc"]]
            block = next(b for b in blocks if b["from"] <= tod < b["to"])
            assert activity_class(block["activity"]) in cp.CLASSES_OF[j["activity_wanted"]], md.job_id(j)
            assert (block["to"] - tod) * 3600 >= cp.MIN_TAIL_S - 1.0
            assert block["activity"] == j["activity_at_start"] and block["module"] == j["module"]
            assert j["module"] not in ("eva", "lifeboat") or not any(f["type"].endswith("_source") for f in j["faults"])
    assert checked > 400  # the medical groups, the exposures and the combinations


def test_the_person_and_the_activity_follow_the_seed(waves):
    for j in (j for jobs in waves.values() for j in jobs if j["group"].startswith("M") and j["group"] != "M9"):
        assert j["npc"] == cp.PEOPLE[j["seed"] % 4]
        assert j["activity_wanted"] == cp.ROTATION[(j["seed"] // 4) % 3]
    assert {j["activity_at_start"] for j in waves[1] if j["group"] == "M9"} == {"exercise_aerobic"}


def test_a_plan_job_is_a_features_job_with_its_own_faults(waves):
    j = next(j for j in waves[1] if j["group"] == "M3" and j["seed"] == 101)
    assert j["features"] and j["faults"][0]["targets"] == [j["npc"]] and j["faults"][0]["id"].startswith(j["npc"])
    assert 130 <= j["faults"][0]["params"]["hr_to"] <= 170 and 600 <= j["faults"][0]["duration_s"] <= 3600
    assert j["faults"][0]["params"]["arrhythmia"] == "af"  # what the range does not name stays as the event file has it


def _tick(t, npcs, tod=6.0):
    return SimpleNamespace(t_sim_s=t, time_of_day_h=tod, npcs={k: SimpleNamespace(met=m, activity=a) for k, (m, a) in npcs.items()})


def test_the_crew_extractor_reads_the_context_on_synthetic_ticks():
    sensors = [SimpleNamespace(id=f"{n}_hr", target=f"npc:{n}", metric="hr") for n in ("a", "b")]
    cx = CrewFeatureExtractor(["a", "b"], crew_sensor_map(sensors))
    idx = {n: i for i, n in enumerate(cx.names)}
    for t in range(4000):  # a: sleeps 0-1000 s, exercises 2000-2300 s at 7 MET, then works; b always works at 1.5 MET
        a = (0.9, "sleep") if t < 1000 else (7.0, "exercise_aerobic") if 2000 <= t < 2300 else (1.5, "work")
        obs = [SimpleNamespace(sensor_id="a_hr", value=60.0 + (t % 3)), SimpleNamespace(sensor_id="b_hr", value=float("nan"))]
        cx.push(_tick(float(t), {"a": a, "b": (1.5, "meal")}), obs)
        if t == 1700:
            assert cx.ready(float(t)) is False
    assert cx.ready(3999.0)
    fa, fb = (cx.compute(3999.0)[n] for n in ("a", "b"))
    assert fa[idx["ctx|met_max30"]] == 7.0 and fb[idx["ctx|met_max30"]] == 1.5
    assert fa[idx["ctx|min_since_ex"]] == pytest.approx((3999 - 2299) / 60.0) and fb[idx["ctx|min_since_ex"]] == 120.0
    assert [fa[idx[f"ctx|{n}"]] for n in ("act_sleep", "act_nominal", "act_aerobic", "act_resistive", "act_recovery")] == [0, 1, 0, 0, 0]
    assert fa[idx["ctx|min_since_sleep"]] == 0.0  # awake
    assert 59.0 < fa[idx["hr|lv10"]] < 63.0 and fa[idx["hr|sd10"]] > 0.5
    assert np.isnan(fb[idx["hr|lv10"]])  # a lost sample is simply missing
    assert fa[idx["clock|sin"]] == pytest.approx(1.0) and len(fa) == cx.n_features == len(cx.names)
    # asleep: minutes since the sleep began, from the first tick of sleep
    cx2 = CrewFeatureExtractor(["a"], {})
    for t in range(2400):
        cx2.push(_tick(float(t), {"a": (0.9, "sleep")}), [])
    assert cx2.compute(2399.0)["a"][cx2.names.index("ctx|min_since_sleep")] == pytest.approx(2399 / 60.0)


def test_the_rows_of_a_run_are_the_rows_of_the_extractor_run_by_hand(tmp_path):
    """Online = offline: ``crew.parquet`` of a short run on the test habitat holds what ``CrewFeatureExtractor`` gives on the same ticks."""
    import pandas as pd

    from ares3.core.engine import Engine
    from ares3.schemas.monitor import MonitorConfig

    job = {"scenario": str(ROOT / "scenarios" / "events" / "debug_station.yaml"), "seed": 3, "days": 1.0, "ticks": 2400,
           "features": True, "out": str(tmp_path / "run")}
    out = Path(md.run_one(job))
    df = pd.read_parquet(out / "crew.parquet")
    sc, ticks = md._prepare(job)
    sc.monitor = MonitorConfig()
    cx = CrewFeatureExtractor([m.id for m in sc.crew.members], crew_sensor_map(sc.layout.sensors))
    rows = []
    for res in Engine(sc).run(ticks):
        cx.push(res.tick, res.observations)
        if cx.ready(res.tick.t_sim_s) and res.tick.tick % 60 == 0:
            rows += [(res.tick.t_sim_s, n, v) for n, v in cx.compute(res.tick.t_sim_s).items()]
    assert len(df) == len(rows) and rows
    np.testing.assert_array_equal(df[cx.names].to_numpy(), np.asarray([v for _, _, v in rows], dtype=np.float32))
    assert df["t_s"].tolist() == [r[0] for r in rows] and df["npc"].tolist() == [r[1] for r in rows]
    truth = [c for c in df.columns if c.startswith("truth|")]
    assert len(truth) == 10 and not df[truth].isna().any().any()  # the truth is there, and apart from the features
    assert not set(truth) & set(cx.names)
    assert out.joinpath("features.parquet").is_file() and md.features_hash(out) == md.features_hash(out)


def test_a_run_shorter_than_the_warmup_writes_empty_files_with_the_columns(tmp_path):
    import pandas as pd

    job = {"scenario": str(ROOT / "scenarios" / "events" / "debug_station.yaml"), "seed": 3, "days": 1.0, "ticks": 120,
           "features": True, "out": str(tmp_path / "short")}
    out = Path(md.run_one(job))
    crew, feat = pd.read_parquet(out / "crew.parquet"), pd.read_parquet(out / "features.parquet")
    assert len(crew) == len(feat) == 0 and {"t_s", "npc", "hr|lv10", "truth|module", "truth|activity"} <= set(crew.columns)
    assert "faults" in feat.columns
