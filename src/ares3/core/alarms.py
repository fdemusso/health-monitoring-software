"""Limit monitor driven by the environment profile's ``alarm_rules`` (NASA-STD-3001 in the shipped
profiles). Evaluates the TRUE module state, never sensor readings, so sensor noise cannot make an
alarm flicker. Windowed rules (``window_s > 0``) use the running mean over the window."""

from __future__ import annotations

from collections import deque

from ares3.schemas.environment import AlarmRule
from ares3.sdk.metrics import module_metric
from ares3.sdk.types import AlarmEvent, ModuleState


class _Window:
    """Running mean over ``window_s``. A window longer than an hour keeps at most ~3600 samples (decimated), so a 7-day
    criterion costs the same memory as a 1-hour one."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self.items: deque[tuple[float, float]] = deque()
        self.total = 0.0
        self._every = max(0.0, window_s / 3600.0)
        self._last = -1e30

    def push(self, t: float, v: float) -> float:
        if not self.items or t - self._last >= self._every:
            self._last = t
            self.items.append((t, v))
            self.total += v
        while self.items and self.items[0][0] <= t - self.window_s:
            _, old = self.items.popleft()
            self.total -= old
        return self.total / len(self.items)


class AlarmMonitor:
    def __init__(self, rules: list[AlarmRule], occupied_only: frozenset[str] = frozenset(), never: frozenset[str] = frozenset(),
                 module_rules: dict[str, list[AlarmRule]] | None = None) -> None:
        self.rules = rules
        self.occupied_only = occupied_only
        self.never = never  # modules that are not alarmed
        self.module_rules = module_rules or {}  # modules that have limits of their own
        self._windows: dict[tuple[str, str], _Window] = {}

    def evaluate(self, t_s: float, modules: dict[str, ModuleState]) -> tuple[AlarmEvent, ...]:
        events: list[AlarmEvent] = []
        for mid, m in modules.items():
            if mid in self.never or (mid in self.occupied_only and not m.occupants):
                continue
            for rule in self.module_rules.get(mid, self.rules):
                value = module_metric(m, rule.metric)
                if rule.window_s > 0:
                    win = self._windows.setdefault((rule.code, mid), _Window(rule.window_s))
                    value = win.push(t_s, value)
                if (rule.min is not None and value < rule.min) or (rule.max is not None and value > rule.max):
                    events.append(AlarmEvent(
                        code=rule.code, module_id=mid, metric=rule.metric, value=value,
                        limit_min=rule.min, limit_max=rule.max, severity=rule.severity, source=rule.source,
                    ))
        return tuple(events)
