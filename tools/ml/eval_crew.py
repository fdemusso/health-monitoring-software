"""Offline evaluation of the crew stage A with the SAME scoring code as the detector (``CrewBaselineModel`` + ``ema``): the rows of
``crew.parquet`` are what ``CrewFeatureExtractor`` computes online, so the statistic, the exponential mean and the debounce are
reproduced here and the numbers are those the live monitor would give.

    uv run python tools/ml/eval_crew.py --split val
    uv run python tools/ml/eval_crew.py --split test        # opened ONCE, with the models frozen (refuses a second time without --again)

Metrics (plan section 3):
* false alarms per day on the nominal runs (val: N1 val; test: N2 + N3), per crew and per person, with the 95 % upper bound (rule of
  three for 0, exact Poisson otherwise), and the signals raised DURING nominal exercise (class aerobic / resistive, or < 30 min after
  a MET >= 4): the target is 0 (the case of 126 bpm at 7 MET);
* event recall on the M runs: detected when a signal on the AFFECTED person is confirmed between the start and the end + 30 min (a
  signal on anybody else, or on that person outside the window, is a false alarm), per event with the 95 % Wilson interval;
* delay from the moment the fault is first visible (the twin run: the same seed without the fault) when the twin exists, from the
  start + ramp otherwise (+ 1 h for the dehydration): median and p90 with a bootstrap interval over the runs;
* the table of the acceptance criteria of section 7 that stage A can be judged on.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crew_data import CrewRun, default_dirs, find_runs

from ares3.plugins.monitor.ml.crew_baseline import QUANTITIES, CrewBaselineModel, ema, load_model

SLOW_CONFIRM_S = 600.0  # ``confirm_s`` of the YAML for the slow detector
FAST_CONFIRM_S = 120.0
AFTER_END_S = 1800.0  # a signal this long after the end of the event still counts for it
VISIBLE_K = 3.0  # sigmas from the twin run
EXERCISE_QUIET_MIN = 30.0  # minutes after exercise that still count as exercise for the nominal-run check
MODEL_DEFAULT = ROOT / "models" / "station_v2" / "crew_baseline.joblib"


# ------------------------------------------------------------------ statistics
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def poisson_upper(k: int, days: float, conf: float = 0.95) -> float:
    """Upper confidence bound (one-sided) of a rate in events per day: exact Poisson; for k = 0 it is the rule of three, 3 / days."""
    from scipy.stats import chi2

    return float(chi2.ppf(conf, 2 * (k + 1)) / 2.0 / days) if days > 0 else math.nan


def bootstrap_median(xs: list[float], q: float = 50.0, n: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """(statistic, low, high) of the ``q`` percentile of ``xs`` with a 95 % bootstrap interval over the items."""
    if not xs:
        return (math.nan, math.nan, math.nan)
    a = np.asarray(xs, dtype=float)
    rng = np.random.default_rng(seed)
    boot = [np.percentile(rng.choice(a, size=len(a), replace=True), q) for _ in range(n)]
    return float(np.percentile(a, q)), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


# ------------------------------------------------------------------ series and alarms
@dataclass
class NpcSeries:
    npc: str
    t: np.ndarray
    z: np.ndarray  # (rows, quantities)
    zm: np.ndarray  # directional part
    exercising: np.ndarray  # bool: nominal exercise now or just before
    value: np.ndarray  # (rows, quantities) the sensed quantities
    every_s: float


Alarm = tuple[float, float, float]  # (start, confirmation, end) in simulated seconds


def episodes_full(over: np.ndarray, t: np.ndarray, confirm_s: float) -> list[Alarm]:
    """The stretches of ``over`` lasting ``confirm_s``: (start, confirmation, last time over), as the classifier would open them."""
    out: list[Alarm] = []
    start = None
    conf = None
    for i, flag in enumerate(over):
        if not flag:
            if start is not None and conf is not None:
                out.append((float(t[start]), conf, float(t[i - 1])))
            start, conf = None, None
            continue
        if start is None:
            start = i
        if conf is None and t[i] - t[start] >= confirm_s:
            conf = float(t[i])
    if start is not None and conf is not None:
        out.append((float(t[start]), conf, float(t[len(over) - 1])))
    return out


def run_series(model: CrewBaselineModel, run: CrewRun) -> dict[str, NpcSeries]:
    """The z series of every crew member of a run."""
    df = run.crew
    out = {}
    pos = {c: i for i, c in enumerate(model.columns)}
    for npc, g in df.groupby("npc", sort=False):
        if npc not in model.regressors:
            continue
        g = g.sort_values("t_s")
        X = g[model.columns].to_numpy(dtype=float)
        z, _ = model.z_batch(npc, X)
        t = g["t_s"].to_numpy(dtype=float)
        ex = (X[:, pos["ctx|act_aerobic"]] > 0) | (X[:, pos["ctx|act_resistive"]] > 0) | (X[:, pos["ctx|min_since_ex"]] < EXERCISE_QUIET_MIN)
        out[str(npc)] = NpcSeries(str(npc), t, z, model._mask(z), ex, X[:, [pos[q] for q in QUANTITIES]],
                                  float(np.median(np.diff(t))) if len(t) > 1 else 60.0)
    return out


def alarms_of(model: CrewBaselineModel, s: NpcSeries, mode: str) -> list[Alarm]:
    """The alarms of one crew member with the limits ``model`` carries: ``slow`` | ``fast``."""
    if mode == "fast":
        return episodes_full(model.fast_stat(s.zm) >= 1.0, s.t, FAST_CONFIRM_S)
    stat, _, _ = model.stats(s.npc, s.z)
    return episodes_full(ema(stat, s.every_s, model.tau_s) >= 1.0, s.t, SLOW_CONFIRM_S)


def merge_alarms(alarm_lists: list[list[Alarm]]) -> list[Alarm]:
    """One list from several detectors of the same person: alarms that overlap in time are the same emergency (the monitor merges them)."""
    items = sorted(a for lst in alarm_lists for a in lst)
    out: list[Alarm] = []
    for a in items:
        if out and a[0] <= out[-1][2]:
            prev = out[-1]
            out[-1] = (prev[0], min(prev[1], a[1]), max(prev[2], a[2]))
        else:
            out.append(a)
    return out


def all_alarms(model: CrewBaselineModel, series: dict[str, NpcSeries], modes: tuple[str, ...] = ("slow", "fast")) -> dict[str, list[Alarm]]:
    return {npc: merge_alarms([alarms_of(model, s, m) for m in modes]) for npc, s in series.items()}


def exercise_alarms(s: NpcSeries, alarms: list[Alarm]) -> int:
    """How many of ``alarms`` have a row of nominal exercise between their start and their confirmation."""
    n = 0
    for a in alarms:
        sel = (s.t >= a[0]) & (s.t <= a[1])
        n += int(s.exercising[sel].any())
    return n


# ------------------------------------------------------------------ events
def visible_from_twin(model: CrewBaselineModel, run: CrewRun, twin: CrewRun | None) -> tuple[float, str]:
    """(time the fault is first visible, how): the first row at or after the start where some quantity of the affected person is
    ``VISIBLE_K`` of the model's sigmas away from the twin; without a twin, the start + ramp (+ 1 h for the dehydration)."""
    fault = next(iter(run.faults.values()))
    start = float(fault["start_s"])
    npc = fault["targets"][0]
    if twin is not None:
        a = run.crew[run.crew["npc"] == npc].set_index("t_s")
        b = twin.crew[twin.crew["npc"] == npc].set_index("t_s")
        idx = a.index.intersection(b.index)
        a, b = a.loc[idx], b.loc[idx]
        sig = model.sigma[npc][:, 1]  # nominal class
        diff = np.abs(a[list(QUANTITIES)].to_numpy(dtype=float) - b[list(QUANTITIES)].to_numpy(dtype=float)) / sig
        hit = np.nonzero((idx.to_numpy() >= start) & (np.nan_to_num(diff).max(axis=1) >= VISIBLE_K))[0]
        if len(hit):
            return float(idx.to_numpy()[hit[0]]), "twin"
    ramp = float(fault.get("params", {}).get("ramp_s", 0.0))
    return start + ramp + (3600.0 if run.job.get("event") == "dehydration" else 0.0), "start+ramp"


