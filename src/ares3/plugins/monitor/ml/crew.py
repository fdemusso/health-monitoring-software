"""Feature extraction for the crew model: ONE implementation used online (a detector inside the simulation) and offline
(``tools/ml/make_dataset.py`` writes ``crew.parquet`` with the same rows), like ``features.py``.

One vector per crew member, from the SENSED wearable observations (``Observation.value``, never the true vitals) plus the
context of the programme of the day (``NPCState.met`` / ``activity``: what the OSTPV gives on the ISS, as
``EarlyWarningScore`` already reads it). Samples are averaged into bins of ``bin_s`` seconds in a ring buffer of 1 h.

Per vital (``hr``, ``resp_rate``, ``spo2``, ``core_temp_c``, ``skin_temp_c``, ``hrv_rmssd``):

* ``lv10``  mean of the last 10 min (a LEVEL: the wearables have no fixed error per unit, ``WearableSensor`` is truth plus
  white noise, so the level is a lawful feature here, unlike the ambient sensors of ``features.py``)
* ``sd10``  noise: pooled standard deviation of the raw samples inside the bins of the last 10 min
* ``sl1h``  (``core_temp_c`` only) least-squares slope over 1 h, per hour

Context: ``met10`` (mean MET, 10 min), ``met_max30`` (max MET, 30 min), ``min_since_ex`` (minutes since the last MET >= 4, 120 =
never or longer), ``act_*`` (one-hot of the activity class now), ``min_since_sleep`` (minutes since sleep began, 480 at most,
0 awake) and the sin / cos of the local day.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable, Mapping, Sequence

import numpy as np

from .features import BIN_S, _slope

VITALS = ("hr", "resp_rate", "spo2", "core_temp_c", "skin_temp_c", "hrv_rmssd")
CLASSES = ("sleep", "nominal", "exercise_aerobic", "exercise_resistive", "recovery")
ACT_NAMES = ("act_sleep", "act_nominal", "act_aerobic", "act_resistive", "act_recovery")
# the aliases of ``core/metabolism.py::DEFAULT_ALIASES`` (a plugin cannot import the core); an unknown activity counts as nominal
ALIASES = {"work": "nominal", "rest": "nominal", "meal": "nominal", "exercise": "exercise_aerobic"}
EXERCISE_MET = 4.0  # a MET at or above this is exercise (the threshold of ``EarlyWarningScore``)
READY_S = 1800.0  # the 10 min windows and the 30 min MET maximum are full after this
W10_S, W30_S, W1H_S = 600.0, 1800.0, 3600.0
SINCE_EX_MAX_MIN = 120.0
SINCE_SLEEP_MAX_MIN = 480.0
_N = len(VITALS) + 1  # series per crew member: the vitals and the MET


def activity_class(activity: str) -> str:
    """Class of the activity of a block (``CLASSES``): the aliases resolved, an unknown name counts as nominal."""
    name = ALIASES.get(activity, activity)
    return name if name in CLASSES else "nominal"


def crew_sensor_map(sensors: Iterable) -> dict[str, tuple[str, str]]:
    """``{sensor id: (npc id, metric)}`` of the wearable sensors of a layout (``SensorSpec`` with target ``npc:<id>``)."""
    out = {}
    for s in sensors:
        kind, _, ident = s.target.partition(":")
        if kind == "npc" and s.metric in VITALS:
            out[s.id] = (ident, s.metric)
    return out


class CrewFeatureExtractor:
    """Rolling features of each crew member. ``push`` every tick, ``compute`` when a row is wanted."""

    def __init__(self, npc_ids: Sequence[str], sensor_map: Mapping[str, tuple[str, str]], bin_s: float = BIN_S) -> None:
        self.npc_ids = list(npc_ids)
        self.bin_s = float(bin_s)
        self._row = {}  # sensor id -> series index
        for sid, (npc, metric) in sensor_map.items():
            if npc in self.npc_ids:
                self._row[sid] = self.npc_ids.index(npc) * _N + VITALS.index(metric)
        self._n_bins = round(W1H_S / self.bin_s)
        n = len(self.npc_ids) * _N
        self._mean = np.full((n, self._n_bins), np.nan)  # mean of the samples of each bin
        self._var = np.full((n, self._n_bins), np.nan)  # their variance inside the bin
        self._max = np.full((n, self._n_bins), np.nan)  # their maximum (the MET series)
        self._sum, self._sq, self._k, self._mx = np.zeros(n), np.zeros(n), np.zeros(n), np.full(n, -np.inf)
        self._bin = 0
        self._started: float | None = None
        self._last_ex = np.full(len(self.npc_ids), -np.inf)  # time of the last MET >= EXERCISE_MET
        self._asleep_since = np.full(len(self.npc_ids), np.nan)
        self._act = np.zeros((len(self.npc_ids), len(CLASSES)))  # one-hot of the class at the last tick
        self._tod_h = 0.0
        self.names = ([f"{m}|{s}" for m in VITALS for s in ("lv10", "sd10")] + ["core_temp_c|sl1h"]
                      + ["ctx|met10", "ctx|met_max30", "ctx|min_since_ex"] + [f"ctx|{a}" for a in ACT_NAMES]
                      + ["ctx|min_since_sleep", "clock|sin", "clock|cos"])

    @property
    def n_features(self) -> int:
        return len(self.names)

    def _flush(self, upto: int) -> None:
        """Close the bin being filled and every empty one up to (not including) ``upto``."""
        has = self._k > 0
        mean = np.where(has, self._sum / np.maximum(self._k, 1.0), np.nan)
        var = np.where(has, np.maximum(self._sq / np.maximum(self._k, 1.0) - mean**2, 0.0), np.nan)
        slot = self._bin % self._n_bins
        self._mean[:, slot], self._var[:, slot] = mean, var
        self._max[:, slot] = np.where(has, self._mx, np.nan)
        self._sum[:], self._sq[:], self._k[:], self._mx[:] = 0.0, 0.0, 0.0, -np.inf
        for b in range(self._bin + 1, min(upto, self._bin + self._n_bins + 1)):  # empty bins (a gap in the stream)
            s = b % self._n_bins
            self._mean[:, s] = self._var[:, s] = self._max[:, s] = np.nan
        self._bin = upto

    def _add(self, i: int, v: float) -> None:
        self._sum[i] += v
        self._sq[i] += v * v
        self._k[i] += 1.0
        self._mx[i] = max(self._mx[i], v)

    def push(self, tick, observations: Iterable) -> None:
        """One tick: the sensed vitals of ``observations`` (a lost sample is simply absent) and, from ``tick``, the MET and
        the activity of every crew member."""
        t = tick.t_sim_s
        if self._started is None:
            self._started, self._bin = t, int(t // self.bin_s)
        b = int(t // self.bin_s)
        if b != self._bin:
            self._flush(b)
        for o in observations:
            i = self._row.get(o.sensor_id)
            if i is not None and math.isfinite(o.value):
                self._add(i, o.value)
        for j, npc in enumerate(self.npc_ids):
            state = tick.npcs.get(npc)
            if state is None:
                continue
            self._add(j * _N + len(VITALS), state.met)
            if state.met >= EXERCISE_MET:
                self._last_ex[j] = t
            cls = activity_class(state.activity)
            self._act[j] = [c == cls for c in CLASSES]
            if cls == "sleep":
                if math.isnan(self._asleep_since[j]):
                    self._asleep_since[j] = t
            else:
                self._asleep_since[j] = np.nan
        self._tod_h = tick.time_of_day_h

    def ready(self, t_s: float) -> bool:
        return self._started is not None and t_s - self._started >= READY_S

    def _last(self, arr: np.ndarray, n_bins: int) -> np.ndarray:
        """The last ``n_bins`` CLOSED bins, oldest first."""
        idx = (self._bin - n_bins + np.arange(n_bins)) % self._n_bins
        return arr[:, idx]

    def compute(self, t_s: float) -> dict[str, np.ndarray]:
        """``{npc id: feature vector}`` at ``t_s`` (call after the ``push`` of that tick); NaN where a vital has no data."""
        w10, w30, w1h = (round(w / self.bin_s) for w in (W10_S, W30_S, W1H_S))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices are expected (a vital with no samples)
            m1 = self._last(self._mean, w1h)
            lv10 = np.nanmean(m1[:, -w10:], axis=1)
            sd10 = np.sqrt(np.nanmean(self._last(self._var, w10), axis=1))
            max30 = np.nanmax(self._last(self._max, w30), axis=1)
            slope = _slope(m1) * 3600.0 / self.bin_s
        phase = 2.0 * math.pi * self._tod_h / 24.0
        out = {}
        for j, npc in enumerate(self.npc_ids):
            base = j * _N
            vit = [x for k in range(len(VITALS)) for x in (lv10[base + k], sd10[base + k])]
            since_ex = min((t_s - self._last_ex[j]) / 60.0, SINCE_EX_MAX_MIN)  # -inf -> the limit
            since_sleep = 0.0 if math.isnan(self._asleep_since[j]) else min((t_s - self._asleep_since[j]) / 60.0, SINCE_SLEEP_MAX_MIN)
            ctx = [lv10[base + len(VITALS)], max30[base + len(VITALS)], since_ex, *self._act[j], since_sleep]
            out[npc] = np.asarray([*vit, slope[base + VITALS.index("core_temp_c")], *ctx, math.sin(phase), math.cos(phase)])
        return out
