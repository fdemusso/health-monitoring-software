"""Dataset generator for the ML alert model: one simulation per job, many jobs in parallel.

A job is a plain dict (no Engine or Scenario crosses a process boundary)::

    {"scenario": "scenarios/station/events/F-SEN-DERIVA-CO2.yaml", "seed": 3, "days": 3.0, "out": "output/ml/<id>",
     "fault_overrides": {"start_s": 7200, "params": {...}}}      # optional, merged into every fault of the scenario

``run_one(job)`` builds the Engine, runs it and writes the dataset of that job with ``DatasetWriter`` (long + wide
Parquet). With ``"features": true`` it writes instead one row of ML features every ``eval_every_s`` (the SAME
``FeatureExtractor`` the detector runs online, so there is no gap between training and inference), plus the active faults. The engine is a deterministic sequential loop (one root seed, one stream per component), so it is NEVER split:
only independent jobs run side by side, and a job gives the same rows with 1 worker or 16.

A job may also carry ``"per_fault": {fault id: {"start_s": .., "params": {..}, "scale": ..}}`` (the values drawn for ONE run from the ranges of
the workbook, ``scenarios/station/fault_ranges.yaml``), ``"faults_file"`` + ``"amp"`` (a medical event of ``scenarios/events`` injected
on the station crew, amplitude +-30 %: plan D2) and ``"extra_faults"`` (a second catalog fault on top of the first: a combination, D10).

    uv run python tools/ml/make_dataset.py --seeds 1-3 --days 3 --workers 8
    uv run python tools/ml/make_dataset.py --only F-SEN-DERIVA-CO2,F-FIS-PERDITA-PRK --seeds 1 --days 1 --resume
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import multiprocessing as mp
import os
import shutil
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "scenarios" / "station" / "events"
NOMINAL = ROOT / "scenarios" / "station" / "nominal.yaml"
DEFAULT_OUT = ROOT / "output" / "ml"
FAULTS = ROOT / "scenarios" / "station" / "faults"
RANGES = ROOT / "scenarios" / "station" / "fault_ranges.yaml"
MEDICAL_DIR = ROOT / "scenarios" / "events"
MEDICAL = ["fever", "dehydration", "fibrillation", "motion_sickness", "stress"]  # events that act on the crew, not on a module (co2_release targets `hab`, the small habitat)
SCALED = ("core_temp_delta", "skin_temp_delta", "fluid_loss_pct_per_h", "hr_delta", "resp_delta", "mol_s")  # amplitudes of a medical event
START_RANGE_S = (6 * 3600.0, 30 * 3600.0)  # plan D9: the fault starts anywhere between 6 and 30 h
# pairs of catalog faults at the same time: the two of the guide (sec. 6.1: a sensor drift on a degrading scrubber; the PrK leak while the
# PCA is closed) and two of ours (an ageing O2 cell with a weaker OGA; the IMV and the cabin fan, both actuators: a limit of one-per-family)
COMBOS = [("F-SEN-DERIVA-CO2", "F-ATT-CDRA-DEGRADO"), ("F-FIS-PERDITA-PRK", "F-ATT-PCA-CHIUSA"),
          ("F-SEN-INVECCHIA-O2", "F-ATT-OGA-STACK"), ("F-ATT-IMV-FOD", "F-ATT-CQFAN-FOD")]


def job_id(job: dict) -> str:
    """Stable name of a job: scenario stem, seed and length (a ``ticks`` job is named by its ticks)."""
    length = f"t{job['ticks']}" if job.get("ticks") else f"d{job['days']:g}"
    name = "+".join([Path(job["scenario"]).stem, *job.get("extra_faults", [])]) if job.get("extra_faults") else Path(job["scenario"]).stem
    if job.get("faults_file"):
        name = f"med-{Path(job['faults_file']).stem.removesuffix('_faults')}"
    return f"{name}_s{job['seed']}_{length}" + ("_r" if job.get("per_fault") else "") + ("_f" if job.get("features") else "")


def _catalog_faults(fid: str) -> list:
    import yaml

    from ares3.schemas.faults import FaultSpec

    return [FaultSpec.model_validate(f) for f in yaml.safe_load((FAULTS / f"{fid}.yaml").read_text(encoding="utf-8"))["faults"]]


def _apply(fault, patch: dict) -> None:
    from ares3.schemas.scenario import deep_merge

    if "start_s" in patch:
        fault.start_s = float(patch["start_s"])
    if "params" in patch:
        fault.params = deep_merge(fault.params, patch["params"])
    if "scale" in patch:  # a leak whose rate is quoted as ``kg_day`` and / or ``steps``: all of it scales
        k = float(patch["scale"])
        p = dict(fault.params)
        if "kg_day" in p:
            p["kg_day"] = float(p["kg_day"]) * k
        if "steps" in p:
            p["steps"] = [[t, float(r) * k] for t, r in p["steps"]]
        fault.params = p


def _prepare(job: dict):
    """Scenario of a job (seed, fault overrides applied) and its length in ticks."""
    import yaml

    from ares3.schemas.faults import FaultSpec
    from ares3.schemas.scenario import load_scenario

    sc = load_scenario(job["scenario"])
    sc.file.seed = int(job["seed"])  # every component derives its stream from this one seed
    for fid in job.get("extra_faults", []):  # a second catalog fault on top of the first (a combination)
        sc.faults.faults.extend(_catalog_faults(fid))
    if job.get("faults_file"):  # a medical event of Luca's, on the station crew
        raw = yaml.safe_load(Path(job["faults_file"]).read_text(encoding="utf-8"))["faults"]
        amp = float(job.get("amp", 1.0))
        for f in raw:
            spec = FaultSpec.model_validate(f)
            spec.params = {k: (float(v) * amp if k in SCALED else v) for k, v in spec.params.items()}
            if "start_s" in job:
                spec.start_s = float(job["start_s"])
            sc.faults.faults.append(spec)
    patch = job.get("fault_overrides") or {}
    per_fault = job.get("per_fault") or {}
    for fault in sc.faults.faults:
        _apply(fault, patch)
        _apply(fault, per_fault.get(fault.id, {}))
    ticks = job.get("ticks") or round(float(job["days"]) * sc.environment.day_length_s / sc.file.dt_s)
    return sc, ticks


def _publish(tmp: Path, out: Path) -> str:
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    return str(out)


def run_one(job: dict) -> str:
    """Run one job and return the directory of its dataset. Written to ``<out>.tmp`` and renamed at the end, so a
    directory that exists is a complete one (``--resume`` relies on it)."""
    if job.get("features"):
        return run_features(job)
    from ares3.core.engine import Engine
    from ares3.export import DatasetWriter

    sc, ticks = _prepare(job)
    out = Path(job["out"])
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    writer = DatasetWriter(tmp, sc)
    try:
        for res in Engine(sc).run(ticks):
            writer.add(res)
    finally:
        writer.close()
    return _publish(tmp, out)


def run_features(job: dict) -> str:
    """One row of ML features every ``eval_every_s`` (default 60 s), for EVERY sensor of the scenario, run WITHOUT the
    monitor (pure signatures, and the twin run of a fault is exact). ``features.parquet`` has the columns ``t_s``, the
    feature names, and ``faults`` (ids of the faults active at that time, ``|`` separated); ``meta.json`` describes the
    run (the faults with their targets, label, start; the feature names; the clock periods)."""
    import json

    import numpy as np
    import pandas as pd

    from ares3.core.engine import Engine
    from ares3.plugins.monitor.ml.features import FeatureExtractor, clock_periods, tick_samples
    from ares3.schemas.monitor import MonitorConfig

    sc, ticks = _prepare(job)
    sc.monitor = MonitorConfig()
    every = float(job.get("eval_every_s", 60.0))
    fx = FeatureExtractor([s.id for s in sc.layout.sensors], clock_periods(sc.environment))
    t_rows, rows, active = [], [], []
    for res in Engine(sc).run(ticks):
        t = res.tick.t_sim_s
        fx.push(t, tick_samples(res.tick, res.observations))
        if fx.ready(t) and res.tick.tick % round(every / sc.file.dt_s) == 0:
            t_rows.append(t)
            rows.append(fx.compute(t))
            active.append("|".join(res.tick.active_faults))
    out = Path(job["out"])
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    df = pd.DataFrame(np.asarray(rows, dtype=np.float32).reshape(len(rows), fx.n_features), columns=fx.names)
    df.insert(0, "t_s", np.asarray(t_rows))
    df["faults"] = active
    df.to_parquet(tmp / "features.parquet", index=False)
    meta = {"job": {k: v for k, v in job.items() if k != "out"}, "eval_every_s": every, "n_rows": len(rows),
            "clock_periods_s": list(clock_periods(sc.environment)), "dt_s": sc.file.dt_s,
            "faults": {f.id: {"label": f.label, "type": f.type, "category": f.category, "targets": list(f.targets),
                              "start_s": f.start_s, "duration_s": f.duration_s, "priority": f.priority, "params": f.params}
                       for f in sc.faults.faults}}
    (tmp / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return _publish(tmp, out)


def rows_hash(out_dir: str | Path) -> str:
    """Hash of the VALUES of a dataset (long format), independent of Parquet file metadata."""
    import pandas as pd

    h = hashlib.sha256()
    for part in sorted((Path(out_dir) / "long").glob("part-*.parquet")):
        df = pd.read_parquet(part)
        h.update(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes())
    return h.hexdigest()


def run_jobs(jobs: list[dict], workers: int, resume: bool = False, log=print) -> dict[str, str]:
    """Run ``jobs`` on ``workers`` processes (``spawn``: the only start method on Windows, and the safest elsewhere).
    Returns ``{job id: dataset directory}``; with ``resume`` the jobs whose directory already exists are skipped."""
    done: dict[str, str] = {}
    todo = []
    for job in jobs:
        if resume and Path(job["out"]).is_dir():
            done[job_id(job)] = job["out"]
        else:
            todo.append(job)
    if resume and done:
        log(f"resume: {len(done)} of {len(jobs)} jobs already written")
    if not todo:
        return done
    os.environ.setdefault("OMP_NUM_THREADS", "1")  # inherited by the workers: one run = one core, no BLAS oversubscription
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    t0 = time.perf_counter()
    if workers <= 1:
        for i, job in enumerate(todo, 1):
            done[job_id(job)] = run_one(job)
            log(f"[{i}/{len(todo)}] {job_id(job)} ({time.perf_counter() - t0:.0f} s)")
        return done
    with cf.ProcessPoolExecutor(max_workers=min(workers, len(todo)), mp_context=mp.get_context("spawn")) as pool:
        futures = {pool.submit(run_one, job): job for job in todo}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            job = futures[fut]
            done[job_id(job)] = fut.result()  # a failed job raises here, with its own traceback
            log(f"[{i}/{len(todo)}] {job_id(job)} ({time.perf_counter() - t0:.0f} s)")
    return done


def parse_seeds(text: str) -> list[int]:
    """``1,2,5`` or ``1-3`` or ``1-3,7``."""
    seeds: list[int] = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        seeds += range(int(a), int(b or a) + 1)
    return seeds


def draw_catalog(fid: str, seed: int, ranges: dict) -> dict[str, dict]:
    """The values of ONE run of catalog fault ``fid``: a start time in [6 h, 30 h] and a value in each range of the sheet. Drawn
    from (seed, fault id), so the same job is the same job everywhere. Returns ``{fault id: {start_s, params, scale}}``."""
    import numpy as np

    rng = np.random.default_rng([int(seed), zlib.crc32(fid.encode())])
    start = float(rng.uniform(*START_RANGE_S))
    out = {f.id: {"start_s": start} for f in _catalog_faults(fid)}
    for knob in ranges.get(fid, []):
        entry = out[knob["fault"]]
        if "scale" in knob:
            entry["scale"] = float(rng.uniform(knob["min"], knob["max"]))
        elif "choose" in knob:  # a subset of the modules
            n = int(rng.integers(round(knob["min"]), round(knob["max"]) + 1))
            pick = sorted(rng.choice(knob["from"], size=n, replace=False).tolist())
            entry.setdefault("params", {})[knob["choose"].removeprefix("params.")] = pick
        else:
            v = float(rng.uniform(knob["min"], knob["max"])) * float(knob.get("factor", 1.0))
            if knob.get("sign") and rng.random() < 0.5:
                v = -v
            entry.setdefault("params", {})[knob["set"].removeprefix("params.")] = v
    return out


def build_jobs(seeds: list[int], days: float, only: list[str] | None, out: Path, nominal: bool,
               ticks: int | None = None, features: bool = False, randomize: bool = False, medical: bool = False,
               combos: bool = False) -> list[dict]:
    """One job per (fault, seed); ``only`` restricts the faults (ids as in ``scenarios/station/events``); ``nominal`` adds the
    fault-free run of each seed (the twin of every fault with that seed, and the detector's baseline); ``randomize`` draws the start
    and the parameters of each run from the ranges of the workbook; ``medical`` adds the medical events on the station crew;
    ``combos`` the pairs of faults."""
    import yaml

    available = {p.stem: p for p in sorted(EVENTS.glob("*.yaml"))}
    if only == ["nominal"]:  # the fault-free runs alone
        nominal, only, available = True, None, {}
    if only:
        unknown = [f for f in only if f not in available]
        if unknown:
            raise SystemExit(f"unknown fault(s) {unknown}; known: {', '.join(available)}")
        chosen = {f: available[f] for f in only}
    else:
        chosen = available
    ranges = yaml.safe_load(RANGES.read_text(encoding="utf-8")) if randomize else {}
    base: list[dict] = [{"scenario": str(NOMINAL)}] if nominal else []
    base += [{"scenario": str(path)} for path in chosen.values()]
    if combos:
        base += [{"scenario": str(available[a]), "extra_faults": [b]} for a, b in COMBOS]
    if medical:
        base += [{"scenario": str(NOMINAL), "faults_file": str(MEDICAL_DIR / f"{m}_faults.yaml")} for m in MEDICAL]
    jobs = []
    for seed in seeds:
        for spec in base:
            job = {**spec, "seed": seed, "days": days}
            if ticks:
                job["ticks"] = ticks
            if features:
                job["features"] = True
            if randomize:
                fid = Path(spec["scenario"]).stem
                if fid in available:
                    job["per_fault"] = draw_catalog(fid, seed, ranges)
                    for second in spec.get("extra_faults", []):
                        job["per_fault"].update(draw_catalog(second, seed + 1000, ranges))
                if spec.get("faults_file"):  # amplitude +-30 %, start between 6 and 30 h (D2)
                    import numpy as np

                    rng = np.random.default_rng([int(seed), zlib.crc32(Path(spec["faults_file"]).stem.encode())])
                    job["amp"], job["start_s"] = float(rng.uniform(0.7, 1.3)), float(rng.uniform(*START_RANGE_S))
            job["out"] = str(out / job_id(job))
            jobs.append(job)
    return jobs


def shard_jobs(jobs: list[dict], spec: str) -> list[dict]:
    """``"0,1,2/10"``: the jobs at positions 0, 1, 2 modulo 10. The list is built the same way on every machine, and positions
    interleave the long and the short runs, so equal shards cost about the same."""
    mine, _, n = spec.partition("/")
    wanted, total = {int(x) for x in mine.split(",")}, int(n)
    if total < 1 or not wanted or not all(0 <= w < total for w in wanted):
        raise SystemExit(f"--shard {spec!r}: expected K[,K...]/N with 0 <= K < N")
    return [j for i, j in enumerate(jobs) if i % total in wanted]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate labelled station datasets, one process per simulation")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="processes (default: cores - 1)")
    p.add_argument("--seeds", default="1", help="e.g. 1-3 or 1,2,5")
    p.add_argument("--days", type=float, default=3.0, help="simulated days per run")
    p.add_argument("--only", help="comma-separated fault ids (F-SEN-DERIVA-CO2,...); default: all 26; ``nominal``: no faults")
    p.add_argument("--nominal", action="store_true", help="also run the fault-free station for each seed")
    p.add_argument("--resume", action="store_true", help="skip the jobs whose dataset is already written")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--ticks", type=int, help="override --days with a number of ticks (smoke tests)")
    p.add_argument("--randomize", action="store_true", help="draw each fault's start and parameters from the workbook ranges")
    p.add_argument("--medical", action="store_true", help="add the medical events (fever, dehydration, ...) on the station crew")
    p.add_argument("--combos", action="store_true", help="add the four pairs of faults")
    p.add_argument("--features", action="store_true", help="write ML feature rows (features.parquet) instead of the raw dataset")
    p.add_argument("--shard", help="split the job list over several machines: e.g. 0,1,2/10 takes the jobs whose position is 0, 1 or 2 "
                                   "modulo 10 (every machine gets the same list and takes its own shards)")
    args = p.parse_args(argv)
    jobs = build_jobs(parse_seeds(args.seeds), args.days, args.only.split(",") if args.only else None,
                      Path(args.out), args.nominal, args.ticks, args.features,
                      args.randomize, args.medical, args.combos)
    if args.shard:
        jobs = shard_jobs(jobs, args.shard)
    print(f"{len(jobs)} jobs on {min(args.workers, len(jobs))} workers -> {args.out}")
    t0 = time.perf_counter()
    run_jobs(jobs, args.workers, args.resume)
    print(f"done in {time.perf_counter() - t0:.0f} s")
    return 0


if __name__ == "__main__":  # the guard keeps the spawned workers from running main() again
    sys.exit(main())
