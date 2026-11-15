"""Train the crew stage A (``CrewBaselineModel``): the expected value of each vital given only the context, learned on NOMINAL days, and
write ``models/station_v2/crew_baseline.joblib`` plus ``model_card_crew.json``.

    uv run python tools/ml/train_crew.py                  # trains the regressor AND the table model, keeps the better on the validation
    uv run python tools/ml/train_crew.py --kind table     # only plan B

Data: ``crew.parquet`` of the N1 runs (nominal, programme with jitter): seeds ``--train-seeds`` fit the regressors, ``--val-seeds``
give the scale of each residual (a robust sigma per person, quantity and activity class, raised by a small regressor of the size of the
residual where the context says the body is in transition), the precision matrix and the limits. The TEST seeds (141+) are never read
here: every choice (margin, fast factor, regressor or table) is made on the validation seeds, with the M runs 131-138 for the recall.

The limits are a margin times the largest level the validation days SUSTAINED for the confirmation time of the detector (11 minutes of
the smoothed statistic for the slow one, 3 samples of the heart rate for the fast one): a transition of a few minutes (waking up, the
first minutes of exercise) is what the debounce lets through and must not set the limit. The margin is the LOWEST of ``--margins``
with no false alarm on the N1 validation runs, on a split-half check (limits from half of the validation runs, false alarms counted on
the other half) and on the stretches of the M validation runs outside their event; the recall on those M runs is printed for every
candidate. The fast factor is chosen the same way.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "6")  # the machine is shared with the generators: at most 6 threads

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crew_data import default_dirs, find_runs, parse_seeds
from eval_crew import (
    FAST_CONFIRM_S,
    SLOW_CONFIRM_S,
    NpcSeries,
    all_alarms,
    event_result,
    nominal_report,
    run_series,
)
from train_anomaly import provenance

from ares3.plugins.monitor.ml.crew import ACT_NAMES, CLASSES, VITALS
from ares3.plugins.monitor.ml.crew_baseline import (
    EVERY_S,
    FAST_QUANTITIES,
    MEMORY_TAU_MIN,
    QUANTITIES,
    TAU_S,
    Z_CLIP,
    CrewBaselineModel,
    TableRegressor,
    ema,
)

NPC_ORDER = ("cmd", "eng", "med", "bot")
LIMIT_FLOOR_Z = 3.0  # sigmas: no quantity alarms below this (ESTIMATE)
LIMIT_FLOOR_D = 30.0  # D2 of 7 quantities: chi-square p ~ 1e-4 (ESTIMATE)
LIMIT_FLOOR_FAST = 4.0
LIMIT_CAP_Z = 0.95 * Z_CLIP  # a limit above the clip could never be reached by that quantity alone (z is clipped before the slow statistic)


def feature_names() -> list[str]:
    return ([f"{m}|{s}" for m in VITALS for s in ("lv10", "sd10")] + ["core_temp_c|sl1h"]
            + ["ctx|met10", "ctx|met_max30", "ctx|min_since_ex"] + [f"ctx|{a}" for a in ACT_NAMES]
            + ["ctx|min_since_sleep", "clock|sin", "clock|cos"])


def class_index(df: pd.DataFrame) -> np.ndarray:
    act = df[[f"ctx|{a}" for a in ACT_NAMES]].to_numpy(dtype=float)
    return np.where(act.sum(axis=1) > 0, act.argmax(axis=1), CLASSES.index("nominal"))


def fit_regressor(kind: str, ctx: np.ndarray, y: np.ndarray, loss: str = "absolute_error", depth: int = 3, iters: int = 200):
    ok = np.isfinite(y)
    if kind == "table":
        return TableRegressor.fit(ctx[ok], y[ok])
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(loss=loss, max_depth=depth, max_iter=iters, early_stopping=False, random_state=0).fit(ctx[ok], y[ok])


def mad_sigma(res: np.ndarray, cls: np.ndarray, min_rows: int = 60) -> np.ndarray:
    """1.4826 x MAD of the residuals per activity class (a class with fewer than ``min_rows`` rows takes the pooled value)."""
    ok = np.isfinite(res)
    pooled = 1.4826 * np.median(np.abs(res[ok] - np.median(res[ok])))
    out = np.full(len(CLASSES), pooled)
    for c in range(len(CLASSES)):
        sel = ok & (cls == c)
        if sel.sum() >= min_rows:
            out[c] = 1.4826 * np.median(np.abs(res[sel] - np.median(res[sel])))
    return out


def stack(shell: CrewBaselineModel, frames: list[pd.DataFrame], names: list[str]):
    """(context matrix, quantities, activity class) of the rows of several runs of ONE person: the memory restarts in each run."""
    ctx = np.vstack([shell.context(f[names].to_numpy(dtype=float)) for f in frames])
    df = pd.concat(frames, ignore_index=True)
    return ctx, df[list(QUANTITIES)].to_numpy(dtype=float), class_index(df)


def fit_model(kind: str, train: dict[str, list[pd.DataFrame]], val: dict[str, list[pd.DataFrame]], names: list[str]) -> CrewBaselineModel:
    from sklearn.covariance import MinCovDet

    model = CrewBaselineModel(npc_ids=list(NPC_ORDER), columns=names, regressors={}, sigma={}, precision={}, kind=kind)
    for npc in NPC_ORDER:
        ctx_tr, y_tr, cls_tr = stack(model, train[npc], names)
        ctx_va, y_va, cls_va = stack(model, val[npc], names)
        model.regressors[npc], model.scale_models[npc] = {}, {}
        sig = np.zeros((len(QUANTITIES), len(CLASSES)))
        for qi, q in enumerate(QUANTITIES):
            reg = fit_regressor(kind, ctx_tr, y_tr[:, qi])
            model.regressors[npc][q] = reg
            res_va = y_va[:, qi] - reg.predict(ctx_va)
            s_val = mad_sigma(res_va, cls_va)
            s_train = mad_sigma(y_tr[:, qi] - reg.predict(ctx_tr), cls_tr)
            # the floor against a class whose residual is almost always 0: half the scale on the training days
            sig[qi] = np.maximum(np.maximum(s_val, 0.5 * s_train), 1e-6 + 1e-3 * abs(np.nanmedian(y_va[:, qi])))
            # the size of the residual from the context: larger in transition than in a steady state (median of |residual|)
            model.scale_models[npc][q] = fit_regressor("regressor", ctx_va, np.abs(res_va), loss="absolute_error", depth=3, iters=100)
        model.sigma[npc] = sig
    for npc in NPC_ORDER:  # the precision matrix on the validation z (robust: the days hold some transitions)
        z = np.clip(np.vstack([model.z_batch(npc, f[names].to_numpy(dtype=float))[0] for f in val[npc]]), -Z_CLIP, Z_CLIP)
        cov = MinCovDet(random_state=0).fit(z).covariance_ + 1e-6 * np.eye(len(QUANTITIES))
        model.precision[npc] = np.linalg.inv(cov)
    return model


def sustained_max(x: np.ndarray, n: int) -> float:
    """The largest level that ``x`` held for ``n`` consecutive samples (max over time of the minimum over a window of ``n``)."""
    if len(x) < n:
        return 0.0
    return float(np.lib.stride_tricks.sliding_window_view(x, n).min(axis=1).max())


def series_maxima(model: CrewBaselineModel, ser: dict[str, NpcSeries]) -> tuple[float, np.ndarray, np.ndarray]:
    """Sustained maxima of one run: the smoothed D2 and z of every quantity over the slow confirmation, the raw heart-rate z over the fast one."""
    n_slow, n_fast = int(SLOW_CONFIRM_S / EVERY_S) + 1, int(FAST_CONFIRM_S / EVERY_S) + 1
    ix = [QUANTITIES.index(q) for q in FAST_QUANTITIES]
    d_max, z_max, f_max = 0.0, np.zeros(len(QUANTITIES)), np.zeros(len(FAST_QUANTITIES))
    for npc, s in ser.items():
        _, d2, zm = model.stats(npc, s.z)
        d_max = max(d_max, sustained_max(ema(d2, s.every_s, model.tau_s), n_slow))
        for qi in range(len(QUANTITIES)):
            z_max[qi] = max(z_max[qi], sustained_max(ema(zm[:, qi], s.every_s, model.tau_s), n_slow))
        zf = model._mask(s.z)  # the fast statistic reads the unclipped z
        for k, qi in enumerate(ix):
            f_max[k] = max(f_max[k], sustained_max(zf[:, qi], n_fast))
    return d_max, z_max, f_max


def combine(maxima: list[tuple[float, np.ndarray, np.ndarray]]) -> tuple[float, np.ndarray, np.ndarray]:
    return (max(m[0] for m in maxima), np.maximum.reduce([m[1] for m in maxima]), np.maximum.reduce([m[2] for m in maxima]))


def limited(model: CrewBaselineModel, maxima: tuple[float, np.ndarray, np.ndarray], margin: float, factor: float) -> CrewBaselineModel:
    d_max, z_max, f_max = maxima
    return replace(model, limit_d=max(margin * d_max, LIMIT_FLOOR_D), limit_z=np.clip(margin * z_max, LIMIT_FLOOR_Z, LIMIT_CAP_Z),
                   limit_fast=np.maximum(margin * f_max, LIMIT_FLOOR_FAST), fast_factor=factor)


def count_alarms(model: CrewBaselineModel, series: list[dict[str, NpcSeries]], modes: tuple[str, ...]) -> int:
    return sum(len(lst) for ser in series for lst in all_alarms(model, ser, modes).values())


def event_counts(model: CrewBaselineModel, runs, series, modes: tuple[str, ...]) -> tuple[int, int, int]:
    """(detected, events, alarms outside the events) over the M runs."""
    det = outside = 0
    for r, ser in zip(runs, series, strict=True):
        al = all_alarms(model, ser, modes)
        res = event_result(r, ser, al, 0.0, SLOW_CONFIRM_S)
        det += int(res["detected"])
        outside += res["wrong_person"] + res["other_alarms_same_person"]
    return det, len(runs), outside


def calibrate(model: CrewBaselineModel, nom_val, ev_runs, ev_series, margins, factors, log) -> tuple[CrewBaselineModel, dict]:
    """Choose the margin and the fast factor on the validation runs; returns the model with the limits and the table of candidates."""
    per_series = [series_maxima(model, s) for s in nom_val]
    maxima = combine(per_series)
    max_a, max_b = combine(per_series[: len(nom_val) // 2]), combine(per_series[len(nom_val) // 2:])
    half_a, half_b = nom_val[: len(nom_val) // 2], nom_val[len(nom_val) // 2:]
    table = []
    for margin, factor in itertools.product(margins, factors):
        m = limited(model, maxima, margin, factor)
        fa_val = {mode: count_alarms(m, nom_val, (mode,)) for mode in ("slow", "fast")}
        fa_cross = {mode: count_alarms(limited(model, max_a, margin, factor), half_b, (mode,))
                    + count_alarms(limited(model, max_b, margin, factor), half_a, (mode,)) for mode in ("slow", "fast")}
        row = {"margin": margin, "fast_factor": factor, "fa_n1_val": fa_val, "fa_n1_split_half": fa_cross}
        for modes in (("slow",), ("fast",), ("slow", "fast")):
            det, n, out = event_counts(m, ev_runs, ev_series, modes)
            row["+".join(modes)] = {"detected": det, "events": n, "alarms_outside_events": out}
        table.append(row)
        log(f"margin {margin:<5} fast x{factor:<4} FA N1 val {fa_val} half-split {fa_cross}  recall slow {row['slow']['detected']}/{row['slow']['events']} "
            f"fast {row['fast']['detected']} both {row['slow+fast']['detected']}  outside: slow {row['slow']['alarms_outside_events']} "
            f"fast {row['fast']['alarms_outside_events']} both {row['slow+fast']['alarms_outside_events']}")

    def cost(row, mode):  # (false alarms on the nominal checks, alarms outside the events), lexicographic; ties -> the smaller value
        return (row["fa_n1_val"][mode] + row["fa_n1_split_half"][mode], row[mode]["alarms_outside_events"])

    best_margin = min(margins, key=lambda g: (min(cost(r, "slow") for r in table if r["margin"] == g), g))
    best_factor = min(factors, key=lambda f: (min(cost(r, "fast") for r in table if r["fast_factor"] == f), f))
    chosen = limited(model, maxima, best_margin, best_factor)
    log(f"chosen: margin {best_margin}, fast factor {best_factor}; limits D2 {chosen.limit_d:.1f}, z {np.round(chosen.limit_z, 1).tolist()}, "
        f"fast {np.round(chosen.limit_fast, 1).tolist()}")
    return chosen, {"candidates": table, "margin": best_margin, "fast_factor": best_factor, "sustained_max_d2": maxima[0],
                    "sustained_max_z": dict(zip(QUANTITIES, maxima[1].tolist(), strict=True)),
                    "sustained_max_fast": dict(zip(FAST_QUANTITIES, maxima[2].tolist(), strict=True))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--features", nargs="*", default=None, help="folders with the runs (default: every crew* folder of output/ml)")
    p.add_argument("--out", default=str(ROOT / "models" / "station_v2"))
    p.add_argument("--train-seeds", default="101-124")
    p.add_argument("--val-seeds", default="131-136", help="the N1 validation runs (scale, precision, limits)")
    p.add_argument("--event-val-seeds", default="131-138", help="the M runs the recall is read on")
    p.add_argument("--kind", choices=["both", "regressor", "table"], default="both")
    p.add_argument("--margins", default="1.25,1.5,1.75,2.0")
    p.add_argument("--fast-factors", default="1.5,2.0,3.0")
    args = p.parse_args(argv)

    def log(*a):
        print(*a, flush=True)

    runs = find_runs(args.features or default_dirs())
    tr_seeds, va_seeds, ev_seeds = (set(parse_seeds(s)) for s in (args.train_seeds, args.val_seeds, args.event_val_seeds))
    n1 = [r for r in runs if r.group == "N1"]
    n1_train = [r for r in n1 if r.seed in tr_seeds]
    n1_val = [r for r in n1 if r.seed in va_seeds]
    ev_runs = [r for r in runs if r.group.startswith("M") and r.seed in ev_seeds]
    if not (n1_train and n1_val and ev_runs):
        raise SystemExit("need N1 runs for the training and the validation seeds, and M runs for the recall")
    log(f"N1: {len(n1_train)} train, {len(n1_val)} val; M validation runs: {len(ev_runs)}")
    names = feature_names()
    assert list(n1_train[0].crew.columns[2:2 + len(names)]) == names, "crew.parquet and CrewFeatureExtractor disagree"

    def by_npc(rs):
        out = {npc: [] for npc in NPC_ORDER}
        for r in rs:
            df = r.crew
            for npc in NPC_ORDER:
                out[npc].append(df[df["npc"] == npc].sort_values("t_s").reset_index(drop=True))
        return out

    train, val = by_npc(n1_train), by_npc(n1_val)
    kinds = ["regressor", "table"] if args.kind == "both" else [args.kind]
    results = {}
    for kind in kinds:
        log(f"\n== {kind} ==")
        model = fit_model(kind, train, val, names)
        nom_val = [run_series(model, r) for r in n1_val]
        ev_series = [run_series(model, r) for r in ev_runs]
        chosen, cal = calibrate(model, nom_val, ev_runs, ev_series, [float(x) for x in args.margins.split(",")],
                                [float(x) for x in args.fast_factors.split(",")], log)
        both = event_counts(chosen, ev_runs, ev_series, ("slow", "fast"))
        regressor = ("HistGradientBoostingRegressor(absolute_error, depth 3, 200 it) on the context and the memory of the programme"
                     if kind == "regressor" else "median per (activity class, MET band 1)")
        chosen.info = {"kind": kind, "train_seeds": sorted(tr_seeds), "val_seeds": sorted(va_seeds), "event_val_seeds": sorted(ev_seeds),
                       "train_rows": int(sum(len(f) for v in train.values() for f in v)), "val_rows": int(sum(len(f) for v in val.values() for f in v)),
                       "margin": cal["margin"], "fast_factor": cal["fast_factor"], "tau_s": TAU_S, "memory_tau_min": list(MEMORY_TAU_MIN),
                       "regressor": regressor, "limit_floors": {"z": LIMIT_FLOOR_Z, "d2": LIMIT_FLOOR_D, "fast": LIMIT_FLOOR_FAST}, "limit_cap_z": LIMIT_CAP_Z,
                       "test_seeds_read": False, **provenance()}
        results[kind] = {"model": chosen, "calibration": cal, "recall_val": both}
        log(f"{kind}: validation recall slow+fast {both[0]}/{both[1]}, alarms outside events {both[2]}")

    # keep the better one on the validation: the fewer false alarms first (N1 validation, split-half, outside the M events: a false alarm
    # costs the crew's attention, the plan weighs precision twice), then the recall of the M validation runs; on a tie the table
    def merit(kind):
        det, _n, out = results[kind]["recall_val"]
        cal = results[kind]["calibration"]
        row = next(r for r in cal["candidates"] if r["margin"] == cal["margin"] and r["fast_factor"] == cal["fast_factor"])
        false_alarms = sum(row["fa_n1_val"].values()) + sum(row["fa_n1_split_half"].values()) + out
        results[kind]["false_alarm_checks"] = false_alarms
        return (false_alarms, -det, 0 if kind == "table" else 1)

    keep = min(results, key=merit)
    summary = ", ".join("{}: {}/{} detected, {} outside, {} false-alarm checks".format(k, *v["recall_val"], v["false_alarm_checks"]) for k, v in results.items())
    log(f"\nkept: {keep}  ({summary})")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import joblib

    model = results[keep]["model"]
    joblib.dump(model, out / "crew_baseline.joblib")
    nom = nominal_report(model, n1_val)
    card = {"kept": keep, "split": {"train": sorted(tr_seeds), "val": sorted(va_seeds), "event_val": sorted(ev_seeds), "test": "not read"},
            "info": model.info, "limit_d": model.limit_d, "limit_z": dict(zip(QUANTITIES, model.limit_z.tolist(), strict=True)),
            "limit_fast": dict(zip(FAST_QUANTITIES, model.limit_fast.tolist(), strict=True)),
            "fast_factor": model.fast_factor, "tau_s": model.tau_s,
            "sigma": {npc: {q: dict(zip(CLASSES, model.sigma[npc][i].round(4).tolist(), strict=True)) for i, q in enumerate(QUANTITIES)} for npc in NPC_ORDER},
            "validation": {"n1_false_alarms": nom["alarms"], "n1_days": nom["days"], "n1_during_exercise": nom["during_exercise"],
                           "comparison": {k: {"calibration": v["calibration"], "recall_val_detected_events_outside": v["recall_val"]} for k, v in results.items()}}}
    (out / "model_card_crew.json").write_text(json.dumps(card, indent=1, default=float), encoding="utf-8")
    log(f"written {out / 'crew_baseline.joblib'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
