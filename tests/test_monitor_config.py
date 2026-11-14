import pytest

from ares3.schemas.monitor import MonitorConfig
from ares3.schemas.scenario import validate_references
from ares3.sdk import ControlAPI, Emergency, MonitorEvent, PendingAction, SimulationTick
from ares3.sdk.types import Action


def test_scenarios_load_the_monitor_config(station):
    mon = station.monitor
    assert {d.emergency for d in mon.detectors} == {"depressurization", "equipment", "fire", "medical"}
    depress = next(p for p in mon.playbooks if p.emergency == "depressurization")
    assert [a.level for a in depress.actions] == ["auto", "auto", "auto", "confirm", "confirm"]
    fire = next(p for p in mon.playbooks if p.emergency == "fire")
    assert [a.do for a in fire.actions if a.level == "auto"][:2] == ["ventilation", "actuator"]  # attack oxygen first
    assert [a.do for a in fire.actions if a.level == "confirm"] == ["extinguish"]
    # life-saving confirm steps go ahead when nobody answers; the others would be discarded
    assert all(a.on_timeout == "execute" for a in depress.actions if a.level == "confirm")


def test_scenario_without_monitor_has_an_empty_one(emergency):
    assert emergency.monitor == MonitorConfig()


def test_tick_carries_monitor_state_with_empty_defaults(station):
    from ares3.core.engine import Engine
    tick = next(iter(Engine(station).run(1))).tick
    assert tick.emergencies == () and tick.pending_actions == () and tick.monitor_events == ()
    assert isinstance(tick, SimulationTick)


def test_monitor_types_round_trip_as_json():
    action = Action(id="a1", emergency_id="e1", kind="hatch", target="hab:lab", command="close", level="confirm")
    pending = PendingAction(action=action, t_proposed_s=10, deadline_s=30, on_timeout="execute")
    emergency = Emergency(id="e1", kind="depressurization", module_id="lab", severity="critical",
                          state="confirmed", t_open_s=5, t_update_s=10, tres_s=240.0)
    event = MonitorEvent(t_s=10, kind="action_approved", message="ok", action_id="a1", by="eng")
    for obj in (pending, emergency, event):
        assert type(obj).model_validate_json(obj.model_dump_json()) == obj


def test_dangling_playbook_references_fail_at_load(station):
    bad = station.model_copy(deep=True)
    bad.monitor.playbooks[0].actions[0].target = "no_such_actuator"
    with pytest.raises(ValueError, match="unknown actuator"):
        validate_references(bad)
    bad = station.model_copy(deep=True)
    bad.monitor.playbooks[0].actions[3].target = "hab:greenhouse2"
    with pytest.raises(ValueError, match="no hatch"):
        validate_references(bad)


def test_control_api_is_a_protocol():
    assert hasattr(ControlAPI, "approve_action") and hasattr(ControlAPI, "declare_emergency")
