"""Event-based metrics for the alert model, as in the ESA anomaly benchmark (ESA-ADB, Kotowski et al. 2024 [R6]): what counts is the
EVENT (a stretch of time with a fault, a stretch of alarm), not the row. Consecutive rows are nearly identical, so row metrics would
reward a model for staying on one long event.

* an alarm is a stretch of ``over`` that lasts ``confirm_s`` (what the classifier would confirm), reported as (start, confirmation);
* an alarm is a TRUE alarm when it overlaps a real event (``slack_s`` of tolerance either side), a false alarm otherwise;
* event recall = real events with at least one true alarm / real events; precision = true alarms / alarms; F0.5 weighs precision
  twice as much as recall (a false alarm costs the crew's attention);
* detection delay = confirmation of the first true alarm minus the START of the event, or minus ``visible_since_s`` when the run has
  a twin (the same seed without the fault) that says when the fault could first be seen at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

Event = tuple[float, float]  # (start, end) in simulated seconds


def episodes(over: np.ndarray, t: np.ndarray, confirm_s: float) -> list[Event]:
    """(start, confirmation time) of every stretch of ``over`` (a boolean per row) that lasts ``confirm_s``: the alarms the
    classifier would open."""
    out: list[Event] = []
    start, done = None, False
    for i, flag in enumerate(over):
        if not flag:
            start, done = None, False
            continue
        start = i if start is None else start
        if not done and t[i] - t[start] >= confirm_s:
            out.append((float(t[start]), float(t[i])))
            done = True
    return out


def _overlaps(a: Event, b: Event, slack_s: float) -> bool:
    return a[0] <= b[1] + slack_s and b[0] <= a[1] + slack_s


@dataclass
class EventScores:
    n_events: int
    n_alarms: int
    true_alarms: int
    detected_events: int
    precision: float | None
    recall: float | None
    f05: float | None
    delays_s: list[float]  # one per detected event

    @property
    def false_alarms(self) -> int:
        return self.n_alarms - self.true_alarms


def event_scores(alarms: Sequence[Event], events: Sequence[Event], slack_s: float = 0.0,
                 visible_since_s: Sequence[float | None] | None = None) -> EventScores:
    """Score a list of alarms (start, confirmation) against the real events (start, end). ``visible_since_s`` (one per event, or None)
    replaces the event start as the origin of the delay."""
    true_alarms = sum(any(_overlaps(a, e, slack_s) for e in events) for a in alarms)
    delays, detected = [], 0
    for i, ev in enumerate(events):
        hits = [a for a in alarms if _overlaps(a, ev, slack_s)]
        if not hits:
            continue
        detected += 1
        origin = ev[0] if visible_since_s is None or visible_since_s[i] is None else visible_since_s[i]
        delays.append(max(0.0, min(a[1] for a in hits) - origin))
    precision = true_alarms / len(alarms) if alarms else None
    recall = detected / len(events) if events else None
    if precision is None or recall is None:
        f05 = None
    else:
        f05 = 0.0 if precision + recall == 0 else 1.25 * precision * recall / (0.25 * precision + recall)
    return EventScores(len(events), len(alarms), true_alarms, detected, precision, recall, f05, delays)


def false_alarms_per_day(n_false: int, simulated_s: float) -> float:
    return n_false / (simulated_s / 86400.0) if simulated_s > 0 else 0.0
