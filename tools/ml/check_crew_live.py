"""The LIVE station monitor (scenarios/station/monitor.yaml: rules + crew baseline + diagnosis gated by it) on a whole run with, optionally, one
medical event, and what it opened: kind, person, cause, colour, and when, against the start of the event. A demo-day check.

    uv run python tools/ml/check_crew_live.py --event none --days 1 --seed 5      # a nominal day: no alarm expected from the crew models
    uv run python tools/ml/check_crew_live.py --event af --npc cmd --days 0.4     # atrial fibrillation of 25 min at 5 h
    uv run python tools/ml/check_crew_live.py --event fever --npc eng --days 1.2  # fever of 4 h at 7 h
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

EVENTS = {
    "af": {"start_s": 18000.0, "duration_s": 1500.0, "anomaly_type": "atrial_fibrillation_suspected", "priority": 8,
           "params": {"hr_to": 150.0, "spo2_to": 93.0, "arrhythmia": "af", "resp_delta": 3, "ramp_s": 40.0}},
    "fever": {"start_s": 25200.0, "duration_s": 14400.0, "anomaly_type": "fever", "priority": 6,
              "params": {"core_temp_delta": 1.4, "skin_temp_delta": 0.9, "hrv_factor": 0.8, "ramp_s": 2400.0}},
}


def main(argv: list[str] | None = None) -> int:
    import yaml

    from ares3.core.engine import Engine
    from ares3.schemas.faults import FaultSpec
    from ares3.schemas.monitor import MonitorConfig
    from ares3.schemas.scenario import load_scenario

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--event", choices=["none", *EVENTS], default="none")
    p.add_argument("--npc", default="cmd")
    p.add_argument("--seed", type=int, default=5)
    p.add_argument("--days", type=float, default=1.0)
    p.add_argument("--monitor", default=str(ROOT / "scenarios" / "station" / "monitor.yaml"))
    args = p.parse_args(argv)

    sc = load_scenario(ROOT / "scenarios" / "station" / "nominal.yaml")
    sc.file.seed = args.seed
    sc.monitor = MonitorConfig.model_validate(yaml.safe_load(Path(args.monitor).read_text(encoding="utf-8")))
    start = None
    if args.event != "none":
        spec = {"id": f"{args.npc}_{args.event}", "type": "medical", "targets": [args.npc], **EVENTS[args.event]}
        sc.faults.faults.append(FaultSpec.model_validate(spec))
        start = spec["start_s"]
    ticks = round(args.days * sc.environment.day_length_s / sc.file.dt_s)
    seen: dict[str, dict] = {}
    t0 = time.perf_counter()
    for res in Engine(sc).run(ticks):
        for e in res.tick.emergencies:
            row = seen.setdefault(e.id, {"first": res.tick.t_sim_s, "confirmed": None})
            row.update(kind=e.kind, subject=e.subject, cause=e.cause, cls=e.alert_class, module=e.module_id, detectors=e.detectors, evidence=e.evidence)
            if e.state == "confirmed" and row["confirmed"] is None:
                row["confirmed"] = res.tick.t_sim_s
    print(f"{args.event} on {args.npc if start else '-'}, {args.days} d, {1000 * (time.perf_counter() - t0) / ticks:.1f} ms/tick: {len(seen)} emergencies")
    for eid, r in seen.items():
        rel = "" if start is None else f" ({(r['first'] - start) / 60:+.0f} min from the start, confirmed {((r['confirmed'] or 0) - start) / 60:+.0f})"
        print(f"  {eid}: {r['kind']} subject={r['subject']} cause={r['cause']} class={r['cls']} in {r['module']} at t={r['first']:.0f}s{rel}; "
              f"detectors {list(r['detectors'])}; {(r['evidence'] or ('',))[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
