"""Command line: ``ares3 run scenarios/nominal.yaml -o output/run1 --days 2``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ares3.core.engine import Engine
from ares3.export import DatasetWriter
from ares3.schemas.scenario import load_scenario


def _run(args: argparse.Namespace) -> int:
    sc = load_scenario(args.scenario)
    engine = Engine(sc)
    dt = sc.file.dt_s
    if args.ticks is not None:
        ticks: int | None = args.ticks
    else:
        days = args.days if args.days is not None else sc.file.duration_days
        ticks = None if days is None else round(days * sc.environment.day_length_s / dt)
    if ticks is None and not args.forever:
        print("no duration: pass --days/--ticks, set duration_days in the scenario, or use --forever (Ctrl-C to stop)",
              file=sys.stderr)
        return 2
    out = Path(args.output) if args.output else Path("output") / sc.file.name
    writer = DatasetWriter(out, sc)
    n = 0
    alarm_ticks = 0
    try:
        for res in engine.run(ticks):
            writer.add(res)
            n += 1
            alarm_ticks += bool(res.tick.alarms)
            if args.progress and n % args.progress == 0:
                print(f"tick {n} | day {res.tick.day} {res.tick.time_of_day_h:05.2f} h | alarms {len(res.tick.alarms)}")
    except KeyboardInterrupt:
        print("interrupted, flushing...", file=sys.stderr)
    finally:
        writer.close()
    print(f"{n} ticks ({n * dt / 3600:.1f} simulated h, {alarm_ticks} ticks with an alarm) -> {out}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    sc = load_scenario(args.scenario)
    Engine(sc)  # builds every plugin: catches bad `kind` / params
    print(f"ok: {sc.file.name} | env {sc.environment.name} | {len(sc.layout.modules)} modules, "
          f"{len(sc.crew.members)} crew, {len(sc.layout.sensors)} sensors, {len(sc.faults.faults)} faults")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ares3", description="ARES 3 simulation engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario and export the dataset")
    r.add_argument("scenario")
    r.add_argument("-o", "--output")
    r.add_argument("--days", type=float, help="simulated days (local days of the environment profile)")
    r.add_argument("--ticks", type=int)
    r.add_argument("--forever", action="store_true", help="no limit; stop with Ctrl-C")
    r.add_argument("--progress", type=int, default=0, metavar="N", help="print a line every N ticks")
    r.set_defaults(fn=_run)
    v = sub.add_parser("validate", help="load a scenario and build every plugin without running")
    v.add_argument("scenario")
    v.set_defaults(fn=_validate)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
