"""Write ``output/ml/monitor_crew_test.yaml``: the station monitor plus the two crew baseline detectors (slow and fast) AFTER the rules
and the stage A/B detectors list, and the diagnoser of ``models/station_v2``. A test monitor kept OUT of the generated station files:
the live monitor stays on ``station_v1`` until phase 3 (``tools/build_station.py`` will own this).

    uv run python tools/ml/make_crew_test_monitor.py
    uv run python tools/ml/check_monitor.py --monitor output/ml/monitor_crew_test.yaml --nominal --seeds 151 --days 1
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scenarios" / "station" / "monitor.yaml"
OUT = ROOT / "output" / "ml" / "monitor_crew_test.yaml"
ANCHOR = "  # Stage B (ML, supervised on the labelled fault catalog)"
CREW = '''  # Crew stage A: each person's vitals against what the programme of the day predicts (plugins/monitor/ml/crew_baseline.py). Slow: the
  # smoothed statistic over its limit for 10 min; fast: the heart rate far from the expected one for 2 min (an acute arrhythmia).
  - {id: ml_crew_slow, kind: "ares3.plugins.monitor.ml.crew_baseline:CrewBaselineDetector", emergency: medical, severity: warning,
     params: {model: "models/station_v2/crew_baseline.joblib", mode: slow}, confirm_s: 600, clear_s: 1200}
  - {id: ml_crew_fast, kind: "ares3.plugins.monitor.ml.crew_baseline:CrewBaselineDetector", emergency: medical, severity: warning,
     params: {model: "models/station_v2/crew_baseline.joblib", mode: fast}, confirm_s: 120, clear_s: 600}
'''


def build(diagnoser: str = "models/station_v2/diagnoser.joblib") -> str:
    text = SOURCE.read_text(encoding="utf-8")
    if ANCHOR not in text:
        raise SystemExit("the anchor of the stage B detector was not found in monitor.yaml")
    text = text.replace(ANCHOR, CREW + ANCHOR, 1)
    return text.replace("models/station_v1/diagnoser.joblib", diagnoser)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--diagnoser", default="models/station_v2/diagnoser.joblib", help="the stage B model the test monitor loads")
    args = p.parse_args(argv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(args.diagnoser), encoding="utf-8")
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
