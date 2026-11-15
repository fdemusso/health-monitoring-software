"""Dataset generator for the ML alert model: one simulation per job, many jobs in parallel.

A job is a plain dict (no Engine or Scenario crosses a process boundary)::

    {"scenario": "scenarios/station/events/F-SEN-DERIVA-CO2.yaml", "seed": 3, "days": 3.0, "out": "output/ml/<id>",
     "fault_overrides": {"start_s": 7200, "params": {...}}}      # optional, merged into every fault of the scenario

``run_one(job)`` builds the Engine, runs it and writes the dataset of that job with ``DatasetWriter`` (long + wide
Parquet). The engine is a deterministic sequential loop (one root seed, one stream per component), so it is NEVER split:
only independent jobs run side by side, and a job gives the same rows with 1 worker or 16.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "scenarios" / "station" / "events"
NOMINAL = ROOT / "scenarios" / "station" / "nominal.yaml"
DEFAULT_OUT = ROOT / "output" / "ml"


def job_id(job: dict) -> str:
    """Stable name of a job: scenario stem, seed and length (a ``ticks`` job is named by its ticks)."""
    length = f"t{job['ticks']}" if job.get("ticks") else f"d{job['days']:g}"
    return f"{Path(job['scenario']).stem}_s{job['seed']}_{length}"


def run_one(job: dict) -> str:
    """Run one job and return the directory of its dataset. Written to ``<out>.tmp`` and renamed at the end, so a
    directory that exists is a complete one (``--resume`` relies on it)."""
    from ares3.core.engine import Engine
    from ares3.export import DatasetWriter
    from ares3.schemas.scenario import deep_merge, load_scenario

    sc = load_scenario(job["scenario"])
    sc.file.seed = int(job["seed"])  # every component derives its stream from this one seed
    patch = job.get("fault_overrides") or {}
    for fault in sc.faults.faults:
        if "start_s" in patch:
            fault.start_s = float(patch["start_s"])
        if "params" in patch:
            fault.params = deep_merge(fault.params, patch["params"])
    ticks = job.get("ticks") or round(float(job["days"]) * sc.environment.day_length_s / sc.file.dt_s)

    out = Path(job["out"])
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    writer = DatasetWriter(tmp, sc)
    try:
        for res in Engine(sc).run(ticks):
            writer.add(res)
    finally:
        writer.close()
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    return str(out)


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


def build_jobs(seeds: list[int], days: float, only: list[str] | None, out: Path, nominal: bool,
               ticks: int | None = None) -> list[dict]:
    """One job per (fault, seed); ``only`` restricts the faults (ids as in ``scenarios/station/events``);
    ``nominal`` adds the fault-free run of each seed (the twin of every fault with that seed, and the detector's baseline)."""
    available = {p.stem: p for p in sorted(EVENTS.glob("*.yaml"))}
    if only:
        unknown = [f for f in only if f not in available]
        if unknown:
            raise SystemExit(f"unknown fault(s) {unknown}; known: {', '.join(available)}")
        chosen = {f: available[f] for f in only}
    else:
        chosen = available
    scenarios = ([NOMINAL] if nominal else []) + list(chosen.values())
    jobs = []
    for seed in seeds:
        for path in scenarios:
            job = {"scenario": str(path), "seed": seed, "days": days}
            if ticks:
                job["ticks"] = ticks
            job["out"] = str(out / job_id(job))
            jobs.append(job)
    return jobs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate labelled station datasets, one process per simulation")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="processes (default: cores - 1)")
    p.add_argument("--seeds", default="1", help="e.g. 1-3 or 1,2,5")
    p.add_argument("--days", type=float, default=3.0, help="simulated days per run")
    p.add_argument("--only", help="comma-separated fault ids (F-SEN-DERIVA-CO2,...); default: all 26")
    p.add_argument("--nominal", action="store_true", help="also run the fault-free station for each seed")
    p.add_argument("--resume", action="store_true", help="skip the jobs whose dataset is already written")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--ticks", type=int, help="override --days with a number of ticks (smoke tests)")
    args = p.parse_args(argv)
    jobs = build_jobs(parse_seeds(args.seeds), args.days, args.only.split(",") if args.only else None,
                      Path(args.out), args.nominal, args.ticks)
    print(f"{len(jobs)} jobs on {min(args.workers, len(jobs))} workers -> {args.out}")
    t0 = time.perf_counter()
    run_jobs(jobs, args.workers, args.resume)
    print(f"done in {time.perf_counter() - t0:.0f} s")
    return 0


if __name__ == "__main__":  # the guard keeps the spawned workers from running main() again
    sys.exit(main())
