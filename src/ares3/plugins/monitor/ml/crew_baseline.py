"""Stage A of the crew: "is this person's body doing what it should do, given what they are doing?", learned from NOMINAL days
only (``tools/ml/train_crew.py``). The rule detectors judge a vital against a fixed band (126 bpm at 7 MET is a fault to a band
and normal to a physiologist); this one predicts each vital from the CONTEXT ALONE (the MET and the activity of the programme,
the minutes since exercise or since sleep began, the clock: ``crew.py``) and judges the residual.

Per (crew member, quantity) a regressor gives the expected value; ``z`` = residual / sigma, where sigma is a robust scale per
activity class, raised where the context says the body is in transition (a second small regressor of the size of the residual).
The context is the row of ``crew.py`` plus a MEMORY of the programme: exponential means of ``ctx|met10`` with time constants of 30,
120 and 360 min, computed row after row (the detector and the offline evaluation run the same recursion), because the heart rate
stays above rest for hours after exercise and ``ctx|min_since_ex`` stops counting at 2 h.

The quantities are the 10 min means of the six vitals plus the noise of the heart rate (``hr|sd10``: the irregularity of an atrial
fibrillation shows there). Each has a clinical direction (SpO2 only down, core temperature and the heart rate irregularity only up).
Two statistics per crew member:

* ``D2``: robust Mahalanobis distance of the (directional) z vector, with the precision matrix of that person;
* ``max z``: the largest directional z.

``stat`` = max(D2 / L_D, max_q z_q / L_z[q]); the limits are a margin times the largest level that the validation days SUSTAINED for
the confirmation time of the detector (a stretch that short is what the debounce of the YAML lets through, so a transition of a few
minutes sets no limit). The ``slow`` detector smooths ``stat`` (exponential mean, 5 min) and signals at >= 1; the ``fast`` one looks
at the heart rate alone, unsmoothed, at ``fast_factor`` times its limit (an acute arrhythmia: the debounce of the YAML does the rest).

SECURITY: ``joblib`` runs code when it loads a file. Load only the models this project produced (``models/``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ares3.sdk import BaseDetector, Observation, Signal, StepContext

from .crew import ACT_NAMES, CLASSES, VITALS, CrewFeatureExtractor

_ROOT = Path(__file__).resolve().parents[5]  # the repository, when the model path is relative and not found from the cwd

Z_CLIP = 10.0  # sigmas: what one quantity can add, at most (as in ``anomaly.py``)
TAU_S = 300.0  # time constant of the slow statistic
QUANTITIES = tuple(f"{v}|lv10" for v in VITALS) + ("hr|sd10",)
# clinical direction: +1 only above the expected value counts, -1 only below, 0 both ways
DIRECTION = {"hr|lv10": 0, "resp_rate|lv10": 0, "spo2|lv10": -1, "core_temp_c|lv10": +1, "skin_temp_c|lv10": 0,
             "hrv_rmssd|lv10": 0, "hr|sd10": +1}
FAST_QUANTITIES = ("hr|lv10", "hr|sd10")
MEMORY_TAU_MIN = (30.0, 120.0, 360.0)  # time constants of the memory of the programme (the means of ``ctx|met10``)
EVERY_S = 60.0  # the rows of the extractor are one minute apart
CTX_COLUMNS = ("ctx|met10", "ctx|met_max30", "ctx|min_since_ex", *(f"ctx|{a}" for a in ACT_NAMES), "ctx|min_since_sleep",
               "clock|sin", "clock|cos")
_NOMINAL = CLASSES.index("nominal")
# (label, unit) of each quantity in the words for the crew
_WORDS = {"hr|lv10": ("FC", "bpm"), "resp_rate|lv10": ("FR", "atti/min"), "spo2|lv10": ("SpO2", "%"),
          "core_temp_c|lv10": ("temperatura centrale", "°C"), "skin_temp_c|lv10": ("temperatura cutanea", "°C"),
          "hrv_rmssd|lv10": ("HRV", "ms"), "hr|sd10": ("irregolarità della FC", "bpm")}
_DECIMALS = {"hr|lv10": 0, "resp_rate|lv10": 0, "spo2|lv10": 1, "core_temp_c|lv10": 1, "skin_temp_c|lv10": 1, "hrv_rmssd|lv10": 0,
             "hr|sd10": 1}


def _it(x: float, decimals: int) -> str:
    return f"{x:.{decimals}f}".replace(".", ",")


class TableRegressor:
    """Plan B of the expected value: the median of the quantity per (activity class, MET band of width 1). Same interface as an
    sklearn regressor over ``CTX_COLUMNS`` (``predict``), so the model and the detector do not care which one they hold."""

    def __init__(self, medians: dict[tuple[int, int], float], by_class: dict[int, float], overall: float) -> None:
        self.medians, self.by_class, self.overall = medians, by_class, overall

    @staticmethod
    def keys(ctx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        act = ctx[:, CTX_COLUMNS.index("ctx|act_sleep"):CTX_COLUMNS.index("ctx|act_sleep") + len(CLASSES)]
        cls = np.where(act.sum(axis=1) > 0, act.argmax(axis=1), _NOMINAL)
        met = np.nan_to_num(ctx[:, 0], nan=1.0)
        return cls, np.clip(np.floor(met), 0, 20).astype(int)

    @classmethod
    def fit(cls, ctx: np.ndarray, y: np.ndarray) -> TableRegressor:
        k, b = cls.keys(ctx)
        ok = np.isfinite(y)
        medians = {}
        for ci in np.unique(k[ok]):
            for bi in np.unique(b[ok & (k == ci)]):
                sel = ok & (k == ci) & (b == bi)
                if sel.sum() >= 20:
                    medians[(int(ci), int(bi))] = float(np.median(y[sel]))
        by_class = {int(ci): float(np.median(y[ok & (k == ci)])) for ci in np.unique(k[ok])}
        return cls(medians, by_class, float(np.median(y[ok])))

    def predict(self, ctx: np.ndarray) -> np.ndarray:
        k, b = self.keys(np.atleast_2d(ctx))
        return np.asarray([self.medians.get((int(ci), int(bi)), self.by_class.get(int(ci), self.overall))
                           for ci, bi in zip(k, b, strict=True)])


class _StackedForest:
    """Several fitted ``HistGradientBoostingRegressor`` (numerical features, identity link) evaluated TOGETHER on ONE row with numpy: all
    their trees are padded into arrays and walked level by level at once, then summed per model. A one-row ``predict`` of scikit-learn
    costs ~1 ms of overhead each (14 per person per evaluation); this costs ~0.1 ms for all of them. The answer is the model's, to the
    rounding of the sum (``tests/test_crew_baseline.py`` checks it against ``predict``). Built from the private tree arrays of
    scikit-learn: ``try_build`` gives None for anything it does not know (categorical splits, another link) and the caller falls back."""

    def __init__(self, models: list) -> None:
        trees, self.offsets, base = [], [], []
        for m in models:
            self.offsets.append(len(trees))
            base.append(float(np.ravel(m._baseline_prediction)[0]))
            trees += [p[0].nodes for p in m._predictors]
        t, width = len(trees), max(len(n) for n in trees)
        self.feat = np.zeros((t, width), dtype=np.intp)
        self.thr = np.zeros((t, width))
        self.miss = np.zeros((t, width), dtype=bool)
        self.left = np.zeros((t, width), dtype=np.intp)
        self.right = np.zeros((t, width), dtype=np.intp)
        self.value = np.zeros((t, width))
        for i, n in enumerate(trees):
            k = len(n)
            leaf = n["is_leaf"].astype(bool)
            own = np.arange(k)
            self.feat[i, :k], self.thr[i, :k], self.miss[i, :k] = n["feature_idx"], n["num_threshold"], n["missing_go_to_left"].astype(bool)
            self.left[i, :k] = np.where(leaf, own, n["left"])  # a leaf points at itself: the walk can run a fixed number of levels
            self.right[i, :k] = np.where(leaf, own, n["right"])
            self.value[i, :k] = n["value"]
        self.depth = max(int(n["depth"].max()) for n in trees)
        self.base = np.asarray(base)
        self._rows = np.arange(t)

    @classmethod
    def try_build(cls, models: list) -> _StackedForest | None:
        try:
            for m in models:
                if type(m).__name__ != "HistGradientBoostingRegressor" or type(m._loss.link).__name__ != "IdentityLink"                         or m.n_trees_per_iteration_ != 1 or any(p[0].nodes["is_categorical"].any() for p in m._predictors):
                    return None
            return cls(models)
        except (AttributeError, KeyError, ValueError, IndexError):
            return None

    def predict(self, x: np.ndarray) -> np.ndarray:
        """One value per model for the row ``x`` (``x`` as the models were fitted: the same columns)."""
        idx = np.zeros(len(self._rows), dtype=np.intp)
        for _ in range(self.depth):
            xv = x[self.feat[self._rows, idx]]
            go_left = np.where(np.isnan(xv), self.miss[self._rows, idx], xv <= self.thr[self._rows, idx])
            idx = np.where(go_left, self.left[self._rows, idx], self.right[self._rows, idx])
        return np.add.reduceat(self.value[self._rows, idx], self.offsets) + self.base


@dataclass
class CrewBaselineModel:
    """A fitted model (plain numpy and sklearn objects, picklable)."""

    npc_ids: list[str]
    columns: list[str]  # the crew feature names it expects, in order (``CrewFeatureExtractor.names``)
    regressors: dict[str, dict[str, Any]]  # npc -> quantity -> object with ``predict(context matrix)``
    sigma: dict[str, np.ndarray]  # npc -> (quantities, classes): robust scale of the residual
    precision: dict[str, np.ndarray]  # npc -> (quantities, quantities)
    limit_d: float = 1.0
    limit_z: np.ndarray = field(default_factory=lambda: np.ones(len(QUANTITIES)))
    fast_factor: float = 2.0
    tau_s: float = TAU_S
    kind: Literal["regressor", "table"] = "regressor"
    info: dict = field(default_factory=dict)  # how it was trained (split, margins, metrics, versions): the model card
    limit_fast: np.ndarray = field(default_factory=lambda: np.ones(len(FAST_QUANTITIES)))  # limits of the fast statistic
    scale_models: dict[str, dict[str, Any]] = field(default_factory=dict)  # npc -> quantity -> regressor of the size of the residual

    def _idx(self) -> tuple[list[int], list[int], list[int]]:
        pos = {c: i for i, c in enumerate(self.columns)}
        return [pos[c] for c in CTX_COLUMNS], [pos[q] for q in QUANTITIES], [pos[f"ctx|{a}"] for a in ACT_NAMES]

    @staticmethod
    def memory_step(prev: np.ndarray | None, met10: float, every_s: float = EVERY_S) -> np.ndarray:
        """The memory of the programme after one more row: exponential means of ``met10`` (the first row starts them at its value).
        The online detector calls this once per evaluation; ``memory`` below calls it down a column."""
        met = met10 if math.isfinite(met10) else 1.0
        if prev is None:
            return np.full(len(MEMORY_TAU_MIN), met)
        a = 1.0 - np.exp(-every_s / (np.asarray(MEMORY_TAU_MIN) * 60.0))
        return prev + a * (met - prev)

    def memory(self, X: np.ndarray, every_s: float = EVERY_S) -> np.ndarray:
        """(rows, 3): the memory down the rows of ONE person, consecutive and ``every_s`` apart (what the detector does online)."""
        mets = np.asarray(X[:, self._idx()[0][0]], dtype=float)
        mets = np.where(np.isfinite(mets), mets, 1.0)
        a = 1.0 - np.exp(-every_s / (np.asarray(MEMORY_TAU_MIN) * 60.0))  # the same arithmetic as ``memory_step``, column by column
        out = np.empty((len(X), len(MEMORY_TAU_MIN)))
        for k in range(len(MEMORY_TAU_MIN)):
            ak, state = float(a[k]), 0.0
            col = out[:, k]
            for i, met in enumerate(mets.tolist()):
                state = met if i == 0 else state + ak * (met - state)
                col[i] = state
        return out

    @staticmethod
    def _mask(z: np.ndarray) -> np.ndarray:
        """The part of each z that counts in its clinical direction (>= 0)."""
        d = np.asarray([DIRECTION[q] for q in QUANTITIES], dtype=float)
        return np.where(d == 0, np.abs(z), np.maximum(d * z, 0.0))

    def _stack(self, npc: str) -> _StackedForest | None:
        cache = self.__dict__.setdefault("_stacked", {})
        if npc not in cache:
            models = [self.regressors[npc][q] for q in QUANTITIES] + [self.scale_models[npc][q] for q in QUANTITIES if self.scale_models.get(npc)]
            cache[npc] = _StackedForest.try_build(models)
        return cache[npc]

    def context(self, X: np.ndarray, mem: np.ndarray | None = None) -> np.ndarray:
        """The input of the regressors: the context columns of ``X`` and the memory of the programme (``mem``: one row per row of ``X``;
        by default computed down the rows of ``X``, which must then be one person's consecutive rows)."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        return np.hstack([X[:, self._idx()[0]], self.memory(X) if mem is None else np.atleast_2d(mem)])

    def z_batch(self, npc: str, X: np.ndarray, mem: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(z, expected), both (rows, quantities): ``X`` has one row of crew features per row, in ``columns`` order. A feature that
        could not be computed (no samples) is taken as normal (z = 0). ``z`` is not clipped (see ``stats``)."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        _, q_i, act_i = self._idx()
        ctx = self.context(X, mem)
        act = X[:, act_i]
        cls = np.where(act.sum(axis=1) > 0, act.argmax(axis=1), _NOMINAL)
        sig = self.sigma[npc][np.arange(len(QUANTITIES))[None, :], cls[:, None]]
        stack = self._stack(npc) if len(X) == 1 else None
        if stack is not None:  # the live detector: one row, the 14 forests of the person at once
            out = stack.predict(ctx[0])
            expected = out[None, :len(QUANTITIES)]
            if self.scale_models.get(npc):
                sig = np.maximum(sig, 1.4826 * np.maximum(out[None, len(QUANTITIES):], 0.0))
        else:
            expected = np.column_stack([self.regressors[npc][q].predict(ctx) for q in QUANTITIES])
            if self.scale_models.get(npc):  # in transition the residual is larger than in a steady state: the context says so
                sig = np.maximum(sig, 1.4826 * np.column_stack([np.maximum(self.scale_models[npc][q].predict(ctx), 0.0) for q in QUANTITIES]))
        z = (X[:, q_i] - expected) / sig
        return np.where(np.isfinite(z), z, 0.0), expected  # NOT clipped: ``stats`` clips for D2 and the slow statistic, the fast one reads it whole

    def z_cached(self, npc: str, row: np.ndarray, mem: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``z_batch`` of one row, remembering the last call per person: the slow and the fast detector evaluate the same row of the same
        person at the same moment and share the 14 predictions (the dominant cost of the stage)."""
        key = row.tobytes() + mem.tobytes()
        cache = self.__dict__.setdefault("_zcache", {})
        hit = cache.get(npc)
        if hit is not None and hit[0] == key:
            return hit[1]
        out = self.z_batch(npc, row, mem)
        cache[npc] = (key, out)
        return out

    def stats(self, npc: str, z: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(stat, D2, directional z) for the z of ``z_batch``; ``stat`` is the instantaneous slow statistic (not smoothed). The z is
        clipped to +-``Z_CLIP`` here: one quantity cannot add more than that to the slow statistic."""
        zm = self._mask(np.clip(z, -Z_CLIP, Z_CLIP))
        d2 = np.einsum("ij,jk,ik->i", zm, self.precision[npc], zm)
        stat = np.maximum(d2 / self.limit_d, (zm / self.limit_z).max(axis=1))
        return stat, d2, zm

    def fast_stat(self, z: np.ndarray) -> np.ndarray:
        """The fast statistic: the largest directional z of the heart rate quantities over ``fast_factor`` times its limit. It reads the
        UNCLIPPED z: the first minutes of a change of activity reach ~10 sigmas for a few minutes, an arrhythmia tens of them."""
        zm = self._mask(z)
        ix = [QUANTITIES.index(q) for q in FAST_QUANTITIES]
        return (zm[:, ix] / (self.fast_factor * self.limit_fast)).max(axis=1)

    def score(self, npc: str, row: np.ndarray, mem: np.ndarray | None = None) -> tuple[float, np.ndarray, str]:
        """(stat, z, explanation) of one row of crew features (``mem``: the memory of that person's programme; by default the row alone)."""
        z, expected = self.z_batch(npc, row, mem)
        stat, _, _ = self.stats(npc, z)
        return float(stat[0]), z[0], self.explain(npc, np.asarray(row, dtype=float), z[0], expected[0])[0]

    def explain(self, npc: str, row: np.ndarray, z: np.ndarray, expected: np.ndarray,
                top: int = 3) -> tuple[str, tuple[str, ...]]:
        """(the evidence in one sentence, the ``top`` phrases): "FC 105 bpm, attesi 68 a riposo (z 6,1)"."""
        ctx_i, q_i, _ = self._idx()
        met = float(row[ctx_i[0]]) if math.isfinite(row[ctx_i[0]]) else 0.0
        where = "a riposo" if met < 2.0 else f"a {_it(met, 1)} MET"
        z = np.clip(z, -Z_CLIP, Z_CLIP)
        zm = self._mask(z[None, :])[0]
        order = [i for i in np.argsort(zm)[::-1][:top] if zm[i] > 0]
        phrases = []
        for i in order:
            q = QUANTITIES[i]
            label, unit = _WORDS[q]
            dec = _DECIMALS[q]
            phrases.append(f"{label} {_it(float(row[q_i[i]]), dec)} {unit}, attesi {_it(float(expected[i]), dec)} {where} "
                           f"(z {_it(float(z[i]), 1)})")
        return "; ".join(phrases), tuple(phrases)


def ema(series: np.ndarray, every_s: float, tau_s: float = TAU_S) -> np.ndarray:
    """Exponential mean of a series sampled every ``every_s`` seconds, starting at its first value: the SAME recursion the detector
    runs online, so the offline evaluation reproduces it."""
    a = 1.0 - math.exp(-every_s / tau_s)
    out = np.empty(len(series))
    acc = 0.0
    for i, x in enumerate(series):
        acc = float(x) if i == 0 else acc + a * (float(x) - acc)
        out[i] = acc
    return out


_LOADED: dict[Path, CrewBaselineModel] = {}  # one copy per file: the slow and the fast detector (and a rebuilt engine) share it


def load_model(path: str | Path) -> CrewBaselineModel:
    import joblib

    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = _ROOT / p
    key = p.resolve()
    stamp = (key.stat().st_mtime_ns, key.stat().st_size)
    cached = _LOADED.get(key)
    if cached is None or cached.__dict__.get("_stamp") != stamp:  # a file trained again is read again
        cached = joblib.load(p)
        cached.__dict__["_stamp"] = stamp
        _LOADED[key] = cached
    return cached


class _CrewBaselineParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str  # path of a ``CrewBaselineModel`` joblib file (``tools/ml/train_crew.py``)
    mode: Literal["slow", "fast"] = "slow"
    eval_every_s: float = Field(default=60.0, gt=0)


class CrewBaselineDetector(BaseDetector):
    """Stage A of the crew. Reads the SENSED wearable observations and, from the tick, only ``NPCState.met`` / ``activity`` (the
    programme of the day, as ``EarlyWarningScore`` does), never ``vitals``. One ``Signal(emergency="medical", cause="crew_baseline")``
    per flagged crew member, with the member as ``subject``; the classifier debounces it (``confirm_s`` 600 for ``slow``, 120 for
    ``fast``). ``metric`` and ``targets`` of the spec are not used: the model knows its crew."""

    Params = _CrewBaselineParams

    def reset(self) -> None:
        self.model = load_model(self.params.model)
        try:  # a prediction of ONE row gains nothing from threads and their start-up costs more than the prediction
            from threadpoolctl import threadpool_limits

            threadpool_limits(limits=1)
        except ImportError:
            pass
        self._fx: CrewFeatureExtractor | None = None
        self._ignore: set[str] = set()  # the sensors that are not a wearable of a crew member
        self._bucket = -1
        self._ema: dict[str, float] = {}
        self._mem: dict[str, np.ndarray] = {}  # the memory of the programme of each person (``CrewBaselineModel.memory_step``)
        self._latched: dict[str, Signal] = {}
        self.last_score = 0.0

    def forget(self, entity_id: str) -> None:
        self._ema.pop(entity_id, None)
        self._latched.pop(entity_id, None)

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        tick = ctx.tick
        if self._fx is None:
            self._fx = CrewFeatureExtractor(list(tick.npcs), {})
            assert self._fx.names == self.model.columns, "the model and the extractor disagree"
        row, ignore, mine = self._fx._row, self._ignore, []
        for o in observations:  # ~1000 a tick: a sensor is classified once, afterwards one set lookup; the wearables are the sensors of a crew member
            sid = o.sensor_id
            if sid in ignore:
                continue
            if sid not in row:
                if o.metric in VITALS and o.entity_id in tick.npcs:
                    self._fx.register(sid, o.entity_id, o.metric)
                else:
                    ignore.add(sid)
                    continue
            mine.append(o)
        self._fx.push(tick, mine)
        t = tick.t_sim_s
        bucket = int(t // self.params.eval_every_s)
        if bucket != self._bucket and self._fx.ready(t):
            self._bucket = bucket
            self._evaluate(ctx, self._fx.compute(t))
        return list(self._latched.values())

    def _evaluate(self, ctx: StepContext, rows: dict[str, np.ndarray]) -> None:
        m, fast = self.model, self.params.mode == "fast"
        a = 1.0 - math.exp(-self.params.eval_every_s / m.tau_s)
        self._latched = {}
        best = 0.0
        for npc, row in rows.items():
            if npc not in m.regressors or npc not in ctx.tick.npcs:
                continue
            row = row.astype(np.float32).astype(np.float64)  # the precision the dataset stores (``crew.parquet``): online = offline, bit for bit
            self._mem[npc] = m.memory_step(self._mem.get(npc), float(row[m._idx()[0][0]]), self.params.eval_every_s)
            z, expected = m.z_cached(npc, row, self._mem[npc])
            stat, _, _ = m.stats(npc, z)
            if fast:
                score = float(m.fast_stat(z)[0])
            else:
                prev = self._ema.get(npc)
                score = float(stat[0]) if prev is None else prev + a * (float(stat[0]) - prev)
                self._ema[npc] = score
            best = max(best, score)
            if score >= 1.0:
                text, phrases = m.explain(npc, row, z[0], expected[0])
                self._latched[npc] = Signal(
                    detector_id=self.id, emergency="medical", module_id=ctx.tick.npcs[npc].module_id, severity="warning",
                    subject=npc, value=score, cause="crew_baseline", evidence=phrases,
                    detail=f"{npc}: {text} (score {score:.1f})")
        self.last_score = best
