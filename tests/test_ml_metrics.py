"""Event metrics (ESA-ADB style): alarms and events, not rows."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ml"))
import metrics as m


def test_an_alarm_needs_the_confirmation_time():
    t = np.arange(0.0, 600.0, 60.0)
    over = np.array([0, 1, 1, 0, 1, 1, 1, 1, 1, 1], dtype=bool)
    assert m.episodes(over, t, 120.0) == [(240.0, 360.0)]  # the two-row blip is too short, the long stretch is one alarm
    assert m.episodes(over, t, 0.0) == [(60.0, 60.0), (240.0, 240.0)]


def test_event_scores_precision_recall_f05_and_delay():
    events = [(1000.0, 2000.0), (5000.0, 6000.0), (9000.0, 9500.0)]
    alarms = [(1100.0, 1400.0), (5900.0, 6300.0), (7000.0, 7300.0)]  # the 2nd is late but overlaps; the 3rd is false; the 3rd event is missed
    s = m.event_scores(alarms, events)
    assert (s.n_events, s.n_alarms, s.true_alarms, s.detected_events, s.false_alarms) == (3, 3, 2, 2, 1)
    assert s.precision == pytest.approx(2 / 3) and s.recall == pytest.approx(2 / 3)
    assert s.f05 == pytest.approx(2 / 3)  # equal precision and recall: F0.5 = both
    assert s.delays_s == [400.0, 1300.0]
    # the delay counts from the moment the fault could first be seen, when a twin run says so
    s = m.event_scores(alarms[:1], events[:1], visible_since_s=[1300.0])
    assert s.delays_s == [100.0]


def test_f05_prefers_precision_and_empty_inputs_are_not_numbers():
    few = m.event_scores([(0.0, 1.0)], [(0.0, 5.0), (10.0, 15.0)])  # precision 1, recall 0.5
    many = m.event_scores([(0.0, 1.0), (10.0, 11.0), (20.0, 21.0), (30.0, 31.0)], [(0.0, 5.0), (10.0, 15.0)])  # precision 0.5, recall 1
    assert few.f05 > many.f05
    nothing = m.event_scores([], [(0.0, 5.0)])
    assert nothing.precision is None and nothing.f05 is None and nothing.recall == 0.0
    assert m.false_alarms_per_day(3, 2 * 86400.0) == 1.5
