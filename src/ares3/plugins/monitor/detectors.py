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


class _VarianceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_s: float = Field(default=600.0, gt=0)  # the noise is measured over this window
    warmup_s: float = Field(default=3600.0, ge=0)  # no judgement before this much history (the baseline needs it)
    baseline_s: float = Field(default=21600.0, gt=0)  # time constant of the slow baseline of each sensor's own noise
    stuck_ratio: float = Field(default=0.05, gt=0)  # fires when the noise falls below this fraction of the baseline
    noise_ratio: float = Field(default=3.0, gt=1)  # ... or rises above this multiple of it
    every_s: float = Field(default=5.0, ge=0)  # looks at one sample every this many seconds (the cost of a window push is the monitor's main cost)


class _Spread:
    """Standard deviation of a window from two running ``_Window`` sums (values shifted by the first one, so the sum of
    squares does not lose the small noise on top of a large level)."""

    def __init__(self, window_s: float) -> None:
        self.v, self.v2, self.ref = _Window(window_s), _Window(window_s), None

    def push(self, t: float, x: float) -> None:
        if self.ref is None:
            self.ref = x
        self.v.push(t, x)
        self.v2.push(t, (x - self.ref) ** 2)

    def full(self) -> bool:
        return self.v.full()

    def std(self) -> float:
        m = self.v.mean() - self.ref
        return math.sqrt(max(self.v2.mean() - m * m, 0.0))


class Variance(BaseDetector):
    """A sensor whose NOISE changed: stuck (no variation at all) or much noisier than its own usual level.

    Every sensor of ``metric`` on ``targets`` is compared with its OWN baseline (a slow average of its noise), so there is
    no threshold in the unit of the metric: the rule is the same for a thermometer and a CO2 probe. This is the
    "varianza ~0 = sensore_bloccato, deviazione alta con media ferma = rumore_sensore" of the fault catalog (sheet 06).
    The noise is estimated from the DIFFERENCES between consecutive samples, so a real change of the quantity (CO2 rising
    in a small volume) does not look like noise. A sensor that rotates over several modules (the MCA) is followed per
    module. The signal is about one sensor: ``subject`` is its id, ``module_id`` the module it measures. The classifier
    opens a ``sensor_fault`` emergency per sensor."""

    Params = _VarianceParams

    def reset(self) -> None:
        self._sp: dict[tuple[str, str], _Spread] = {}
        self._prev: dict[tuple[str, str], float] = {}
        self._last_seen: dict[tuple[str, str], float] = {}
        self._base: dict[tuple[str, str], float] = {}
        self._t_first: dict[tuple[str, str], float] = {}
        self._last_t: dict[tuple[str, str], float] = {}
        self._latched: dict[tuple[str, str], Signal] = {}  # the monitor's debounce wants the signal on every tick, not every every_s

    def forget(self, entity_id: str) -> None:
        pass  # a sensor fault is not repaired by the crew: nothing to drop

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        p = self.params
        out = []
        for o in observations:
            if o.metric != self.metric or o.entity_id not in self.targets:
                continue
            sid = o.sensor_id
            key = (sid, o.entity_id)
            seen = self._last_seen.get(key)
            if seen is not None and o.t_s - seen < p.every_s - 1e-9:
                if key in self._latched:
                    out.append(self._latched[key])
                continue
            self._last_seen[key] = o.t_s
            self._latched.pop(key, None)
            prev = self._prev.get(key)
            self._prev[key] = o.value
            if prev is None:
                self._sp[key] = _Spread(p.window_s)
                self._t_first[key] = self._last_t[key] = o.t_s
                continue
            sp = self._sp[key]
            sp.push(o.t_s, o.value - prev)
            if o.t_s - self._t_first[key] < p.warmup_s or not sp.full():
                continue
            sd = sp.std()
            base = self._base.get(key)
            if base is None:
                self._base[key], self._last_t[key] = sd, o.t_s
                continue
            if base > 0.0 and (sd < p.stuck_ratio * base or sd > p.noise_ratio * base):
                what = "stuck" if sd < base else "noisy"
                sig = Signal(detector_id=self.id, emergency="sensor_fault", module_id=o.entity_id, severity="warning",
                             subject=sid, value=sd, detail=f"{sid} {what}: noise {sd:.3g} vs {base:.3g} usual")
                self._latched[key] = sig
                out.append(sig)
            else:
                alpha = min(1.0, (o.t_s - self._last_t[key]) / p.baseline_s)
                self._base[key] = base + alpha * (sd - base)  # the baseline only learns from healthy samples
            self._last_t[key] = o.t_s
        return out


