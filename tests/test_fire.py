from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec
from ares3.schemas.scenario import load_scenario
from conftest import SCENARIOS


def _fire(module="hab", fid="debug_fire", **params):
    return FaultSpec(id=fid, type="fire", targets=[module], start_s=0, params={"heat_w": 1000, **params},
                     anomaly_type="fire", priority=10)


def _bare(station, **kw):
    """Station without the monitoring system: pure physics."""
    sc = station.model_copy(update={"monitor": station.monitor.model_copy(update={"detectors": [], "playbooks": [],
                                                                                 "crew_response": None})})
    eng = Engine(sc)
    for _ in eng.run(10):
        pass
    return eng


def _engine(station, start_h=7.5):
    sc = station.model_copy(update={"file": station.file.model_copy(update={"start_time_of_day_h": start_h})})
    eng = Engine(sc)
    for _ in eng.run(30):
        pass
    return eng


def _until(eng, cond, max_ticks=600):
    log = []
    for res in eng.run(max_ticks):
        log += res.tick.monitor_events
        if cond(res):
            return res, log
    raise AssertionError("never happened; events: " + "; ".join(e.message for e in log))


def _hab(res, key="smoke_mg_m3", module="hab"):
    return getattr(res.tick.modules[module], key)


def test_fire_makes_heat_smoke_co_and_burns_oxygen(station):
    eng = _bare(station)
    o2_0 = eng.world.modules["hab"].partial_kpa("o2")
    t_0 = eng.world.modules["hab"].temp_c
    eng.inject(_fire())
    for res in eng.run(120):
        pass
    assert _hab(res) > 1.0 and _hab(res, "co_ppm") > 1.0  # smoke mg/m3, CO ppm
    assert eng.world.modules["hab"].partial_kpa("o2") < o2_0
    assert eng.world.modules["hab"].temp_c > t_0
    assert any(r["anomaly_type"] == "fire" for r in res.rows)


def test_without_airflow_the_fire_is_starved(station):
    on, off = _bare(station), _bare(station)
    off.world.set_fans("hab", False)
    for eng in (on, off):
        eng.inject(_fire())
    for _ in range(100):
        r_on, r_off = next(iter(on.run(1))), next(iter(off.run(1)))
    assert _hab(r_off, "co_ppm") < 0.3 * _hab(r_on, "co_ppm")


def test_fire_dies_with_its_fuel_and_in_thin_air(station):
    eng = _bare(station)
    eng.inject(_fire(fuel_kj=5.0))  # 5 s of a 1 kW fire
    for _ in eng.run(60):
        pass
    peak = eng.world.modules["hab"].smoke_mg
    for _ in eng.run(60):
        pass
    assert eng.world.modules["hab"].smoke_mg < peak  # no more smoke is made: it only decays

    eng = _bare(station)
    eng.world.modules["hab"].n["o2"] *= 0.4  # pO2 ~ 8 kPa, under the flammability limit
    eng.inject(_fire())
    for _ in eng.run(60):
        pass
    assert eng.world.modules["hab"].smoke_mg == 0.0


def test_smoke_spreads_through_open_hatches_not_closed_ones(station):
    eng = _bare(station)
    eng.inject(_fire())
    for res in eng.run(240):
        pass
    assert _hab(res, module="lab") > 0.05  # hab-lab hatch is open
    assert _hab(res, module="lifeboat") == 0.0  # hab-lifeboat hatch is sealed


def test_monitor_detects_the_fire_and_runs_the_iss_safing(station):
    eng = _engine(station)
    eng.inject(_fire())
    res, log = _until(eng, lambda r: any(e.kind == "action_executed" and "ventilation" in e.message
                                         for e in r.tick.monitor_events))
    msgs = [e.message for e in log]
    assert any(e.kind == "emergency_confirmed" and "fire" in e.message for e in log)
    assert any("actuator o2gen_hab -> off" in m for m in msgs) and any("actuator press_hab -> off" in m for m in msgs)
    next(iter(eng.run(2)))
    assert eng.world.modules["hab"].fans_on is False
    assert any(pa.action.kind == "extinguish" for pa in res.tick.pending_actions)


def test_extinguisher_puts_the_fire_out_and_everything_is_restored(station):
    eng = _engine(station)
    eng.inject(_fire())
    res, _ = _until(eng, lambda r: any(pa.action.kind == "extinguish" for pa in r.tick.pending_actions))
    pa = next(p for p in res.tick.pending_actions if p.action.kind == "extinguish")
    eng.approve_action(pa.action.id, by="bot")  # any crew member can discharge it
    _until(eng, lambda r: "debug_fire" not in r.tick.active_faults, 10)
    res, log = _until(eng, lambda r: any(e.kind == "emergency_cleared" for e in r.tick.monitor_events), 1500)
    assert _hab(res) < 0.5  # all clear only once the air is clean again, like the ISS analyser
    for _ in eng.run(2):  # commands take effect one tick later
        pass
    assert eng.world.modules["hab"].fans_on  # the ventilation was switched back on at the all-clear
    restored = {e.message.split()[1] for e in log if e.kind == "action_executed" and "-> auto" in e.message}
    assert {"o2gen_hab", "press_hab"} <= restored


def test_unanswered_extinguisher_step_goes_ahead_on_timeout(station):
    eng = _engine(station)
    eng.inject(_fire())
    _, log = _until(eng, lambda r: any(e.kind == "action_expired_executed" for e in r.tick.monitor_events), 300)
    assert any("extinguisher" in e.message for e in log if e.kind == "action_expired_executed")


def test_fire_in_the_hub_sends_the_crew_into_the_escape_vehicle(station):
    eng = _engine(station)
    eng.inject(_fire())
    _until(eng, lambda r: {s.module_id for s in r.tick.npcs.values()} == {"lifeboat"})
    assert eng.crew_response is not None


def test_fire_scenario_runs_and_labels_the_lab(station):
    eng = Engine(load_scenario(SCENARIOS / "events" / "fire.yaml"))
    rows = [r for res in eng.run(3600 + 600) for r in res.rows if r["entity_id"] == "lab"]
    assert {r["anomaly_type"] for r in rows if r["timestamp"] > 3700} == {"fire"}
    assert {r["anomaly_type"] for r in rows if r["timestamp"] < 3500} == {"nominal"}
