from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec


def _leak(module, fid="debug_leak", rate=0.002):
    return FaultSpec(id=fid, type="leak", targets=[module], start_s=0, params={"rate_per_s": rate},
                     anomaly_type="slow_leak", priority=5)


def _hatch(eng, a, b):
    return next(h for h in eng.world.hatches if {h.a, h.b} == {a, b})


def _run_until(eng, cond, max_ticks=300):
    """Step until ``cond(result)`` is true; returns every event seen so far."""
    log = []
    for res in eng.run(max_ticks):
        log += res.tick.monitor_events
        if cond(res):
            return res, log
    raise AssertionError("condition never met; events: " + "; ".join(e.message for e in log))


def _eng_with_leak(scenario, module, start_h=None):
    if start_h is not None:
        scenario = scenario.model_copy(update={"file": scenario.file.model_copy(update={"start_time_of_day_h": start_h})})
    eng = Engine(scenario)
    for _ in eng.run(60):
        pass
    eng.inject(_leak(module))
    return eng


def test_auto_safing_runs_on_confirmation_and_is_restored_on_clear(station):
    eng = _eng_with_leak(station, "hab")
    _, log = _run_until(eng, lambda r: any(e.kind == "action_executed" for e in r.tick.monitor_events))
    assert any("actuator press_hab -> off" in e.message for e in log)
    assert any("actuator o2gen_hab -> off" in e.message for e in log)
    # forced off means it really stays off: the regulator no longer makes up gas
    eng.stop_event("debug_leak")
    _, log = _run_until(eng, lambda r: any(e.kind == "emergency_cleared" for e in r.tick.monitor_events), 600)
    restored = [e for e in log if e.kind == "action_executed" and "-> auto" in e.message]
    assert {e.message.split()[1] for e in restored} == {"press_hab", "o2gen_hab"}


def test_confirm_steps_are_proposed_then_run_on_timeout_if_life_saving(station):
    eng = _eng_with_leak(station, "lab")
    res, _ = _run_until(eng, lambda r: len(r.tick.pending_actions) == 1)
    pa = res.tick.pending_actions[0]
    assert pa.action.target == "hab:lab" and pa.on_timeout == "execute" and pa.deadline_s > pa.t_proposed_s
    assert _hatch(eng, "hab", "lab").open
    _, log = _run_until(eng, lambda r: not r.tick.pending_actions and not _hatch(eng, "hab", "lab").open)
    assert {e.kind for e in log} >= {"action_expired_executed"}


def test_anyone_can_approve(station):
    eng = _eng_with_leak(station, "lab")
    # approved once the crew has left the lab: the ISS rule would block the hatch while anyone is still inside
    res, _ = _run_until(eng, lambda r: len(r.tick.pending_actions) == 1
                        and all(n.module_id != "lab" for n in r.tick.npcs.values()))
    eng.approve_action(res.tick.pending_actions[0].action.id, by="bot")  # not the commander: the monitor is open to all
    _, log = _run_until(eng, lambda r: not r.tick.pending_actions)
    approved = [e for e in log if e.kind == "action_approved"]
    assert [(e.by, e.action_id) for e in approved] == [("bot", res.tick.pending_actions[0].action.id)]
    next(iter(eng.run(2)))
    assert not _hatch(eng, "hab", "lab").open


def test_anyone_can_reject_and_the_step_does_not_come_back(station):
    eng = _eng_with_leak(station, "lab")
    res, _ = _run_until(eng, lambda r: len(r.tick.pending_actions) == 1)
    eng.reject_action(res.tick.pending_actions[0].action.id, by="med")
    _, log = _run_until(eng, lambda r: not r.tick.pending_actions)
    assert [e.by for e in log if e.kind == "action_rejected"] == ["med"]
    for _ in eng.run(60):  # the rejected step must not come back on its deadline
        pass
    assert _hatch(eng, "hab", "lab").open


def test_hatch_is_never_closed_on_someone_cut_off_from_the_escape_vehicle(station):
    # the crew response is off here, so `eng` stays in the lab (07:00-09:00) and the rule is tested on its own
    isolated = station.model_copy(update={"monitor": station.monitor.model_copy(update={"crew_response": None})})
    eng = _eng_with_leak(isolated, "lab", start_h=7.5)
    assert "eng" in eng.world.modules["lab"].occupants
    _, log = _run_until(eng, lambda r: any(e.kind == "action_blocked" and "cut" in e.message
                                           for e in r.tick.monitor_events))
    blocked = [e for e in log if e.kind == "action_blocked" and "cut" in e.message]
    assert "eng" in blocked[0].message
    assert _hatch(eng, "hab", "lab").open


def test_manual_alarm_confirms_at_once_and_runs_the_playbook(station):
    eng = Engine(station)
    for _ in eng.run(10):
        pass
    eid = eng.declare_emergency("depressurization", "hab", by="cmd")
    _, log = _run_until(eng, lambda r: any(e.kind == "action_executed" for e in r.tick.monitor_events), 5)
    assert [e.kind for e in log][:2] == ["emergency_opened", "emergency_confirmed"]
    assert log[0].by == "cmd" and log[0].emergency_id == eid


def test_hatch_closes_once_the_crew_has_left_the_module(station):
    eng = _eng_with_leak(station, "lab", start_h=7.5)  # with the crew response on, eng and med leave the lab first
    _, log = _run_until(eng, lambda r: not _hatch(eng, "hab", "lab").open)
    assert not any(e.kind == "action_blocked" and "cut" in e.message for e in log)
