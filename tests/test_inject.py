import pytest

from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec


def _leak(fid="debug_leak", target="lab", rate=0.002):
    return FaultSpec(id=fid, type="leak", targets=[target], start_s=0, params={"rate_per_s": rate},
                     anomaly_type="slow_leak", priority=5)


def test_inject_starts_now_and_labels_rows(nominal):
    eng = Engine(nominal)
    for _ in eng.run(60):
        pass
    f = eng.inject(_leak())
    assert f.start_s == eng.clock.t_s  # "now", not the 0 written in the spec
    results = list(eng.run(120))
    p0, p1 = (results[0].tick.modules["lab"].pressure_kpa, results[-1].tick.modules["lab"].pressure_kpa)
    assert p1 < p0 - 0.5
    assert "debug_leak" in results[-1].tick.active_faults
    assert any(r["anomaly_type"] == "slow_leak" for res in results for r in res.rows)


def test_inject_does_not_edit_the_scenario(nominal):
    n = len(nominal.faults.faults)
    Engine(nominal).inject(_leak())
    assert len(nominal.faults.faults) == n


def test_stop_event_ends_it(nominal):
    eng = Engine(nominal)
    eng.inject(_leak())
    for _ in eng.run(30):
        pass
    eng.stop_event("debug_leak")
    assert "debug_leak" not in next(iter(eng.run(1))).tick.active_faults


def test_inject_rejects_unknown_target_and_duplicate_id(nominal):
    eng = Engine(nominal)
    with pytest.raises(ValueError):
        eng.inject(_leak(target="nope"))
    eng.inject(_leak())
    with pytest.raises(ValueError):
        eng.inject(_leak())


def test_escape_vehicle_is_declared_and_sealed(nominal):
    vehicles = [m.id for m in nominal.layout.modules if m.return_vehicle]
    assert vehicles == ["lifeboat"]
    hatch = next(h for h in nominal.layout.hatches if "lifeboat" in (h.a, h.b))
    assert hatch.open is False
