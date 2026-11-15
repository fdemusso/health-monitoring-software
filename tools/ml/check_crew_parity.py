"""Online = offline for the crew stage A: run a nominal scenario with the test monitor and compare the score the detector publishes in
``tick.ml`` with the score ``eval_crew.py`` computes from the ``crew.parquet`` rows of the SAME run (the extractor run on the same ticks
without a monitor, stored as float32 like the dataset). Valid while no emergency opens (the response would change the programme).

    uv run python tools/ml/make_crew_test_monitor.py --diagnoser models/station_v1/diagnoser.joblib
    uv run python tools/ml/check_crew_parity.py --seed 151 --hours 6
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: list[str] | None = None) -> int:
    import yaml

    from ares3.core.engine import Engine
    from ares3.plugins.monitor.ml.crew import CrewFeatureExtractor, crew_sensor_map
    from ares3.plugins.monitor.ml.crew_baseline import ema, load_model
    from ares3.schemas.monitor import MonitorConfig
    from ares3.schemas.scenario import load_scenario

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=151)
    p.add_argument("--hours", type=float, default=6.0)
    p.add_argument("--scenario", default=str(ROOT / "scenarios" / "station" / "nominal.yaml"))
    p.add_argument("--monitor", default=str(ROOT / "output" / "ml" / "monitor_crew_test.yaml"))
    p.add_argument("--model", default=str(ROOT / "models" / "station_v2" / "crew_baseline.joblib"))
    args = p.parse_args(argv)

    model = load_model(args.model)
    ticks = round(args.hours * 3600.0)

    def scenario(monitor: bool):
        sc = load_scenario(args.scenario)
        sc.file.seed = args.seed
        sc.monitor = (MonitorConfig.model_validate(yaml.safe_load(Path(args.monitor).read_text(encoding="utf-8")))
                      if monitor else MonitorConfig())
        return sc

    # ---- online: the scores the detectors publish, and what it cost
    sc = scenario(True)
    online, opened = {}, set()
    t0 = time.perf_counter()
    engine = Engine(sc)
    for res in engine.run(ticks):
        t = res.tick.t_sim_s
        if t % 60 == 0 and "ml_crew_slow" in res.tick.ml:  # the detectors' own scores, not the ones rounded for the tick
            score = {d.id: d.last_score for d in engine.monitor.detectors if d.id in ("ml_crew_slow", "ml_crew_fast")}
            online[t] = (score["ml_crew_slow"], score.get("ml_crew_fast"))
        opened.update(e.id for e in res.tick.emergencies)
    ms = 1000.0 * (time.perf_counter() - t0) / ticks
    print(f"online: {len(online)} scores, {len(opened)} emergencies opened, {ms:.1f} ms/tick (the whole monitor)")

    # ---- offline: the rows of the extractor on a run without a monitor, as float32 (what crew.parquet holds)
    sc = scenario(False)
    cx = CrewFeatureExtractor([m.id for m in sc.crew.members], crew_sensor_map(sc.layout.sensors))
    rows: dict[str, list] = {n: [] for n in cx.npc_ids}
    times = []
    for res in Engine(sc).run(ticks):
        cx.push(res.tick, res.observations)
        t = res.tick.t_sim_s
        if t % 60 == 0 and cx.ready(t):
            times.append(t)
            for npc, vec in cx.compute(t).items():
                rows[npc].append(vec.astype(np.float32))
    slow = np.zeros(len(times))
    fast = np.zeros(len(times))
    for npc, vecs in rows.items():
        if npc not in model.regressors:
            continue
        X = np.asarray(vecs, dtype=np.float32).astype(np.float64)
        z, _ = model.z_batch(npc, X)
        stat, _, _ = model.stats(npc, z)
        slow = np.maximum(slow, ema(stat, 60.0, model.tau_s))
        fast = np.maximum(fast, model.fast_stat(z))
    d_slow = max((abs(online[t][0] - s) for t, s in zip(times, slow, strict=True) if t in online), default=float("nan"))
    d_fast = max((abs(online[t][1] - f) for t, f in zip(times, fast, strict=True) if t in online and online[t][1] is not None), default=float("nan"))
    compared = sum(t in online for t in times)
    print(f"offline: {len(times)} rows; compared {compared}; max |online - offline|: slow {d_slow:.3g}, fast {d_fast:.3g} "
          f"; max slow score {slow.max():.3f}, max fast {fast.max():.3f}")
    print("PARITY OK (< 1e-6)" if d_slow < 1e-6 and (np.isnan(d_fast) or d_fast < 1e-6) and not opened else "PARITY NOT PROVEN (see above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
