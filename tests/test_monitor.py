from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec


def _leak(rate=0.002):
    return FaultSpec(id="debug_leak", type="leak", targets=["hab"], start_s=0, params={"rate_per_s": rate},
                     anomaly_type="slow_leak", priority=5)


def test_nominal_day_opens_no_emergency(station):
    results = list(Engine(station).run(14 * 3600))  # 06:00-20:00: meals, work, aerobic + resistive exercise
    assert not [e for r in results for e in r.tick.monitor_events]
    assert not any(r.tick.emergencies for r in results)
    assert {r.tick.monitor_mode for r in results} == {"passive"}  # and the system never leaves passive monitoring


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
    assert [e.kind for e in log if e.kind != "mode_changed"][:2] == ["emergency_opened", "emergency_confirmed"]
    assert states["suspected"] - t_inject < 20  # detected within seconds of the leak, from sensed values only
    assert tres is not None and 0 < tres < 600  # time left to 490 mmHg shrinks as the leak goes on
    assert seen == {("depressurization", "hab")}  # only the leaking module, only that kind

    eng.stop_event("debug_leak")
    cleared = False
    for res in eng.run(900):  # the 300 s rate window still holds the leak: it takes about 10 minutes to clear
        cleared = cleared or any(e.state == "cleared" and e.module_id == "hab" for e in res.tick.emergencies)
    assert cleared


def test_same_seed_gives_the_same_monitor_log(station):
    def run():
        eng = Engine(station)
        for _ in eng.run(30):
            pass
        eng.inject(_leak())
        return [(e.t_s, e.kind, e.emergency_id) for r in eng.run(60) for e in r.tick.monitor_events]
    assert run() == run() != []


def test_leak_goes_passive_alert_reaction_passive(station):
    eng = Engine(station)
    for _ in eng.run(120):
        pass
    eng.inject(_leak())
    modes = []
    for res in eng.run(40):
        modes.append(res.tick.monitor_mode)
        assert all(e.alert_class == "emergency" for e in res.tick.emergencies)  # a rapid leak is critical
    assert modes[0] == "passive" and modes[-1] == "reaction"  # the first ticks are before the detection
    assert modes.index("alert") < modes.index("reaction")  # suspected first, confirmed (playbook running) after


def test_mode_falls_back_to_passive_only_after_the_hold(station):
    eng = Engine(station)
    for _ in eng.run(30):
        pass
    eng.declare_emergency("fire", "hab", by="cmd")  # confirmed at once; nothing backs it, so it clears after clear_s
    modes = [r.tick.monitor_mode for r in eng.run(300)]
    cfg = station.monitor.classifier
    assert modes[0] == "reaction" and modes[-1] == "passive"
    held = modes.index("passive")
    assert held >= cfg.clear_s + cfg.mode_hold_s - 2  # the emergency clears after clear_s, the mode a hold later


def test_mode_changes_are_logged_in_order(station):
    eng = Engine(station)
    for _ in eng.run(30):
        pass
    eng.inject(_leak())
    log = [e.message for r in eng.run(60) for e in r.tick.monitor_events if e.kind == "mode_changed"]
    assert log == ["monitoring: passive -> alert", "monitoring: alert -> reaction"]


def test_alert_class_lookup_prefers_the_most_specific_key():
    from ares3.schemas.monitor import ClassifierConfig
    c = ClassifierConfig(classes={"medical": "caution", "medical:warning:fever": "advisory", "fire": "emergency"})
    assert c.alert_class("medical", "warning", "fever") == "advisory"
    assert c.alert_class("medical", "warning", "hypoxia") == "caution"
    assert c.alert_class("depressurization", "critical") == "emergency"  # default by severity
    assert c.alert_class("depressurization", "warning") == "warning"
