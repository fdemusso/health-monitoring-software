"""Crew procedures: steps of every kind, branching, who closes them, and the outcome in the tick."""

import pytest

from ares3.core.engine import Engine
from ares3.schemas.monitor import ActionSpec, Procedure, ProcedureStep


def _engine(station, steps, *, follow=True, cause=None, kind="medical"):
    proc = Procedure(id="p", emergency=kind, cause=cause, title="Test for {subject} in {module}", steps=steps)
    mon = station.monitor.model_copy(update={"procedures": [proc], "crew_response": station.monitor.crew_response.model_copy(
        update={"npc_follows_procedures": follow})})
    eng = Engine(station.model_copy(update={"monitor": mon}))
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


def _proc(res):
    return res.tick.procedures[0] if res.tick.procedures else None


def _status(res, step):
    return next(s for s in _proc(res).steps if s.id == step).status


def _step(id, do, **kw):
    return ProcedureStep(id=id, do=do, **kw)


def test_instruction_is_closed_by_an_npc_of_the_role_and_the_procedure_ends(station):
    eng = _engine(station, [_step("s1", "instruction", text="Reach {subject}", role="medical", duration_s=5),
                            _step("s2", "instruction", text="Check airway", duration_s=5)])
    eng.declare_emergency("medical", "hab", by="cmd")
    res, log = _until(eng, lambda r: _proc(r) is not None and _proc(r).status == "done")
    p = _proc(res)
    assert [s.status for s in p.steps] == ["done", "done"] and p.title == "Test for the crew in hab"
    first = next(s for s in p.steps if s.id == "s1")
    assert first.by is not None and first.text == "Reach the crew"
    assert [e.kind for e in log if e.kind.startswith(("procedure", "step"))] == [
        "procedure_started", "step_done", "step_done", "procedure_done"]


def test_without_npcs_following_the_ui_closes_the_steps_and_anyone_can(station):
    eng = _engine(station, [_step("s1", "instruction", text="Do it", duration_s=0)], follow=False)
    eng.declare_emergency("medical", "hab", by="cmd")
    res, _ = _until(eng, lambda r: _proc(r) is not None)
    for _ in eng.run(20):  # nobody closes it (a declared alarm lasts 60 s)
        pass
    pid = _proc(eng.step()).id
    with pytest.raises(KeyError):
        eng.ack_step(pid, "nope", by="ui")
    eng.ack_step(pid, "s1", by="ui-user")
    res, _ = _until(eng, lambda r: _proc(r).status == "done", 5)
    assert next(s for s in _proc(res).steps if s.id == "s1").by == "ui-user"


def test_a_check_passes_on_sensed_values_and_fails_after_its_time_with_a_branch(station):
    steps = [_step("c1", "check", metric="P", min=50.0, on_pass="done"),  # hab_P is sensed in kPa
             _step("never", "instruction", text="not reached")]
    eng = _engine(station, steps)
    eng.declare_emergency("medical", "hab", by="cmd")
    res, _ = _until(eng, lambda r: _proc(r) is not None and _proc(r).status == "done")
    assert _status(res, "c1") == "done" and _status(res, "never") == "skipped"

    steps = [_step("c1", "check", metric="P", min=1e9, within_s=20, on_fail="e"),
             _step("skip", "instruction", text="skipped"), _step("e", "escalate", text="Call the flight surgeon")]
    eng = _engine(station, steps)
    eng.declare_emergency("medical", "hab", by="cmd")
    res, log = _until(eng, lambda r: _proc(r) is not None and _proc(r).status == "escalated")
    assert _status(res, "c1") == "failed" and _status(res, "skip") == "skipped" and _status(res, "e") == "done"
    assert any(e.kind == "step_failed" for e in log) and any(e.kind == "procedure_escalated" for e in log)


def test_a_question_branches_on_the_answer(station):
    steps = [_step("q", "question", text="Smoke?", duration_s=1, auto_answer="yes", on_pass="y", on_fail="n"),
             _step("n", "instruction", text="no smoke", on_pass="done"), _step("y", "instruction", text="smoke", duration_s=1)]
    eng = _engine(station, steps)
    eng.declare_emergency("medical", "hab", by="cmd")
    res, _ = _until(eng, lambda r: _proc(r) is not None and _proc(r).status == "done")
    assert next(s for s in _proc(res).steps if s.id == "q").answer == "yes"
    assert _status(res, "y") == "done" and _status(res, "n") == "skipped"


def test_an_action_step_goes_through_the_responder_and_waits_for_the_crew(station):
    act = ActionSpec(do="announce", target="crew", command="procedure_test", level="confirm", confirm_timeout_s=300,
                     on_timeout="discard", reason="test")
    eng = _engine(station, [_step("a", "action", action=act), _step("after", "instruction", text="x", duration_s=1)])
    eng.declare_emergency("medical", "hab", by="cmd")
    res, _ = _until(eng, lambda r: any(p.action.command == "procedure_test" for p in r.tick.pending_actions))
    assert _status(res, "a") == "active"  # waiting for a human
    aid = next(p.action.id for p in res.tick.pending_actions if p.action.command == "procedure_test")
    eng.approve_action(aid, by="eng")
    res, _ = _until(eng, lambda r: _proc(r).status == "done")
    assert _status(res, "a") == "done"

    eng = _engine(station, [_step("a", "action", action=act, on_fail="done")])
    eng.declare_emergency("medical", "hab", by="cmd")
    res, _ = _until(eng, lambda r: any(p.action.command == "procedure_test" for p in r.tick.pending_actions))
    eng.reject_action(next(p.action.id for p in res.tick.pending_actions), by="eng")
    res, _ = _until(eng, lambda r: _proc(r).status == "done")
    assert _status(res, "a") == "failed"  # rejected: the procedure took its failure branch


def test_the_procedure_that_names_the_cause_wins_and_the_run_is_deterministic(station):
    generic = Procedure(id="generic", emergency="medical", title="generic", steps=[_step("s", "instruction", text="g", duration_s=1)])
    hypoxia = Procedure(id="hypoxia", emergency="medical", cause="hypoxia", title="hypoxia",
                        steps=[_step("s", "instruction", text="h", duration_s=1)])
    from ares3.core.procedures import ProcedureRunner
    from ares3.sdk.types import Emergency

    runner = ProcedureRunner([generic, hypoxia], responder=None)
    em = Emergency(id="e", kind="medical", module_id="hab", severity="critical", state="confirmed", t_open_s=0, t_update_s=0,
                   cause="hypoxia")
    assert runner._choose(em).id == "hypoxia"
    assert runner._choose(em.model_copy(update={"cause": "fever"})).id == "generic"

    def log():
        eng = _engine(station, [_step("s", "instruction", text="x", duration_s=3)])
        eng.declare_emergency("medical", "hab", by="cmd")
        return [(e.t_s, e.kind, e.by) for r in eng.run(60) for e in r.tick.monitor_events]
    assert log() == log() != []
