"""Fault injection: which faults are active, their effect on sensor readings, and ground-truth labels.

Sensor faults corrupt the *reading* only (``value``); ``value_true`` is never touched. Physical,
actuator and medical faults are applied by the engine / passed to plugins (see schemas/faults.py).
"""

from __future__ import annotations

import math

import numpy as np

from ares3.core.rng import derive
from ares3.schemas.faults import FaultSpec


class FaultInjector:
    def __init__(self, faults: list[FaultSpec], seed: int) -> None:
        self.faults = list(faults)  # a copy: runtime injection must not edit the scenario
        self._seed = seed
        self._rng = {f.id: derive(seed, "fault", f.id) for f in faults}
        self._stuck: dict[tuple[str, str], float] = {}  # (fault id, sensor id) -> frozen value

    def add(self, fault: FaultSpec) -> None:
        if any(f.id == fault.id for f in self.faults):
            raise ValueError(f"fault id already in use: {fault.id}")
        self.faults.append(fault)
        self._rng[fault.id] = derive(self._seed, "fault", fault.id)

    def stop(self, fault_id: str, t_s: float) -> None:
        """End a fault at ``t_s`` (it stays in the list, so past rows keep their label)."""
        for i, f in enumerate(self.faults):
            if f.id == fault_id:
                if t_s <= f.start_s:
                    del self.faults[i]  # never became active
                elif f.active_at(t_s):
                    self.faults[i] = f.model_copy(update={"duration_s": t_s - f.start_s})
                return
        raise KeyError(fault_id)

    def active(self, t_s: float) -> list[FaultSpec]:
        return [f for f in self.faults if f.active_at(t_s)]

    @staticmethod
    def by_target(active: list[FaultSpec]) -> dict[str, tuple[FaultSpec, ...]]:
        out: dict[str, list[FaultSpec]] = {}
        for f in active:
            for tgt in f.targets:
                out.setdefault(tgt, []).append(f)
        return {k: tuple(v) for k, v in out.items()}

    def corrupt(self, sensor_id: str, value: float, active_on_sensor: tuple[FaultSpec, ...], t_s: float,
                entity_id: str = "", sigma: float = 0.0) -> float | None:
        """Apply the sensor faults active on ``sensor_id``. Returns ``None`` for a dropped sample."""
        for f in active_on_sensor:
            if f.category != "sensor":
                continue
            rng: np.random.Generator = self._rng[f.id]
            if f.type == "dropout":
                only = f.params.get("entities")  # e.g. the MCA sample line to some modules only
                if (only is None or entity_id in only) and rng.random() < float(f.params.get("probability", 1.0)):
                    return None
            elif f.type == "bias":
                tau = f.params.get("decay_tau_s")  # an offset that recovers (condensation on a humidity sensor)
                decay = 1.0 if not tau else math.exp(-(t_s - f.start_s) / float(tau))
                value += float(f.params.get("offset", 0.0)) * decay
            elif f.type == "drift":
                value += float(f.params.get("rate_per_s", 0.0)) * (t_s - f.start_s)
                value *= 1.0 + float(f.params.get("rel_rate_per_s", 0.0)) * (t_s - f.start_s)
            elif f.type == "stuck":
                value = self._stuck.setdefault((f.id, sensor_id), value)
            elif f.type == "noise":
                std = float(f.params["std"]) if "std" in f.params else (float(f.params.get("factor", 1.0)) - 1.0) * sigma
                value += float(rng.normal(0.0, std))
        return value


def label_row(entities: set[str], active: list[FaultSpec]) -> tuple[bool, str, str]:
    """(is_anomaly, anomaly_type, anomaly_ids) for a row touching ``entities``.

    A fault labels the row when any of its targets is among the entities (the sensor, the thing it
    measures, or the module that thing is in). With several faults the highest priority wins, ties
    broken by id; all of them are listed in ``anomaly_ids``.
    """
    hits = sorted((f for f in active if entities.intersection(f.targets)), key=lambda f: (-f.priority, f.id))
    if not hits:
        return False, "nominal", ""
    return True, hits[0].label, "|".join(f.id for f in hits)
