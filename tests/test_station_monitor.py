"""The full monitor on the ISS station (rules + ML + procedures): quiet on a nominal run, and the F4 reactions end to end."""

import pytest

from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec
from ares3.schemas.scenario import load_scenario
from conftest import SCENARIOS


@pytest.fixture(scope="module")
def station_scenario():
    return load_scenario(SCENARIOS / "station" / "nominal.yaml")


def _fault(fid, ftype, targets, **params):
    return FaultSpec(id=fid, type=ftype, targets=targets, start_s=0, params=params, anomaly_type=ftype, priority=5)


def test_nominal_station_stays_passive_with_every_detector_running(station_scenario):
    """4 h: past the 3 h the ML needs to be ready, so the anomaly detectors really judged for an hour."""
    eng = Engine(station_scenario)
    modes, events, ml = set(), [], {}
    for res in eng.run(4 * 3600 + 600):
        modes.add(res.tick.monitor_mode)
        events += [e for e in res.tick.monitor_events if e.kind != "mode_changed"]
        ml = res.tick.ml or ml
    assert modes == {"passive"} and not events
    assert set(ml) >= {"ml_atmosphere_co2", "ml_thermal_humidity"} and max(ml.values()) < 1.0  # scored, below their limits


def test_a_stuck_sensor_is_found_proposed_a_substitute_and_the_control_loops_read_it(station_scenario):
    eng = Engine(station_scenario)
    for _ in eng.run(4500):  # the noise baseline of each sensor is learned in the first 70 minutes
        pass
    eng.inject(_fault("stuck_co2", "stuck", ["nod2_ppCO2_a"]))
    pending = None
    for res in eng.run(3600):
        pending = next((p for p in res.tick.pending_actions if p.action.kind == "sensor"), None)
        if pending:
            break
    assert pending, "the stuck sensor was never found"
    assert (pending.action.target, pending.action.value_id) == ("nod2_ppCO2_a", "nod2_ppCO2_b")
    em = next(e for e in res.tick.emergencies if e.kind == "sensor_fault")
    assert em.subject == "nod2_ppCO2_a" and em.alert_class == "caution"
    eng.approve_action(pending.action.id, by="eng")
    for _ in eng.run(5):
        pass
    assert eng._ctx(eng._last_tick, {}).reading("nod2_ppCO2_a") == eng._readings["nod2_ppCO2_b"].value  # a controller would read b
    assert any(p.procedure_id == "sensor_check" and p.subject == "nod2_ppCO2_a" for p in res.tick.procedures)  # the checklist runs next to the playbook


def test_fire_cuts_the_power_of_an_ordinary_module_at_once_and_asks_before_a_vital_one(station_scenario):
    eng = Engine(station_scenario)
    for _ in eng.run(60):
        pass
    eng.inject(_fault("fire_col", "fire", ["COL"], heat_w=300.0))
    for res in eng.run(240):
        if "COL" in res.tick.powered_off:
            break
    assert res.tick.powered_off == ("COL",)

    eng = Engine(station_scenario)
    for _ in eng.run(60):
        pass
    eng.inject(_fault("fire_usl", "fire", ["USL"], heat_w=300.0, extinguishable=False))
    proposal = None
    for res in eng.run(240):
        proposal = next((p for p in res.tick.pending_actions if p.action.kind == "power"), None)
        if proposal:
            break
    assert proposal and proposal.action.target == "USL" and proposal.on_timeout == "execute" and not res.tick.powered_off
    for res in eng.run(80):  # nobody answers: the life-saving step runs on its timeout
        if res.tick.powered_off:
            break
    assert res.tick.powered_off == ("USL",)
