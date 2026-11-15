"""Stage B of the ML monitor: WHICH fault, WHERE, how sure, and WHY. Supervised, trained on the labelled catalog
(``tools/ml/train_diagnoser.py``); stage A (``anomaly.py``) only says "something is abnormal".

One gradient-boosting classifier per FAMILY of faults (physical / actuator / sensor / medical), each with its own ``nominal`` class:
two faults of different families at the same time are both recognised (a drifting sensor on a degrading scrubber); two of the same
family give only the stronger one. The input is the same feature vector as stage A (``features.py``: the sensed values only).

The explanation is part of the decision: for the predicted class the model keeps its SIGNATURE (the mean standardised feature vector of
that class's rows); the features that are both far from nominal NOW and part of the signature are the evidence, in words
(``features.describe``), and the sensor of the strongest one gives the module (or the crew member, or the sensor) the fault is in.

SECURITY: ``joblib`` runs code when it loads a file. Load only the models this project produced (``models/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ares3.sdk import BaseDetector, Observation, Signal, StepContext

from .features import FeatureExtractor, describe


@dataclass
class DiagnoserModel:
    keys: list[str]  # every sensor of the station
    columns: list[str]  # feature names, in order (``FeatureExtractor(keys, clock).names``)
    clock_periods_s: tuple[float, ...]
    mean: np.ndarray  # of the nominal rows
    scale: np.ndarray
    families: dict[str, Any]  # family -> fitted classifier (``classes_`` includes ``nominal``)
    signatures: dict[str, np.ndarray]  # label -> mean z-score of its rows
    sensor_info: dict[str, tuple[str, str]]  # sensor id -> (kind: module | actuator | npc | other, module or crew id)
    phrases: dict[str, str] = field(default_factory=dict)  # label -> sentence for the crew
    info: dict = field(default_factory=dict)  # training: seeds, rows, metrics, versions (the model card)
    live: dict[str, bool] = field(default_factory=dict)  # label -> False: trained but too few examples, the live monitor ignores it
    min_proba: dict[str, float] = field(default_factory=dict)  # label -> its own threshold (tuned on validation); else the detector's

    def is_live(self, label: str) -> bool:
        return getattr(self, "live", {}).get(label, True)  # a model saved before the field existed has every class live

    def threshold(self, label: str, default: float) -> float:
        return getattr(self, "min_proba", {}).get(label, default)

    def decide(self, family: str, proba: np.ndarray, default: float = 0.6) -> tuple[np.ndarray, np.ndarray]:
        """The rule of the live detector on a MATRIX of probabilities (rows x ``classes_`` of the family): per row the most likely live,
        non-nominal class and its probability; the label is ``nominal`` where that probability is under the class's threshold."""
        cl = self.families[family].classes_
        usable = np.asarray([c != "nominal" and self.is_live(c) for c in cl])
        masked = np.where(usable[None, :], proba, -1.0)
        best = masked.argmax(axis=1)
        p = masked[np.arange(len(masked)), best]
        thr = np.asarray([self.threshold(c, default) for c in cl])[best]
        label = np.where((p >= thr) & usable[best], cl[best], "nominal")
        return label, np.maximum(p, 0.0)

    def z(self, x: np.ndarray) -> np.ndarray:
        z = (np.asarray(x, dtype=float) - self.mean) / self.scale
        return np.where(np.isfinite(z), z, 0.0)

    def predict(self, x: np.ndarray) -> dict[str, tuple[str, float]]:
        """family -> (most likely non-nominal class, its probability); the probability is of THAT class, so a family where
        ``nominal`` wins with 0.9 gives a class at 0.1 and stays quiet."""
        out = {}
        row = np.asarray(x, dtype=float).reshape(1, -1)
        for fam, clf in self.families.items():
            proba = clf.predict_proba(row)[0]
            ranked = [(c, float(p)) for c, p in zip(clf.classes_, proba, strict=True) if c != "nominal" and self.is_live(c)]
            out[fam] = max(ranked, key=lambda cp: cp[1]) if ranked else ("nominal", 0.0)
        return out

    def explain(self, x: np.ndarray, label: str, top: int = 3) -> tuple[list[str], str | None]:
        """(phrases of the ``top`` features that are far from nominal and in the signature of ``label``, sensor of the strongest)."""
        sig = self.signatures.get(label)
        if sig is None:
            return [], None
        z = self.z(x)
        agree = z * sig
        agree[~np.isfinite(agree)] = 0.0
        order = np.argsort(agree)[::-1][:top]
        order = [i for i in order if agree[i] > 0]
        phrases = [f"{describe(self.columns[i])} ({z[i]:+.1f} sigma)" for i in order]
        return phrases, (self.columns[order[0]].split("|")[0] if order else None)


class _DiagnosisParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str  # path of a ``DiagnoserModel`` joblib file (``tools/ml/train_diagnoser.py``)
    eval_every_s: float = Field(default=60.0, gt=0)
    min_proba: float = Field(default=0.6, gt=0, le=1)  # plan D7: below this the family stays quiet


class DiagnosisDetector(BaseDetector):
    """Stage B. Every ``eval_every_s`` each family gives its most likely fault; above ``min_proba`` it becomes a ``Signal`` whose
    ``cause`` is the label of the catalog (the ``diagnosis`` table of the monitor config says what emergency it opens). The module
    comes from the strongest feature of the explanation, ``subject`` is the sensor (sensor faults) or the crew member (medical)."""

    Params = _DiagnosisParams

    def reset(self) -> None:
        import joblib

        p = Path(self.params.model)
        if not p.is_absolute() and not p.exists():
            p = Path(__file__).resolve().parents[5] / p
        self.model: DiagnoserModel = joblib.load(p)
        self._fx = FeatureExtractor(self.model.keys, self.model.clock_periods_s)
        assert self._fx.names == self.model.columns, "the model and the extractor disagree"
        self._bucket = -1
        self._latched: list[Signal] = []
        self.last_score = 0.0  # the probability of the most likely fault of any family

    def forget(self, entity_id: str) -> None:
        self._latched = []  # a repair was done there: wait for the next evaluation

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        t = ctx.tick.t_sim_s
        self._fx.push(t, [(o.sensor_id, o.value) for o in observations])
        bucket = int(t // self.params.eval_every_s)
        if bucket != self._bucket and self._fx.ready(t):
            self._bucket = bucket
            x = self._fx.compute(t)
            self._latched = []
            best = 0.0
            for fam, (label, proba) in self.model.predict(x).items():
                best = max(best, proba)
                if proba < self.model.threshold(label, self.params.min_proba):
                    continue
                phrases, sensor = self.model.explain(x, label)
                kind, where = self.model.sensor_info.get(sensor or "", ("other", ""))
                subject = module = None
                if fam == "medical" and kind == "npc" and where in ctx.tick.npcs:
                    subject, module = where, ctx.tick.npcs[where].module_id
                elif fam == "sensor" and sensor:
                    subject = sensor
                module = module or (where if where in ctx.tick.modules else "station")
                if fam == "medical" and subject is None:
                    continue  # a crew diagnosis has to name the person
                text = self.model.phrases.get(label, label)
                self._latched.append(Signal(
                    detector_id=self.id, emergency="anomaly", module_id=module, subject=subject, severity="warning",
                    value=proba, cause=label, evidence=(text, *phrases),
                    detail=f"{label} ({proba:.0%}): {text}" + (f"; {'; '.join(phrases)}" if phrases else "")))
            self.last_score = best
        return list(self._latched)
