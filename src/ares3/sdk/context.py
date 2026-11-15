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

    def capacity_factor(self, actuator_id: str, component: str = "main") -> float:
        """Product of the active ``actuator_degrade`` faults on ``actuator_id`` for one ``component`` (the fault's
        ``params.component``, default ``main``; a CCAA has a ``fan`` and a ``chx``): 1.0 healthy, ``fraction`` once a
        degradation has fully set in; it ramps linearly over ``ramp_s`` from the fault's start."""
        k = 1.0
        for f in self._faults.get(actuator_id, ()):
            if f.type != "actuator_degrade" or f.params.get("component", "main") != component:
                continue
            ramp = float(f.params.get("ramp_s", 0.0))
            x = 1.0 if ramp <= 0 else min(1.0, max(0.0, (self.tick.t_sim_s - f.start_s) / ramp))
            k *= 1.0 + (float(f.params.get("fraction", 0.0)) - 1.0) * x
        return k
