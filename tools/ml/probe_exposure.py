"""Probe of the exposures of the crew dataset: which sources take the TRUE air of the crew past the early thresholds in hours?

Six candidates run side by side for 12 simulated hours, without the monitor (~3 min on 9 cores): ``co2_source`` 1e-3 and 3e-3 mol/s in a crew
quarter at night, ``co_source`` 2e-5 and 1e-4 mol/s in COL (where ``bot`` works by day), the PRK leak at 3 x the top of its range together with
the weak OGA stack, and the EVA decompression; plus three more that check the range proposed for E3 after the first six (``co_source`` 2e-4 and
8e-4 in COL) and the low end of E1 in a big module (``co2_source`` 5e-4 in COL). For each, per hour: the maximum ppCO2 and COHb and the minimum PIO2 and SpO2 of the TRUE state
of the exposed crew members (the module they are in, like the ``truth|...`` columns of ``crew.parquet``), and how far that is from the early
thresholds of the labels (ppCO2 >= 4 mmHg, COHb >= 2.5 %, PIO2 <= 135 mmHg). The decision (E3 range, E4 on or off) is printed at the end and
written into ``tools/ml/crew_plan.yaml`` by hand.

    uv run python tools/ml/probe_exposure.py [--hours 12]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import math
import multiprocessing as mp
import os
import sys
import time

import make_dataset as md

THRESHOLDS = {"ppco2": 4.0, "cohb": 2.5, "pio2": 135.0}  # the early thresholds of the labels (docs/piano-ml-equipaggio.md, 2.2)
HOUR = 3600.0
START_S = 1800.0  # the source starts after half an hour


def _fault(fid, ftype, targets, params, duration_s=None, start_s=START_S):
    return {"id": fid, "type": ftype, "targets": targets, "start_s": start_s, "duration_s": duration_s, "params": params,
            "anomaly_type": fid, "priority": 8}


def candidates() -> dict[str, dict]:
    """``{name: {"job": ..., "start_tod_h": ..., "modules": [...] | None, "skip": [...]}}``: ``modules`` are where the exposed people are (None:
    the whole crew, but never in the modules of ``skip``: the EVA volume is 42 % O2 at 46.7 kPa, PIO2 130 mmHg by design, not an exposure)."""
    prk = md.EVENTS / "F-FIS-PERDITA-PRK.yaml"
    out = {}
    for mol in (1e-3, 3e-3):  # cmd sleeps in CQ1 from 22:00
        out[f"co2_source {mol:g} mol/s in CQ1, night"] = {
            "job": {"faults": [_fault("co2", "co2_source", ["CQ1"], {"mol_s": mol})]}, "start_tod_h": 22.0, "modules": ["CQ1"]}
    for mol in (2e-5, 1e-4, 2e-4, 8e-4):  # bot works in COL from 07:30
        out[f"co_source {mol:g} mol/s in COL"] = {
            "job": {"faults": [_fault("co", "co_source", ["COL"], {"mol_s": mol})]}, "start_tod_h": 7.5, "modules": ["COL"]}
    out["co2_source 0.0005 mol/s in COL, day"] = {
        "job": {"faults": [_fault("co2", "co2_source", ["COL"], {"mol_s": 5e-4})]}, "start_tod_h": 7.5, "modules": ["COL"]}
    out["PRK leak x11.3 + OGA-STACK"] = {  # 3 x the top of the range of the sheet (3.78)
        "job": {"scenario": str(prk), "extra_faults": ["F-ATT-OGA-STACK"],
                "per_fault": {"F-FIS-PERDITA-PRK": {"start_s": START_S, "scale": 3 * 3.7777777}, "F-ATT-OGA-STACK": {"start_s": START_S}}},
        "start_tod_h": 6.0, "modules": None, "skip": ["eva"]}
    eva = md.MEDICAL_DIR / "eva_decompression_faults.yaml"
    out["EVA decompression"] = {  # at 10:10, when `med` is out (the file times are for another start of the day)
        "job": {"faults_file": str(eva), "start_s": 15000.0}, "start_tod_h": 6.0, "modules": None, "skip": []}
    return out


def probe_one(item: tuple[str, dict], hours: int) -> tuple[str, list[list[float]]]:
    """Run one candidate; returns ``(name, rows)`` with a row ``[max ppCO2, max COHb, min PIO2, min SpO2, ticks with someone exposed]`` per hour."""
    from ares3.core.engine import Engine
    from ares3.schemas.monitor import MonitorConfig

    name, cand = item
    job = {"scenario": str(md.NOMINAL), "seed": 1, "days": 1.0, "ticks": int(hours * HOUR), **cand["job"]}
    sc, ticks = md._prepare(job)
    sc.monitor = MonitorConfig()
    sc.file.start_time_of_day_h = cand["start_tod_h"]
    exposed, skip = cand["modules"], cand.get("skip", [])
    rows = [[-math.inf, -math.inf, math.inf, math.inf, 0] for _ in range(hours)]
    for res in Engine(sc).run(ticks):
        if res.tick.tick % 60:
            continue
        row = rows[min(int(res.tick.t_sim_s // HOUR), hours - 1)]
        for npc in res.tick.npcs.values():
            if (exposed is not None and npc.module_id not in exposed) or npc.module_id in skip:
                continue
            mod = res.tick.modules[npc.module_id]
            row[0], row[1] = max(row[0], mod.ppco2_mmhg), max(row[1], npc.vitals.get("cohb_pct", -math.inf))
            row[2], row[3] = min(row[2], mod.pio2_mmhg), min(row[3], npc.vitals.get("spo2", math.inf))
            row[4] += 1
    return name, rows


def _fmt(v: float) -> str:
    return "     -" if math.isinf(v) else f"{v:6.2f}"


def report(name: str, rows: list[list[float]]) -> dict:
    """Print the table of a candidate; returns what the decision needs (the first hour each threshold is crossed, the extremes)."""
    print(f"\n== {name}")
    print("  hour  ppCO2max  COHbmax  PIO2min  SpO2min  (ppCO2 -> 4, COHb -> 2.5 %, PIO2 -> 135)")
    first = {"ppco2": None, "cohb": None, "pio2": None}
    for h, (p, c, o, s, n) in enumerate(rows, 1):
        print(f"  {h:4d}  {_fmt(p)}    {_fmt(c)}   {_fmt(o)}   {_fmt(s)}" + ("" if n else "   (nobody in the module)"))
        for key, hit in (("ppco2", p >= THRESHOLDS["ppco2"]), ("cohb", c >= THRESHOLDS["cohb"]), ("pio2", o <= THRESHOLDS["pio2"])):
            if hit and first[key] is None:
                first[key] = h
    ext = {"ppco2": max(r[0] for r in rows), "cohb": max(r[1] for r in rows), "pio2": min(r[2] for r in rows), "spo2": min(r[3] for r in rows)}
    print("  first hour past the threshold: " + ", ".join(f"{k} {'never' if v is None else v}" for k, v in first.items()))
    print(f"  to go at the end: ppCO2 {THRESHOLDS['ppco2'] - ext['ppco2']:+.2f} mmHg, COHb {THRESHOLDS['cohb'] - ext['cohb']:+.2f} %, "
          f"PIO2 {ext['pio2'] - THRESHOLDS['pio2']:+.1f} mmHg (a negative number = past it)")
    return {"first": first, **ext}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe of the exposures of the crew dataset (E1-E4)")
    p.add_argument("--hours", type=int, default=12)
    p.add_argument("--workers", type=int, default=9)
    args = p.parse_args(argv)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    cands = candidates()
    t0 = time.perf_counter()
    with cf.ProcessPoolExecutor(max_workers=min(args.workers, len(cands)), mp_context=mp.get_context("spawn")) as pool:
        futures = [pool.submit(probe_one, item, args.hours) for item in cands.items()]
        results = dict(f.result() for f in futures)
    print(f"{len(cands)} candidates, {args.hours} h each, {time.perf_counter() - t0:.0f} s")
    summary = {name: report(name, rows) for name, rows in results.items()}
    print("\n== decision")
    co = [(n, s) for n, s in summary.items() if n.startswith("co_source")]
    for n, s in co:
        print(f"  {n}: COHb reaches 2.5 % at hour {s['first']['cohb']}, top {s['cohb']:.2f} %")
    hit = [n for n, s in co if s["first"]["cohb"] is not None]
    print("  E3 (co_source): " + (f"the lowest rate that crosses 2.5 % is {min(hit, key=lambda n: summary[n]['cohb'])}; the range goes from it to the highest tested"
                                  if hit else "no candidate crosses 2.5 %: raise the range"))
    leak = summary["PRK leak x11.3 + OGA-STACK"]
    eva = summary["EVA decompression"]
    print(f"  E4 (hypoxia): PRK leak (nominal EVA left out) PIO2 min {leak['pio2']:.1f} mmHg (hour {leak['first']['pio2']}), SpO2 min {leak['spo2']:.1f} %; "
          f"EVA decompression PIO2 min {eva['pio2']:.1f} mmHg, SpO2 min {eva['spo2']:.1f} %")
    print("  E4 " + ("stays (enabled: true)" if leak["first"]["pio2"] is not None else "is OFF (enabled: false): no cause takes PIO2 under 135 mmHg in 12 h"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
