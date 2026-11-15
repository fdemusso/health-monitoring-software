"""Stage B medical diagnosis GATED by the crew baseline (stage A), on the VALIDATION seeds only: the diagnosis speaks only while the baseline
flags somebody and the person it names is the one the baseline flags (``DiagnosisDetector(gate_board=...)``). Compared with the diagnosis alone.

    uv run python tools/ml/eval_gated.py [--confirm-x 2]

Same rows and same rules as the live monitor: the baseline flags a person when its slow statistic (smoothed) or its fast one is >= 1; the
diagnosis is the best live class over its own threshold; an alarm is a class held for ``confirm_x`` x ``confirm_s`` of ``classes.yaml``
(the live ``diagnosis`` table doubles it). Per event: right label AND right person (the person the baseline flags most), the person right with
any label, the delay from the visible time; false alarms per day on the nominal days of validation (N1 val and the stretch of every M run
before its event). The test seeds (141+) are refused: that test is spent.
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

import medical
from crew_data import parse_seeds
from eval_crew import bootstrap_median, run_series, wilson
from medical import AFTER_END_S, best_live, episodes, nominal_slices

from ares3.plugins.monitor.ml.crew_baseline import ema, load_model


def flag_scores(a_model, run, t_rows: np.ndarray) -> tuple[list[str], np.ndarray]:
    """(people, scores): the baseline score of each person at each of the times ``t_rows`` (max of the smoothed slow statistic and the fast one;
    0 where the baseline is not ready yet)."""
    ser = run_series(a_model, run)
    people = list(ser)
    out = np.zeros((len(t_rows), len(people)))
    for j, npc in enumerate(people):
        s = ser[npc]
        stat, _, _ = a_model.stats(npc, s.z)
        score = np.maximum(ema(stat, s.every_s, a_model.tau_s), a_model.fast_stat(s.z))
        idx = np.searchsorted(s.t, t_rows)
        ok = (idx < len(s.t)) & (s.t[np.minimum(idx, len(s.t) - 1)] == t_rows)
        out[ok, j] = score[idx[ok]]
    run.free()
    return people, out


def decisions(model, v: medical.ValRun) -> np.ndarray:
    lab, p = best_live(model, v.proba)
    thr = np.asarray([model.threshold(c, 0.6) for c in lab])
    return np.where(p >= thr, lab, "nominal")


def alarms(dec: np.ndarray, t: np.ndarray, subject: np.ndarray, confirm: dict[str, float], cx: float) -> list[dict]:
    out = []
    for label in sorted(set(dec) - {"nominal"}):
        for start, conf in episodes(dec == label, t, confirm.get(label, 300.0) * cx):
            i = min(int(np.searchsorted(t, conf)), len(t) - 1)
            out.append({"label": label, "start_s": start, "confirm_s": conf, "subject": subject[i]})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--diagnoser", default=str(ROOT / "models" / "station_v2" / "diagnoser.joblib"))
    p.add_argument("--crew", default=str(ROOT / "models" / "station_v2" / "crew_baseline.joblib"))
    p.add_argument("--classes", default=str(Path(__file__).with_name("classes.yaml")))
    p.add_argument("--val-seeds", default="131-138")
    p.add_argument("--confirm-x", type=float, default=2.0)
    args = p.parse_args(argv)
    seeds = set(parse_seeds(args.val_seeds))
    if any(s >= 141 for s in seeds):
        raise SystemExit("the test seeds (141+) were opened once and are spent: validation only")

    diag = joblib.load(args.diagnoser)
    crew = load_model(args.crew)
    classes = yaml.safe_load(Path(args.classes).read_text(encoding="utf-8"))
    confirm = {k: v.get("confirm_s", 300.0) for k, v in classes.items()}
    medical.FALLBACK_LABELS = set(diag.info["medical"]["fallback_visible_labels"])
    runs = medical.load_all()
    twins = medical.twin_index(runs)
    pick = [r for r in runs if r.seed in seeds and (r.group == "N1" or r.group.startswith("M"))]
    val = medical.predict_val(diag.families["medical"], pick, twins, diag.scale, list(diag.columns), classes,
                              float(diag.info["medical"]["visible_k"]), False)
    by_name = {r.name: r for r in pick}

    rows = []  # per run: B decisions, the gate, the person
    for v in val:
        people, score = flag_scores(crew, by_name[v.name], v.t)
        flag = (score >= 1.0).any(axis=1)
        subject = np.asarray(people, dtype=object)[score.argmax(axis=1)]
        dec = decisions(diag, v)
        rows.append((v, dec, np.where(flag, dec, "nominal"), subject, flag))

    # ---- false alarms per day on the nominal days of validation
    nom = {id(v): s for v, s in nominal_slices([r[0] for r in rows])}
    days = sum((r[0].t[nom[id(r[0])]][-1] - r[0].t[nom[id(r[0])]][0]) / 86400.0 for r in rows if id(r[0]) in nom)
    fa = {"B alone": 0, "A+B gated": 0}
    fa_by_class: dict[str, dict[str, int]] = {}
    for v, dec, gdec, subj, _flag in rows:
        s = nom.get(id(v))
        if s is None:
            continue
        for key, d in (("B alone", dec), ("A+B gated", gdec)):
            al = alarms(d[s], v.t[s], subj[s], confirm, args.confirm_x)
            fa[key] += len(al)
            for a in al:
                fa_by_class.setdefault(a["label"], {"B alone": 0, "A+B gated": 0})[key] += 1

    # ---- events
    per: dict[str, dict] = {}
    for v, dec, gdec, subj, _flag in rows:
        if v.event is None:
            continue
        r = per.setdefault(v.event, {"n": 0, "alone_label": 0, "gated_label_person": 0, "gated_person_any_label": 0, "delays": []})
        r["n"] += 1
        lo_s, hi_s = v.start_s, v.end_s + AFTER_END_S
        alone = [a for a in alarms(dec, v.t, subj, confirm, args.confirm_x) if lo_s <= a["confirm_s"] <= hi_s and a["label"] == v.event]
        gated = [a for a in alarms(gdec, v.t, subj, confirm, args.confirm_x) if lo_s <= a["confirm_s"] <= hi_s]
        r["alone_label"] += bool(alone)
        right = [a for a in gated if a["label"] == v.event and a["subject"] == v.npc]
        r["gated_label_person"] += bool(right)
        r["gated_person_any_label"] += any(a["subject"] == v.npc for a in gated)
        if right:
            r["delays"].append((min(a["confirm_s"] for a in right) - (v.visible_s if v.visible_s is not None else v.start_s)) / 60.0)

    print(f"validation, confirm x{args.confirm_x:g}: {days:.1f} nominal days")
    print(f"false alarms: B alone {fa['B alone']} ({fa['B alone'] / days:.3f}/day), A+B gated {fa['A+B gated']} ({fa['A+B gated'] / days:.3f}/day); "
          f"by class {fa_by_class}")
    print(f"\n{'event':32s} {'n':>2s} {'B alone: label':>15s} {'gated: label+person':>20s} {'gated: person':>14s}  delay median min")
    tot = {"n": 0, "alone_label": 0, "gated_label_person": 0, "gated_person_any_label": 0}
    for ev, r in sorted(per.items()):
        for k in tot:
            tot[k] += r[k]
        d = bootstrap_median(r["delays"], 50)[0] if r["delays"] else float("nan")
        print(f"{ev:32s} {r['n']:2d} {r['alone_label']:>11d}/{r['n']:<3d} {r['gated_label_person']:>15d}/{r['n']:<4d} {r['gated_person_any_label']:>9d}/{r['n']:<4d}  {d:6.1f}")
    for k, name in (("alone_label", "B alone, right label (person not asked)"), ("gated_label_person", "A+B gated, right label AND person"),
                    ("gated_person_any_label", "A+B gated, right person, any label")):
        lo, hi = wilson(tot[k], tot["n"])
        print(f"overall {name}: {tot[k]}/{tot['n']} = {tot[k] / tot['n']:.2f}  Wilson95 {lo:.2f}-{hi:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
