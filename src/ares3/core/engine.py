"""The tick loop. One ``Engine.step()`` runs these phases in a fixed, documented order:

 1. active faults for this tick
 2. NPCs: schedule -> module, activity, MET -> metabolic rates
 3. physical effects: crew exchange (O2, CO2, vapour, heat) and physical faults (leak, CO2 source, heat source)
 4. actuators (reading the sensed values and the agent's commands of the PREVIOUS tick) -> flows
 5. world physics: hatch diffusion, heat balance, condensation
 6. snapshot of the physical state
 7. physiology models: module -> NPC vital signs
 8. sensors on the final snapshot, then sensor faults -> observations (labelled with ground truth)
 9. alarm monitor on the true state; agent decides commands applied on the NEXT tick
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ares3.schemas.scenario import Scenario
from ares3.sdk.base import BaseActuator, BaseAgent, BaseSensor, PhysiologyModel
from ares3.sdk.context import StepContext
from ares3.sdk.registry import resolve
from ares3.sdk.types import Command, NPCState, Observation, SimulationTick

from .alarms import AlarmMonitor
from .clock import SimClock
from .constants import SPECIES
from .faults import FaultInjector, label_row
from .metabolism import build_catalog
from .npc import NPC
from .rng import derive
from .world import World

_ZERO = {sp: 0.0 for sp in SPECIES}


@dataclass(frozen=True)
class StepResult:
    tick: SimulationTick
    observations: tuple[Observation, ...]  # every sensed sample of this tick
    rows: tuple[dict, ...]  # labelled long-format rows, only for samples due at their ``rate_hz``


class Engine:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        sf = scenario.file
        env = scenario.environment
        self.env = env
        self.clock = SimClock(dt_s=sf.dt_s, day_length_s=env.day_length_s, start_tod_h=sf.start_time_of_day_h)
        self.world = World(scenario.layout, env.atmosphere, env.exterior_temp_c)
        self.catalog = build_catalog(scenario.crew.activities)
        self.injector = FaultInjector(scenario.faults.faults, sf.seed)
        self.alarms = AlarmMonitor(
            env.alarm_rules, frozenset(m.id for m in scenario.layout.modules if m.alarm_mode == "occupied"))
        self.npcs: dict[str, NPC] = {m.id: NPC.from_spec(m) for m in scenario.crew.members}

        self.physiology: dict[str, PhysiologyModel] = {}
        for m in scenario.crew.members:
            spec = m.physiology or scenario.crew.physiology
            self.physiology[m.id] = resolve(spec.kind).from_config(m.id, spec.params, derive(sf.seed, "physiology", m.id))

        self.sensors: list[BaseSensor] = []
        for s in scenario.layout.sensors:
            self.sensors.append(resolve(s.kind).from_config(
                s.id, s.params, derive(sf.seed, "sensor", s.id), target=s.target, metric=s.metric, rate_hz=s.rate_hz))
        self.actuators: list[BaseActuator] = []
        for a in scenario.layout.actuators:
            self.actuators.append(resolve(a.kind).from_config(
                a.id, a.params, derive(sf.seed, "actuator", a.id), module=a.module))
        self.agent: BaseAgent | None = None
        if sf.agent is not None:
            self.agent = resolve(sf.agent.kind).from_config("agent", sf.agent.params, derive(sf.seed, "agent"))

        self._pending: dict[str, Command] = {}
        self._readings: dict[str, Observation] = {}
        self._last_tick = self._snapshot(active_faults=())
        self._seed_npcs()
        self._last_tick = self._snapshot(active_faults=())
        for comp in (*self.physiology.values(), *self.sensors, *self.actuators):
            comp.reset()

    # ---- helpers ------------------------------------------------------------------------------
    def _seed_npcs(self) -> None:
        for npc in self.npcs.values():
            npc.update(self.clock.time_of_day_h, self.catalog, self.env.reference_body_mass_kg)
            self.world.modules[npc.block.module].occupants.append(npc.id)
        tick = self._snapshot(active_faults=())
        for npc in self.npcs.values():
            state = self._npc_state(npc)
            upd = self.physiology[npc.id].initial_vitals(state, tick.modules[npc.block.module])
            npc.vitals, npc.latent = dict(upd.vitals), dict(upd.latent)

    def _npc_state(self, npc: NPC) -> NPCState:
        r = npc.rates
        return NPCState(
            id=npc.id, profile=npc.spec.profile, module_id=npc.block.module, activity=npc.block.activity,
            met=r.met, vo2_l_min=r.vo2_l_min, vco2_l_min=r.vco2_l_min, heat_w=r.heat_sensible_w,
            vitals=dict(npc.vitals), latent=dict(npc.latent),
        )

    def _snapshot(self, active_faults: tuple[str, ...], alarms=()) -> SimulationTick:
        return SimulationTick(
            tick=self.clock.tick, t_sim_s=self.clock.t_s, dt_s=self.clock.dt_s, day=self.clock.day,
            time_of_day_h=self.clock.time_of_day_h,
            modules={mid: self.world.snapshot_module(m) for mid, m in self.world.modules.items()},
            npcs={nid: self._npc_state(n) for nid, n in self.npcs.items() if n.block and n.rates},
            hatches=self.world.snapshot_hatches(), active_faults=active_faults, alarms=alarms,
        )

    def _ctx(self, tick: SimulationTick, by_target) -> StepContext:
        return StepContext(tick=tick, env=self.env, _faults=by_target, _readings=self._readings)

    # ---- one tick ------------------------------------------------------------------------------
    def step(self) -> StepResult:
        dt, t = self.clock.dt_s, self.clock.t_s
        w = self.world

        active = self.injector.active(t)  # 1
        by_target = self.injector.by_target(active)
        w.begin_tick()

        for npc in self.npcs.values():  # 2
            npc.update(self.clock.time_of_day_h, self.catalog, self.env.reference_body_mass_kg)
            w.modules[npc.block.module].occupants.append(npc.id)

        for npc in self.npcs.values():  # 3: crew exchange
            r, mid = npc.rates, npc.block.module
            w.add_moles(mid, "o2", -r.o2_mol_s * dt, f"crew:{npc.id}")
            w.add_moles(mid, "co2", r.co2_mol_s * dt, f"crew:{npc.id}")
            w.add_moles(mid, "h2o", r.h2o_mol_s * dt, f"crew:{npc.id}")
            w.book(f"crew:{npc.id}", "sweat_kg", r.sweat_kg_s * dt)
            w.add_heat(mid, r.heat_sensible_w)
        for f in active:  # 3: physical faults
            if f.category != "physical":
                continue
            for mid in f.targets:
                if f.type == "leak":
                    frac = float(f.params.get("rate_per_s", 0.0)) * dt
                    for sp in SPECIES:
                        w.add_moles(mid, sp, -w.modules[mid].n[sp] * frac, f"fault:{f.id}")
                elif f.type == "co2_source":
                    w.add_moles(mid, "co2", float(f.params.get("mol_s", 0.0)) * dt, f"fault:{f.id}")
                elif f.type == "heat_source":
                    w.add_heat(mid, float(f.params.get("watts", 0.0)))

        prev_ctx = self._ctx(self._last_tick, by_target)  # 4: actuators
        for act in self.actuators:
            if any(f.type == "actuator_offline" for f in by_target.get(act.id, ())):
                continue
            for flow in act.step(dt, prev_ctx, self._pending.get(act.id)):
                for sp, mol_s in flow.mol_s.items():
                    w.add_moles(flow.module_id, sp, mol_s * dt, f"actuator:{act.id}")
                w.add_heat(flow.module_id, flow.heat_w)
        self._pending = {}

        w.step(dt)  # 5
        tick = self._snapshot(tuple(f.id for f in active))  # 6

        ctx = self._ctx(tick, by_target)  # 7
        for npc in self.npcs.values():
            upd = self.physiology[npc.id].step(dt, self._npc_state(npc), tick.modules[npc.block.module], ctx)
            npc.vitals, npc.latent = dict(upd.vitals), dict(upd.latent)
        tick = self._snapshot(tuple(f.id for f in active))
        ctx = self._ctx(tick, by_target)

        observations: list[Observation] = []  # 8
        rows: list[dict] = []
        for s in self.sensors:
            obs = s.step(dt, ctx)
            if obs is None:
                continue
            sensed = self.injector.corrupt(s.id, obs.value, by_target.get(s.id, ()), t)
            if sensed is None:
                continue
            obs = obs.model_copy(update={"value": sensed})
            observations.append(obs)
            self._readings[s.id] = obs
            if self.clock.tick % max(1, round(1.0 / (s.rate_hz * dt))) == 0:
                rows.append(self._row(obs, s, tick, active))

        tick = self._snapshot(tuple(f.id for f in active), self.alarms.evaluate(t, tick.modules))  # 9
        if self.agent is not None:
            for cmd in self.agent.decide(self._ctx(tick, by_target), observations):
                self._pending[cmd.actuator_id] = cmd

        self._last_tick = tick
        self.clock.advance()
        return StepResult(tick=tick, observations=tuple(observations), rows=tuple(rows))

    def _row(self, obs: Observation, sensor: BaseSensor, tick: SimulationTick, active) -> dict:
        # a fault labels a row when it targets the sensor, the thing measured, the module it is in,
        # or an actuator of that module (e.g. a failed scrubber labels the module's sensors)
        entities = {sensor.id, obs.entity_id}
        npc = tick.npcs.get(obs.entity_id)
        module_id = npc.module_id if npc is not None else obs.entity_id
        entities.add(module_id)
        entities.update(a.id for a in self.actuators if a.module == module_id)
        is_anom, a_type, a_ids = label_row(entities, active)
        return {
            "tick": obs.tick, "timestamp": obs.t_s, "sensor_id": obs.sensor_id, "entity_id": obs.entity_id,
            "metric": obs.metric, "value": obs.value, "value_true": obs.value_true,
            "is_anomaly": is_anom, "anomaly_type": a_type, "anomaly_ids": a_ids,
        }

    def run(self, ticks: int | None = None) -> Iterator[StepResult]:
        """Yield ``ticks`` results, or forever when ``ticks`` is None (stop by breaking out)."""
        n = 0
        while ticks is None or n < ticks:
            yield self.step()
            n += 1
