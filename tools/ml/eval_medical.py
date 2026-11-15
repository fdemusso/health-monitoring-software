"""The test of the crew models, opened ONCE with the models frozen: the medical family of the diagnoser (stage B), the crew baseline
(stage A) and the two together, on the test seeds (M runs 141-148, N2 30 d and N3 15 d of nominal days).

    uv run python tools/ml/eval_medical.py --diagnoser models/station_v2/diagnoser.joblib --crew models/station_v2/crew_baseline.joblib

It refuses to run a second time (``--again`` overrides) and writes ``eval_medical_test.json`` with the time it was opened. Nothing is
tuned here: thresholds, margins and the choice of the model were made on the validation seeds.

Per event type and overall (Wilson 95 % interval): the event is detected by
* stage A: a signal on the AFFECTED person confirmed between the start and the end + 30 min;
* stage B, right label: the diagnosis of that very class in the window, and its subject (the person the explanation points to) is the
  affected one (``right person``: the same without asking the label);
* A + B: either of them (A on the right person, B right label and person).
False alarms per day on the nominal days (95 % upper bound), the signals during nominal exercise, and the delay from the moment the
fault is visible (the twin run) with a bootstrap interval.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import joblib
import medical
from crew_data import parse_seeds
from eval_crew import (
    SLOW_CONFIRM_S,
    all_alarms,
    bootstrap_median,
    event_result,
    exercise_alarms,
    poisson_upper,
    run_series,
    wilson,
)
from medical import AFTER_END_S, best_live, episodes

from ares3.plugins.monitor.ml.crew_baseline import load_model as load_crew


def b_alarms(model, v: medical.ValRun, confirm: dict[str, float], npc_of) -> list[dict]:
    """The alarms of the medical family on one run (every live class, the tuned thresholds, the debounce of the YAML), each with the person
    its explanation points to (as the live detector would name the ``subject``)."""
    lab, p = best_live(model, v.proba)
    thr = np.asarray([model.threshold(c, 0.6) for c in lab])
    dec = np.where(p >= thr, lab, "nominal")
    out = []
    for label in sorted(set(dec) - {"nominal"}):
        for start, conf in episodes(dec == label, v.t, confirm.get(label, 300.0)):
            i = int(np.searchsorted(v.t, conf))
            _, sensor = model.explain(v.x[min(i, len(v.x) - 1)], label)
            kind, who = model.sensor_info.get(sensor or "", ("other", ""))
            out.append({"label": label, "start_s": start, "confirm_s": conf, "subject": who if kind == "npc" else None})
    return sorted(out, key=lambda a: a["start_s"])


def fmt(iv) -> str:
    return f"{iv[0]:.2f}-{iv[1]:.2f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--diagnoser", default=str(ROOT / "models" / "station_v2" / "diagnoser.joblib"))
    p.add_argument("--crew", default=str(ROOT / "models" / "station_v2" / "crew_baseline.joblib"))
    p.add_argument("--classes", default=str(Path(__file__).with_name("classes.yaml")))
    p.add_argument("--features", nargs="*", default=None)
    p.add_argument("--test-seeds", default="141-160")
    p.add_argument("--fallback-visible", action="store_true", help="no twin: visible = start + ramp_s (+ 1 h for the dehydration)")
    p.add_argument("--again", action="store_true")
    args = p.parse_args(argv)

    out_json = Path(args.diagnoser).parent / "eval_medical_test.json"
    if out_json.exists() and not args.again:
        raise SystemExit(f"the test was already opened ({out_json}); it is opened once, with the models frozen. --again to override.")
    diag = joblib.load(args.diagnoser)  # our own files: joblib runs code on load
    crew = load_crew(args.crew)
    classes = yaml.safe_load(Path(args.classes).read_text(encoding="utf-8"))
    confirm = {k: v.get("confirm_s", 300.0) for k, v in classes.items()}
    seeds = set(parse_seeds(args.test_seeds))
    medical.FALLBACK_LABELS = set(diag.info.get("medical", {}).get("fallback_visible_labels", []))  # as in the training
    runs = medical.load_all([Path(d) for d in args.features] if args.features else None)
    twins = medical.twin_index(runs)
    pick = [r for r in runs if r.seed in seeds and (r.group in ("N2", "N3") or r.group.startswith("M"))]
    k = float(diag.info["medical"]["visible_k"])
    val = medical.predict_val(diag.families["medical"], pick, twins, diag.scale, list(diag.columns), classes, k, args.fallback_visible, keep_x=True)
    by_name = {r.name: r for r in pick}
    opened = medical.stamp()
    print(f"test opened at {opened}: {sum(v.event is not None for v in val)} event runs, {sum(v.event is None for v in val)} nominal runs", flush=True)

    # ---- nominal days: false alarms and signals during exercise
    nom_days = 0.0
    fa = {"A": 0, "B": 0, "A+B": 0}
    ex = {"A": 0, "B": 0}
    fa_list = []
    for v in val:
        if v.event is not None:
            continue
        run = by_name[v.name]
        days = (v.t[-1] - v.t[0]) / 86400.0
        nom_days += days
        ser = run_series(crew, run)
        a_al = all_alarms(crew, ser)
        n_a = sum(len(x) for x in a_al.values())
        b_al = [al for al in b_alarms(diag, v, confirm, None) if al["subject"] is not None]  # the live detector drops a diagnosis that names no person
        for al in b_al:
            if al["subject"] in ser:
                s = ser[al["subject"]]
                ex["B"] += int(s.exercising[(s.t >= al["start_s"]) & (s.t <= al["confirm_s"])].any())
        for npc, lst in a_al.items():
            ex["A"] += exercise_alarms(ser[npc], lst)
        fa["A"] += n_a
        fa["B"] += len(b_al)
        both = [(a[0], a[2]) for lst in a_al.values() for a in lst] + [(al["start_s"], al["confirm_s"]) for al in b_al]
        merged = []
        for s0, e0 in sorted(both):  # an alarm of A and one of B that overlap in time are one emergency for the crew
            if merged and s0 <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e0)
            else:
                merged.append([s0, e0])
        fa["A+B"] += len(merged)
        fa_list += [{"run": v.name, "stage": "B", **al} for al in b_al]
        run.free()
    nominal = {"days": nom_days, "alarms": fa, "per_day": {k_: n / nom_days for k_, n in fa.items()},
               "upper95_per_day": {k_: poisson_upper(n, nom_days) for k_, n in fa.items()}, "during_exercise": ex, "stage_b_alarms": fa_list}

    # ---- events
    per: dict[str, dict] = {}
    runs_out = []
    for v in val:
        if v.event is None:
            continue
        run = by_name[v.name]
        ser = run_series(crew, run)
        a_al = all_alarms(crew, ser)
        a_res = event_result(run, ser, a_al, v.visible_s if v.visible_s is not None else v.start_s, SLOW_CONFIRM_S)
        b_al = b_alarms(diag, v, confirm, None)
        window = [al for al in b_al if v.start_s <= al["confirm_s"] <= v.end_s + AFTER_END_S]
        right_label = [al for al in window if al["label"] == v.event and al["subject"] == v.npc]
        right_person = [al for al in window if al["subject"] == v.npc]
        origin = v.visible_s if v.visible_s is not None else v.start_s
        times = {"A": a_res["delay_s"] + origin if a_res["delay_s"] is not None else None,
                 "B": min((al["confirm_s"] for al in right_label), default=None),
                 "A+B": min([t_ for t_ in (a_res["delay_s"] + origin if a_res["delay_s"] is not None else None,
                                         min((al["confirm_s"] for al in right_person), default=None)) if t_ is not None], default=None)}
        rec = {"run": v.name, "event": v.event, "npc": v.npc, "visible_how": v.how, "A": a_res["detected"], "B_right_label": bool(right_label),
               "B_right_person": bool(right_person), "B_any_alarm": bool(window),
               "A+B": a_res["detected"] or bool(right_person),
               "delay_s": {k_: (t_ - origin if t_ is not None else None) for k_, t_ in times.items()},
               "b_labels_in_window": sorted({al["label"] for al in window}), "A_wrong_person_alarms": a_res["wrong_person"]}
        runs_out.append(rec)
        run.free()
    for ev in sorted({r["event"] for r in runs_out}):
        sel = [r for r in runs_out if r["event"] == ev]
        row = {"n": len(sel)}
        for key in ("A", "B_right_label", "B_right_person", "A+B"):
            kk = sum(r[key] for r in sel)
            row[key] = {"detected": kk, "recall": kk / len(sel), "wilson95": wilson(kk, len(sel))}
        for stage in ("A", "B", "A+B"):
            d = [r["delay_s"][stage] / 60 for r in sel if r["delay_s"][stage] is not None]
            row[f"delay_{stage}_min"] = {"median": bootstrap_median(d, 50), "p90": bootstrap_median(d, 90)[0], "n": len(d)}
        row["labels_given"] = {lab: sum(lab in r["b_labels_in_window"] for r in sel) for lab in sorted({x for r in sel for x in r["b_labels_in_window"]})}
        per[ev] = row
    total = {"n": len(runs_out)}
    for key in ("A", "B_right_label", "B_right_person", "A+B"):
        kk = sum(r[key] for r in runs_out)
        total[key] = {"detected": kk, "recall": kk / len(runs_out) if runs_out else math.nan, "wilson95": wilson(kk, len(runs_out))}

    print(f"\nnominal days {nom_days:.1f}: false alarms per day  A {nominal['per_day']['A']:.3f}  B {nominal['per_day']['B']:.3f}  A+B {nominal['per_day']['A+B']:.3f}"
          f"   (95 % upper bound A {nominal['upper95_per_day']['A']:.3f}, B {nominal['upper95_per_day']['B']:.3f}, A+B {nominal['upper95_per_day']['A+B']:.3f}); "
          f"signals during nominal exercise: {ex}")
    print(f"\n{'event':32s} {'n':>2s}  {'A':>5s} {'B label+person':>15s} {'B person':>9s} {'A+B':>5s}   delays median min (A / B / A+B)   labels given by B")
    for ev, r in per.items():
        d = r["delay_A_min"]["median"][0], r["delay_B_min"]["median"][0], r["delay_A+B_min"]["median"][0]
        print(f"{ev:32s} {r['n']:2d}  {r['A']['detected']:>2d}/{r['n']:<2d} {r['B_right_label']['detected']:>6d}/{r['n']:<2d}"
              f"   {r['B_right_person']['detected']:>3d}/{r['n']:<2d} {r['A+B']['detected']:>2d}/{r['n']:<2d}   {d[0]:6.1f} / {d[1]:6.1f} / {d[2]:6.1f}   {r['labels_given']}")
    for key in ("A", "B_right_label", "B_right_person", "A+B"):
        t = total[key]
        print(f"overall {key:15s}: {t['detected']}/{total['n']} = {t['recall']:.2f}  Wilson95 {fmt(t['wilson95'])}")
    out_json.write_text(json.dumps({"opened_at": opened, "test_seeds": sorted(seeds), "diagnoser": str(args.diagnoser), "crew": str(args.crew),
                                    "visible_from": sorted({r["visible_how"] for r in runs_out}), "nominal": nominal, "events": per,
                                    "total": total, "runs": runs_out}, indent=1, default=float), encoding="utf-8")
    print(f"\nwritten {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
