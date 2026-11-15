"""Train the crew stage A (``CrewBaselineModel``): the expected value of each vital given only the context, learned on NOMINAL days, and
write ``models/station_v2/crew_baseline.joblib`` plus ``model_card_crew.json``.

    uv run python tools/ml/train_crew.py                  # trains the regressor AND the table model, keeps the better on the validation
    uv run python tools/ml/train_crew.py --kind table     # only plan B

Data: ``crew.parquet`` of the N1 runs (nominal, programme with jitter): seeds ``--train-seeds`` fit the regressors, ``--val-seeds``
give the scale of each residual (a robust sigma per person, quantity and activity class, so it includes the generalisation error),
the precision matrix and the limits. The TEST seeds (141+) are never read here: every choice (margin, fast factor, regressor or
table) is made on the validation seeds, with the M runs 131-138 for the recall.

The limits are a margin times the largest value seen on validation; the margin is the LOWEST of ``--margins`` with no false alarm on
the N1 validation runs, on a split-half check (limits from half of the validation runs, false alarms counted on the other half) and
on the stretches of the M validation runs outside their event; the recall on those M runs is printed for every candidate. The fast
factor is chosen the same way.
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
from eval_crew import NpcSeries, all_alarms, event_result, nominal_report, run_series
from train_anomaly import provenance

from ares3.plugins.monitor.ml.crew import CLASSES
from ares3.plugins.monitor.ml.crew_baseline import (
    CTX_COLUMNS,
    QUANTITIES,
    TAU_S,
    CrewBaselineModel,
    TableRegressor,
)

NPC_ORDER = ("cmd", "eng", "med", "bot")


def feature_names() -> list[str]:
    from ares3.plugins.monitor.ml.crew import ACT_NAMES, VITALS

    return ([f"{m}|{s}" for m in VITALS for s in ("lv10", "sd10")] + ["core_temp_c|sl1h"]
            + ["ctx|met10", "ctx|met_max30", "ctx|min_since_ex"] + [f"ctx|{a}" for a in ACT_NAMES]
            + ["ctx|min_since_sleep", "clock|sin", "clock|cos"])


def class_index(df: pd.DataFrame) -> np.ndarray:
    act = df[[f"ctx|{a}" for a in ("act_sleep", "act_nominal", "act_aerobic", "act_resistive", "act_recovery")]].to_numpy(dtype=float)
    return np.where(act.sum(axis=1) > 0, act.argmax(axis=1), CLASSES.index("nominal"))


def fit_regressor(kind: str, ctx: np.ndarray, y: np.ndarray):
    ok = np.isfinite(y)
    if kind == "table":
        return TableRegressor.fit(ctx[ok], y[ok])
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, max_iter=200, early_stopping=False, random_state=0).fit(ctx[ok], y[ok])


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


def fit_model(kind: str, train: dict[str, pd.DataFrame], val: dict[str, pd.DataFrame], names: list[str]) -> CrewBaselineModel:
    from sklearn.covariance import MinCovDet

    regs, sigma, precision = {}, {}, {}
    for npc in NPC_ORDER:
        tr, va = train[npc], val[npc]
        ctx_tr, ctx_va = tr[list(CTX_COLUMNS)].to_numpy(dtype=float), va[list(CTX_COLUMNS)].to_numpy(dtype=float)
        cls_tr, cls_va = class_index(tr), class_index(va)
        regs[npc], sig = {}, np.zeros((len(QUANTITIES), len(CLASSES)))
        for qi, q in enumerate(QUANTITIES):
            y_tr, y_va = tr[q].to_numpy(dtype=float), va[q].to_numpy(dtype=float)
            reg = fit_regressor(kind, ctx_tr, y_tr)
            regs[npc][q] = reg
            s_val = mad_sigma(y_va - reg.predict(ctx_va), cls_va)
            s_train = mad_sigma(y_tr - reg.predict(ctx_tr), cls_tr)
            # the floor against a class whose residual is almost always 0: half the scale on the training days
            sig[qi] = np.maximum(s_val, 0.5 * s_train)
            sig[qi] = np.maximum(sig[qi], 1e-6 + 1e-3 * abs(np.nanmedian(y_va)))
        sigma[npc] = sig
    model = CrewBaselineModel(npc_ids=list(NPC_ORDER), columns=names, regressors=regs, sigma=sigma, precision={}, kind=kind)
    for npc in NPC_ORDER:  # the precision matrix on the validation z (robust: the nights hold some exercise transitions)
        z, _ = model.z_batch(npc, val[npc][names].to_numpy(dtype=float))
        cov = MinCovDet(random_state=0).fit(z).covariance_ + 1e-6 * np.eye(len(QUANTITIES))
        precision[npc] = np.linalg.inv(cov)
    model.precision = precision
    return model


def raw_maxima(model: CrewBaselineModel, series: list[dict[str, NpcSeries]]) -> tuple[float, np.ndarray]:
    """Largest D2 and largest directional z per quantity seen in ``series`` (every person)."""
    d_max, z_max = 0.0, np.zeros(len(QUANTITIES))
    for ser in series:
        for npc, s in ser.items():
            _, d2, zm = model.stats(npc, s.z)
            d_max = max(d_max, float(d2.max()))
            z_max = np.maximum(z_max, zm.max(axis=0))
    return d_max, z_max


def limited(model: CrewBaselineModel, maxima: tuple[float, np.ndarray], margin: float, factor: float) -> CrewBaselineModel:
    d_max, z_max = maxima
    return replace(model, limit_d=margin * d_max, limit_z=np.maximum(margin * z_max, 1e-6), fast_factor=factor)


def count_alarms(model: CrewBaselineModel, series: list[dict[str, NpcSeries]], modes: tuple[str, ...]) -> int:
    return sum(len(lst) for ser in series for lst in all_alarms(model, ser, modes).values())


def event_counts(model: CrewBaselineModel, runs, series, modes: tuple[str, ...]) -> tuple[int, int, int]:
    """(detected, events, alarms outside the events) over the M runs."""
    det = outside = 0
    for r, ser in zip(runs, series, strict=True):
        al = all_alarms(model, ser, modes)
        res = event_result(r, ser, al, 0.0, 600.0)
        det += int(res["detected"])
        outside += res["wrong_person"] + res["other_alarms_same_person"]
    return det, len(runs), outside


def calibrate(model: CrewBaselineModel, nom_val, ev_runs, ev_series, margins, factors, log) -> tuple[CrewBaselineModel, dict]:
    """Choose the margin and the fast factor on the validation runs; returns the model with the limits and the table of candidates."""
    maxima = raw_maxima(model, nom_val)
    half_a, half_b = nom_val[: len(nom_val) // 2], nom_val[len(nom_val) // 2:]
    max_a, max_b = raw_maxima(model, half_a), raw_maxima(model, half_b)
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
    log(f"chosen: margin {best_margin}, fast factor {best_factor}")
    return chosen, {"candidates": table, "margin": best_margin, "fast_factor": best_factor,
                    "raw_max_d2": maxima[0], "raw_max_z": dict(zip(QUANTITIES, maxima[1].tolist(), strict=True))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--features", nargs="*", default=None, help="folders with the runs (default: every crew* folder of output/ml)")
    p.add_argument("--out", default=str(ROOT / "models" / "station_v2"))
    p.add_argument("--train-seeds", default="101-124")
    p.add_argument("--val-seeds", default="131-136", help="the N1 validation runs (scale, precision, limits)")
    p.add_argument("--event-val-seeds", default="131-138", help="the M runs the recall is read on")
    p.add_argument("--kind", choices=["both", "regressor", "table"], default="both")
    p.add_argument("--margins", default="1.25,1.5,2.0")
    p.add_argument("--fast-factors", default="1.5,2.0,3.0")
    args = p.parse_args(argv)

    log = lambda *a: print(*a, flush=True)
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
        df = pd.concat([r.crew for r in rs], ignore_index=True)
        return {npc: df[df["npc"] == npc].reset_index(drop=True) for npc in NPC_ORDER}

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
        # residual scale of the validation days: how well the context explains each quantity (median |z| would be 0.67 by construction)
        chosen.info = {"kind": kind, "train_seeds": sorted(tr_seeds), "val_seeds": sorted(va_seeds), "event_val_seeds": sorted(ev_seeds),
                       "train_rows": int(sum(len(v) for v in train.values())), "val_rows": int(sum(len(v) for v in val.values())),
                       "margin": cal["margin"], "fast_factor": cal["fast_factor"], "tau_s": TAU_S, "regressor": "HistGradientBoostingRegressor(absolute_error, depth 3, 200 it)" if kind == "regressor" else "median per (class, MET band 1)",
                       "test_seeds_read": False, **provenance()}
        results[kind] = {"model": chosen, "calibration": cal, "recall_val": both,
                         "score": (cal["candidates"], both)}
        log(f"{kind}: validation recall slow+fast {both[0]}/{both[1]}, alarms outside events {both[2]}")

    # keep the better one on the validation: the recall of the M validation runs, then the fewer alarms outside the events; on a tie the table
    def merit(kind):
        det, _n, out = results[kind]["recall_val"]
        return (-det, out, 0 if kind == "table" else 1)

    keep = min(results, key=merit)
    summary = ", ".join("{}: {}/{} detected, {} outside".format(k, *v["recall_val"]) for k, v in results.items())
    log(f"\nkept: {keep}  ({summary})")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(results[keep]["model"], out / "crew_baseline.joblib")
    model = results[keep]["model"]
    nom = nominal_report(model, n1_val)
    card = {"kept": keep, "split": {"train": sorted(tr_seeds), "val": sorted(va_seeds), "event_val": sorted(ev_seeds), "test": "not read"},
            "info": model.info, "limit_d": model.limit_d, "limit_z": dict(zip(QUANTITIES, model.limit_z.tolist(), strict=True)),
            "fast_factor": model.fast_factor, "tau_s": model.tau_s,
            "sigma": {npc: {q: dict(zip(CLASSES, model.sigma[npc][i].round(4).tolist(), strict=True)) for i, q in enumerate(QUANTITIES)} for npc in NPC_ORDER},
            "validation": {"n1_false_alarms": nom["alarms"], "n1_days": nom["days"], "n1_during_exercise": nom["during_exercise"],
                           "comparison": {k: {"calibration": v["calibration"], "recall_val_detected_events_outside": v["recall_val"]} for k, v in results.items()}}}
    (out / "model_card_crew.json").write_text(json.dumps(card, indent=1, default=float), encoding="utf-8")
    log(f"written {out / 'crew_baseline.joblib'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
