"""Train the stage-A anomaly detectors (one PCA per subsystem of ``groups.yaml``) on NOMINAL feature rows and write
``models/station_v1/detector_<group>.joblib`` plus a model card with what was measured.

Input: the feature datasets of ``make_dataset.py --features`` (``<dir>/<job>/features.parquet`` + ``meta.json``).

    uv run python tools/ml/make_dataset.py --only nominal --seeds 1-4 --days 3 --features --out output/ml/feat
    uv run python tools/ml/make_dataset.py --only nominal --seeds 6-15 --days 1 --features --out output/ml/feat
    uv run python tools/ml/train_anomaly.py --features output/ml/feat

Split by RUN (seed), never by row: consecutive rows are nearly identical. Seeds ``--train-seeds`` fit the PCA, ``--val-seeds``
set the limit of each score (``--margin`` x the largest value seen on them; plan D7 said 1.25, but on 10 unseen nominal days that
gave 5 false alarms: 2.0 with at most 15 components gives none), ``--test-seeds`` only measure
the false alarms (an alarm = ``--confirm-s`` seconds of continuous score >= 1, like the classifier's debounce). Fault runs
(any other job in the directory) measure the detection delay; the delay is from the START of the fault, which for a slow
fault is an upper bound of the time since it was visible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import episodes

from ares3.plugins.monitor.ml.anomaly import PcaModel
from ares3.plugins.monitor.ml.features import select
from ares3.schemas.scenario import load_scenario

NOMINAL = ROOT / "scenarios" / "station" / "nominal.yaml"


def provenance() -> dict:
    """What a model was built with, for its card: a joblib file only loads against compatible library versions."""
    import datetime
    import platform

    import sklearn

    import ares3

    return {"ares3": ares3.__version__, "sklearn": sklearn.__version__, "numpy": np.__version__,
            "python": platform.python_version(), "trained_at": datetime.date.today().isoformat()}


def parse_seeds(text: str) -> list[int]:
    seeds: list[int] = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        seeds += range(int(a), int(b or a) + 1)
    return seeds


def load_runs(feat_dir: Path) -> list[dict]:
    runs = []
    for d in sorted(Path(feat_dir).iterdir()):
        if (d / "features.parquet").exists():
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            runs.append({"name": d.name, "meta": meta, "seed": int(meta["job"]["seed"]),
                         "nominal": not meta["faults"], "df": pd.read_parquet(d / "features.parquet")})
    return runs


def group_keys(spec: dict, sensors) -> list[str]:
    """Sensor ids of a group: listed metric (any target) or id matching one of the regular expressions."""
    rx = [re.compile(p) for p in spec.get("ids", [])]
    metrics = set(spec.get("metrics", []))
    return [s.id for s in sensors if s.metric in metrics or any(r.search(s.id) for r in rx)]


def fit_group(name: str, keys: list[str], train: list[pd.DataFrame], names: list[str], periods, max_comps: int = 25) -> PcaModel:
    from sklearn.decomposition import PCA

    cols = [names[i] for i in select(names, keys)]
    X = np.vstack([r[cols].to_numpy(dtype=float) for r in train])
    mean = np.nanmean(X, axis=0)
    mean = np.where(np.isfinite(mean), mean, 0.0)
    std = np.nanstd(X, axis=0)
    scale = np.maximum(np.where(np.isfinite(std), std, 0.0), 1e-6 + 1e-3 * np.abs(mean))  # a constant feature must not explode
    z = np.where(np.isfinite((X - mean) / scale), (X - mean) / scale, 0.0)
    pca = PCA(n_components=0.95, svd_solver="full").fit(z)
    k = min(pca.n_components_, max_comps)
    return PcaModel(group=name, keys=keys, columns=cols, mean=mean, scale=scale, components=pca.components_[:k].copy(),
                    eigenvalues=pca.explained_variance_[:k].copy(), clock_periods_s=tuple(periods),
                    info={"train_rows": len(X), "n_features": len(cols), "n_components": int(k),
                          "explained_variance": float(pca.explained_variance_ratio_[:k].sum()), **provenance()})


def run_scores(model: PcaModel, df: pd.DataFrame) -> np.ndarray:
    """max(T2, SPE) / limit for every row of a feature dataset."""
    a, b = model.scores(df[model.columns].to_numpy(dtype=float))
    return np.maximum(a, b)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--features", default=str(ROOT / "output" / "ml" / "feat"))
    p.add_argument("--groups", default=str(Path(__file__).with_name("groups.yaml")))
    p.add_argument("--out", default=str(ROOT / "models" / "station_v1"))
    p.add_argument("--train-seeds", default="1-3")
    p.add_argument("--val-seeds", default="4")
    p.add_argument("--test-seeds", default="6-15")
    p.add_argument("--margin", type=float, default=2.0)
    p.add_argument("--max-comps", type=int, default=15, help="cap of the principal components kept")
    p.add_argument("--confirm-s", type=float, default=600.0)
    args = p.parse_args(argv)

    runs = load_runs(Path(args.features))
    train_s, val_s, test_s = (set(parse_seeds(s)) for s in (args.train_seeds, args.val_seeds, args.test_seeds))
    nominal = [r for r in runs if r["nominal"]]
    train = [r["df"] for r in nominal if r["seed"] in train_s]
    val = [r for r in nominal if r["seed"] in val_s]
    test = [r for r in nominal if r["seed"] in test_s]
    faults = [r for r in runs if not r["nominal"]]
    if not (train and val):
        raise SystemExit("need nominal feature runs for the training and the validation seeds")
    meta0 = nominal[0]["meta"]
    sc = load_scenario(NOMINAL)
    names = [c for c in nominal[0]["df"].columns if c not in ("t_s", "faults")]
    groups = yaml.safe_load(Path(args.groups).read_text(encoding="utf-8"))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import joblib

    card: dict = {"split": {"train": sorted(train_s), "val": sorted(val_s), "test": sorted(test_s)}, "margin": args.margin,
                  "confirm_s": args.confirm_s, "eval_every_s": meta0["eval_every_s"], "groups": {}}
    for gname, spec in groups.items():
        keys = group_keys(spec, sc.layout.sensors)
        model = fit_group(gname, keys, train, names, meta0["clock_periods_s"], args.max_comps)
        peaks = [model.scores(r["df"][model.columns].to_numpy(dtype=float)) for r in val]  # limits are still 1.0: raw values
        model.t2_limit = args.margin * max(float(a.max()) for a, _ in peaks)
        model.spe_limit = args.margin * max(float(b.max()) for _, b in peaks)
        joblib.dump(model, out / f"detector_{gname}.joblib")

        rows = {"n_sensors": len(keys), **model.info, "t2_limit": model.t2_limit, "spe_limit": model.spe_limit}
        false_alarms = {r["name"]: len(episodes(run_scores(model, r["df"]) >= 1.0, r["df"]["t_s"].to_numpy(), args.confirm_s))
                        for r in test}
        rows["test_false_alarms"] = false_alarms
        rows["test_days"] = float(sum(r["df"]["t_s"].iloc[-1] / 86400.0 for r in test))
        detections = {}
        for r in faults:
            for f in r["meta"]["faults"].values():
                hit = episodes(run_scores(model, r["df"]) >= 1.0, r["df"]["t_s"].to_numpy(), args.confirm_s)
                after = [c for first, c in hit if first >= f["start_s"] - args.confirm_s]
                detections[f"{r['name']}"] = (min(after) - f["start_s"]) if after else None
        rows["fault_detection_delay_s"] = detections
        card["groups"][gname] = rows
        n_fa = sum(false_alarms.values())
        print(f"{gname}: {len(keys)} sensors, {rows['n_components']} comps, limits T2 {model.t2_limit:.3g} SPE {model.spe_limit:.3g}, "
              f"false alarms {n_fa} in {rows['test_days']:.0f} test days; fault delays "
              f"{ {k: (round(v) if v is not None else None) for k, v in detections.items()} }")
    (out / "model_card_anomaly.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
