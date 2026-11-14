from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec


def _leak(rate=0.002):
    return FaultSpec(id="debug_leak", type="leak", targets=["hab"], start_s=0, params={"rate_per_s": rate},
                     anomaly_type="slow_leak", priority=5)


def test_nominal_day_opens_no_emergency(station):
    results = list(Engine(station).run(14 * 3600))  # 06:00-20:00: meals, work, aerobic + resistive exercise
    assert not [e for r in results for e in r.tick.monitor_events]
    assert not any(r.tick.emergencies for r in results)


def test_injected_leak_is_detected_confirmed_with_tres_and_cleared(station):
    eng = Engine(station)
    for _ in eng.run(120):
        pass
    t_inject = eng.clock.t_s
    eng.inject(_leak())
    log, states, tres, seen = [], {}, None, set()
    for res in eng.run(40):
        log += res.tick.monitor_events
        for e in res.tick.emergencies:
            seen.add((e.kind, e.module_id))
            states[e.state] = states.get(e.state, res.tick.t_sim_s)
            if e.state == "confirmed" and e.tres_s is not None:
                tres = e.tres_s
    assert [e.kind for e in log][:2] == ["emergency_opened", "emergency_confirmed"]
    assert states["suspected"] - t_inject < 20  # detected within seconds of the leak, from sensed values only
    assert tres is not None and 0 < tres < 600  # time left to 490 mmHg shrinks as the leak goes on
    assert seen == {("depressurization", "hab")}  # only the leaking module, only that kind

    eng.stop_event("debug_leak")
    cleared = False
    for res in eng.run(600):
        cleared = cleared or any(e.state == "cleared" for e in res.tick.emergencies)
    assert cleared


def test_same_seed_gives_the_same_monitor_log(station):
    def run():
        eng = Engine(station)
        for _ in eng.run(30):
            pass
        eng.inject(_leak())
        return [(e.t_s, e.kind, e.emergency_id) for r in eng.run(60) for e in r.tick.monitor_events]
    assert run() == run() != []
