"""Base classes for the things Mario (sensors, actuators) and Luca (physiology) implement.

A component is a small class with a validated ``Params`` model (filled from YAML) and one ``step``
method. It receives a read-only :class:`StepContext`, returns a value or effects, and never mutates
the world; the core applies the effects in the right phase of the tick.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict

from .context import StepContext
from .types import Command, ModuleFlow, ModuleState, NPCState, Observation, VitalsUpdate


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Component(ABC):
    """Common shape: ``Params`` (pydantic, validates the YAML ``params:`` block), an id and a private RNG."""

    Params: ClassVar[type[BaseModel]] = EmptyParams

    def __init__(self, id: str, params: BaseModel, rng: np.random.Generator) -> None:
        self.id = id
        self.params = params
        self.rng = rng  # derived from the scenario seed and ``id``: deterministic and independent

    @classmethod
    def from_config(cls, id: str, raw_params: dict[str, Any], rng: np.random.Generator, **spec: Any):
        return cls(id=id, params=cls.Params.model_validate(raw_params), rng=rng, **spec)

    def reset(self) -> None:
        """Called once before the first tick; clear filters/state here."""


class BaseSensor(Component):
    """Measures one metric of a module (``module:<id>``) or an NPC (``npc:<id>``).

    ``step`` is called every tick so that lag filters run at the simulation rate; the engine decides
    which samples are logged according to ``rate_hz``. Return ``None`` for "no sample".
    Do not model faults here: the engine applies sensor faults (bias, drift, stuck, dropout, noise)
    on top of what you return.
    """

    def __init__(self, id: str, params: BaseModel, rng: np.random.Generator, *, target: str, metric: str,
                 rate_hz: float = 1.0) -> None:
        super().__init__(id, params, rng)
        self.target = target
        self.metric = metric
        self.rate_hz = rate_hz

    @property
    def entity_id(self) -> str:
        return self.target.partition(":")[2]

    @abstractmethod
    def step(self, dt: float, ctx: StepContext) -> Observation | None: ...


class BaseActuator(Component):
    """Acts on one module. Returns rates; the core integrates them. ``command`` is the agent's command
    for this actuator issued on the previous tick (``None`` if none)."""

    def __init__(self, id: str, params: BaseModel, rng: np.random.Generator, *, module: str) -> None:
        super().__init__(id, params, rng)
        self.module = module

    @abstractmethod
    def step(self, dt: float, ctx: StepContext, command: Command | None) -> list[ModuleFlow]: ...


class PhysiologyModel(Component):
    """Maps (NPC metabolic state, the module's environment) to the NPC's true vital signs.

    ``npc.vitals`` / ``npc.latent`` hold the previous values; return the new ones. Medical emergencies
    arrive through ``ctx.faults_for(npc.id)``.
    """

    @abstractmethod
    def step(self, dt: float, npc: NPCState, env: ModuleState, ctx: StepContext) -> VitalsUpdate: ...

    def initial_vitals(self, npc: NPCState, env: ModuleState) -> VitalsUpdate:
        """Resting state at t=0. Default: step once with dt=0 is not assumed; override to seed ``latent``."""
        return VitalsUpdate(vitals={}, latent={})


class BaseAgent(Component):
    """Autonomous first responder: PASSIVE_MONITORING -> ALERT -> REACTION. Sees the sensed
    observations of this tick (never the truth) and returns commands applied on the next tick."""

    @abstractmethod
    def decide(self, ctx: StepContext, observations: list[Observation]) -> list[Command]: ...
