from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec


def _leak(module, rate=0.002):
    return FaultSpec(id="debug_leak", type="leak", targets=[module], start_s=0, params={"rate_per_s": rate},
                     anomaly_type="slow_leak", priority=5)


def _engine(scenario, start_h=6.0, **response):
    sf = scenario.file.model_copy(update={"start_time_of_day_h": start_h})
    sc = scenario.model_copy(update={"file": sf})
    if response:
        cr = sc.monitor.crew_response.model_copy(update=response)
        sc = sc.model_copy(update={"monitor": sc.monitor.model_copy(update={"crew_response": cr})})
    eng = Engine(sc)
    for _ in eng.run(30):
        pass
    return eng


def _until(eng, cond, max_ticks=400):
    log = []
    for res in eng.run(max_ticks):
        log += res.tick.monitor_events
        if cond(res):
            return res, log
    raise AssertionError("never happened; events: " + "; ".join(e.message for e in log))


def _where(res):
    return {n: s.module_id for n, s in res.tick.npcs.items()}


def test_crew_leaves_the_leaking_module_and_gathers_at_the_safe_haven(station):
    eng = _engine(station, start_h=7.5)  # eng and med work in the lab 07:00-09:00
    assert set(eng.world.modules["lab"].occupants) == {"eng", "med"}
    eng.inject(_leak("lab"))
    res, log = _until(eng, lambda r: any(e.kind == "crew_gathered" for e in r.tick.monitor_events))
    assert {m for m in _where(res).values()} == {"hab"}  # lab is hazardous, hab is next to the escape vehicle
    assert [e.kind for e in log if e.kind.startswith("crew_")][:2] == ["crew_alerted", "crew_gathered"]
    phases = {n: s.response_phase for n, s in res.tick.npcs.items()}
    assert set(phases.values()) <= {"work", "gather", "warn"}
    roles = {n: s.role for n, s in res.tick.npcs.items()}
    assert roles["cmd"] == "incident_commander" and roles["eng"] == "systems" and roles["med"] == "medical"


def test_leak_in_the_hub_sends_the_crew_into_the_escape_vehicle_and_opens_its_hatch(station):
    eng = _engine(station)
    eng.inject(_leak("hab"))
    _until(eng, lambda r: set(_where(r).values()) == {"lifeboat"})
    next(iter(eng.run(2)))
    hatch = next(h for h in eng.world.hatches if {h.a, h.b} == {"hab", "lifeboat"})
    assert hatch.open


def test_low_tres_triggers_evacuation(station):
    eng = _engine(station, start_h=7.5)
    eng.inject(_leak("lab", rate=0.02))  # ~2 kPa/s: TRes of a few seconds
    _until(eng, lambda r: any(e.kind == "crew_evacuating" for e in r.tick.monitor_events))
    res, _ = _until(eng, lambda r: set(_where(r).values()) == {"lifeboat"})
    assert {s.response_phase for s in res.tick.npcs.values()} <= {"evacuate", "work"}


def test_schedules_resume_after_the_all_clear(station):
    eng = _engine(station, start_h=7.5, stand_down_delay_s=30.0)
    eng.inject(_leak("lab"))
    _until(eng, lambda r: any(e.kind == "crew_gathered" for e in r.tick.monitor_events))
    eng.stop_event("debug_leak")
    _until(eng, lambda r: any(e.kind == "crew_stood_down" for e in r.tick.monitor_events), 1500)
    res = next(iter(eng.run(3)))
    assert _where(res)["eng"] == "lab"  # back to the 07:00-09:00 lab shift
    assert all(s.response_phase is None and s.role is None for s in res.tick.npcs.values())


def test_no_crew_response_config_means_npcs_ignore_emergencies(station):
    sc = station.model_copy(update={"monitor": station.monitor.model_copy(update={"crew_response": None})})
    eng = _engine(sc, start_h=7.5)
    eng.inject(_leak("lab"))
    res, _ = _until(eng, lambda r: any(e.kind == "emergency_confirmed" for e in r.tick.monitor_events))
    assert _where(res)["eng"] == "lab"


def _hurt(npcs, nid, state, module=None):
    n = npcs[nid]
    update = {"vitals": {**n.vitals, "health_state": state}}
    if module:
        update["module_id"] = module
    npcs[nid] = n.model_copy(update=update)


def _gathered(station):
    eng = _engine(station, start_h=7.5)
    eng.inject(_leak("lab"))
    res, _ = _until(eng, lambda r: any(e.kind == "crew_gathered" for e in r.tick.monitor_events))
    return eng, res


def test_command_passes_down_the_succession_when_the_commander_is_incapacitated(station):
    eng, res = _gathered(station)
    npcs = dict(res.tick.npcs)
    _hurt(npcs, "cmd", 3.0)
    out = eng.crew_response.step(res.tick.t_sim_s + 1, res.tick.model_copy(update={"npcs": npcs}))
    assert out.phases["cmd"] == "incapacitated" and out.orders["cmd"].module == npcs["cmd"].module_id  # frozen in place
    assert out.roles["eng"] == "incident_commander"  # the engineer is next in the succession
    assert "crew_command_passed" in [e.kind for e in out.events]


def test_medic_goes_to_a_casualty_and_the_worst_case_comes_first(station):
    eng, res = _gathered(station)
    npcs = dict(res.tick.npcs)
    _hurt(npcs, "bot", 2.0, module="greenhouse")
    out = eng.crew_response.step(res.tick.t_sim_s + 1, res.tick.model_copy(update={"npcs": npcs}))
    assert out.phases["med"] == "assist" and out.orders["med"].module == "greenhouse"
    assert "crew_assisting" in [e.kind for e in out.events]
    _hurt(npcs, "cmd", 3.0)  # now someone is worse: the medic prefers the unconscious commander (in hab)
    out = eng.crew_response.step(res.tick.t_sim_s + 2, res.tick.model_copy(update={"npcs": npcs}))
    assert out.orders["med"].module == npcs["cmd"].module_id


def test_medic_does_not_enter_a_hazardous_module_for_a_casualty(station):
    eng = _engine(station, start_h=7.5)
    eng.inject(_leak("lab"))
    res, _ = _until(eng, lambda r: any(e.kind == "crew_gathered" for e in r.tick.monitor_events))
    npcs = dict(res.tick.npcs)
    npcs["bot"] = npcs["bot"].model_copy(update={"vitals": {**npcs["bot"].vitals, "health_state": 2.0},
                                                 "module_id": "lab"})  # casualty inside the leaking module
    out = eng.crew_response.step(res.tick.t_sim_s + 1, res.tick.model_copy(update={"npcs": npcs}))
    assert out.phases["med"] == "work" and out.orders["med"].module == "hab"


def test_npc_commander_approves_pending_actions_when_enabled(station):
    eng = _engine(station, start_h=7.5, npc_approves_actions=True, approve_delay_s=3.0)
    eng.inject(_leak("lab"))
    _, log = _until(eng, lambda r: any(e.kind == "action_approved" for e in r.tick.monitor_events))
    approved = [e for e in log if e.kind == "action_approved"]
    assert approved[0].by == "cmd"  # the acting commander, not a UI user


def test_same_seed_same_reactions(station):
    def run():
        eng = _engine(station, start_h=7.5)
        eng.inject(_leak("lab"))
        return [(e.t_s, e.kind, e.message) for r in eng.run(120) for e in r.tick.monitor_events]
    assert run() == run()
