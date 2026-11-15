"""Run scenarios WITH the monitoring system and report what it opened: false alarms on nominal days, detection delays on
faults. One process per run (``spawn``), like ``make_dataset.py``.

    uv run python tools/ml/check_monitor.py --nominal --seeds 6-8 --days 1
    uv run python tools/ml/check_monitor.py --only F-SEN-BLOCCO,F-SEN-DERIVA-CO2 --seeds 5 --days 1

The delay is from the START of the fault to the CONFIRMATION of the first emergency opened afterwards (the classifier's
``confirm_s`` is included); ``-`` means never. Emergencies opened before the fault start are false alarms.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_dataset import build_jobs, parse_seeds

MONITOR = ROOT / "scenarios" / "station" / "monitor.yaml"


def check_one(job: dict) -> dict:
    """Run one job with the station monitor; return plain data: the emergencies and mode changes, and the cost per tick."""
    import yaml

    from ares3.core.engine import Engine
    from ares3.schemas.monitor import MonitorConfig
    from ares3.schemas.scenario import load_scenario

    sc = load_scenario(job["scenario"])
    sc.file.seed = int(job["seed"])
    sc.monitor = MonitorConfig.model_validate(yaml.safe_load(Path(job.get("monitor") or MONITOR).read_text(encoding="utf-8")))
    ticks = job.get("ticks") or round(float(job["days"]) * sc.environment.day_length_s / sc.file.dt_s)
    events, modes, opened = [], [], {}
    t0 = time.perf_counter()
    for res in Engine(sc).run(ticks):
        for e in res.tick.monitor_events:
            if e.kind in ("emergency_opened", "emergency_confirmed"):
                events.append((e.t_s, e.kind, e.emergency_id, e.message))
            elif e.kind == "mode_changed":
                modes.append((e.t_s, e.message))
        for em in res.tick.emergencies:
            opened.setdefault(em.id, (em.kind, em.module_id, em.subject, em.cause, em.alert_class))
    return {"job": job["scenario"], "seed": job["seed"], "ticks": ticks, "events": events, "modes": modes, "emergencies": opened,
            "faults": {f.id: {"start_s": f.start_s, "label": f.label} for f in sc.faults.faults},
            "ms_per_tick": 1000.0 * (time.perf_counter() - t0) / ticks}


def summarise(r: dict) -> str:
    name = Path(r["job"]).stem
    starts = [f["start_s"] for f in r["faults"].values()]
    t_fault = min(starts) if starts else None
    confirmed = [(t, i) for t, k, i, _ in r["events"] if k == "emergency_confirmed"]
    opened = [(t, i) for t, k, i, _ in r["events"] if k == "emergency_opened"]
    false = [(t, i) for t, i in opened if t_fault is None or t < t_fault]
    line = f"{name} s{r['seed']}: {len(opened)} opened, {len(false)} before any fault, {r['ms_per_tick']:.1f} ms/tick"
    if t_fault is not None:
        hits = [(t, i) for t, i in confirmed if t >= t_fault]
        line += "; first confirmed after the fault: " + (
            f"{hits[0][0] - t_fault:.0f} s ({hits[0][1]})" if hits else "-")
    for t, i in false[:6]:
        line += f"\n    false alarm t={t:.0f}: {i}: " + next(m for tt, k, ii, m in r["events"] if ii == i and k == "emergency_opened")
    return line


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--seeds", default="5")
    p.add_argument("--days", type=float, default=1.0)
    p.add_argument("--ticks", type=int)
    p.add_argument("--only", help="comma-separated fault ids")
    p.add_argument("--nominal", action="store_true", help="include the fault-free station")
    p.add_argument("--monitor", help="monitor YAML (default: scenarios/station/monitor.yaml)")
    args = p.parse_args(argv)
    only = args.only.split(",") if args.only else (["nominal"] if args.nominal else None)
    jobs = build_jobs(parse_seeds(args.seeds), args.days, only, Path("."), args.nominal and bool(args.only), args.ticks)
    for j in jobs:
        j["monitor"] = args.monitor
    print(f"{len(jobs)} runs on {min(args.workers, len(jobs))} workers")
    with cf.ProcessPoolExecutor(max_workers=min(args.workers, len(jobs)), mp_context=mp.get_context("spawn")) as pool:
        for fut in cf.as_completed([pool.submit(check_one, j) for j in jobs]):
            print(summarise(fut.result()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
