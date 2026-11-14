"""Scenario = environment + layout + crew + faults + seed + duration, loaded from YAML.

Paths inside a scenario file are relative to that file. ``environment_overrides`` is deep-merged over
the environment profile, so the environment can be tweaked per scenario without copying the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .crew import CrewConfig
from .environment import EnvironmentProfile
from .faults import FaultsConfig
from .layout import LayoutConfig
from .monitor import MODULE_TEMPLATE, MonitorConfig


class ExportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["parquet", "csv"] = "parquet"
    chunk_hours: float = Field(default=1.0, gt=0)  # simulated hours per output file
    long: bool = True  # one row per (timestamp, sensor): the ground-truth dataset
    wide: bool = True  # one row per timestamp, one column per sensor


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    params: dict[str, Any] = {}


class ScenarioFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    seed: int = 0
    dt_s: float = Field(default=1.0, gt=0)
    duration_days: float | None = Field(default=None, gt=0)  # None = unbounded (needs --days/--ticks or Ctrl-C)
    start_time_of_day_h: float = Field(default=6.0, ge=0, lt=24)
    environment: str
    environment_overrides: dict[str, Any] = {}
    physiology_overrides: dict[str, Any] = {}  # merged into the params of every crew member's physiology (e.g. death_enabled)
    layout: str | list[str]  # one file, or several merged in order (modules, sensors, actuators in separate files)
    crew: str
    faults: str | None = None
    monitor: str | None = None  # detectors + playbooks; None = no monitoring system
    agent: AgentSpec | None = None
    export: ExportConfig = ExportConfig()


class Scenario(BaseModel):
    """Fully resolved scenario handed to the engine."""

    file: ScenarioFile
    environment: EnvironmentProfile
    layout: LayoutConfig
    crew: CrewConfig
    faults: FaultsConfig
    monitor: MonitorConfig = MonitorConfig()


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if data is not None else {}


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path).resolve()
    sf = ScenarioFile.model_validate(_read_yaml(path))
    base = path.parent
    env_data = deep_merge(_read_yaml(base / sf.environment), sf.environment_overrides)
    crew = CrewConfig.model_validate(_read_yaml(base / sf.crew))
    if sf.physiology_overrides:
        crew.physiology.params = deep_merge(crew.physiology.params, sf.physiology_overrides)
        for member in crew.members:
            if member.physiology is not None:
                member.physiology.params = deep_merge(member.physiology.params, sf.physiology_overrides)
    layout_files = [sf.layout] if isinstance(sf.layout, str) else sf.layout
    merged: dict[str, list] = {}
    for name in layout_files:
        for key, items in _read_yaml(base / name).items():
            merged.setdefault(key, []).extend(items)
    layout = LayoutConfig.model_validate(merged).expand_sensor_sets([m.id for m in crew.members])
    scenario = Scenario(
        file=sf,
        environment=EnvironmentProfile.model_validate(env_data),
        layout=layout,
        crew=crew,
        faults=FaultsConfig.model_validate(_read_yaml(base / sf.faults)) if sf.faults else FaultsConfig(),
        monitor=MonitorConfig.model_validate(_read_yaml(base / sf.monitor)) if sf.monitor else MonitorConfig(),
    )
    validate_references(scenario)
    return scenario


def validate_references(sc: Scenario) -> None:
    """Fail early on duplicate ids and dangling references instead of mid-simulation."""
    modules = {m.id for m in sc.layout.modules}
    npcs = {m.id for m in sc.crew.members}
    sensors = {s.id for s in sc.layout.sensors}
    actuators = {a.id for a in sc.layout.actuators}
    groups = [
        [m.id for m in sc.layout.modules], [m.id for m in sc.crew.members],
        [s.id for s in sc.layout.sensors], [a.id for a in sc.layout.actuators],
    ]
    all_ids = [i for g in groups for i in g]
    dups = {i for i in all_ids if all_ids.count(i) > 1}
    if dups:
        raise ValueError(f"ids must be unique across modules, crew, sensors, actuators: {sorted(dups)}")
    for h in sc.layout.hatches:
        if h.a not in modules or h.b not in modules:
            raise ValueError(f"hatch {h.a}-{h.b} references an unknown module")
    for a in sc.layout.actuators:
        if a.module not in modules:
            raise ValueError(f"actuator {a.id}: unknown module {a.module}")
    for s in sc.layout.sensors:
        kind, _, ident = s.target.partition(":")
        if kind == "module" and ident in modules:
            continue
        if kind == "npc" and ident in npcs:
            continue
        raise ValueError(f"sensor {s.id}: bad target {s.target!r} (use module:<id> or npc:<id>)")
    for m in sc.crew.members:
        for b in m.schedule:
            if b.module not in modules:
                raise ValueError(f"{m.id}: schedule references unknown module {b.module}")
    known = modules | npcs | sensors | actuators
    for f in sc.faults.faults:
        missing = [t for t in f.targets if t not in known]
        if missing:
            raise ValueError(f"fault {f.id}: unknown targets {missing}")
    _validate_monitor(sc, modules, actuators)
    cr = sc.monitor.crew_response
    if cr is not None:
        profiles = {m.profile for m in sc.crew.members}
        unknown = (set(cr.roles) | set(cr.succession)) - profiles
        if unknown:
            raise ValueError(f"monitor.crew_response: no crew member with profile {sorted(unknown)}")
        if not any(m.return_vehicle for m in sc.layout.modules):
            raise ValueError("monitor.crew_response needs a module with return_vehicle: true")


def _validate_monitor(sc: Scenario, modules: set[str], actuators: set[str]) -> None:
    npcs = {m.id for m in sc.crew.members}
    ids = [d.id for d in sc.monitor.detectors]
    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        raise ValueError(f"monitor: duplicate detector ids {sorted(dups)}")
    for d in sc.monitor.detectors:
        known = modules | npcs | {"all_modules", "all_npcs"}
        missing = [t for t in d.targets if t not in known]
        if missing:
            raise ValueError(f"detector {d.id}: unknown targets {missing}")
    for pb in sc.monitor.playbooks:
        for a in pb.actions:
            if MODULE_TEMPLATE in a.target:
                continue  # resolved when the emergency happens
            if a.do in ("ventilation", "extinguish") and a.target not in modules:
                raise ValueError(f"playbook {pb.emergency}: unknown module {a.target}")
            if a.do == "actuator" and a.target not in actuators:
                raise ValueError(f"playbook {pb.emergency}: unknown actuator {a.target}")
            if a.do == "hatch":
                ends = a.target.split(":")
                known = {(h.a, h.b) for h in sc.layout.hatches} | {(h.b, h.a) for h in sc.layout.hatches}
                if len(ends) != 2 or tuple(ends) not in known:
                    raise ValueError(f"playbook {pb.emergency}: no hatch {a.target!r} (use a:b)")
