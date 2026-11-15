"""Train the stage-B diagnoser (one gradient-boosting classifier per family of faults) and write ``models/station_v1/diagnoser.joblib``
plus a model card with the measured results.

Input: feature datasets of ``make_dataset.py --features`` run with ``--randomize --medical --combos`` (and ``--nominal``):

    uv run python tools/ml/make_dataset.py --nominal --randomize --medical --combos --seeds 1-5 --days 2 --features --out output/ml/feat
    uv run python tools/ml/train_diagnoser.py --features output/ml/feat

Labels: a row of a fault run is positive for its fault only from ``visible_since_s``, the first time a feature of the run differs from
the TWIN run (the same seed without the fault: the engine is deterministic and every component has its own random stream, so the two
runs are identical until the fault has an effect) by more than ``--visible-k`` nominal standard deviations. Between the start and that
time the row is dropped (it would teach noise); before the start it is nominal. Split by run: seeds ``--train-seeds`` train, the
others only measure. Combinations of two faults are never trained on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from train_anomaly import episodes, load_runs, parse_seeds, provenance

from ares3.plugins.monitor.ml.diagnoser import DiagnoserModel
from ares3.schemas.scenario import load_scenario

NOMINAL = ROOT / "scenarios" / "station" / "nominal.yaml"
AFTER_END_S = 3600.0  # rows this long after a fault ends are dropped: the effect lingers


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ("t_s", "faults")]


def visible_since(run: dict, twin: dict, scale: np.ndarray, cols: list[str], k: float) -> dict[str, float | None]:
    """For each fault of ``run``: the first time at or after its start that some feature is >= ``k`` sigmas away from the twin run."""
    a = run["df"].merge(twin["df"][["t_s", *cols]], on="t_s", suffixes=("", "_twin"))
    diff = np.abs(a[cols].to_numpy(dtype=float) - a[[c + "_twin" for c in cols]].to_numpy(dtype=float)) / scale
    peak = np.nanmax(np.where(np.isfinite(diff), diff, 0.0), axis=1)
    t = a["t_s"].to_numpy()
    out: dict[str, float | None] = {}
    for fid, f in run["meta"]["faults"].items():
        hit = np.nonzero((t >= f["start_s"]) & (peak >= k))[0]
        out[fid] = float(t[hit[0]]) if len(hit) else None
    return out


def labelled(run: dict, vis: dict[str, float | None], classes: dict) -> pd.DataFrame:
    """Rows of one run with a label per family (``nominal`` / a class / ``drop`` = not used for training)."""
    df = run["df"]
    t = df["t_s"].to_numpy()
    labels = {fam: np.full(len(df), "nominal", dtype=object) for fam in {c["family"] for c in classes.values()}}
    for fid, f in run["meta"]["faults"].items():
        cls = classes.get(f["label"])
        if cls is None:
            continue
        fam = cls["family"]
        end = f["start_s"] + f["duration_s"] if f.get("duration_s") else np.inf
        v = vis.get(fid)
        began = t >= f["start_s"]
        labels[fam][began] = "drop"  # started but not (yet) visible
        if v is not None:
            labels[fam][(t >= v) & (t < end)] = f["label"]
            labels[fam][t >= end] = "drop"
    out = df[["t_s"]].copy()
    for fam, y in labels.items():
        out[f"y_{fam}"] = y
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--features", nargs="*", default=None, help="folders with the runs (default: output/ml/feat; with --families, every crew* folder)")
    p.add_argument("--classes", default=str(Path(__file__).with_name("classes.yaml")))
    p.add_argument("--out", default=str(ROOT / "models" / "station_v1"))
    p.add_argument("--train-seeds", default="1-3")
    p.add_argument("--stride", type=int, default=5, help="use every n-th feature row (rows 60 s apart)")
    p.add_argument("--visible-k", type=float, default=3.0)
    p.add_argument("--min-proba", type=float, default=0.6)
    p.add_argument("--max-iter", type=int, default=150)
    p.add_argument("--families", default=None, help="train only these families (today: medical) on the crew dataset; needs --base-model")
    p.add_argument("--base-model", default=None, help="the diagnoser whose other families, scale and signatures are kept")
    p.add_argument("--val-seeds", default="131-138", help="with --families: the seeds that set the thresholds and are read for the confusion matrix")
    p.add_argument("--fa-target", type=float, default=0.05, help="with --families: false alarms per day allowed per class on the nominal validation days")
    p.add_argument("--min-rows", type=int, default=300, help="with --families: positive rows a class needs to be live in the monitor")
    p.add_argument("--fallback-labels", default="dehydration", help="with --families: classes whose visible time is start + ramp_s (+ 1 h for the dehydration) "
                   "because the twin never shows them at k sigmas")
    p.add_argument("--fallback-visible", action="store_true", help="with --families: no twin -> visible = start + ramp_s (+ 1 h for the dehydration)")
    args = p.parse_args(argv)
    if args.families:
        if args.families != "medical" or not args.base_model:
            raise SystemExit("--families takes 'medical' and needs --base-model")
        if args.train_seeds == "1-3":
            args.train_seeds = "1-3,101-124"
        import medical

        medical.FALLBACK_LABELS = {x for x in args.fallback_labels.split(",") if x}
        return medical.train(args)
    args.features = str(args.features[0]) if args.features else str(ROOT / "output" / "ml" / "feat")

    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier

    classes = yaml.safe_load(Path(args.classes).read_text(encoding="utf-8"))
    runs = load_runs(Path(args.features))
    train_seeds = set(parse_seeds(args.train_seeds))
    nominal = {r["seed"]: r for r in runs if r["nominal"] and r["meta"]["job"].get("days", 3) >= 2}
    cols = feature_columns(runs[0]["df"])
    train_nom = [r["df"] for r in runs if r["nominal"] and r["seed"] in train_seeds]
    X0 = np.vstack([d[cols].to_numpy(dtype=float) for d in train_nom])
    mean = np.where(np.isfinite(np.nanmean(X0, axis=0)), np.nanmean(X0, axis=0), 0.0)
    std = np.nan_to_num(np.nanstd(X0, axis=0))
    scale = np.maximum(std, 1e-6 + 1e-3 * np.abs(mean))

    frames = {"train": [], "test": []}
    visible: dict[str, dict[str, float | None]] = {}
    for r in runs:
        job = r["meta"]["job"]
        single = len(r["meta"]["faults"]) <= 1 and "+" not in r["name"]
        twin = nominal.get(r["seed"])
        if r["nominal"]:
            vis = {}
        elif twin is None:
            print(f"no nominal twin for seed {r['seed']}: {r['name']} skipped")
            continue
        else:
            vis = visible_since(r, twin, scale, cols, args.visible_k)
            visible[r["name"]] = vis
        y = labelled(r, vis, classes)
        part = "train" if (r["seed"] in train_seeds and single and "extra_faults" not in job) else "test"
        d = pd.concat([r["df"][cols].reset_index(drop=True), y.reset_index(drop=True)], axis=1)
        d["run"] = r["name"]
        frames[part].append(d)
    train = pd.concat(frames["train"]).iloc[:: args.stride]
    families = sorted({c["family"] for c in classes.values()})
    models, signatures = {}, {}
    Z = (train[cols].to_numpy(dtype=float) - mean) / scale
    Z = np.where(np.isfinite(Z), Z, 0.0)
    for fam in families:
        y = train[f"y_{fam}"].to_numpy()
        keep = y != "drop"
        counts = pd.Series(y[keep]).value_counts().to_dict()
        print(f"{fam}: {int(keep.sum())} rows, classes {counts}", flush=True)
        if len(counts) < 2:
            continue
        clf = HistGradientBoostingClassifier(max_iter=args.max_iter, learning_rate=0.1, class_weight="balanced", random_state=0)
        clf.fit(train.loc[keep, cols].to_numpy(dtype=float), y[keep])
        models[fam] = clf
        for label in counts:
            if label != "nominal":
                signatures[label] = Z[(y == label)].mean(axis=0)

    sc = load_scenario(NOMINAL)
    act_module = {a.id: a.module for a in sc.layout.actuators}
    info = {}
    for s in sc.layout.sensors:
        kind, _, ent = s.target.partition(":")
        info[s.id] = (kind, act_module.get(ent, ent) if kind == "actuator" else ent) if kind in ("module", "actuator", "npc") else ("other", "")
    meta0 = runs[0]["meta"]
    model = DiagnoserModel(
        keys=[s.id for s in sc.layout.sensors], columns=cols,
        clock_periods_s=tuple(meta0["clock_periods_s"]), mean=mean, scale=scale, families=models, signatures=signatures,
        sensor_info=info, phrases={k: v["phrase"] for k, v in classes.items()},
        info={"train_seeds": sorted(train_seeds), "stride": args.stride, "visible_k": args.visible_k, "min_proba": args.min_proba,
              **provenance()})

    # ---- evaluation on the runs never trained on
    card: dict = {"info": model.info, "families": {}, "faults": {}, "false_alarms": {}}
    test = pd.concat(frames["test"]) if frames["test"] else pd.DataFrame()
    confirm = {k: v.get("confirm_s", 900) for k, v in classes.items()}
    for name, grp in test.groupby("run"):
        probs = {fam: models[fam].predict_proba(grp[cols].to_numpy(dtype=float)) for fam in models}
        t = grp["t_s"].to_numpy()
        res = {}
        for fam, pr in probs.items():
            cl = models[fam].classes_
            nom = int(np.nonzero(cl == "nominal")[0][0])
            best = np.where(np.arange(len(cl))[None, :] == nom, -1.0, pr).argmax(axis=1)
            bp = pr[np.arange(len(pr)), best]
            pred = np.where(bp >= args.min_proba, cl[best], "nominal")
            truth = grp[f"y_{fam}"].to_numpy()
            ok = truth != "drop"
            res[fam] = {"rows": int(ok.sum()), "accuracy": float((pred[ok] == truth[ok]).mean()) if ok.any() else None}
            for label in set(pred) - {"nominal"}:
                hit = episodes(pred == label, t, confirm.get(label, 900))
                if hit:
                    res.setdefault("first_diagnosis", {})[label] = hit[0][1]
        card["faults"][name] = res
    # per-fault delay from the visible time and false alarms on the nominal test runs
    for name, vis in visible.items():
        first = card["faults"].get(name, {}).get("first_diagnosis", {})
        for fid, v in vis.items():
            label = next((r["meta"]["faults"][fid]["label"] for r in runs if r["name"] == name), None)
            card["faults"].setdefault(name, {}).setdefault("delay_from_visible_s", {})[fid] = (
                first[label] - v if v is not None and label in first else None)
    for r in runs:
        if r["nominal"] and r["seed"] not in train_seeds:
            x = r["df"][cols].to_numpy(dtype=float)
            n_alarms = 0
            for fam, clf in models.items():
                pr = clf.predict_proba(x)
                cl = clf.classes_
                nom = int(np.nonzero(cl == "nominal")[0][0])
                best = np.where(np.arange(len(cl))[None, :] == nom, -1.0, pr).argmax(axis=1)
                bp = pr[np.arange(len(pr)), best]
                for label in set(cl[best[bp >= args.min_proba]]):
                    n_alarms += len(episodes((cl[best] == label) & (bp >= args.min_proba), r["df"]["t_s"].to_numpy(), confirm.get(label, 900)))
            card["false_alarms"][r["name"]] = n_alarms
    card["false_alarms_total"] = int(sum(card["false_alarms"].values()))
    card["nominal_test_days"] = float(sum(r["df"]["t_s"].iloc[-1] / 86400.0 for r in runs if r["nominal"] and r["seed"] not in train_seeds))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.info["metrics"] = {"false_alarms": card["false_alarms_total"], "nominal_test_days": card["nominal_test_days"]}
    joblib.dump(model, out / "diagnoser.joblib")
    (out / "model_card_diagnoser.json").write_text(json.dumps(card, indent=1, default=float), encoding="utf-8")
    print(f"false alarms on {card['nominal_test_days']:.0f} nominal test days: {card['false_alarms_total']}")
    for name, res in sorted(card["faults"].items()):
        print(name, {k: v for k, v in res.items() if k in ("delay_from_visible_s", "first_diagnosis")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
