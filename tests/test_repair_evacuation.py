from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec


def _engine(station, start_h=7.5, **response):
    sc = station.model_copy(update={"file": station.file.model_copy(update={"start_time_of_day_h": start_h})})
    if response:
        cr = sc.monitor.crew_response.model_copy(update=response)
        sc = sc.model_copy(update={"monitor": sc.monitor.model_copy(update={"crew_response": cr})})
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


def _fire(module="lab", **params):
    return FaultSpec(id="fire1", type="fire", targets=[module], start_s=0, params={"heat_w": 1000, **params},
                     anomaly_type="fire", priority=10)


def test_a_fire_the_extinguisher_cannot_put_out_sends_everyone_to_the_vehicle(station):
    eng = _engine(station, fire_evacuate_s=30)
    eng.inject(_fire("lab", extinguishable=False))
    res, _ = _until(eng, lambda r: any(e.kind == "action_executed" and e.message.startswith("extinguish")
                                         for e in r.tick.monitor_events), 400)
    assert "fire1" in res.tick.active_faults
    _, _log = _until(eng, lambda r: any(e.kind == "crew_evacuating" and "extinguisher" in e.message
                                         for e in r.tick.monitor_events), 200)
    _until(eng, lambda r: {s.module_id for s in r.tick.npcs.values()} == {"lifeboat"}, 100)


def test_an_extinguished_fire_does_not_trigger_the_evacuation(station):
    eng = _engine(station, fire_evacuate_s=30)
    eng.inject(_fire("lab"))
    _until(eng, lambda r: any(e.kind == "action_executed" and e.message.startswith("extinguish") for e in r.tick.monitor_events), 400)
    res, log = _until(eng, lambda r: "fire1" not in r.tick.active_faults, 10)
    for res in eng.run(120):
        log += res.tick.monitor_events
    assert not any(e.kind == "crew_evacuating" for e in log)


def test_the_crew_comes_back_from_the_vehicle_after_the_all_clear(station):
    eng = _engine(station, fire_evacuate_s=30, stand_down_delay_s=30)
    eng.inject(_fire("lab", extinguishable=False, fuel_kj=60))
    _until(eng, lambda r: {s.module_id for s in r.tick.npcs.values()} == {"lifeboat"}, 600)
    _until(eng, lambda r: any(e.kind == "crew_stood_down" for e in r.tick.monitor_events), 4000)
    res = next(iter(eng.run(5)))
    assert "lifeboat" not in {s.module_id for s in res.tick.npcs.values()}
    assert all(s.response_phase is None for s in res.tick.npcs.values())


def test_the_engineer_repairs_the_scrubber_and_goes_back_to_work(station):
    eng = _engine(station, start_h=7.5, repair_s=120)
    fault = FaultSpec(id="scrub_off", type="actuator_offline", targets=["scrubber_hab"], start_s=0,
                      anomaly_type="scrubber_failure", priority=5)
    eng.inject(fault)
    eng.world.modules["hab"].n["co2"] *= 6  # a quicker route to the ppCO2 alarm than waiting for the crew to breathe it
    res, log = _until(eng, lambda r: any(e.kind == "crew_repairing" for e in r.tick.monitor_events), 4000)
    assert res.tick.npcs["eng"].response_phase == "repair" and res.tick.npcs["eng"].module_id == "hab"
    res, log = _until(eng, lambda r: any(e.kind == "crew_repaired" for e in r.tick.monitor_events), 400)
    assert any("scrub_off" in e.message for e in log if e.kind == "crew_repaired")
    assert "scrub_off" not in next(iter(eng.run(2))).tick.active_faults
