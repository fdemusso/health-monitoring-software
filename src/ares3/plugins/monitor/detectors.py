"""PLACEHOLDER - awaiting the team. Reference detectors for the monitor (YAML: ``monitor.detectors``).

A detector reads the SENSED observations of ``metric`` on its ``targets`` (module ids) and returns a
:class:`Signal` while the evidence holds. It does not debounce or open emergencies: the classifier does.
Modules with no sensor for the metric are simply not covered. Add your own by subclassing ``BaseDetector``.
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ares3.sdk import BaseDetector, Observation, Signal, StepContext

_MIN_SPAN = 0.5  # a trend needs samples covering at least this fraction of the window


class _Window:
    """Sensed samples of one module over the last ``window_s`` seconds."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self.items: deque[tuple[float, float]] = deque()

    def push(self, t: float, v: float) -> None:
        self.items.append((t, v))
        while self.items and self.items[0][0] < t - self.window_s:
            self.items.popleft()

    def mean(self) -> float:
        return sum(v for _, v in self.items) / len(self.items)

    def slope(self) -> float | None:
        """Least-squares slope (unit/s); ``None`` until the window is mostly filled."""
        n = len(self.items)
        if n < 3 or self.items[-1][0] - self.items[0][0] < _MIN_SPAN * self.window_s:
            return None
        tm = sum(t for t, _ in self.items) / n
        vm = sum(v for _, v in self.items) / n
        den = sum((t - tm) ** 2 for t, _ in self.items)
        return sum((t - tm) * (v - vm) for t, v in self.items) / den if den else None

    def full(self) -> bool:
        return self.items[-1][0] - self.items[0][0] >= _MIN_SPAN * self.window_s


class _Windowed(BaseDetector):
    window_s: float

    def reset(self) -> None:
        self._win = {m: _Window(self.window_s) for m in self.targets}

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

    window_s: float = Field(default=10.0, gt=0)
    min_drop_kpa_s: float = Field(gt=0)  # fires when the pressure falls faster than this
    tres_floor_kpa: float = Field(default=65.3, gt=0)  # 490 mmHg: the ISS minimum used for TRes


class PressureDrop(_Windowed):
    """Pressure falling faster than ``min_drop_kpa_s`` (least-squares slope over ``window_s``): a leak. Reports TRes,
    the time left at the current rate to reach ``tres_floor_kpa``. Use one detector per time scale (fast + slow)."""

    Params = _DropParams

    def reset(self) -> None:
        self.window_s = self.params.window_s
        super().reset()

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        out = []
        for mid in self._feed(observations):
            win = self._win[mid]
            slope = win.slope()
            if slope is None or -slope < self.params.min_drop_kpa_s:
                continue
            p = win.items[-1][1]
            tres = max(0.0, (p - self.params.tres_floor_kpa) / -slope)
            out.append(Signal(detector_id=self.id, emergency="depressurization", module_id=mid, severity="critical",
                              value=slope, tres_s=tres, detail=f"P falling {-slope:.3f} kPa/s, TRes {tres:.0f} s"))
        return out
