"""Sweep the decision threshold (and the confirmation time) of a trained stage-B model on the runs it never saw, without retraining.

For every threshold: false alarms per day on the nominal test runs, and on the single faults of the test seeds how many are diagnosed
with the RIGHT label, how many with another one, and the median delay from the moment the fault is visible (twin run).

uv run python tools/ml/sweep_diagnoser.py [--features output/ml/feat] [--thresholds 0.6,0.8,0.9,0.95] [--confirm-x 1,2]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from train_anomaly import episodes, load_runs
from train_diagnoser import feature_columns, visible_since


def alarms(model, df, thr: float, confirm: dict[str, float], confirm_x: float) -> dict[str, float]:
    """label -> time of the first confirmed alarm of the run (every family, the best non-nominal class above ``thr``)."""
    x = df[model.columns].to_numpy(dtype=float)
    t = df["t_s"].to_numpy()
    first: dict[str, float] = {}
    n_alarms = 0
    for clf in model.families.values():
        pr = clf.predict_proba(x)
        cl = clf.classes_
        nom = int(np.nonzero(cl == "nominal")[0][0])
        best = np.where(np.arange(len(cl))[None, :] == nom, -1.0, pr).argmax(axis=1)
        bp = pr[np.arange(len(pr)), best]
        for label in set(cl[best[bp >= thr]]):
            hit = episodes((cl[best] == label) & (bp >= thr), t, confirm.get(label, 900.0) * confirm_x)
            n_alarms += len(hit)
            if hit:
                first[label] = min(first.get(label, np.inf), hit[0][1])
    first["__n__"] = n_alarms
    return first


def sweep_medical(args) -> int:
    """The table threshold -> false alarms per day / recall of every live class of the medical family, on the validation seeds."""
    import medical
    from crew_data import parse_seeds

    model = joblib.load(args.model)
    classes = yaml.safe_load(Path(args.classes).read_text(encoding="utf-8"))
    confirm = {k: v.get("confirm_s", 300.0) for k, v in classes.items()}
    seeds = set(parse_seeds(args.val_seeds))
    if any(s >= 141 for s in seeds):
        raise SystemExit("the test seeds (141+) are opened once, by eval_medical.py")
    runs = medical.load_all([Path(d) for d in args.features] if isinstance(args.features, list) and args.features else None)
    twins = medical.twin_index(runs)
    pick = [r for r in runs if r.seed in seeds and (r.group == "N1" or r.group.startswith("M"))]
    val = medical.predict_val(model.families["medical"], pick, twins, model.scale, list(model.columns), classes,
                              float(model.info.get("medical", {}).get("visible_k", 3.0)), args.fallback_visible)
    out = medical.tune(model, val, confirm, args.fa_target)
    print(f"\nnominal validation days: {out['nominal_days']:.1f}")
    for label, rows in out["table"].items():
        print(f"\n{label}")
        for r in rows:
            print(f"  min_proba {r['threshold']:.2f}  false alarms {r['per_day']:6.3f}/day ({r['false_alarms']:3d})  recall {r['detected']}/{r['events']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--features", nargs="*", default=None, help="folders with the runs (default: output/ml/feat; with --medical, every crew* folder)")
    p.add_argument("--model", default=str(ROOT / "models" / "station_v1" / "diagnoser.joblib"))
    p.add_argument("--classes", default=str(Path(__file__).with_name("classes.yaml")))
    p.add_argument("--thresholds", default="0.6,0.8,0.9,0.95")
    p.add_argument("--confirm-x", default="1,2", help="multiples of each class's confirm_s")
    p.add_argument("--medical", action="store_true", help="the medical family on the crew dataset: per class the false alarms per day and the recall at each "
                   "threshold, on the validation seeds (the test seeds are never read here)")
    p.add_argument("--val-seeds", default="131-138")
    p.add_argument("--fa-target", type=float, default=0.05)
    p.add_argument("--fallback-visible", action="store_true", help="no twin: visible = start + ramp_s (+ 1 h for the dehydration)")
    args = p.parse_args(argv)
    if args.medical:
        return sweep_medical(args)

    model = joblib.load(args.model)  # our own file: joblib runs code on load
    classes = yaml.safe_load(Path(args.classes).read_text(encoding="utf-8"))
    confirm = {k: v.get("confirm_s", 900.0) for k, v in classes.items()}
    train_seeds = set(model.info["train_seeds"])
    runs = load_runs(Path(args.features[0] if args.features else ROOT / "output" / "ml" / "feat"))
    cols = feature_columns(runs[0]["df"])
    nominal = {r["seed"]: r for r in runs if r["nominal"] and r["meta"]["job"].get("days", 3) >= 2}
    nom_test = [r for r in runs if r["nominal"] and r["seed"] not in train_seeds]
    days = sum(r["df"]["t_s"].iloc[-1] / 86400.0 for r in nom_test)
    faults = []  # (run, fault id, true label, visible_since): single catalog faults of the test seeds
    for r in runs:
        if r["nominal"] or r["seed"] in train_seeds or "+" in r["name"] or r["seed"] not in nominal:
            continue
        vis = visible_since(r, nominal[r["seed"]], model.scale, cols, float(model.info["visible_k"]))
        for fid, f in r["meta"]["faults"].items():
            if f["label"] in classes and vis.get(fid) is not None:
                faults.append((r, f["label"], vis[fid], f["start_s"]))
    print(f"{len(nom_test)} nominal test runs = {days:.1f} days; {len(faults)} test faults visible in the twin run")

    for x in [float(v) for v in args.confirm_x.split(",")]:
        for thr in [float(v) for v in args.thresholds.split(",")]:
            fa = sum(alarms(model, r["df"], thr, confirm, x)["__n__"] for r in nom_test)
            right = wrong = 0
            delays = []
            per_family: dict[str, list[int]] = {}
            for r, label, vis, _start in faults:
                got = alarms(model, r["df"], thr, confirm, x)
                fam = classes[label]["family"]
                ok = label in got and got[label] >= vis - 3600.0  # an alarm long before the effect shows is not a diagnosis
                if ok:
                    right += 1
                    delays.append(got[label] - vis)
                elif any(k != "__n__" for k in got):
                    wrong += 1
                per_family.setdefault(fam, [0, 0])[0] += int(ok)
                per_family[fam][1] += 1
            med = f"{np.median(delays) / 60:.0f} min" if delays else "-"
            fams = " ".join(f"{k}:{v[0]}/{v[1]}" for k, v in sorted(per_family.items()))
            print(f"confirm x{x:g}  thr {thr:.2f}  false alarms {fa:3d} ({fa / days:.2f}/day)  right {right}/{len(faults)}  "
                  f"other label {wrong}  median delay {med}   [{fams}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
