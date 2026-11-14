"""Discrete simulation clock. Time of day follows the environment profile's day length (24 h on
Earth/orbit, 88775.244 s on Mars), so circadian logic never hardcodes 24 h."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SimClock:
    dt_s: float
    day_length_s: float = 86400.0
    start_tod_h: float = 0.0
    tick: int = 0

    @property
    def t_s(self) -> float:
        return self.tick * self.dt_s

    @property
    def day(self) -> int:
        return int((self.start_tod_h * self.day_length_s / 24.0 + self.t_s) // self.day_length_s)

    @property
    def time_of_day_h(self) -> float:
        """Hours of the local day in [0, 24); a day is always 24 'local hours' long."""
        frac = ((self.start_tod_h / 24.0) * self.day_length_s + self.t_s) % self.day_length_s
        return 24.0 * frac / self.day_length_s

    def advance(self) -> None:
        self.tick += 1