class _ResidualParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_s: float = Field(default=1800.0, gt=0)
    baseline_s: float = Field(default=3600.0, ge=0)  # the offsets of the units are learned over this long, after the first window
    max_change: float = Field(gt=0)  # fires when a residual moves this far from its baseline (unit of the metric)
    # a sensor with fewer samples than this in a window is not judged: the MCA samples a module once in 20 minutes, its window mean
    # is a couple of samples and would "disagree" with everything by chance
    min_samples: int = Field(default=60, ge=1)
    every_s: float = Field(default=10.0, ge=0)  # looks at one sample every this many seconds: a window MEAN does not need more


class RedundancyResidual(BaseDetector):
    """Redundant sensors of one place that stop agreeing. Each module with two or more sensors of ``metric`` gets a
    residual per sensor (its window mean minus the mean of the others'); the units differ by a fixed error each, so what
    counts is how far a residual MOVES from its own baseline (learned over ``baseline_s`` after the first window).

    Catches a bias, a drift or an offset on ONE of the sensors (``bias_sensore_P``, ``deriva_sensore_CO2``, ...), which a
    threshold on the value cannot tell from a real change. With three or more sensors ``subject`` is the one that moved
    most; with two the culprit is not known and ``subject`` names the pair (``usl_P_a~usl_P_b``). Leave out of ``targets``
    the modules whose sensors do not see the same air (an outlet next to a scrubber)."""

    Params = _ResidualParams

    def reset(self) -> None:
        self._win: dict[tuple[str, str], _Window] = {}  # (sensor, module): a sensor that rotates over modules (the MCA) counts in each
        self._members: dict[str, list[tuple[str, str]]] = {}  # module -> its (sensor, module) keys
        self._base: dict[str, dict[tuple[str, str], float]] = {}  # module -> sensor -> baseline residual
        self._acc: dict[str, dict[tuple[str, str], list[float]]] = {}
        self._t_ready: dict[str, float] = {}
        self._latched: dict[str, Signal] = {}  # the monitor's debounce wants the signal on every tick, not every every_s

    def forget(self, entity_id: str) -> None:
        pass  # a sensor fault is not repaired by the crew

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        p = self.params
        touched: set[str] = set()
        for o in observations:
            if o.metric != self.metric or o.entity_id not in self.targets:
                continue
            key = (o.sensor_id, o.entity_id)
            if key not in self._win:
                self._win[key] = _Window(p.window_s)
                self._members.setdefault(o.entity_id, []).append(key)
            elif o.t_s - self._win[key].items[-1][0] < p.every_s - 1e-9:
                continue
            self._win[key].push(o.t_s, o.value)
            touched.add(o.entity_id)
        out = [sig for mid, sig in self._latched.items() if mid not in touched]
        t = ctx.tick.t_sim_s
        for mid in sorted(touched):
            self._latched.pop(mid, None)
            ids = [i for i in self._members[mid] if self._win[i].full() and len(self._win[i].items) >= p.min_samples]
            if len(ids) < 2:  # the sparse sensors (the MCA) are left out, they do not veto the others
                continue
            means = {i: self._win[i].mean() for i in ids}
            resid = {i: means[i] - sum(v for j, v in means.items() if j != i) / (len(ids) - 1) for i in ids}
            t0 = self._t_ready.setdefault(mid, t)
            if t - t0 < p.baseline_s:  # learning the fixed offsets of the units
                acc = self._acc.setdefault(mid, {i: [] for i in ids})
                for i in ids:
                    acc[i].append(resid[i])
                continue
            if mid not in self._base:
                self._base[mid] = {i: sum(v) / len(v) for i, v in self._acc.get(mid, {}).items() if v} or dict(resid)
            base = self._base[mid]
            moved = {i: resid[i] - base[i] for i in ids if i in base}
            worst = max(moved, key=lambda i: abs(moved[i]), default=None)
            if worst is not None and abs(moved[worst]) > p.max_change:
                who = worst[0] if len(ids) > 2 else "~".join(sorted(k[0] for k in ids))
                sig = Signal(detector_id=self.id, emergency="sensor_fault", module_id=mid, severity="warning",
                             subject=who, value=moved[worst],
                             detail=f"{who}: {self.metric} no longer agrees with its redundant sensor "
                                    f"({moved[worst]:+.3g} from its usual offset)")
                self._latched[mid] = sig
                out.append(sig)
        return out


