"""Medical crew procedures (scenarios/monitor_placeholder.yaml): every cause the monitor can name has its own procedure, the happy
path ends ``done``, a treatment that does not work ends ``escalated``. The runner is driven with synthetic emergencies and wearable
readings: no engine and no ML model are involved, so the result does not depend on the trained models."""

import pytest
import yaml

from ares3.core.procedures import ProcedureRunner
from ares3.schemas.monitor import Procedure
from ares3.sdk.types import Emergency, Observation
from conftest import SCENARIOS

ROOT = SCENARIOS.parent

# cause -> procedure (the cause is matched exactly; None = the generic one)
EXPECTED = {
    "hypoxia": "med_hypoxia",
    "co_poisoning": "med_co",
    "fever_or_heat": "med_heat",
    "fever": "med_fever",
    "dehydration": "med_dehydration",
    "atrial_fibrillation_suspected": "med_afib",
    "svt_suspected": "med_svt",
    "bradycardia": "med_bradycardia",
    "acute_stress": "med_stress",
    "space_motion_sickness": "med_motion_sickness",
    "respiratory_infection": "med_respiratory",
    "abnormal_exertion": "med_exertion",
    "crew_baseline": "med_crew_baseline",
    "hypoxia_crew": "med_hypoxia_crew",
    "co_exposure_crew": "med_co_crew",
    "hypercapnia_crew": "med_hypercapnia_crew",
    None: "med_generic",
}
HEALTHY = {"hr": 70.0, "spo2": 97.0, "core_temp_c": 36.8, "resp_rate": 14.0, "cohb_pct": 1.0}
BAD = {"hr": 150.0, "spo2": 80.0, "core_temp_c": 40.0, "resp_rate": 30.0, "cohb_pct": 30.0}
BAD_FOR = {"med_bradycardia": {"hr": 30.0}}  # the one procedure whose check is a minimum


def _procedures(path):
    return [p for p in _load(path) if p.emergency == "medical"]


def _load(path):
    return [Procedure(**p) for p in yaml.safe_load(path.read_text(encoding="utf-8"))["procedures"]]


def _runner(path):
    return ProcedureRunner(_load(path), responder=None, follow=False)


def _em(cause):
    return Emergency(id="e1", kind="medical", module_id="NOD1", severity="warning", state="confirmed", t_open_s=0.0,
                     t_update_s=0.0, subject="ASTRO_01", cause=cause)


def _obs(t, values):
    return [Observation(tick=int(t), t_s=t, sensor_id=f"w_{m}", entity_id="ASTRO_01", metric=m, value=v, value_true=v)
            for m, v in values.items()]


def _drive(runner, cause, values, max_s=8000.0):
    """Walk the procedure of ``cause``: the crew closes every instruction / question (the question's auto answer), the checks read
    ``values``. Returns the final status and the log of (t, kind)."""
    em, t, log = _em(cause), 0.0, []
    while t < max_s:
        states, events, _ = runner.step(t, [em], _obs(t, values), {}, {})
        log += [(e.t_s, e.kind, e.message) for e in events]
        run = states[0]
        if run.status != "running":
            return run, log
        spec = next(s for s in runner._runs[run.id].proc.steps if s.id == run.current)
        if spec.do in ("instruction", "question"):
            runner.ack(run.id, run.current, by="test", answer=spec.auto_answer if spec.do == "question" else None)
        t += 10.0
    raise AssertionError(f"{cause}: never finished")


@pytest.mark.parametrize("path", [SCENARIOS / "monitor_placeholder.yaml", ROOT / "scenarios" / "station" / "monitor.yaml"])
def test_every_medical_cause_gets_its_own_procedure(path):
    procs = _load(path)
    assert {p.id for p in procs} >= set(EXPECTED.values())
    runner = ProcedureRunner(procs, responder=None)
    for cause, pid in EXPECTED.items():
        assert runner._choose(_em(cause)).id == pid, cause


def test_every_label_of_the_medical_family_has_a_procedure():
    classes = yaml.safe_load((ROOT / "tools" / "ml" / "classes.yaml").read_text(encoding="utf-8"))
    medical = [k for k, v in classes.items() if v.get("family") == "medical"]
    assert medical
    assert [k for k in medical if k not in EXPECTED] == []


@pytest.mark.parametrize("cause", [c for c in EXPECTED if c is not None])
def test_the_happy_path_ends_done_and_the_failing_one_escalates(cause):
    runner = ProcedureRunner(_load(ROOT / "scenarios" / "station" / "monitor.yaml"), responder=None, follow=False)
    pid = EXPECTED[cause]
    run, log = _drive(runner, cause, HEALTHY)
    assert run.procedure_id == pid and run.status == "done", (cause, [(s.id, s.status) for s in run.steps])
    assert "procedure_started" in [k for _, k, _ in log]

    runner = ProcedureRunner(_load(ROOT / "scenarios" / "station" / "monitor.yaml"), responder=None, follow=False)
    run, log = _drive(runner, cause, {**BAD, **BAD_FOR.get(pid, {})})
    if pid == "med_motion_sickness":  # no check: the instructions are all there is
        assert run.status == "done"
    else:
        assert run.status == "escalated", (cause, [(s.id, s.status) for s in run.steps])
        assert "procedure_escalated" in [k for _, k, _ in log]


def test_no_step_is_left_hanging_and_texts_have_no_dose():
    for p in _procedures(ROOT / "scenarios" / "station" / "monitor.yaml"):
        assert p.steps[-1].do in ("escalate", "instruction", "check"), p.id
        for s in p.steps:
            assert not any(u in s.text.lower().split() for u in ("mg", "ml", "mcg", "units")), (p.id, s.id)
            if s.do == "instruction":
                assert s.role in ("medical", "systems", "incident_commander", "sensing", None), (p.id, s.id)


def test_a_procedure_run_is_deterministic():
    def one():
        runner = ProcedureRunner(_load(ROOT / "scenarios" / "station" / "monitor.yaml"), responder=None, follow=False)
        return _drive(runner, "hypercapnia_crew", BAD)[1]

    assert one() == one() != []
