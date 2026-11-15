"""Loss of cabin air, graded like the ISS does it (rapid / fast / slow leak, reserve time, isolation, sealed vehicle)."""

import math

import numpy as np

from ares3.core.constants import MMHG_PER_KPA
from ares3.core.engine import Engine
from ares3.core.responder import Responder
from ares3.plugins.monitor.detectors import PressureDrop, _Window
from ares3.schemas.faults import FaultSpec
from ares3.schemas.monitor import ActionSpec, Playbook
from ares3.sdk import Emergency, Observation


def _leak(module, rate, fid="leak"):
    return FaultSpec(id=fid, type="leak", targets=[module], start_s=0, params={"rate_per_s": rate},
                     anomaly_type="slow_leak", priority=5)


def _obs(i, t, v, module="hab"):
    return Observation(tick=i, t_s=t, sensor_id=f"{module}_P", entity_id=module, metric="P", value=v, value_true=v)


# ---- the detector -------------------------------------------------------------------------------------------------
def test_window_running_sums_match_a_least_squares_fit():
    rng = np.random.default_rng(1)
    win, t, v = _Window(600.0), np.arange(50_000, dtype=float), 100.0 + np.cumsum(rng.normal(0.0, 0.01, 50_000))
    for i in range(50_000):  # crosses the periodic exact recomputation twice
        win.push(float(t[i]), float(v[i]))
        if i in (700, 20_500, 49_999):
            ts, vs = np.array([x for x, _ in win.items]), np.array([y for _, y in win.items])
            assert math.isclose(win.slope(), np.polyfit(ts, vs, 1)[0], rel_tol=1e-6, abs_tol=1e-9)
            assert math.isclose(win.mean(), float(vs.mean()), rel_tol=1e-9)


def test_reserve_time_is_the_iss_formula():
    # leak proportional to the pressure: P = P0 exp(-r t), so TRes = P ln(P / 490 mmHg) / |dP/dt| = ln(P / 490 mmHg) / r
    det = PressureDrop.from_config("d", {"window_s": 60, "min_drop_mmhg_min": 1.0}, np.random.default_rng(0),
                                   metric="P", targets=["hab"])
    det.reset()
    r, tres = 2e-4, None
    for i in range(180):
        p = 101.0 * math.exp(-r * i)
        for s in det.detect(None, [_obs(i, float(i), p)]):
            tres, p_now = s.tres_s, p
    assert tres is not None
    assert math.isclose(tres, math.log(p_now * MMHG_PER_KPA / 490.0) / r, rel_tol=0.05)


def test_the_station_detectors_tell_the_iss_leak_levels_apart(station):
    """Sensed pressure with the probe's noise (0.05 kPa): a flat 2.5 h, then a fall at a constant rate. Which detectors
    fire says which level the crew is told about; a calm cabin fires none."""
    specs = [d for d in station.monitor.detectors if d.kind.endswith("PressureDrop")]
    severity = {d.id: d.severity for d in specs}

    def fired(rate_mmhg_min, fall_s):
        dets = [PressureDrop.from_config(d.id, d.params, np.random.default_rng(0), metric="P", targets=["hab"])
                for d in specs]
        for d in dets:
            d.reset()
        noise, seen, p = np.random.default_rng(5), set(), 101.0
        for i, t in enumerate(range(0, 9000 + fall_s, 2)):
            if t >= 9000:
                p -= rate_mmhg_min / MMHG_PER_KPA / 60.0 * 2.0
            o = [_obs(i, float(t), p + 0.05 * float(noise.standard_normal()))]
            for d in dets:
                if d.detect(None, o):
                    seen.add(d.id)
        return seen

    assert "leak_breach" in fired(12.0, 120)  # a hull breach: caught while the reserve time is still meaningful
    rapid = fired(2.0, 900)  # between the ISS rapid threshold (0.87) and the breach one
    assert "leak_rapid" in rapid and "leak_breach" not in rapid
    fast = fired(0.6, 3600)  # the ISS fast leak band (0.4 - 0.87)
    assert "leak_fast" in fast and not {"leak_breach", "leak_rapid"} & fast
    slow = fired(0.15, 3 * 3600)  # an ISS slow leak (< 0.4)
    assert "leak_slow" in slow and not {"leak_breach", "leak_rapid", "leak_fast"} & slow
    assert fired(0.0, 3600) == set()
    assert {severity[d] for d in rapid} == {"critical", "warning"}  # rapid is critical, the slower ones that follow warnings
    assert {severity[d] for d in slow} == {"warning"}  # a slow leak never raises the group alarm


# ---- the response -------------------------------------------------------------------------------------------------
def test_a_worse_severity_runs_its_own_playbook_on_top():
    warn = Playbook(emergency="depressurization", severity="warning",
                    actions=[ActionSpec(do="announce", target="crew", command="leak_check")])
    crit = Playbook(emergency="depressurization", severity="critical",
                    actions=[ActionSpec(do="actuator", target="press_hab", command="off")])
    resp = Responder([warn, crit], {"press_hab"}, set(), lambda a: None, {"hab"})

    def em(severity):
        return Emergency(id="e1", kind="depressurization", module_id="hab", severity=severity, state="confirmed",
                         t_open_s=0.0, t_update_s=0.0)

    run, _ = resp.step(1.0, (em("warning"),))
    assert [a.kind for a in run] == ["announce"]  # the slow leak keeps the make-up gas on
    assert resp.step(2.0, (em("warning"),))[0] == []  # once
    run, _ = resp.step(3.0, (em("critical"),))
    assert [(a.kind, a.target) for a in run] == [("actuator", "press_hab")]  # it got worse: safing now


def test_a_slow_leak_is_patched_by_the_engineer_without_a_group_alarm(station):
    eng = Engine(station)
    for _ in eng.run(4000):
        pass
    eng.inject(_leak("hab", 2e-5))  # ~0.15 mmHg/min over the station: an ISS slow leak
    log = []
    for res in eng.run(14_000):
        log += res.tick.monitor_events
    kinds = [e.kind for e in log]
    assert "emergency_confirmed" in kinds and "crew_repaired" in kinds and "emergency_cleared" in kinds
    assert not {"crew_alerted", "crew_gathered", "crew_evacuating", "crew_sealed"} & set(kinds)
    assert not any("press_hab -> off" in e.message for e in log)  # gas introduction keeps making up the loss
    assert "leak" not in res.tick.active_faults
    assert res.tick.modules["hab"].pressure_kpa > 98.0 and not any(e.module_id == "hab" for e in res.tick.emergencies)


def test_a_module_bled_towards_vacuum_stays_an_emergency(station):
    """The leak flow is proportional to the pressure, so near vacuum the rate falls under every threshold: only the
    pressure floor keeps the emergency open (and the crew where it is)."""
    eng = Engine(station)
    for _ in eng.run(120):
        pass
    eng.inject(_leak("lab", 3e-4))
    for res in eng.run(14_000):
        pass
    assert res.tick.modules["lab"].pressure_kpa < 20.0
    lab = [e for e in res.tick.emergencies if e.module_id == "lab" and e.kind == "depressurization"]
    assert lab and lab[0].severity == "critical" and lab[0].state == "confirmed"
    assert res.tick.modules["lifeboat"].pressure_kpa > 95.0  # the escape vehicle never lost its air
