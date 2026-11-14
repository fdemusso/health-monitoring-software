from pathlib import Path

import pytest

from ares3.core.engine import Engine
from ares3.schemas.scenario import load_scenario

SCEN = Path(__file__).resolve().parents[1] / "scenarios"
EVENTS = sorted(p for p in (SCEN / "events").glob("*.yaml") if not p.name.endswith("_faults.yaml"))


@pytest.mark.parametrize("path", EVENTS, ids=lambda p: p.stem)
def test_every_event_scenario_loads_and_builds(path):
    Engine(load_scenario(path))


def _vitals(name: str, tick_idx: int, npc: str) -> dict:
    eng = Engine(load_scenario(SCEN / "events" / f"{name}.yaml"))
    for i, res in enumerate(eng.run(tick_idx + 1)):
        if i == tick_idx:
            return res.tick.npcs[npc].vitals
    raise AssertionError


def test_fibrillation_raises_hr_then_recovers():
    # scenario starts 10:00, episode 11:10-11:25 = t 4200..5100 s
    assert _vitals("fibrillation", 3000, "eng")["hr"] < 100
    assert _vitals("fibrillation", 4800, "eng")["hr"] > 140
    assert _vitals("fibrillation", 6900, "eng")["hr"] < 100


def test_eva_decompression_collapses_pio2_and_spo2():
    eng = Engine(load_scenario(SCEN / "events" / "eva_decompression.yaml"))
    ticks = [r.tick for r in eng.run(4400)]
    assert ticks[4100].modules["eva"].pio2_mmhg > 60  # EVA at 10:08, before the event
    assert ticks[4399].modules["eva"].pio2_mmhg < 10
    assert ticks[4399].npcs["med"].vitals["spo2"] < ticks[4100].npcs["med"].vitals["spo2"] - 20
    assert any(a.module_id == "eva" for a in ticks[4399].alarms)


def test_eva_module_does_not_alarm_when_empty():
    eng = Engine(load_scenario(SCEN / "nominal.yaml"))
    for res in eng.run(600):  # 06:00-06:10, nobody on EVA
        assert not any(a.module_id == "eva" for a in res.tick.alarms)


def test_spo2_curve_is_monotonic_in_pio2():
    from ares3.plugins.physiology.baseline import spo2_from_pio2

    assert spo2_from_pio2(149) > spo2_from_pio2(127) > spo2_from_pio2(85) > spo2_from_pio2(49) > spo2_from_pio2(0)
