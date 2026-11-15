"""Stage A of the ML monitor: "is something abnormal here?", learned from NOMINAL data only (no fault is needed to train it,
so it also sees faults nobody has catalogued). NASA's Inductive Monitoring System does the same on ISS telemetry [R4]: the
distance from the behaviour learned on archived nominal data.

One model per subsystem (``atmosphere_co2``, ``thermal_humidity``, ...), so the explanation is "the CO2 subsystem" and a
fault in one group does not dilute the other. A model is a PCA on standardised features (``features.py``) with the two
classic scores: Hotelling T2 (the point is far along the usual directions) and SPE / Q (it breaks the usual correlations:
two redundant sensors that stopped agreeing). Both are divided by their limit, learned on separate nominal days
(``tools/ml/train_anomaly.py``), so a score >= 1 is an anomaly. The contribution of each feature to the score says WHERE.

SECURITY: ``joblib`` runs code when it loads a file. Load only the models this project produced (``models/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ares3.sdk import BaseDetector, Observation, Signal, StepContext

from .features import FeatureExtractor, describe, select

_ROOT = Path(__file__).resolve().parents[5]  # the repository, when the model path is relative and not found from the cwd


Z_CLIP = 10.0  # sigmas: what the score takes from a single feature, at most


@dataclass
class PcaModel:
    """A fitted subsystem model (plain numpy, picklable). ``columns`` are the feature names it expects, in order."""

    group: str
    keys: list[str]  # the sensors of the subsystem
    columns: list[str]
    mean: np.ndarray
    scale: np.ndarray
    components: np.ndarray  # (k, n_features), orthonormal rows
    eigenvalues: np.ndarray  # variance along each component
    t2_limit: float = 1.0
    spe_limit: float = 1.0
    clock_periods_s: tuple[float, ...] = ()
    info: dict = field(default_factory=dict)  # how it was trained (seeds, rows, margin, version): the model card

    def standardise(self, x: np.ndarray) -> np.ndarray:
        """z-scores, limited to +-``Z_CLIP``: a feature that never moved in the training days (a hatch position, a valve) has a tiny
        scale, and one change would give a score of millions that says no more than 10 sigma does. A feature that could not be
        computed (no samples yet) is taken as normal (0)."""
        z = (np.asarray(x, dtype=float) - self.mean) / self.scale
        return np.clip(np.where(np.isfinite(z), z, 0.0), -Z_CLIP, Z_CLIP)

    def scores(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(T2, SPE) divided by their limits, for one row or a matrix of rows."""
        z = np.atleast_2d(self.standardise(x))
        t = z @ self.components.T
        t2 = (t * t / self.eigenvalues).sum(axis=1)
        resid = z - t @ self.components
        return t2 / self.t2_limit, (resid * resid).sum(axis=1) / self.spe_limit

    def score(self, x: np.ndarray) -> float:
        a, b = self.scores(x)
        return float(max(a[0], b[0]))

    def contributions(self, x: np.ndarray) -> np.ndarray:
        """Per-feature share of the anomaly: the squared residual (what breaks the correlations) plus the T2 terms of the
        feature (what is far along the usual directions), each over its limit."""
        z = self.standardise(x)
        t = z @ self.components.T
        resid = z - t @ self.components
        t2_part = (self.components.T * (t / self.eigenvalues)).sum(axis=1) * z
        return np.abs(t2_part) / self.t2_limit + resid * resid / self.spe_limit

    def explain(self, x: np.ndarray, labels: dict[str, str] | None = None, top: int = 3) -> tuple[list[str], str]:
        """(the ``top`` contributions as phrases, sensor of the largest): ["usl_ppCO2_a: slope over 6 h (+4.1 sigma)", ...]."""
        c = self.contributions(x)
        z = self.standardise(x)
        order = np.argsort(c)[::-1][:top]
        parts = [f"{describe(self.columns[i], labels)} ({z[i]:+.1f} sigma)" for i in order]
        return parts, self.columns[order[0]].split("|")[0]


def load_model(path: str | Path) -> PcaModel:
    import joblib

    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = _ROOT / p
    return joblib.load(p)


class _AnomalyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str  # path of a ``PcaModel`` joblib file (``tools/ml/train_anomaly.py``)
    eval_every_s: float = Field(default=60.0, gt=0)  # slow faults evolve over hours; the tick budget is a few ms
    min_score: float = Field(default=1.0, gt=0)  # the model's limits are already 1.0; raise it to make the detector blunter


class AnomalyDetector(BaseDetector):
    """Stage A: a ``PcaModel`` over the SENSED samples of one subsystem, evaluated every ``eval_every_s``. While the score is
    above ``min_score`` it reports ``Signal(emergency="anomaly")`` on the module with the largest contribution, with the
    top contributions as ``detail``. The classifier debounces it (``confirm_s`` of the spec) like any other detector.
    ``metric`` and ``targets`` of the spec are not used: the model knows its sensors."""

    Params = _AnomalyParams

    def reset(self) -> None:
        self.model = load_model(self.params.model)
        self._fx = FeatureExtractor(self.model.keys, self.model.clock_periods_s)
        self._cols = select(self._fx.names, self.model.keys)
        assert [self._fx.names[i] for i in self._cols] == self.model.columns, "the model and the extractor disagree"
        self._mine = frozenset(self.model.keys)
        self._entity: dict[str, str] = {}
        self._bucket = -1
        self._latched: Signal | None = None
        self.last_score = 0.0

    def forget(self, entity_id: str) -> None:
        self._latched = None  # a repair was done there: wait for the next evaluation

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        t = ctx.tick.t_sim_s
        mine = [o for o in observations if o.sensor_id in self._mine]
        for o in mine:
            self._entity[o.sensor_id] = o.entity_id
        self._fx.push(t, [(o.sensor_id, o.value) for o in mine])
        bucket = int(t // self.params.eval_every_s)
        if bucket != self._bucket and self._fx.ready(t):
            self._bucket = bucket
            x = self._fx.compute(t)[self._cols]
            self.last_score = self.model.score(x)
            self._latched = None
            if self.last_score >= self.params.min_score:
                parts, sensor = self.model.explain(x)
                entity = self._entity.get(sensor, "")  # a module; the telemetry of an actuator is about "the station"
                self._latched = Signal(detector_id=self.id, emergency="anomaly",
                                       module_id=entity if entity in ctx.tick.modules else "station",
                                       severity="warning", value=self.last_score, evidence=tuple(parts),
                                       detail=f"{self.model.group}: score {self.last_score:.1f}; {'; '.join(parts)}")
        return [self._latched] if self._latched is not None else []
