"""F4: the ``power`` action (cut the supply of a module) and ``sensor substitute`` (read a redundant sensor)."""

from ares3.core.engine import Engine
from ares3.core.responder import Responder
from ares3.schemas.faults import FaultSpec
from ares3.schemas.monitor import ActionSpec, Playbook
from ares3.sdk.types import Action, Emergency


def _fire(module="hab", **params):
    return FaultSpec(id="debug_fire", type="fire", targets=[module], start_s=0, params={"heat_w": 1000, **params},
                     anomaly_type="fire", priority=10)


def _engine(station, start_h=7.5):
    sc = station.model_copy(update={"file": station.file.model_copy(update={"start_time_of_day_h": start_h})})
    eng = Engine(sc)
    for _ in eng.run(30):
        pass
    return eng


def _log(eng, ticks, until=None):
    log, last = [], None
    for res in eng.run(ticks):
        log += res.tick.monitor_events
        last = res
        if until and until(res):
            break
    return last, log


def test_fire_playbook_cuts_the_power_and_the_fire_is_weaker_than_an_electrical_free_one(station):
    smoke = {}
    for electrical in (True, False):
        eng = _engine(station)
        eng.inject(_fire(extinguishable=False, electrical=electrical))
        res, log = _log(eng, 150)
        smoke[electrical] = res.tick.modules["hab"].smoke_mg_m3
        if electrical:
            assert any("power hab -> off" in e.message and e.kind == "action_executed" for e in log)
            assert res.tick.powered_off == ("hab",)
    assert smoke[True] < smoke[False]  # no supply, no electrical ignition source: it burns at ~20 %


def test_a_module_without_power_stops_its_actuators_and_fans(station):
    eng = _engine(station)
    scrubber = next(a for a in eng.actuators if a.id == "scrubber_hab")
    calls, step = [], scrubber.step
    scrubber.step = lambda *a, **k: calls.append(1) or step(*a, **k)
    eng.step()
    assert len(calls) == 1 and eng.world.modules["hab"].fans_on
    eng._queued_power.append(("hab", False))
    assert eng.step().tick.powered_off == ("hab",)
    assert len(calls) == 1 and not eng.world.modules["hab"].fans_on  # the scrubber is not even asked
    eng._queued_power.append(("hab", True))
    assert eng.step().tick.powered_off == ()
    assert len(calls) == 2


def test_the_power_of_the_return_vehicle_and_of_the_suit_volume_is_never_cut(station):
    eng = _engine(station)
    for module in ("lifeboat", "eva"):
        a = Action(id="x", emergency_id="e", kind="power", target=module, command="off")
        assert "own power supply" in eng._guard(a)
    assert eng._guard(Action(id="x", emergency_id="e", kind="power", target="hab", command="off")) is None


def test_the_restoration_of_the_power_is_proposed_when_the_fire_is_out_and_done_if_nobody_answers(station):
    eng = _engine(station)
    eng.inject(_fire(fuel_kj=1.0e4))  # burns out quickly
    res, _ = _log(eng, 1500, until=lambda r: any(e.kind == "emergency_cleared" for e in r.tick.monitor_events))
    proposals = [p for p in res.tick.pending_actions if p.action.kind == "power"]
    assert proposals and proposals[0].action.command == "on" and proposals[0].on_timeout == "execute"
    assert res.tick.powered_off == ("hab",)  # still dark while the crew decides
    eng.approve_action(proposals[0].action.id, by="eng")
    last, _ = _log(eng, 5)
    assert last.tick.powered_off == ()


def test_a_module_left_dark_gets_its_power_back_when_nobody_answers(station):
    eng = _engine(station)
    eng.inject(_fire(fuel_kj=1.0e4))
    res, _ = _log(eng, 1500, until=lambda r: any(e.kind == "emergency_cleared" for e in r.tick.monitor_events))
    assert res.tick.powered_off == ("hab",)
    last, _ = _log(eng, 700)  # the proposal lasts 600 s
    assert last.tick.powered_off == ()


def _responder(substitutes):
    pb = [Playbook(emergency="sensor_fault", actions=[
        ActionSpec(do="sensor", target="{subject}", command="substitute", value_id="auto", reason="use the twin")])]
    return Responder(pb, set(), set(), lambda *a, **k: None, {"m"}, None, {"s_a", "s_b", "s_c"}, substitutes)


def _em(state, subject="s_a"):
    return Emergency(id="sensor_fault:s_a:1", kind="sensor_fault", module_id="m", severity="warning", state=state,
                     t_open_s=0.0, t_update_s=0.0, subject=subject)


def test_a_faulty_sensor_is_replaced_by_its_redundant_one_and_back_when_the_emergency_clears():
    r = _responder({"s_a": ["s_b"]})
    run, _ = r.step(1.0, (_em("confirmed"),))
    assert [(a.kind, a.target, a.command, a.value_id) for a in run] == [("sensor", "s_a", "substitute", "s_b")]
    assert r.step(2.0, (_em("confirmed"),))[0] == []  # once
    run, _ = r.step(3.0, (_em("cleared"),))
    assert [(a.target, a.command) for a in run] == [("s_a", "restore")]


def test_no_substitute_when_there_is_none_or_the_culprit_is_unknown():
    r = _responder({})
    run, ev = r.step(1.0, (_em("confirmed"),))
    assert run == [] and any(e.kind == "action_blocked" and "no redundant sensor" in e.message for e in ev)
    r = _responder({"s_a": ["s_b"]})
    run, ev = r.step(1.0, (_em("confirmed", subject="s_a~s_b"),))  # a pair: which of the two? (stage B will say)
    assert run == [] and any(e.kind == "action_blocked" for e in ev)


def test_the_engine_reads_the_substitute_in_place_of_the_faulty_sensor(station):
    eng = _engine(station)
    for _ in range(5):
        eng.step()
    ctx = eng._ctx(eng._last_tick, {})
    own, other = ctx.reading("hab_T"), ctx.reading("lab_T")
    assert own != other
    eng._queued_sub.append(("hab_T", "lab_T"))
    eng.step()
    assert eng._ctx(eng._last_tick, {}).reading("hab_T") == eng._readings["lab_T"].value
    eng._queued_sub.append(("hab_T", None))
    eng.step()
    assert eng._ctx(eng._last_tick, {}).reading("hab_T") == eng._readings["hab_T"].value
