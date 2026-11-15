"""The tick loop. One ``Engine.step()`` runs these phases in a fixed, documented order:

 1. active faults for this tick
 2. NPCs: schedule -> module, activity, MET -> metabolic rates
 3. physical effects: crew exchange (O2, CO2, vapour, heat) and physical faults (leak, CO2 source, heat source)
 4. actuators (reading the sensed values and the agent's commands of the PREVIOUS tick) -> flows
 5. world physics: hatch diffusion, heat balance, condensation
 6. snapshot of the physical state
 7. physiology models: module -> NPC vital signs
 8. sensors on the final snapshot, then sensor faults -> observations (labelled with ground truth)
 9. alarm monitor on the true state; monitoring system (sensed values only) -> emergencies; agent decides
    commands applied on the NEXT tick
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ares3.schemas.faults import FaultSpec
from ares3.schemas.monitor import EmergencyKind
from ares3.schemas.scenario import Scenario
from ares3.sdk.base import BaseActuator, BaseAgent, BaseSensor, PhysiologyModel
from ares3.sdk.context import StepContext
from ares3.sdk.registry import resolve
from ares3.sdk.types import Action, Command, MonitorEvent, NPCState, Observation, SimulationTick

from .alarms import AlarmMonitor
from .clock import SimClock
from .constants import SPECIES
from .faults import FaultInjector, label_row
from .metabolism import build_catalog
from .monitor import Monitor
from .npc import NPC
from .orbit import Orbit, flux_swing_w_m2
from .procedures import ProcedureRunner
from .responder import Responder
from .response import CrewResponse
from .rng import derive
from .world import World

_ZERO = {sp: 0.0 for sp in SPECIES}
AIR_MOLAR_KG = 0.02896  # dry air [SI]; a leak is quoted in kg of air per day


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
            env.alarm_rules, frozenset(m.id for m in scenario.layout.modules if m.alarm_mode == "occupied"),
            frozenset(m.id for m in scenario.layout.modules if m.alarm_mode == "never"),
            {m.id: m.alarm_rules for m in scenario.layout.modules if m.alarm_rules is not None})
        self.npcs: dict[str, NPC] = {m.id: NPC.from_spec(m) for m in scenario.crew.members}
        self.monitor = Monitor(scenario.monitor, [m.id for m in scenario.layout.modules], sf.seed,
                               [m.id for m in scenario.crew.members])
        self.responder = Responder(
            scenario.monitor.playbooks, {a.id for a in scenario.layout.actuators},
            {frozenset((h.a, h.b)) for h in scenario.layout.hatches}, self._guard,
            {m.id for m in scenario.layout.modules},
            frozenset(frozenset((h.a, h.b)) for h in scenario.layout.hatches if h.closable),
            {s.id for s in scenario.layout.sensors}, scenario.monitor.substitutes)
        cr0 = scenario.monitor.crew_response
        self.procedures = ProcedureRunner(scenario.monitor.procedures, self.responder,
                                          follow=cr0 is not None and cr0.npc_follows_procedures,
                                          profile_roles=cr0.roles if cr0 else None, succession=cr0.succession if cr0 else ())
        self._unpowered: set[str] = set()  # modules whose power was cut by a ``power off`` (applied one tick after the command)
        self._queued_power: list[tuple[str, bool]] = []
        self._substitute: dict[str, str] = {}  # faulty sensor -> the sensor the control loops read instead
        self._queued_sub: list[tuple[str, str | None]] = []  # (sensor, replacement or None = restore)
        self._readings_view: dict[str, Observation] | None = None
        self._queued_fans: list[tuple[str, bool]] = []  # (module, on), applied at the start of the next tick
        self._extinguished_t: dict[str, float] = {}  # module -> when the extinguisher was last discharged
        self._queued_extinguish: list[str] = []  # modules where the crew discharges an extinguisher
        self._fire_left_kj: dict[str, float] = {}  # fuel left per fire fault id
        self._queued_hatches: list[tuple[str, str, bool]] = []  # monitor actions, applied at the start of the next tick
        cr = scenario.monitor.crew_response
        self.crew_response = (CrewResponse(cr, scenario.crew.members, scenario.layout.modules, sf.seed)
                              if cr is not None else None)
        self._orders: dict = {}  # emergency orders per NPC, applied at the next tick
        self._crew_roles: dict[str, str] = {}
        self._crew_phases: dict[str, str] = {}

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

        self.orbit = Orbit(env.orbit) if env.orbit is not None else None
        self._station = None  # StationState of the current tick
        self._load_w = 0.0  # electrical draw of the actuators in the previous tick
        self._act_telemetry: dict[str, dict[str, float]] = {}
        self._near_cache: dict[str, frozenset[str]] = {}
        self._actuator_module = {a.id: a.module for a in scenario.layout.actuators}
        self._fans = {h.imv: h.key for h in scenario.layout.hatches if h.imv}  # fan actuator id -> hatch id
        if self.orbit is not None:
            self._station = self.orbit.step(0.0, 0.0, 0.0)
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
            sex=npc.spec.sex, age_y=npc.spec.age_y, height_cm=npc.spec.height_cm, body_mass_kg=npc.spec.body_mass_kg,
            vitals=dict(npc.vitals), latent=dict(npc.latent),
            role=self._crew_roles.get(npc.id), response_phase=self._crew_phases.get(npc.id),
        )

    def _snapshot(self, active_faults: tuple[str, ...], alarms=(), emergencies=(), monitor_events=(),
                  pending_actions=(), monitor_mode="passive", procedures=(), ml=None) -> SimulationTick:
        return SimulationTick(
            tick=self.clock.tick, t_sim_s=self.clock.t_s, dt_s=self.clock.dt_s, day=self.clock.day,
            time_of_day_h=self.clock.time_of_day_h,
            modules={mid: self.world.snapshot_module(m) for mid, m in self.world.modules.items()},
            npcs={nid: self._npc_state(n) for nid, n in self.npcs.items() if n.block and n.rates},
            hatches=self.world.snapshot_hatches(), station=self._station, actuators=self._act_telemetry,
            active_faults=active_faults, alarms=alarms,
            emergencies=emergencies, pending_actions=pending_actions, monitor_events=monitor_events,
            monitor_mode=monitor_mode, procedures=procedures, ml=ml or {}, powered_off=tuple(sorted(self._unpowered)),
        )

    def _ctx(self, tick: SimulationTick, by_target) -> StepContext:
        readings = self._readings
        if self._substitute:  # control loops read the redundant sensor instead of the faulty one
            readings = {**readings, **{bad: readings[good] for bad, good in self._substitute.items() if good in readings}}
        return StepContext(tick=tick, env=self.env, _faults=by_target, _readings=readings)

    # ---- runtime events (debug button / UI) ----------------------------------------------------
    def inject(self, fault: FaultSpec, *, now: bool = True) -> FaultSpec:
        """Cause an event during the run. With ``now`` the fault starts at the current simulated time
        (``start_s`` is overwritten); otherwise its own ``start_s`` is kept. Same effect and labels as a
        fault written in the scenario, so the dataset stays consistent. Returns the fault as scheduled."""
        known = {m.id for m in self.scenario.layout.modules} | set(self.npcs) \
            | {s.id for s in self.sensors} | {a.id for a in self.actuators} | set(self.world.hatch_by_id)
        unknown = [t for t in fault.targets if t not in known]
        if unknown:
            raise ValueError(f"unknown targets: {unknown}")
        if now:
            fault = fault.model_copy(update={"start_s": self.clock.t_s})
        self.injector.add(fault)
        return fault

    def approve_action(self, action_id: str, by: str | None = None) -> None:
        """Approve a pending ``confirm`` action (anyone can); it runs on the next tick."""
        self.responder.approve(action_id, by)

    def reject_action(self, action_id: str, by: str | None = None) -> None:
        self.responder.reject(action_id, by)

    def ack_step(self, procedure_id: str, step_id: str, by: str | None = None, answer: str | None = None) -> None:
        """Close the active step of a crew procedure (anyone can); ``answer`` is yes / no for a question."""
        self.procedures.ack(procedure_id, step_id, by, answer)

    def declare_emergency(self, kind: EmergencyKind, module_id: str, by: str | None = None) -> str:
        """Manual alarm, as a crew member can on the ISS. Held for the classifier's ``clear_s`` unless detectors back it."""
        if module_id not in self.world.modules:
            raise ValueError(f"unknown module {module_id}")
        return self.monitor.declare(kind, module_id, self.clock.t_s, by)

    def stop_event(self, fault_id: str) -> None:
        """End an event now (e.g. the crew fixed it, or the debug button is toggled off)."""
        self.injector.stop(fault_id, self.clock.t_s)

    # ---- one tick ------------------------------------------------------------------------------
    def step(self) -> StepResult:
        dt, t = self.clock.dt_s, self.clock.t_s
        w = self.world

        active = self.injector.active(t)  # 1
        by_target = self.injector.by_target(active)
        for hid, hatch in w.hatch_by_id.items():
            hatch.stuck = any(f.type == "hatch_stuck" for f in by_target.get(hid, ()))
        for a, b, open_ in self._queued_hatches:  # monitor actions of the previous tick
            w.set_hatch(a, b, open_)
        self._queued_hatches = []
        for mid, on in self._queued_power:
            (self._unpowered.add if not on else self._unpowered.discard)(mid)
            if not on:
                w.set_fans(mid, False)  # no power, no fans (they stay off after the power is back until the crew restarts them)
        self._queued_power = []
        for sensor, good in self._queued_sub:
            if good is None:
                self._substitute.pop(sensor, None)
            else:
                self._substitute[sensor] = good
        self._queued_sub = []
        for mid, on in self._queued_fans:
            w.set_fans(mid, on)
        self._queued_fans = []
        for mid in self._queued_extinguish:
            self._extinguished_t[mid] = t
            for f in self.injector.active(t):
                if f.type == "fire" and mid in f.targets and f.params.get("extinguishable", True):  # False: it keeps burning
                    self.injector.stop(f.id, t)
        if self._queued_extinguish:
            active = self.injector.active(t)  # the fires put out above no longer count this tick
            by_target = self.injector.by_target(active)
        self._queued_extinguish = []
        w.begin_tick()
        if self.orbit is not None:  # orbit: sun, battery, and the heat swing the cabin sees through the insulation
            self._station = self.orbit.step(t, dt, self._load_w)
            oc = self.env.orbit
            swing = flux_swing_w_m2(oc, self._station.sun, self.orbit.f_ecl) * oc.mli_attenuation
        else:
            swing = 0.0
        for m in w.modules.values():
            if (m.spec.base_heat_w and m.id not in self._unpowered) or swing:
                area = m.spec.surface_m2 if m.spec.surface_m2 is not None else 4.6 * m.spec.volume_m3 ** (2.0 / 3.0)
                w.add_heat(m.id, (0.0 if m.id in self._unpowered else m.spec.base_heat_w) + swing * area)

        for npc in self.npcs.values():  # 2
            npc.override = self._orders.get(npc.id)
            npc.update(self.clock.time_of_day_h, self.catalog, self.env.reference_body_mass_kg)
            w.modules[npc.block.module].occupants.append(npc.id)

        for npc in self.npcs.values():  # 3: crew exchange
            r, mid = npc.rates, npc.block.module
            g = npc.vitals.get("gas_scale", 1.0)  # physiology: unconscious -> resting exchange, dead -> none
            w.add_moles(mid, "o2", -r.o2_mol_s * g * dt, f"crew:{npc.id}")
            w.add_moles(mid, "co2", r.co2_mol_s * g * dt, f"crew:{npc.id}")
            w.add_moles(mid, "h2o", r.h2o_mol_s * g * dt, f"crew:{npc.id}")
            w.book(f"crew:{npc.id}", "sweat_kg", r.sweat_kg_s * g * dt)
            w.add_heat(mid, r.heat_sensible_w * g)
        for m in w.modules.values():  # 3: the structural leak every real module has
            if m.spec.leak_kg_day and m.n_total > 0:
                frac = m.spec.leak_kg_day / 86400.0 / AIR_MOLAR_KG * (m.pressure_kpa / 101.3) / m.n_total * dt
                for sp in SPECIES:
                    w.add_moles(m.id, sp, -m.n[sp] * frac, "structural_leak")
        for f in active:  # 3: physical faults
            if f.category != "physical":
                continue
            for mid in f.targets:
                if f.type == "leak":
                    for sp in SPECIES:
                        w.add_moles(mid, sp, -w.modules[mid].n[sp] * self._leak_fraction(f, mid, t) * dt, f"fault:{f.id}")
                elif f.type == "co2_source":
                    w.add_moles(mid, "co2", float(f.params.get("mol_s", 0.0)) * dt, f"fault:{f.id}")
                elif f.type == "co_source":
                    w.add_contaminant(mid, "co_mol", float(f.params.get("mol_s", 0.0)) * dt)
                elif f.type == "heat_source":
                    w.add_heat(mid, float(f.params.get("watts", 0.0)))
                elif f.type == "fire":
                    self._fire(f, mid, dt)

        prev_ctx = self._ctx(self._last_tick, by_target)  # 4: actuators
        self._load_w = 0.0
        telemetry: dict[str, dict[str, float]] = {}
        for act in self.actuators:
            faults = by_target.get(act.id, ())
            if self._actuator_module.get(act.id) in self._unpowered or any(f.type == "actuator_offline" for f in faults):
                telemetry[act.id] = act.telemetry_offline()
                if act.id in self._fans:
                    w.hatch_by_id[self._fans[act.id]].fan_flow_m3_s = 0.0
                continue
            command = self._pending.get(act.id)
            for f in faults:
                if f.type == "actuator_stuck":  # a valve that no longer follows its command
                    command = Command(actuator_id=act.id, action=str(f.params.get("command", "on")),
                                      value=f.params.get("value"))
            for flow in act.step(dt, prev_ctx, command):
                for sp, mol_s in flow.mol_s.items():
                    w.add_moles(flow.module_id, sp, mol_s * dt, f"actuator:{act.id}")
                w.add_heat(flow.module_id, flow.heat_w)
                self._load_w += flow.power_w
            telemetry[act.id] = act.telemetry()
            if act.id in self._fans:
                w.hatch_by_id[self._fans[act.id]].fan_flow_m3_s = act.hatch_flow_m3_s() or 0.0
        self._act_telemetry = telemetry
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
            sensed = self.injector.corrupt(s.id, obs.value, by_target.get(s.id, ()), t, obs.entity_id, s.sigma)
            if sensed is None:
                continue
            obs = obs.model_copy(update={"value": sensed})
            observations.append(obs)
            self._readings[s.id] = obs
            if self.clock.tick % max(1, round(1.0 / (s.rate_hz * dt))) == 0:
                rows.append(self._row(obs, s, tick, active))

        emergencies, monitor_events = self.monitor.step(self._ctx(tick, by_target), observations)  # 9
        actions, response_events = self.responder.step(t, emergencies)
        procs, proc_events, proc_actions = self.procedures.step(t, emergencies, observations, tick.npcs, self._crew_roles)
        actions += proc_actions
        tick = self._snapshot(tuple(f.id for f in active), self.alarms.evaluate(t, tick.modules), emergencies,
                              (*monitor_events, *response_events, *proc_events), self.responder.pending, self.monitor.mode, procs, self.monitor.scores)
        if self.crew_response is not None:  # orders take effect on the next tick, like every command
            fires = {m: self._extinguished_t.get(m) for f in active if f.type == "fire" for m in f.targets}
            crew = self.crew_response.step(t, tick, fires)
            self._orders, self._crew_roles, self._crew_phases = crew.orders, crew.roles, crew.phases
            for action_id, by in crew.approvals:
                self.responder.approve(action_id, by)
            self._queued_hatches += [(a, b, True) for a, b in crew.open_hatches]
            self._queued_hatches += [(a, b, False) for a, b in crew.close_hatches]
            events = list(crew.events)
            for mid in crew.leak_repairs:  # the engineer patches the hole: the leak stops
                sealed = [f.id for f in self.injector.active(t)
                          if f.type == "leak" and mid in f.targets and f.params.get("repairable", True)]
                for fid in sealed:
                    self.injector.stop(fid, t)
                if sealed:
                    events.append(MonitorEvent(t_s=t, kind="crew_repaired", message=f"leak patched in {mid}: {', '.join(sealed)}"))
                    self.monitor.forget(mid)
            for mid in crew.repairs:  # the engineer brings the offline actuators of the module back
                acts = {a.id for a in self.scenario.layout.actuators if a.module == mid}
                fixed = [f.id for f in self.injector.active(t) if f.type == "actuator_offline" and acts & set(f.targets)]
                for fid in fixed:
                    self.injector.stop(fid, t)
                if fixed:
                    events.append(MonitorEvent(t_s=t, kind="crew_repaired", message=f"repaired in {mid}: {', '.join(fixed)}"))
                    self.monitor.forget(mid)
            if events:
                tick = tick.model_copy(update={"monitor_events": (*tick.monitor_events, *events)})
        if self.agent is not None:
            for cmd in self.agent.decide(self._ctx(tick, by_target), observations):
                self._pending[cmd.actuator_id] = cmd
        for a in actions:  # after the agent: a safing action of the monitor wins
            if a.kind == "actuator":
                self._pending[a.target] = Command(actuator_id=a.target, action=a.command, value=a.value)
            elif a.kind == "hatch":
                x, y = a.target.split(":")
                self._queued_hatches.append((x, y, a.command == "open"))
            elif a.kind == "ventilation":
                self._queued_fans.append((a.target, a.command == "on"))
            elif a.kind == "extinguish":
                self._queued_extinguish.append(a.target)
            elif a.kind == "power":
                self._queued_power.append((a.target, a.command == "on"))
            elif a.kind == "sensor":
                self._queued_sub.append((a.target, a.value_id if a.command == "substitute" else None))

        self._last_tick = tick
        self.clock.advance()
        return StepResult(tick=tick, observations=tuple(observations), rows=tuple(rows))

    def _leak_fraction(self, f: FaultSpec, mid: str, t: float) -> float:
        """Fraction of the module's gas lost per second by leak fault ``f`` at time ``t``. Quoted as ``rate_per_s``
        (a fraction), as an air mass flow ``kg_day`` (constant, a linear ramp ``kg_day_to`` over ``ramp_s``, or
        ``steps`` of [seconds since the start, kg/day]) or as a pressure drop ``kpa_min`` at the current pressure."""
        p, m = f.params, self.world.modules[mid]
        n = m.n_total
        if n <= 0.0:
            return 0.0
        if "rate_per_s" in p:
            return float(p["rate_per_s"])
        if "kpa_min" in p:  # constant volumetric loss: dP/dt = kpa_min / 60 while the module holds pressure
            return min(1.0, float(p["kpa_min"]) / 60.0 / max(m.pressure_kpa, 1e-9))
        kg_day = float(p.get("kg_day", 0.0))
        rel = t - f.start_s
        if "steps" in p:
            for t_rel, rate in p["steps"]:
                if rel >= float(t_rel):
                    kg_day = float(rate)
        elif "kg_day_to" in p:
            x = min(1.0, rel / float(p.get("ramp_s", 1.0)))
            kg_day += (float(p["kg_day_to"]) - kg_day) * x
        # the flow through a hole is proportional to the pressure: it fades as the module empties
        scale = m.pressure_kpa / float(p.get("ref_kpa", 101.3))
        return kg_day / 86400.0 / AIR_MOLAR_KG * scale / n

    def _fire(self, f: FaultSpec, mid: str, dt: float) -> None:
        """Combustion in module ``mid``: heat, O2 consumed, CO2, CO and smoke released. Intensity follows the ISS fire
        triangle: it falls with the O2 partial pressure (flammability limit), drops when the fans are off (no
        convection in microgravity) and the fire ends when its fuel is spent. All defaults are ESTIMATES (owner: Mario)
        except the O2 energy equivalent, ~419 kJ per mol O2 (13.1 MJ/kg, Huggett 1980)."""
        w, p = self.world, f.params
        m = w.modules[mid]
        left = self._fire_left_kj.setdefault(f.id, float(p.get("fuel_kj", 5.0e5)))
        if left <= 0.0:
            return
        heat = float(p.get("heat_w", 1000.0))
        o2_rate = float(p.get("o2_mol_s", heat / 4.19e5))
        po2_min, po2_ref = float(p.get("min_po2_kpa", 12.0)), 21.2
        k = min(1.0, max(0.0, (m.partial_kpa("o2") - po2_min) / (po2_ref - po2_min)))
        if not m.fans_on:
            k *= float(p.get("no_airflow_factor", 0.15))
        if mid in self._unpowered and p.get("electrical", True):  # an electrical ignition source loses its supply (ESTIMATE)
            k *= float(p.get("unpowered_factor", 0.2))
        src = f"fault:{f.id}"
        w.add_heat(mid, heat * k)
        burned = -w.add_moles(mid, "o2", -o2_rate * k * dt, src)
        w.add_moles(mid, "co2", float(p.get("co2_mol_s", 0.8 * o2_rate)) * k * dt, src)
        w.add_contaminant(mid, "co_mol", float(p.get("co_mol_s", 0.05 * 0.8 * o2_rate)) * k * dt)
        w.add_contaminant(mid, "smoke_mg", float(p.get("smoke_mg_s", 2.0)) * k * dt)
        self._fire_left_kj[f.id] = left - heat * k * dt / 1000.0 if burned > 0 else left

    def _guard(self, a: Action, also_closed: frozenset[frozenset[str]] = frozenset()) -> str | None:
        """Safety rules of the ISS: never close a hatch that cuts someone off from the return vehicle, and never cut the
        power of the return vehicle or of a suit volume (they have their own supply)."""
        if a.kind == "power" and a.command == "off":
            m = self.world.modules.get(a.target)
            own = m is not None and (m.spec.return_vehicle or m.spec.alarm_mode == "occupied")
            return "the return vehicle and the suit volume have their own power supply" if own else None
        if a.kind != "hatch" or a.command != "close":
            return None
        x, y = a.target.split(":")
        vehicles = {m.id for m in self.scenario.layout.modules if m.return_vehicle}
        if not vehicles:
            return None
        if x in vehicles or y in vehicles:
            return "never close the hatch of the return vehicle"
        adj: dict[str, set[str]] = {}
        for h in self.world.hatches:
            adj.setdefault(h.a, set())
            adj.setdefault(h.b, set())
            # the vehicle hatch counts as passable: the crew opens it when they retreat
            if {h.a, h.b} != {x, y} and frozenset((h.a, h.b)) not in also_closed and (
                    h.open or h.a in vehicles or h.b in vehicles):
                adj[h.a].add(h.b)
                adj[h.b].add(h.a)
        reach, todo = set(vehicles), list(vehicles)
        while todo:
            for n in adj.get(todo.pop(), ()):
                if n not in reach:
                    reach.add(n)
                    todo.append(n)
        # modules with no hatch at all (the EVA volume) are reached by schedule, not through the graph
        cut = [o for mid, m in self.world.modules.items() if mid in adj and mid not in reach for o in m.occupants]
        return f"would cut {', '.join(cut)} off from the return vehicle" if cut else None

    def _row(self, obs: Observation, sensor: BaseSensor, tick: SimulationTick, active) -> dict:
        # a fault labels a row when it targets the sensor, the thing measured, the module it is in,
        # or an actuator of that module (e.g. a failed scrubber labels the module's sensors)
        npc = tick.npcs.get(obs.entity_id)
        if not active:  # the common case: nothing to label
            is_anom, a_type, a_ids = False, "nominal", ""
        else:
            module_id = npc.module_id if npc is not None else self._actuator_module.get(obs.entity_id, obs.entity_id)
            near = self._near_cache.get(module_id)
            if near is None:  # the module, its actuators and its hatches: a fault on any of them labels its rows
                near = self._near_cache[module_id] = frozenset(
                    [module_id, *(a.id for a in self.actuators if a.module == module_id),
                     *(h.id for h in self.world.hatches if module_id in (h.a, h.b))])
            is_anom, a_type, a_ids = label_row({sensor.id, obs.entity_id} | near, active)
        if npc is not None and npc.vitals.get("health_state", 0.0) >= 4.0:  # dead (Luca: label MORTO)
            is_anom, a_type = True, "dead"
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
