"""The job list of the crew dataset (``tools/ml/crew_plan.yaml``): ``build_plan_jobs(plan, wave, out)`` turns the file into the SAME list
of jobs on every machine (``make_dataset.py --plan FILE --wave N --shard K/N``).

A group of the plan (``M1``, ``E1``, ...) is a scenario family with a list of seeds per split. Every draw comes from
``numpy.random.default_rng([seed, crc32(group)])`` (``crc32(group/event)`` for the variants of a group), so a job is the same everywhere and
adding a group changes no other group. What a group may contain (see the YAML for the numbers):

* ``nominal: true``: the fault-free station; ``jitter: {shift_min, met}`` moves the inner boundaries of the blocks of the programme of the
  day by U(-shift, +shift) min (0 and 24 stay, every block keeps >= 10 min, the order does not change) and multiplies the MET of each block;
* ``medical``: an event of ``scenarios/events`` on ONE person (``[cmd, eng, med, bot][seed % 4]``) that starts in a block of an activity
  (``[sleep, nominal, exercise][(seed // 4) % 3]``, or the one named in ``activity``), with the parameters, ``duration_s`` and ``ramp_s``
  drawn from ranges (never an amplitude that multiplies absolute values: ``hr_to`` is drawn, not scaled);
* ``exposure``: a ``co2_source`` / ``co_source`` in the module where that person is when it starts (``avoid_modules`` are never chosen);
* ``catalog``: faults of the workbook catalog drawn with ``make_dataset.draw_catalog`` (the first one names the scenario);
* ``regenerate``: the whole catalog (``make_dataset.build_jobs``), for the new columns.

Time: ``t = 0`` is NOT midnight, the scenario starts at ``start_time_of_day_h`` (``SimClock``): ``to_sim_s`` does the conversion.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import zlib
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import make_dataset as md  # the module of this folder: the job format, ``draw_catalog``, the paths
import numpy as np
import yaml

ROOT = md.ROOT
PEOPLE = ("cmd", "eng", "med", "bot")  # the person hit by a seed: seed % 4
ROTATION = ("sleep", "nominal", "exercise")  # activity at the start of the event: (seed // 4) % 3
WARMUP_S = 6 * 3600.0  # the earliest start of an event (3 h of warm-up of the windows, margin)
TAIL_S = 4 * 3600.0  # ... and the room left after its end
MIN_TAIL_S = 300.0  # inside the chosen block, at least 5 min before it ends
MIN_BLOCK_H = 10 / 60 + 2e-6  # a block of the jittered programme keeps at least 10 min (the hair is for the rounding of the cuts)
SPLIT_ORDER = ("train", "val", "test")
# the classes of ``plugins/monitor/ml/crew.py::activity_class`` that a plan activity stands for
CLASSES_OF = {"sleep": {"sleep"}, "nominal": {"nominal"}, "exercise": {"exercise_aerobic", "exercise_resistive"},
              "exercise_aerobic": {"exercise_aerobic"}, "exercise_resistive": {"exercise_resistive"}}


def load_plan(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _scenario(path: str):
    from ares3.schemas.scenario import load_scenario

    return load_scenario(path)


def to_sim_s(local_h: float, start_tod_h: float, day_length_s: float) -> float:
    """Simulation time of a local hour counted from the first midnight (``24 * d + h``): the engine's ``SimClock`` starts at
    ``start_tod_h``, so ``t = 0`` is that hour, not midnight."""
    return (local_h - start_tod_h) * day_length_s / 24.0


def schedule_of(member) -> list[dict]:
    """The programme of a crew member as plain dicts (``from`` / ``to`` / ``activity`` / ``module`` / ``met``)."""
    blocks = sorted(member.schedule, key=lambda b: b.from_h)
    return [{"from": b.from_h, "to": b.to_h, "activity": b.activity, "module": b.module, "met": b.met} for b in blocks]


def jitter_schedule(blocks: list[dict], rng: np.random.Generator, shift_min: float, met_range: tuple[float, float],
                    catalog: dict) -> list[dict]:
    """The programme of the day with its inner boundaries moved and the MET of every block scaled (see the module docstring). The
    first block starts at 0 and the last ends at 24, exactly; the blocks stay in order and keep >= 10 min."""
    from ares3.core.metabolism import resolve_activity

    cuts = [0.0] + [b["to"] for b in blocks[:-1]] + [24.0]
    moved = [0.0] + [c + float(rng.uniform(-shift_min, shift_min)) / 60.0 for c in cuts[1:-1]] + [24.0]
    n = len(moved)
    for i in range(1, n - 1):  # forward: a block is not shorter than the minimum
        moved[i] = max(moved[i], moved[i - 1] + MIN_BLOCK_H)
    for i in range(n - 2, 0, -1):  # backward: and the last ones do not push past 24
        moved[i] = min(moved[i], moved[i + 1] - MIN_BLOCK_H)
    moved = [round(c, 6) for c in moved]
    out = []
    for i, b in enumerate(blocks):
        met = b["met"] if b["met"] is not None else resolve_activity(b["activity"], catalog).met
        out.append({**b, "from": moved[i], "to": moved[i + 1], "met": round(met * float(rng.uniform(*met_range)), 4)})
    return out


def _occurrences(blocks: list[dict], classes: set[str], avoid: set[str], run_s: float, start_tod_h: float,
                 day_length_s: float) -> list[tuple[float, float, dict]]:
    """``(t0, t1, block)`` of every occurrence, in simulation time, of a block of one of ``classes`` (not in an avoided module)."""
    from ares3.plugins.monitor.ml.crew import activity_class

    out = []
    for d in range(-1, math.ceil(run_s / day_length_s) + 2):
        for b in blocks:
            if activity_class(b["activity"]) in classes and b["module"] not in avoid:
                t0, t1 = (to_sim_s(24.0 * d + b[k], start_tod_h, day_length_s) for k in ("from", "to"))
                if t1 > 0.0 and t0 < run_s:
                    out.append((t0, t1, b))
    return out


def draw_start(rng: np.random.Generator, blocks: list[dict], classes: set[str], avoid: set[str], run_s: float, dur_s: float,
               start_tod_h: float, day_length_s: float) -> tuple[float, dict, bool]:
    """Start of an event: a block of the class inside ``[6 h, run - duration - 4 h]`` chosen uniformly among the occurrences, then an
    instant uniform in it (>= 5 min before it ends). Returns ``(start_s, block, fallback)``; with no block that fits, the valid start
    NEAREST to the window (``fallback`` True: the plan wanted something else, and the job says so in its meta)."""
    lo, hi = WARMUP_S, run_s - dur_s - TAIL_S
    occ = [(t0, t1 - MIN_TAIL_S, b) for t0, t1, b in _occurrences(blocks, classes, avoid, run_s, start_tod_h, day_length_s)]
    fits = [(max(a, lo, 0.0), min(z, hi), b) for a, z, b in occ if max(a, lo, 0.0) <= min(z, hi)]
    if fits:
        a, z, b = fits[int(rng.integers(len(fits)))]
        return float(rng.uniform(a, z)), b, False
    if not occ:
        raise ValueError(f"no block of {sorted(classes)} in the programme")
    a, z, b = min(occ, key=lambda o: max(o[0] - hi, lo - o[1], 0.0))  # the occurrence whose starts are nearest to the window
    return float(max(min(max(hi if a > hi else lo, a), z), 0.0)), b, True


def _draw(rng: np.random.Generator, spec) -> float:
    """A value of a range: ``[min, max]`` (uniform) or ``{choose: [...]}``; a plain number stays."""
    if isinstance(spec, dict):
        return spec["choose"][int(rng.integers(len(spec["choose"])))]
    if isinstance(spec, (list, tuple)):
        return round(float(rng.uniform(*spec)), 6)
    return spec


def _block_at(blocks: list[dict], t_s: float, start_tod_h: float, day_length_s: float) -> dict:
    """The block of the programme at simulation time ``t_s``, found with the ``SimClock`` of the engine."""
    from ares3.core.clock import SimClock

    clock = SimClock(dt_s=1.0, day_length_s=day_length_s, start_tod_h=start_tod_h, tick=int(t_s))
    tod = clock.time_of_day_h
    return next((b for b in blocks if b["from"] <= tod < b["to"]), blocks[-1])


def _fault(fid: str, ftype: str, targets: list[str], start_s: float, dur_s: float, params: dict, label: str, priority: int) -> dict:
    return {"id": fid, "type": ftype, "targets": targets, "start_s": round(start_s, 3), "duration_s": round(dur_s, 3), "params": params,
            "anomaly_type": label, "priority": priority}


def _sub_groups(name: str, group: dict) -> list[tuple[str, dict]]:
    """The ``(event, spec)`` of a group: the group itself, or one per entry of ``variants`` (each over the keys of the group)."""
    base = {k: v for k, v in group.items() if k != "variants"}
    if "variants" in group:
        return [(v["event"], {**base, **v}) for v in group["variants"]]
    return [(group.get("event") or _default_event(group), base)]


def _default_event(group: dict) -> str:
    """The event of a group without an ``event`` key: ``nominal``, the label of its medical event or exposure, or its catalog faults."""
    if group.get("nominal"):
        return "nominal"
    if group.get("medical") or group.get("exposure"):
        return (group.get("medical") or group.get("exposure"))["label"]
    return "+".join(group["catalog"])


def _medical_spec(spec: dict, plan: dict):
    m = spec.get("medical")
    return plan["groups"][m]["medical"] if isinstance(m, str) else m  # "M1": the medical event of that group


def _job(plan: dict, name: str, event: str, spec: dict, seed: int, split: str, out: Path) -> dict:
    sc = _scenario(str(ROOT / plan.get("scenario", "scenarios/station/nominal.yaml")))
    day_s, start_tod = sc.environment.day_length_s, sc.file.start_time_of_day_h
    days = float(spec["days"])
    run_s = days * day_s
    key = name if len(_sub_groups(name, plan["groups"][name])) == 1 else f"{name}/{event}"
    rng = np.random.default_rng([int(seed), zlib.crc32(key.encode())])
    job: dict = {"scenario": str(md.NOMINAL), "seed": int(seed), "days": days, "features": True, "name": f"crew-{name}-{event}",
                 "group": name, "split": split, "event": event, "npc": None, "activity_at_start": None, "module": None}
    schedules = {m.id: schedule_of(m) for m in sc.crew.members}
    if "jitter" in spec:
        jit = spec["jitter"]
        catalog = _metabolic_catalog(sc)
        schedules = {m: jitter_schedule(b, rng, float(jit["shift_min"]), tuple(jit["met"]), catalog) for m, b in schedules.items()}
        job["crew_schedule"] = schedules
    if spec.get("regenerate"):
        raise ValueError("a regenerate group is expanded by build_plan_jobs, not here")
    medical, exposure, catalog_ids = _medical_spec(spec, plan), spec.get("exposure"), list(spec.get("catalog") or [])
    faults: list[dict] = []
    anchor = medical or exposure
    start_s = None
    if anchor:
        comps = {k: c for k, c in (("medical", medical), ("exposure", exposure)) if c}
        durations = {k: float(_draw(rng, c["duration_s"])) for k, c in comps.items()}
        values = {k: {p: _draw(rng, r) for p, r in c.get("params", {}).items()} for k, c in comps.items()}
        ramp = _draw(rng, medical["ramp_s"]) if medical and "ramp_s" in medical else None
        npc = PEOPLE[seed % 4]
        want = spec.get("activity") or (medical or {}).get("activity") or ROTATION[(seed // 4) % 3]
        avoid = set(exposure.get("avoid_modules", [])) if exposure else set()
        start_s, _, fallback = draw_start(rng, schedules[npc], CLASSES_OF[want], avoid, run_s, max(durations.values()), start_tod, day_s)
        at = _block_at(schedules[npc], start_s, start_tod, day_s)
        job.update(npc=npc, activity_at_start=at["activity"], module=at["module"], activity_wanted=want, start_fallback=fallback,
                   drawn={"start_s": round(start_s, 3), "durations_s": durations, **values})
        if medical:
            raw = yaml.safe_load(Path(ROOT / medical["faults_file"]).read_text(encoding="utf-8"))["faults"]
            for i, f in enumerate(raw):
                params = {**f.get("params", {}), **values["medical"], **({"ramp_s": ramp} if ramp is not None else {})}
                fid = f"{npc}_{medical['label']}" if i == 0 else f"{npc}_{medical['label']}_{i}"
                faults.append(_fault(fid, f["type"], [npc], start_s, durations["medical"], params, medical["label"], medical["priority"]))
        if exposure:
            faults.append(_fault(f"{at['module']}_{exposure['type']}", exposure["type"], [at["module"]], start_s, durations["exposure"],
                                 values["exposure"], exposure["label"], exposure["priority"]))
    if catalog_ids:
        ranges = yaml.safe_load(md.RANGES.read_text(encoding="utf-8"))
        job["scenario"] = str(md.EVENTS / f"{catalog_ids[0]}.yaml") if not anchor else str(md.NOMINAL)
        per_fault: dict = {}
        for i, fid in enumerate(catalog_ids):
            drawn = md.draw_catalog(fid, seed + 1000 * i, ranges)  # the second fault of a pair: another seed, like the combos
            for entry in drawn.values():
                if start_s is not None:
                    entry["start_s"] = round(start_s, 3)  # together with the person's event
                elif i > 0:
                    entry["start_s"] = per_fault[next(iter(per_fault))]["start_s"]
            per_fault.update(drawn)
        if "scale" in spec:
            per_fault[next(iter(_catalog_ids(catalog_ids[0])))]["scale"] = round(float(rng.uniform(*spec["scale"])), 6)
        job["per_fault"] = per_fault
        if anchor or len(catalog_ids) > 1:
            job["extra_faults"] = catalog_ids if anchor else catalog_ids[1:]
        job["drawn_catalog"] = {k: {"start_s": round(v["start_s"], 3), **({"scale": v["scale"]} if "scale" in v else {}),
                                    **({"params": v["params"]} if "params" in v else {})} for k, v in per_fault.items()}
    if faults:
        job["faults"] = faults
    job["out"] = str(out / md.job_id(job))
    return job


def _catalog_ids(fid: str) -> list[str]:
    return [f.id for f in md._catalog_faults(fid)]


def _metabolic_catalog(sc) -> dict:
    from ares3.core.metabolism import build_catalog

    return build_catalog(sc.crew.activities)


def _seeds(group: dict) -> list[tuple[str, int]]:
    """``[(split, seed)]`` of a group in the order train, val, test."""
    return [(s, seed) for s in SPLIT_ORDER if s in group["seeds"] for seed in md.parse_seeds(str(group["seeds"][s]))]


def build_plan_jobs(plan: dict, wave: int, out: Path, ticks: int | None = None) -> list[dict]:
    """The jobs of one wave, in a FIXED order: the seeds of train first, then val, then test; inside a split the groups alternate (a
    round-robin), so every shard (position modulo N) gets useful data early and runs of different lengths. A ``regenerate`` group goes at
    the very end (the first thing to cut). A disabled group (``enabled: false``) gives no job."""
    by_split: dict[str, dict[str, list[dict]]] = {s: defaultdict(list) for s in SPLIT_ORDER}
    last: list[dict] = []
    for name, group in plan["groups"].items():
        if group.get("wave") != wave or not group.get("enabled", True):
            continue
        if group.get("regenerate"):
            ranges_seeds = [seed for _, seed in _seeds(group)]
            for job in md.build_jobs(ranges_seeds, float(group["days"]), None, out, nominal=False, features=True, randomize=True,
                                     combos=bool(group.get("combos"))):
                event = Path(job["scenario"]).stem + "".join("+" + e for e in job.get("extra_faults", []))
                job |= {"name": f"crew-{name}-{event}", "group": name, "split": _split_of(group, job["seed"]), "event": event,
                        "npc": None, "activity_at_start": None, "module": None}
                job["out"] = str(out / md.job_id(job))
                last.append(job)
            continue
        subs = _sub_groups(name, group)
        for split, seed in _seeds(group):
            for event, spec in subs:
                by_split[split][f"{name}/{event}"].append(_job(plan, name, event, spec, seed, split, out))
    jobs: list[dict] = []
    for split in SPLIT_ORDER:
        queues = [q for q in by_split[split].values() if q]
        while any(queues):  # round-robin: one job of each group in turn
            for q in queues:
                if q:
                    jobs.append(q.pop(0))
    jobs += last
    if ticks:
        for j in jobs:
            j["ticks"] = ticks
            j["out"] = str(out / md.job_id(j))
    return jobs


def _split_of(group: dict, seed: int) -> str:
    return next(s for s in SPLIT_ORDER if s in group["seeds"] and seed in md.parse_seeds(str(group["seeds"][s])))


def jobs_hash(jobs: list[dict]) -> str:
    """Hash of the whole list (ids, order and every drawn value, not the output folder nor where the repo is checked out): equal on two
    machines = the same list."""
    h = hashlib.sha256()
    for j in jobs:
        d = {k: v for k, v in j.items() if k != "out"}
        d["scenario"] = Path(d["scenario"]).relative_to(ROOT).as_posix()  # absolute in the job, different on every machine
        h.update(json.dumps(d, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def describe(jobs: list[dict], pick: str | None = None) -> str:
    """The text of ``--list``: the jobs per group and per split and the simulated days."""
    per_group, per_split = defaultdict(int), defaultdict(int)
    days = 0.0
    sc = _scenario(str(md.NOMINAL))
    for j in jobs:
        per_group[j["group"]] += 1
        per_split[j["split"]] += 1
        days += (j["ticks"] * sc.file.dt_s / sc.environment.day_length_s) if j.get("ticks") else j["days"]
    lines = [md.job_id(j) for j in jobs]
    lines += ["", "per group: " + ", ".join(f"{g} {n}" for g, n in per_group.items()),
              "per split: " + ", ".join(f"{s} {per_split[s]}" for s in SPLIT_ORDER if per_split[s]),
              f"{len(jobs)} jobs, {days:.1f} simulated days, list hash {jobs_hash(jobs)}"]
    return "\n".join(lines)


def pick_jobs(jobs: list[dict], regex: str) -> list[dict]:
    rx = re.compile(regex)
    return [j for j in jobs if rx.search(md.job_id(j))]