# NEWS2 (Royal College of Physicians [R8]), scale 1 for SpO2: (upper bound inclusive, points) from the lowest band up.
_NEWS_BANDS = {
    "resp_rate": ((8, 3), (11, 1), (20, 0), (24, 2), (math.inf, 3)),
    "spo2": ((91, 3), (93, 2), (95, 1), (math.inf, 0)),
    "hr": ((40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (math.inf, 3)),
    "core_temp_c": ((35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (math.inf, 2)),
}
_EXERCISE_BLIND = ("hr", "resp_rate")  # a hospital score knows nothing about exercise: these two are not scored while it lasts


def news_points(metric: str, value: float) -> int:
    return next(pts for hi, pts in _NEWS_BANDS[metric] if value <= hi)


class _EwsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_s: float = Field(default=300.0, gt=0)  # the score is computed on the MEAN of each vital over this window
    min_score: int = Field(default=5, ge=1)  # NEWS2 5-6: urgent response; 7 or more: emergency
    single_3: bool = True  # also fires when ONE parameter is at 3 points (NEWS2 "red score")
    exercise_met: float = Field(default=4.0, gt=0)  # while a crew member works at this effort or more, HR and RR are not scored
    exercise_recovery_s: float = Field(default=1800.0, ge=0)  # ... nor for this long after it: heart and breathing take time to settle


class EarlyWarningScore(_Windowed):
    """A NEWS2-style early warning score on the crew's wearables (breathing rate, SpO2, heart rate, core temperature, plus
    consciousness: ``health_state`` >= 2 is 3 points; a wearable has no blood pressure, so that term is missing).
    ESTIMATE: an adaptation of a hospital tool, to confirm with the bioengineer. It uses the MEAN of each vital over
    5 minutes, not the sample, because the score on a continuous wearable stream throws many false alarms [R18]. Use one
    instance per level (``min_score`` 5 -> warning, 7 -> critical, with ``single_3: false``): the severity belongs to
    the YAML spec. ``targets`` are crew ids."""

    Params = _EwsParams
    _METRICS = (*_NEWS_BANDS, "health_state")

    def reset(self) -> None:
        self.window_s = self.params.window_s
        self._wins: dict[tuple[str, str], _Window] = {}
        self._last_exercise: dict[str, float] = {}

    def forget(self, entity_id: str) -> None:
        self._wins = {k: w for k, w in self._wins.items() if k[0] != entity_id}

    def detect(self, ctx: StepContext, observations: list[Observation]) -> list[Signal]:
        p = self.params
        for o in observations:
            if o.metric in self._METRICS and o.entity_id in self.targets:
                self._wins.setdefault((o.entity_id, o.metric), _Window(p.window_s)).push(o.t_s, o.value)
        out = []
        for npc_id in self.targets:
            npc = ctx.tick.npcs.get(npc_id)
            wins = {m: self._wins.get((npc_id, m)) for m in self._METRICS}
            if npc is None or any(wins[m] is None or not wins[m].full() for m in _NEWS_BANDS):
                continue
            t = ctx.tick.t_sim_s
            if npc.met >= p.exercise_met:
                self._last_exercise[npc_id] = t
            exercising = t - self._last_exercise.get(npc_id, -math.inf) < p.exercise_recovery_s
            pts = {m: 0 if exercising and m in _EXERCISE_BLIND else news_points(m, wins[m].mean()) for m in _NEWS_BANDS}
            hs = wins["health_state"]
            if hs is not None and hs.full() and hs.mean() >= 2.0:
                pts["consciousness"] = 3
            total = sum(pts.values())
            if total >= p.min_score or (p.single_3 and 3 in pts.values()):
                worst = ", ".join(f"{m} {v}" for m, v in sorted(pts.items(), key=lambda kv: -kv[1]) if v)
                out.append(Signal(detector_id=self.id, emergency="medical", module_id=npc.module_id, severity="warning",
                                  subject=npc_id, value=float(total), detail=f"early warning score {total} ({worst})"))
        return out
