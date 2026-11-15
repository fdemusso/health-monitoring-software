"""Feature extraction for the ML monitor: ONE implementation used online (the detector inside the simulation) and offline
(``tools/ml/make_dataset.py`` writes the same rows), so training and inference see exactly the same numbers.

The input is a stream of SENSED samples ``(key, value)``, never the true state (a key is a sensor id). Samples are averaged
into bins of ``bin_s`` seconds and kept in a ring buffer; every ``eval_every_s`` the statistics of the windows are computed
with numpy over the whole buffer at once, so the cost per simulated tick is a dictionary lookup per sample.

Per key, over the windows 10 min / 1 h / 6 h (``STATS``):

* ``d10``  mean of the last 10 min minus mean of the last hour  (a recent change)
* ``d1h``  mean of the last hour minus mean of the last 6 h     (a change that has settled)
* ``sd10`` noise: pooled standard deviation of the raw samples inside the bins of the last 10 min
* ``n10``  samples received in the last 10 min  (a silent sensor, a rotating MCA line)
* ``sl1h`` / ``sl6h``  least-squares slope of the bin means over 1 h / 6 h, per hour

Levels are NOT features: every sensor has its own fixed error (``bias_sigma``, different for each unit and seed), so a
level would make each unit look anomalous in a run it was not trained on; what a fault changes is how the signal MOVES
(and how the redundant sensors of one place move together). Plus a clock (sin/cos of the day and of the orbit), because
the orbital cycle and the crew shifts move many signals and are not faults [guide, section 8].
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable, Mapping, Sequence

import numpy as np

BIN_S = 10.0
WINDOWS_S = (600.0, 3600.0, 21600.0)  # 10 min, 1 h, 6 h
STATS = ("d10", "d1h", "sd10", "n10", "sl1h", "sl6h")
WARMUP_S = 0.5 * WINDOWS_S[-1]  # the 6 h statistics need at least half a window of history, like ``_Window``


def orbit_period_s(env) -> float | None:
    """Period of the orbit of an environment profile (None on a planet surface): the same formula as ``core/orbit.py``."""
    orb = getattr(env, "orbit", None)
    if orb is None:
        return None
    r = orb.planet_radius_km + orb.altitude_km
    return 2.0 * math.pi * math.sqrt(r**3 / orb.mu_km3_s2)


def clock_periods(env) -> tuple[float, ...]:
    """Periods (s) the clock features run at: the day of the environment and, on the station, the orbit."""
    period = orbit_period_s(env)
    return (float(env.day_length_s),) + (() if period is None else (period,))


def tick_samples(tick, observations: Iterable) -> list[tuple[str, float]]:
    """The samples of one tick: the sensed value of every observation (NaN-free: a dropped sample is simply absent)."""
    return [(o.sensor_id, o.value) for o in observations]


class FeatureExtractor:
    """Rolling features of a fixed list of ``keys``. ``push`` every tick, ``compute`` when a row is wanted."""

    def __init__(self, keys: Sequence[str], periods_s: Sequence[float] = (), bin_s: float = BIN_S) -> None:
        self.keys = list(keys)
        self.periods_s = tuple(periods_s)
        self.bin_s = float(bin_s)
        self._index = {k: i for i, k in enumerate(self.keys)}
        self._n_bins = round(WINDOWS_S[-1] / self.bin_s)
        n = len(self.keys)
        self._mean = np.full((n, self._n_bins), np.nan)  # mean of the samples of each bin
        self._var = np.full((n, self._n_bins), np.nan)  # their variance inside the bin
        self._cnt = np.zeros((n, self._n_bins))
        self._sum, self._sq, self._k = np.zeros(n), np.zeros(n), np.zeros(n)
        self._bin = 0
        self._started: float | None = None
        self.names = [f"{k}|{s}" for k in self.keys for s in STATS] + [
            f"clock|{fn}{i}" for i in range(len(self.periods_s)) for fn in ("sin", "cos")]

    @property
    def n_features(self) -> int:
        return len(self.names)

    def _flush(self, upto: int) -> None:
        """Close the bin being filled and every empty one up to (not including) ``upto``."""
        has = self._k > 0
        mean = np.where(has, self._sum / np.maximum(self._k, 1.0), np.nan)
        var = np.where(has, np.maximum(self._sq / np.maximum(self._k, 1.0) - mean**2, 0.0), np.nan)
        slot = self._bin % self._n_bins
        self._mean[:, slot], self._var[:, slot], self._cnt[:, slot] = mean, var, self._k
        self._sum[:], self._sq[:], self._k[:] = 0.0, 0.0, 0.0
        for b in range(self._bin + 1, min(upto, self._bin + self._n_bins + 1)):  # empty bins (a gap in the stream)
            s = b % self._n_bins
            self._mean[:, s] = self._var[:, s] = np.nan
            self._cnt[:, s] = 0.0
        self._bin = upto

    def push(self, t_s: float, samples: Iterable[tuple[str, float]]) -> None:
        if self._started is None:
            self._started, self._bin = t_s, int(t_s // self.bin_s)
        b = int(t_s // self.bin_s)
        if b != self._bin:
            self._flush(b)
        for key, v in samples:
            i = self._index.get(key)
            if i is not None:
                self._sum[i] += v
                self._sq[i] += v * v
                self._k[i] += 1.0

    def ready(self, t_s: float) -> bool:
        return self._started is not None and t_s - self._started >= WARMUP_S

    def _last(self, arr: np.ndarray, n_bins: int) -> np.ndarray:
        """The last ``n_bins`` CLOSED bins, oldest first."""
        idx = (self._bin - n_bins + np.arange(n_bins)) % self._n_bins
        return arr[:, idx]

    def compute(self, t_s: float) -> np.ndarray:
        """Feature vector at ``t_s`` (call after the ``push`` of that tick); NaN where a key has no data in a window."""
        w10, w1h, w6h = (round(w / self.bin_s) for w in WINDOWS_S)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices are expected (a key with no samples)
            m6 = self._last(self._mean, w6h)
            m1, m10 = m6[:, -w1h:], m6[:, -w10:]
            mean10, mean1, mean6 = np.nanmean(m10, axis=1), np.nanmean(m1, axis=1), np.nanmean(m6, axis=1)
            var10 = np.nanmean(self._last(self._var, w10), axis=1)
            n10 = self._last(self._cnt, w10).sum(axis=1)
            out = np.empty((len(self.keys), len(STATS)))
            out[:, 0], out[:, 1] = mean10 - mean1, mean1 - mean6
            out[:, 2], out[:, 3] = np.sqrt(var10), n10
            out[:, 4], out[:, 5] = _slope(m1) * 3600.0 / self.bin_s, _slope(m6) * 3600.0 / self.bin_s
        clock = [f(2.0 * math.pi * t_s / p) for p in self.periods_s for f in (math.sin, math.cos)]
        return np.concatenate([out.ravel(), np.asarray(clock)])


def _slope(y: np.ndarray) -> np.ndarray:
    """Least-squares slope (per bin) of each row of ``y``, ignoring NaN; NaN where fewer than 3 bins hold a value."""
    x = np.arange(y.shape[1], dtype=float)
    ok = ~np.isnan(y)
    n = ok.sum(axis=1)
    xm = np.where(ok, x, 0.0).sum(axis=1) / np.maximum(n, 1)
    ym = np.nansum(y, axis=1) / np.maximum(n, 1)
    dx = np.where(ok, x - xm[:, None], 0.0)
    dy = np.where(ok, y - ym[:, None], 0.0)
    den = (dx * dx).sum(axis=1)
    return np.where((n >= 3) & (den > 0), (dx * dy).sum(axis=1) / np.where(den > 0, den, 1.0), np.nan)


def select(names: Sequence[str], keys: Iterable[str]) -> list[int]:
    """Column indices of ``names`` that belong to ``keys`` (plus the clock): how a group takes its slice of the full row."""
    wanted = set(keys)
    return [i for i, n in enumerate(names) if n.split("|")[0] in wanted or n.startswith("clock|")]


def describe(name: str, labels: Mapping[str, str] | None = None) -> str:
    """Human-readable name of a feature, for the explanation shown to the crew."""
    key, _, stat = name.partition("|")
    what = {"d10": "change over 10 min", "d1h": "change over 1 h", "sd10": "noise", "n10": "samples in 10 min",
            "sl1h": "slope over 1 h", "sl6h": "slope over 6 h"}.get(stat, stat)
    return f"{(labels or {}).get(key, key)}: {what}"
