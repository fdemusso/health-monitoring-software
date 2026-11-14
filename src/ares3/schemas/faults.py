"""Fault / emergency injection, declarative.

Categories (``FaultSpec.category``):

* sensor    - corrupts a sensor's *reading*: ``bias``, ``drift``, ``stuck``, ``dropout``, ``noise``
* physical  - changes the module state: ``leak``, ``co2_source``, ``heat_source``
* actuator  - ``actuator_offline`` disables an actuator
* medical   - ``medical`` is passed to the physiology model of the targeted NPC through
              ``StepContext.faults_for(npc_id)``; its ``params`` are model specific
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FaultType = Literal[
    "bias", "drift", "stuck", "dropout", "noise",
    "leak", "co2_source", "heat_source",
    "actuator_offline",
    "medical",
]

_CATEGORY = {
    "bias": "sensor", "drift": "sensor", "stuck": "sensor", "dropout": "sensor", "noise": "sensor",
    "leak": "physical", "co2_source": "physical", "heat_source": "physical",
    "actuator_offline": "actuator",
    "medical": "medical",
}


class FaultSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: FaultType
    targets: list[str] = Field(min_length=1)  # ids of sensors / modules / actuators / NPCs
    start_s: float = Field(ge=0)  # simulation seconds
    duration_s: float | None = Field(default=None, gt=0)  # None = until the end
    params: dict[str, Any] = {}
    anomaly_type: str | None = None  # label written to the dataset; defaults to ``type``
    priority: int = 0  # highest priority wins when several faults label the same row

    @property
    def category(self) -> str:
        return _CATEGORY[self.type]

    @property
    def label(self) -> str:
        return self.anomaly_type or self.type

    def active_at(self, t_s: float) -> bool:
        if t_s < self.start_s:
            return False
        return self.duration_s is None or t_s < self.start_s + self.duration_s


class FaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    faults: list[FaultSpec] = []
