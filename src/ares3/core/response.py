"""How the NPCs react to emergencies: ISS Warn -> Gather -> Work, with roles and a line of succession.

Reads the monitor's confirmed emergencies and the crew's TRUE state (crew members see each other), and
returns *orders*: per NPC, a temporary replacement for the schedule block (module, activity, effort). The
engine applies them on the next tick. Nothing here touches the world.

* Warn: each NPC notices the alarm after a delay (longer if asleep).
* Gather: everyone retreats to the safe haven, the module nearest to a return vehicle that is not hazardous
  and stays reachable (the vehicle itself when the hazard is the module next to it).
* Work: roles. The acting commander (first capable in the succession) counts heads and, if enabled, approves
  pending actions; the medic goes to a casualty unless that means entering a hazardous module.
* Medical: a confirmed ``medical`` emergency (the monitor's, from the wearables) sends the medic to the crew member in
  trouble, with or without a group alarm; the cause the sensors found is in the log line.
* Repair: a confirmed ``equipment`` emergency sends the engineer (role ``systems``) to that module; after ``repair_s``
  there the engine brings the offline actuators of the module back. A leak that is only a warning (fast or slow, no
  group alarm) sends the engineer too; after ``repair_leak_s`` the engine stops the leak.
* Evacuate: when TRes drops under ``evacuate_tres_s``, or the extinguisher was discharged ``fire_evacuate_s`` ago and
  the fire still burns, everyone enters the return vehicle (latched). The all-clear brings them back.
* Seal: once everyone capable is aboard the return vehicle the crew closes its hatches (``seal_vehicle``), so the
  vehicle keeps its air while the station loses its own. The hatch stays closed after the all-clear, as in nominal ops.
* Only CRITICAL emergencies of the ``gather_on`` kinds raise the group alarm: a warning is handled where the crew is.
* Stand down: ``stand_down_delay_s`` after the last emergency clears, the schedules resume.

An incapacitated member (health state 3 or 4) is frozen where they are and holds no role. Moving between
modules is instantaneous (the layout has no geometry); the reaction delay stands for the time it takes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ares3.schemas.crew import ActivityBlock, CrewMember
from ares3.schemas.layout import ModuleSpec
from ares3.schemas.monitor import CrewResponseConfig
from ares3.sdk.types import Emergency, MonitorEvent, SimulationTick

from .rng import derive

_INCAPACITATED = 3.0  # health_state: 3 unconscious, 4 dead
_CASUALTY = 2.0


@dataclass
class CrewOrders:
    orders: dict[str, ActivityBlock] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    phases: dict[str, str] = field(default_factory=dict)
    approvals: list[tuple[str, str]] = field(default_factory=list)  # (action id, npc id)
    open_hatches: list[tuple[str, str]] = field(default_factory=list)  # return-vehicle hatches the crew opens
    close_hatches: list[tuple[str, str]] = field(default_factory=list)  # ... and closes once everyone is aboard
    repairs: list[str] = field(default_factory=list)  # modules where the engineer has finished the repair
    leak_repairs: list[str] = field(default_factory=list)  # modules where the engineer has patched the leak
    events: list[MonitorEvent] = field(default_factory=list)


def _block(module: str, activity: str, met: float | None) -> ActivityBlock:
    return ActivityBlock(from_h=0, to_h=24, activity=activity, module=module, met=met)


class CrewResponse:
    def __init__(self, config: CrewResponseConfig, members: list[CrewMember], modules: list[ModuleSpec],
                 seed: int) -> None:
        self.cfg = config
        self.profiles = {m.id: m.profile for m in members}
        self.vehicles = [m.id for m in modules if m.return_vehicle]
        self._modules = [m.id for m in modules]
        self._rng = {m.id: derive(seed, "response", m.id) for m in members}
        self._alarm_t: float | None = None
        self._clear_t: float | None = None
        self._react_at: dict[str, float] = {}
        self._evacuating = False
        self._sealed = False
        self._haven: str | None = None
        self._gathered_at: str | None = None
        self._acting: str | None = None
        self._assisting: dict[str, str] = {}  # medic id -> casualty id (to log each assignment once)
        self._approved: set[str] = set()
        self._repair_since: dict[str, float] = {}  # equipment emergency id -> when the engineer got there
        self._repaired: set[str] = set()

    # ---- helpers ---------------------------------------------------------------------------------
    def _graph(self, tick: SimulationTick) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = {m: set() for m in self._modules}
        for h in tick.hatches:
            # a return-vehicle hatch counts as passable: the crew opens it when they retreat
            if h.open or h.a in self.vehicles or h.b in self.vehicles:
                adj[h.a].add(h.b)
                adj[h.b].add(h.a)
        return adj

    def _find_haven(self, tick: SimulationTick, hazards: set[str]) -> str:
        if not self.vehicles:
            return next((m for m in self._modules if m not in hazards), self._modules[0])
        adj = self._graph(tick)
        dist = {v: 0 for v in self.vehicles}
        todo = deque(self.vehicles)
        while todo:
            node = todo.popleft()
            for n in sorted(adj[node]):
                if n not in dist and n not in hazards:
                    dist[n] = dist[node] + 1
                    todo.append(n)
        candidates = [m for m in dist if m not in self.vehicles]
        return min(candidates, key=lambda m: (dist[m], m)) if candidates else self.vehicles[0]

    def _acting_commander(self, tick: SimulationTick) -> str | None:
        """First in the succession who is not incapacitated. A commander who has not noticed the alarm yet is
        still the commander: only incapacity passes the command."""
        for profile in self.cfg.succession:
            for nid, prof in self.profiles.items():
                if prof == profile and tick.npcs[nid].vitals.get("health_state", 0.0) < _INCAPACITATED:
                    return nid
        return None

    @staticmethod
    def _casualties(tick: SimulationTick) -> tuple[list[str], dict[str, Emergency]]:
        """Crew in trouble: those the monitor flagged (confirmed ``medical`` emergencies) and anyone visibly hurt.
        Worst first (health state, then id)."""
        flagged = {e.subject: e for e in tick.emergencies
                   if e.kind == "medical" and e.state == "confirmed" and e.subject in tick.npcs}
        hurt = {nid for nid, n in tick.npcs.items() if n.vitals.get("health_state", 0.0) >= _CASUALTY}
        order = sorted(set(flagged) | hurt, key=lambda nid: (-tick.npcs[nid].vitals.get("health_state", 0.0), nid))
        return order, flagged

    def _assist_event(self, t: float, nid: str, victim: str, module: str, flagged: dict[str, Emergency]) -> MonitorEvent | None:
        if self._assisting.get(nid) == victim:
            return None
        self._assisting[nid] = victim
        em = flagged.get(victim)
        why = f" ({em.cause})" if em is not None and em.cause else ""
        return MonitorEvent(t_s=t, kind="crew_assisting", emergency_id=em.id if em is not None else None,
                            message=f"{nid} goes to help {victim}{why} in {module}")

    def _reset(self) -> None:
        self._alarm_t = self._clear_t = self._haven = self._gathered_at = self._acting = None
        self._evacuating = self._sealed = False
        self._react_at.clear()
        self._assisting.clear()
        self._approved.clear()

    def _medic_only(self, t: float, tick: SimulationTick, casualties: list[str], flagged: dict[str, Emergency],
                    out: CrewOrders) -> None:
        """No group alarm: the crew keeps its schedule, only the medic reacts to a crew member in trouble."""
        for nid, npc in tick.npcs.items():
            if self.cfg.roles.get(self.profiles[nid]) != "medical":
                continue
            if npc.vitals.get("health_state", 0.0) >= _INCAPACITATED:
                continue
            victim = next((c for c in casualties if c != nid), None)
            if victim is None:
                self._assisting.pop(nid, None)
                continue
            module = tick.npcs[victim].module_id
            out.orders[nid] = _block(module, "nominal", self.cfg.gather_met)
            out.phases[nid] = "assist"
            out.roles[nid] = "medical"
            ev = self._assist_event(t, nid, victim, module, flagged)
            if ev is not None:
                out.events.append(ev)

    def _repair(self, t: float, tick: SimulationTick, out: CrewOrders) -> None:
        """No group alarm: the engineer goes to the module with a confirmed equipment emergency (or a leak that is only
        a warning) and fixes it."""
        def leak(e: Emergency) -> bool:
            return e.kind == "depressurization"

        todo = [e for e in tick.emergencies if e.state == "confirmed" and e.id not in self._repaired
                and (e.kind == "equipment" or (leak(e) and e.severity == "warning"))]
        engineer = next((nid for nid in sorted(tick.npcs) if self.cfg.roles.get(self.profiles[nid]) == "systems"
                         and tick.npcs[nid].vitals.get("health_state", 0.0) < _INCAPACITATED), None)
        if not todo or engineer is None:
            return
        em = todo[0]
        out.orders[engineer] = _block(em.module_id, "nominal", self.cfg.gather_met)
        out.phases[engineer], out.roles[engineer] = "repair", "systems"
        if tick.npcs[engineer].module_id != em.module_id:
            return
        what, needs = ("the leak", self.cfg.repair_leak_s) if leak(em) else ("the equipment", self.cfg.repair_s)
        if em.id not in self._repair_since:
            self._repair_since[em.id] = t
            out.events.append(MonitorEvent(t_s=t, kind="crew_repairing", emergency_id=em.id,
                                           message=f"{engineer} starts repairing {what} in {em.module_id}"))
        if t - self._repair_since[em.id] >= needs:
            self._repaired.add(em.id)
            (out.leak_repairs if leak(em) else out.repairs).append(em.module_id)

    # ---- one tick --------------------------------------------------------------------------------
    def step(self, t: float, tick: SimulationTick, fires: dict[str, float | None] | None = None) -> CrewOrders:
        """``fires``: modules where a fire burns now -> when the extinguisher was last discharged there (None: not yet)."""
        fires = fires or {}
        out = CrewOrders()
        active: list[Emergency] = [e for e in tick.emergencies if e.state == "confirmed" and e.severity == "critical"
                                   and e.kind in self.cfg.gather_on]
        hazards = {e.module_id for e in active}

        if active:
            self._clear_t = None
            if self._alarm_t is None:
                self._alarm_t = t
                lo, hi = self.cfg.react_delay_s
                for nid, npc in tick.npcs.items():
                    delay = lo + (hi - lo) * float(self._rng[nid].random())
                    asleep = npc.activity == "sleep"
                    self._react_at[nid] = t + delay + (self.cfg.asleep_extra_delay_s if asleep else 0.0)
                out.events.append(MonitorEvent(
                    t_s=t, kind="crew_alerted", emergency_id=active[0].id,
                    message=f"alarm: {', '.join(sorted({e.kind for e in active}))} in {', '.join(sorted(hazards))}"))
        elif self._alarm_t is not None:
            self._clear_t = t if self._clear_t is None else self._clear_t
            if t - self._clear_t >= self.cfg.stand_down_delay_s:
                out.events.append(MonitorEvent(t_s=t, kind="crew_stood_down", message="all clear: back to the schedule"))
                self._reset()
        casualties, flagged = self._casualties(tick)
        if self._alarm_t is None:
            self._medic_only(t, tick, casualties, flagged, out)
            self._repair(t, tick, out)
            return out

        if active:
            self._haven = self._find_haven(tick, hazards)
            if not self._evacuating and any(e.tres_s is not None and e.tres_s <= self.cfg.evacuate_tres_s for e in active):
                self._evacuating = True
                out.events.append(MonitorEvent(t_s=t, kind="crew_evacuating", emergency_id=active[0].id,
                                               message="time to minimum pressure is running out: everyone to the return vehicle"))
            failed = next((m for m in sorted(hazards) if fires.get(m) is not None and t - fires[m] >= self.cfg.fire_evacuate_s), None)
            if not self._evacuating and failed is not None:
                self._evacuating = True
                out.events.append(MonitorEvent(t_s=t, kind="crew_evacuating", emergency_id=active[0].id,
                                               message=f"the extinguisher did not put out the fire in {failed}: everyone to the return vehicle"))
        assert self._haven is not None
        dest = self.vehicles[0] if self._evacuating and self.vehicles else self._haven

        ready = {nid for nid, at in self._react_at.items() if t >= at}
        acting = self._acting_commander(tick)
        if acting != self._acting and acting is not None:
            if self._acting is not None:
                out.events.append(MonitorEvent(t_s=t, kind="crew_command_passed",
                                               message=f"{acting} takes command (succession)"))
            self._acting = acting

        capable = [nid for nid in tick.npcs if tick.npcs[nid].vitals.get("health_state", 0.0) < _INCAPACITATED]

        for nid, npc in tick.npcs.items():
            hs = npc.vitals.get("health_state", 0.0)
            role = self.cfg.roles.get(self.profiles[nid], "sensing")
            if nid == self._acting:
                role = "incident_commander"
            out.roles[nid] = role
            if hs >= _INCAPACITATED:
                out.orders[nid] = _block(npc.module_id, "rest", 1.0)  # stays where they fell
                out.phases[nid] = "incapacitated"
                continue
            if nid not in ready:
                out.phases[nid] = "warn"  # alarm sounding, not yet noticed: keeps the schedule
                continue
            target, phase, met = dest, "evacuate" if self._evacuating else "work", self.cfg.gather_met
            if npc.module_id != dest:
                phase = "evacuate" if self._evacuating else "gather"
            elif role == "medical" and not self._evacuating:
                victim = next((c for c in casualties if c != nid and tick.npcs[c].module_id not in hazards), None)
                if victim is not None:
                    target, phase, met = tick.npcs[victim].module_id, "assist", self.cfg.gather_met
                    ev = self._assist_event(t, nid, victim, target, flagged)
                    if ev is not None:
                        out.events.append(ev)
            out.orders[nid] = _block(target, "nominal", met if phase != "work" else None)  # None: class MET
            out.phases[nid] = phase

        at_dest = [n for n in capable if tick.npcs[n].module_id == dest]
        if capable and len(at_dest) == len(capable) and self._gathered_at != dest:
            self._gathered_at = dest
            out.events.append(MonitorEvent(t_s=t, kind="crew_gathered",
                                           message=f"headcount complete in {dest}: {', '.join(sorted(capable))}"))

        if dest in self.vehicles:
            aboard = bool(capable) and len(at_dest) == len(capable)
            if self.cfg.seal_vehicle and not self._sealed and aboard:
                self._sealed = True  # everyone is aboard: the vehicle keeps its own air from now on
                out.close_hatches += [(h.a, h.b) for h in tick.hatches if h.open and dest in (h.a, h.b)]
                out.events.append(MonitorEvent(t_s=t, kind="crew_sealed", message=f"all aboard {dest}: its hatches are closed"))
            elif not self._sealed:  # the crew opens the vehicle's hatches to retreat into it: only while someone passes
                in_transit = any(nid in ready and tick.npcs[nid].module_id != dest for nid in capable)
                if in_transit or not self.cfg.seal_vehicle:
                    out.open_hatches += [(h.a, h.b) for h in tick.hatches if not h.open and dest in (h.a, h.b)]

        if self.cfg.npc_approves_actions and self._acting is not None and tick.npcs[self._acting].module_id == dest:
            for pa in tick.pending_actions:
                if pa.action.id not in self._approved and t >= pa.t_proposed_s + self.cfg.approve_delay_s:
                    self._approved.add(pa.action.id)
                    out.approvals.append((pa.action.id, self._acting))
        return out