def event_result(run: CrewRun, series: dict[str, NpcSeries], alarms: dict[str, list[Alarm]], visible_s: float,
                 confirm_s: float) -> dict:
    fault = next(iter(run.faults.values()))
    npc = fault["targets"][0]
    start = float(fault["start_s"])
    end = start + float(fault.get("duration_s") or 0.0)
    hits = [a for a in alarms.get(npc, []) if start - confirm_s <= a[0] <= end + AFTER_END_S and start <= a[1] <= end + AFTER_END_S]
    others = [(p, a) for p, lst in alarms.items() for a in lst if p != npc and a[1] >= 1800.0]
    extra = [a for a in alarms.get(npc, []) if a not in hits]
    return {"run": run.name, "event": run.job["event"], "npc": npc, "start_s": start, "end_s": end, "visible_s": visible_s,
            "detected": bool(hits), "delay_s": max(0.0, min(a[1] for a in hits) - visible_s) if hits else None,
            "wrong_person": len(others), "other_alarms_same_person": len(extra)}


# ------------------------------------------------------------------ the evaluation
def nominal_report(model: CrewBaselineModel, runs: list[CrewRun], modes: tuple[str, ...] = ("slow", "fast")) -> dict:
    days = sum(r.crew["t_s"].max() / 86400.0 for r in runs)
    per_person: dict[str, int] = {}
    n_exercise = 0
    detail = []
    for r in runs:
        ser = run_series(model, r)
        al = all_alarms(model, ser, modes)
        for npc, lst in al.items():
            per_person[npc] = per_person.get(npc, 0) + len(lst)
            n_exercise += exercise_alarms(ser[npc], lst)
            detail += [{"run": r.name, "npc": npc, "start_s": a[0], "confirm_s": a[1], "end_s": a[2]} for a in lst]
        r.free()
    total = sum(per_person.values())
    return {"runs": len(runs), "days": days, "alarms": total, "per_person": per_person, "per_day_crew": total / days,
            "upper95_crew": poisson_upper(total, days),
            "upper95_person": {p: poisson_upper(k, days) for p, k in per_person.items()},
            "during_exercise": n_exercise, "list": detail}


