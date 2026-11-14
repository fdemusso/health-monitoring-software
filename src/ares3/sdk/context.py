"""Read-only view handed to every plugin at each ``step``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ares3.schemas.environment import EnvironmentProfile
from ares3.schemas.faults import FaultSpec

from .types import Observation, SimulationTick


@dataclass(frozen=True)
class StepContext:
    tick: SimulationTick
    env: EnvironmentProfile
    _faults: Mapping[str, tuple[FaultSpec, ...]] = field(default_factory=dict)
    _readings: Mapping[str, Observation] = field(default_factory=dict)

    def faults_for(self, entity_id: str) -> tuple[FaultSpec, ...]:
        """Faults currently active on a module / NPC / sensor / actuator id."""
        return self._faults.get(entity_id, ())

    def reading(self, sensor_id: str) -> float | None:
        """Latest SENSED value of a sensor (None before its first sample). Controllers must use this,
        never the true state, so sensor faults propagate into the control loop."""
        obs = self._readings.get(sensor_id)
        return None if obs is None else obs.value
