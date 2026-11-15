"""Command line: ``ares3 run scenarios/nominal.yaml -o output/run1 --days 2``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ares3.core.engine import Engine
from ares3.export import DatasetWriter
from ares3.schemas.scenario import deep_merge, load_scenario


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


def _serve(args: argparse.Namespace) -> int:
    import asyncio

    try:
        import websockets  # noqa: F401

        from ares3.serve.server import serve
    except ImportError:
        print("the WebSocket bridge needs the serve extra: uv sync --extra serve", file=sys.stderr)
        return 2
    from ares3.serve import Session

    sc = load_scenario(args.scenario)
    if args.vital_variability > 0:  # a live demo should not show ruler-straight vitals (the engine default stays smooth: datasets, ML)
        patch = {"variability": args.vital_variability}
        sc.crew.physiology.params = deep_merge(sc.crew.physiology.params, patch)
        for member in sc.crew.members:
            if member.physiology is not None:
                member.physiology.params = deep_merge(member.physiology.params, patch)
    session = Session(sc, speed=min(args.speed, args.max_speed), paused=args.paused, max_fps=args.fps, max_speed=args.max_speed,
                      pause_when_idle=args.pause_when_idle)
    warmup_s, on_warm = args.warmup_h * 3600.0, None
    if args.warmup_cache and warmup_s > 0:
        from ares3.serve import cache

        key = cache.cache_key(sc, warmup_s)
        if cache.load(session, args.warmup_cache, key):
            print(f"warm-up of {args.warmup_h:g} h restored from {args.warmup_cache} (no wait)", flush=True)
            warmup_s = 0.0
        else:
            def on_warm() -> None:
                path = cache.save(session, args.warmup_cache, key)
                if path is not None:
                    print(f"warm-up cache written: {path}", flush=True)
    if warmup_s > 0:
        print(f"warming up {args.warmup_h:g} simulated hours after opening the port (clients see a progress screen)...", flush=True)
    print(f"serving {sc.file.name} on ws://{args.host}:{args.port} (speed {args.speed:g}x, Ctrl-C to stop)")
    try:
        asyncio.run(serve(session, args.host, args.port, token=args.token or os.environ.get("ARES3_TOKEN") or None,
                          origins=args.allow_origin or None, max_clients=args.max_clients,
                          guest_commands=frozenset(c for c in args.guest_commands.split(",") if c),
                          warmup_s=warmup_s, warmup_done=on_warm))
    except KeyboardInterrupt:
        pass
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
    s = sub.add_parser("serve", help="run a scenario live and stream ticks over a WebSocket (for the dashboard)")
    s.add_argument("scenario")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--speed", type=float, default=10.0, help="simulated seconds per real second")
    s.add_argument("--fps", type=float, default=10.0, help="maximum frames per second sent to clients")
    s.add_argument("--paused", action="store_true", help="start paused")
    s.add_argument("--token", help="secret that makes a client an operator (?token=...); others only watch. Default: $ARES3_TOKEN, "
                                   "none = every client may send commands (local use only)")
    s.add_argument("--guest-commands", default="", metavar="CMD,CMD",
                   help="commands a viewer (no token) may send too, e.g. approve_action,reject_action,ack_step (default: none)")
    s.add_argument("--allow-origin", action="append", metavar="URL",
                   help="page allowed to open the socket from a browser, e.g. https://ares.daado.dev (repeatable; default: any)")
    s.add_argument("--pause-when-idle", action="store_true",
                   help="stand still while no client is connected (a server left running costs no CPU; time resumes on the first connection)")
    s.add_argument("--max-clients", type=int, default=100, help="simultaneous connections")
    s.add_argument("--max-speed", type=float, default=60.0, help="highest speed a client can ask for (the dashboard offers 1-60; a public server: 60 or less)")
    s.add_argument("--warmup-h", type=float, default=0.0, metavar="H",
                   help="simulated hours to run ahead at startup: the ML detectors are ready (they need 3 h) and the charts start full "
                        "(~1 min of real time per 4 h). The port is open meanwhile: clients get a `warming` state with progress")
    s.add_argument("--warmup-cache", metavar="DIR",
                   help="save the warmed-up state in DIR and, on the next start with the same code, scenario, models and --warmup-h, "
                        "load it instead of simulating the hours again (a restart is instant). DIR must be ours alone: it is a pickle")
    s.add_argument("--vital-variability", type=float, default=0.3, metavar="K",
                   help="short-term wobble of hr / spo2 / resp_rate, as a multiple of a resting adult's (0 = the smooth model; 1 = a real person, "
                        "but the crew baseline ML of models/station_v2 was trained on smooth vitals and flags everyone from ~0.5: retrain it first)")
    s.set_defaults(fn=_serve)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