def event_report(model: CrewBaselineModel, runs: list[CrewRun], twins: dict[tuple[int, float], CrewRun],
                 modes: tuple[str, ...] = ("slow", "fast")) -> dict:
    results = []
    for r in runs:
        ser = run_series(model, r)
        twin = twins.get((r.seed, r.days))
        vis, how = visible_from_twin(model, r, twin)
        by_mode = {m: all_alarms(model, ser, (m,)) for m in ("slow", "fast")}
        both = all_alarms(model, ser, modes)
        res = event_result(r, ser, both, vis, SLOW_CONFIRM_S)
        res["visible_how"] = how
        res["by_mode"] = {m: event_result(r, ser, by_mode[m], vis, SLOW_CONFIRM_S if m == "slow" else FAST_CONFIRM_S)["detected"]
                          for m in ("slow", "fast")}
        results.append(res)
        r.free()
        if twin is not None:
            twin.free()
    per_event = {}
    for ev in sorted({x["event"] for x in results}):
        sel = [x for x in results if x["event"] == ev]
        k, n = sum(x["detected"] for x in sel), len(sel)
        delays = [x["delay_s"] for x in sel if x["delay_s"] is not None]
        per_event[ev] = {"detected": k, "n": n, "recall": k / n, "wilson95": wilson(k, n),
                         "delay_median_min": bootstrap_median([d / 60 for d in delays], 50), "delay_p90_min": bootstrap_median([d / 60 for d in delays], 90),
                         "slow": sum(x["by_mode"]["slow"] for x in sel), "fast": sum(x["by_mode"]["fast"] for x in sel),
                         "wrong_person": sum(x["wrong_person"] for x in sel), "other_alarms": sum(x["other_alarms_same_person"] for x in sel),
                         "visible_from": sorted({x["visible_how"] for x in sel})}
    k, n = sum(x["detected"] for x in results), len(results)
    return {"n": n, "detected": k, "recall": k / n if n else math.nan, "wilson95": wilson(k, n), "per_event": per_event, "events": results}


def load_twins(dirs=None) -> dict[tuple[int, float], CrewRun]:
    """Nominal runs WITHOUT jitter (group T): the twins of the M runs, keyed by (seed, days)."""
    return {(r.seed, r.days): r for r in find_runs(dirs or default_dirs()) if r.group == "T" and not r.jitter}


def fmt_interval(iv: tuple[float, float]) -> str:
    return f"{iv[0]:.2f}-{iv[1]:.2f}"


