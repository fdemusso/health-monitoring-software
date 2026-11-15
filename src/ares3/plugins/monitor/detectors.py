"""PLACEHOLDER - awaiting the team. Reference detectors for the monitor (YAML: ``monitor.detectors``).

A detector reads the SENSED observations of ``metric`` on its ``targets`` (module ids) and returns a
:class:`Signal` while the evidence holds. It does not debounce or open emergencies: the classifier does.
Modules with no sensor for the metric are simply not covered. Add your own by subclassing ``BaseDetector``.
"""

from __future__ import annotations

import math
from collections import deque

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ares3.core.constants import MMHG_PER_KPA
from ares3.sdk import BaseDetector, Observation, Signal, StepContext

_MIN_SPAN = 0.5  # a trend needs samples covering at least this fraction of the window
_REBASE = 20_000  # pushes between exact recomputations of the running sums (keeps float error bounded)


class _Window:
    """Sensed samples of one module over the last ``window_s`` seconds. Mean and slope come from running sums
    (O(1) per sample), so a window of hours costs the same as one of seconds."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self.items: deque[tuple[float, float]] = deque()
        self._pushes = 0
        self._rebase()

    def _rebase(self) -> None:
        """Recompute the sums exactly, relative to the oldest sample (small numbers, no cancellation)."""
        self._t0, self._v0 = self.items[0] if self.items else (0.0, 0.0)
        self._st = self._sv = self._stt = self._stv = 0.0
        for t, v in self.items:
            self._add(t - self._t0, v - self._v0, 1.0)
        self._pushes = 0

    def _add(self, x: float, y: float, sign: float) -> None:
        self._st += sign * x
        self._sv += sign * y
        self._stt += sign * x * x
        self._stv += sign * x * y

    def push(self, t: float, v: float) -> None:
        if not self.items:
            self._t0, self._v0 = t, v
            self._st = self._sv = self._stt = self._stv = 0.0
        self.items.append((t, v))
        self._add(t - self._t0, v - self._v0, 1.0)
        while self.items and self.items[0][0] < t - self.window_s:
            old_t, old_v = self.items.popleft()
            self._add(old_t - self._t0, old_v - self._v0, -1.0)
        self._pushes += 1
        if self._pushes >= _REBASE:
            self._rebase()

    def mean(self) -> float:
        return self._v0 + self._sv / len(self.items)

    def slope(self) -> float | None:
        """Least-squares slope (unit/s); ``None`` until the window is mostly filled."""
        n = len(self.items)
        if n < 3 or self.items[-1][0] - self.items[0][0] < _MIN_SPAN * self.window_s:
            return None
        den = self._stt - self._st * self._st / n
        return (self._stv - self._st * self._sv / n) / den if den > 0.0 else None

    def full(self) -> bool:
        return self.items[-1][0] - self.items[0][0] >= _MIN_SPAN * self.window_s


class _Windowed(BaseDetector):
    window_s: float

    def reset(self) -> None:
        self._win = {m: _Window(self.window_s) for m in self.targets}

    def forget(self, entity_id: str) -> None:
        if entity_id in self._win:
            self._win[entity_id] = _Window(self.window_s)

    def _feed(self, observations: list[Observation]) -> list[str]:
        """Push this tick's samples; return the modules that got one."""
        touched = []
        for o in observations:
            if o.metric == self.metric and o.entity_id in self._win:
                self._win[o.entity_id].push(o.t_s, o.value)
                touched.append(o.entity_id)
        return touched


class _ThresholdParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    window_s: float = Field(default=0.0, ge=0)  # 0 = the instantaneous reading; >0 = its mean over the window

    @model_validator(mode="after")
    def _has_limit(self):
        if self.min is None and self.max is None:
            raise ValueError("Threshold needs min and/or max")
        return self


class Threshold(_Windowed):
    """Fires while the (mean over ``window_s`` of the) sensed value is outside ``[min, max]``. With a window it
    only judges once the window is mostly filled, like the profile alarms it mirrors."""

    Params = _ThresholdParams

    def reset(self) -> None:
        self.window_s = max(self.params.window_s, 1e-9)
        super().reset()

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        out = []
        for mid in self._feed(observations):
            win = self._win[mid]
            if self.params.window_s > 0 and not win.full():
                continue
            v = win.mean() if self.params.window_s > 0 else win.items[-1][1]
            lo, hi = self.params.min, self.params.max
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                out.append(Signal(detector_id=self.id, emergency="equipment", module_id=mid, severity="warning",
                                  value=v, detail=f"{self.metric} {v:.2f} outside [{lo}, {hi}]"))
        return out


class NpcThreshold(Threshold):
    """``Threshold`` on a wearable metric of the crew (``targets``: crew ids). The signal is about the crew member
    (``subject``) and carries the module they are in, which the monitor knows from crew tracking."""

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        out = []
        for s in super().detect(ctx, observations):
            npc = ctx.tick.npcs.get(s.module_id)  # the base class puts the measured entity id in module_id
            if npc is not None:
                out.append(s.model_copy(update={"subject": s.module_id, "module_id": npc.module_id,
                                                "emergency": "medical"}))
        return out


class _DropParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_s: float = Field(default=300.0, gt=0)
    min_drop_mmhg_min: float = Field(gt=0)  # fires when the pressure falls faster than this
    p_minimum_mmhg: float = Field(default=490.0, gt=0)  # ISS Pminimum, the pressure TRes counts down to


class PressureDrop(_Windowed):
    """Pressure falling faster than ``min_drop_mmhg_min`` (least-squares slope over ``window_s``): a leak.

    The ISS grades a loss of cabin air by its rate [ICES-2025-126]: rapid depressurization >= 0.87 mmHg/min, fast leak
    0.4-0.87, slow leak < 0.4 (smallest rate detectable on board: 2 mmHg/day). The window sets how small a rate can be
    told from the sensor noise: use one detector per time scale (see ``monitor_placeholder.yaml``).

    Reports TRes, the reserve time to ``p_minimum_mmhg``: ``TRes = P * ln(P / Pmin) / |dP/dt|``, the ISS formula
    [ICES-2025-126], exact for a leak proportional to the pressure (the orifice flow the engine models)."""

    Params = _DropParams

    def reset(self) -> None:
        self.window_s = self.params.window_s
        super().reset()

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        out = []
        for mid in self._feed(observations):
            win = self._win[mid]
            slope = win.slope()
            if slope is None:
                continue
            rate = -slope * MMHG_PER_KPA * 60.0  # mmHg/min, positive while falling
            if rate < self.params.min_drop_mmhg_min:
                continue
            p = win.items[-1][1] * MMHG_PER_KPA
            floor = self.params.p_minimum_mmhg
            tres = 60.0 * p * math.log(p / floor) / rate if p > floor else 0.0
            out.append(Signal(detector_id=self.id, emergency="depressurization", module_id=mid, severity="critical",
                              value=slope, tres_s=tres, detail=f"P falling {rate:.2f} mmHg/min, TRes {tres:.0f} s"))
        return out