def criteria(split: str, nom: dict, ev: dict) -> list[tuple[str, bool | None, str]]:
    """The acceptance criteria of section 7 of the plan that stage A can be judged on: (criterion, passed, measured)."""
    rows = [("crew false alarms <= 0.1 / day (95 % upper bound)", nom["upper95_crew"] <= 0.1 if nom["days"] >= 45 else None,
             f"{nom['alarms']} alarms in {nom['days']:.0f} d = {nom['per_day_crew']:.3f}/d, upper bound {nom['upper95_crew']:.3f}/d"
             + ("" if nom["days"] >= 45 else " (fewer than 45 days: not judged)")),
            ("no signal during nominal exercise", nom["during_exercise"] == 0, f"{nom['during_exercise']} signals")]
    pe = ev["per_event"]
    rows.append(("overall event recall >= 0.8", ev["recall"] >= 0.8, f"{ev['detected']}/{ev['n']} = {ev['recall']:.2f} [{fmt_interval(ev['wilson95'])}]"))
    for name in ("atrial_fibrillation_suspected", "svt_suspected", "bradycardia", "fever"):
        if name in pe:
            e = pe[name]
            need = math.ceil(0.75 * e["n"])
            rows.append((f"{name} >= {need}/{e['n']}", e["detected"] >= need, f"{e['detected']}/{e['n']} [{fmt_interval(e['wilson95'])}]"))
    return rows


def print_report(split: str, nom: dict, ev: dict) -> None:
    print(f"\n== stage A crew, {split} ==")
    print(f"nominal runs: {nom['runs']} ({nom['days']:.1f} days): {nom['alarms']} alarms = {nom['per_day_crew']:.3f}/day for the crew, 95 % upper bound "
          f"{nom['upper95_crew']:.3f}/day; per person {nom['per_person']}; during nominal exercise: {nom['during_exercise']}")
    print(f"events: {ev['detected']}/{ev['n']} = {ev['recall']:.2f}  Wilson95 {fmt_interval(ev['wilson95'])}")
    print(f"{'event':32s} {'det':>5s} {'recall':>7s} {'Wilson95':>10s} {'slow':>5s} {'fast':>5s} {'delay med [CI] min':>24s} {'p90':>6s} {'wrong':>5s} {'other':>5s}")
    for name, e in ev["per_event"].items():
        dm = e["delay_median_min"]
        print(f"{name:32s} {e['detected']:>2d}/{e['n']:<2d} {e['recall']:7.2f} {fmt_interval(e['wilson95']):>10s} {e['slow']:5d} {e['fast']:5d} "
              f"{dm[0]:7.1f} [{dm[1]:5.1f},{dm[2]:5.1f}] {e['delay_p90_min'][0]:6.1f} {e['wrong_person']:5d} {e['other_alarms']:5d}  {','.join(e['visible_from'])}")
    print("\ncriteria (section 7):")
    for text, ok, measured in criteria(split, nom, ev):
        print(f"  [{'pass' if ok else 'n/a ' if ok is None else 'FAIL'}] {text}: {measured}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--split", choices=["val", "test"], required=True)
    p.add_argument("--features", nargs="*", default=None, help="folders with the runs (default: every crew* folder of output/ml)")
    p.add_argument("--model", default=str(MODEL_DEFAULT))
    p.add_argument("--again", action="store_true", help="open the test a second time (it should not be needed)")
    args = p.parse_args(argv)

    model = load_model(args.model)
    out_dir = Path(args.model).parent
    out_json = out_dir / f"eval_crew_{args.split}.json"
    if args.split == "test" and out_json.exists() and not args.again:
        raise SystemExit(f"the test was already opened ({out_json}); it is opened once, with the models frozen. --again to override.")
    dirs = args.features or default_dirs()
    runs = find_runs(dirs)
    seeds = {"val": range(131, 141), "test": range(141, 161)}[args.split]
    sel = [r for r in runs if r.seed in seeds]
    nominal = [r for r in sel if r.group in (("N1",) if args.split == "val" else ("N2", "N3"))]
    events = [r for r in sel if r.group.startswith("M")]
    twins = load_twins(dirs)
    print(f"{len(nominal)} nominal runs, {len(events)} event runs, {len(twins)} twins; model {model.kind}, "
          f"L_D {model.limit_d:.3g}, fast factor {model.fast_factor}")
    nom = nominal_report(model, nominal)
    ev = event_report(model, events, twins)
    print_report(args.split, nom, ev)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    out_json.write_text(json.dumps({"opened_at": stamp, "split": args.split, "model": str(args.model), "info": model.info,
                                    "nominal": {k: v for k, v in nom.items() if k != "list"}, "alarms": nom["list"], "events": ev,
                                    "criteria": [{"criterion": c, "passed": ok, "measured": m} for c, ok, m in criteria(args.split, nom, ev)]},
                                   indent=1, default=float), encoding="utf-8")
    print(f"\nwritten {out_json} at {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
