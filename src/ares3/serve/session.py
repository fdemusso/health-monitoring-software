"""A running simulation paced against the wall clock, driven by JSON messages.

Transport-free on purpose: ``Session.handle`` takes a decoded client message and returns the reply, ``Session.run`` yields
the frames to broadcast, so the protocol is testable without a socket (``server.py`` only moves the text around).
Everything runs on one asyncio loop, so the engine is never touched from two places at once.

Server -> client (JSON text frames):
  {"type": "hello", "scenario": str, "dt_s": float, "paused": bool, "speed": float, "role": "operator" | "viewer",
   "state": "warming" | "live", "procedures": [{id, emergency, cause, severity, title, steps: [{id, kind, text, role}]}]}
      ``procedures`` is the catalog of crew procedures (static): the UI proposes the right one before the emergency is confirmed.
      a viewer (connected without the server's token) gets the frames but every command is refused. ``state`` is "warming" while the
      server runs the simulation ahead (``--warmup-h``): the port is open from the start so a UI can show progress instead of a dead
      page. No ``tick`` or ``history`` is sent and every command is refused until the state is "live".
  {"type": "warming", "progress": 0..1, "sim_s": float, "total_s": float}
      during the warm-up, about four times a second (and right after ``hello`` for a client that connects late).
  {"type": "ready"}
      the warm-up is over: ``history`` (to every client) then this, then ticks start. Not sent when there was no warm-up.
  {"type": "history", "samples": [{"t_sim_s", "npcs", "modules"}, ...], "vitals": [{"t_sim_s", "w": {crew: {metric: value}}}, ...]}
      sent once to a new client right after ``hello``: the last 6 simulated hours, so the charts are
      full at once instead of starting empty at the moment of connection (nothing is sent when there is no history yet).
      ``samples`` has one point per simulated minute (modules and ground truth); ``vitals`` one per 10 simulated seconds with what
      the crew's WEARABLES read (hr, spo2, resp_rate, core_temp_c, cohb_pct: sensed values, noisy, as the monitor sees them).
  {"type": "tick", "tick": <SimulationTick>, "wearables": {crew: {metric: value}}, "paused": bool, "speed": float}
      ``tick.monitor_events`` holds the events of every tick since the last frame, so none is lost when frames are thinned.
  {"type": "result", "id": <echo>, "ok": bool, "error"?: str, "data"?: any}
Client -> server:
  {"type": "command", "id": any, "cmd": <name>, "args": {...}} with ``cmd`` one of
  inject_event {fault: FaultSpec} | stop_event {fault_id} | approve_action {action_id, by?} | reject_action {action_id, by?}
  | ack_step {procedure_id, step_id, by?, answer?} | declare_emergency {kind, module_id, by?} | pause | resume | set_speed {speed} | reset
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ares3.core.engine import Engine
from ares3.schemas.faults import FaultSpec
from ares3.schemas.scenario import Scenario
from ares3.sdk.types import MonitorEvent, SimulationTick

MAX_BATCH = 5000  # ticks stepped per loop iteration at most: a slow machine falls behind instead of freezing the loop
HISTORY_STEP_S = 60.0  # simulated seconds between two history samples
HISTORY_LEN = 360  # samples kept: 6 simulated hours
VITALS_STEP_S = 10.0  # the crew's vital signs are kept at a finer step: the charts of a short window need more than 15 points
VITALS_LEN = 2160  # 6 simulated hours at VITALS_STEP_S
WEARABLE_METRICS = ("hr", "spo2", "resp_rate", "core_temp_c", "cohb_pct")  # what the crew's wearables report (what the UI charts)


class Session:
    def __init__(self, scenario: Scenario, *, speed: float = 10.0, paused: bool = False, max_fps: float = 10.0,
                 max_speed: float = 100_000.0, pause_when_idle: bool = False) -> None:
        self.scenario = scenario
        self.max_speed = max_speed
        self.pause_when_idle = pause_when_idle  # no client connected: the simulation stands still (a public server costs nothing when nobody looks)
        self.watchers = 0  # connected clients, kept by the server
        self.speed = speed  # simulated seconds per real second
        self.paused = paused
        self.max_fps = max_fps
        self.engine = Engine(scenario)
        self._latest: SimulationTick | None = None
        self._events: list[MonitorEvent] = []
        self._owed = 0.0  # fractional ticks carried to the next iteration
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LEN)
        self._vitals: deque[dict[str, Any]] = deque(maxlen=VITALS_LEN)
        self._wearables: dict[str, dict[str, float]] = {}  # latest reading of each wearable (measured: noisy, fault-corrupted), by crew id
        self.state = "live"  # "warming" while warm_up_async runs
        self._warm = (0.0, 0.0)  # simulated seconds done, total

    # ---- stepping --------------------------------------------------------------------------------
    def advance(self, n: int) -> None:
        """Step the engine ``n`` ticks now (the pacing loop and the tests use this)."""
        for _ in range(n):
            res = self.engine.step()
            self._latest = res.tick
            self._events.extend(res.tick.monitor_events)
            self._wearables = self._read_wearables(res)
            if not self._vitals or res.tick.t_sim_s - self._vitals[-1]["t_sim_s"] >= VITALS_STEP_S:
                self._vitals.append({"t_sim_s": res.tick.t_sim_s, "w": self._wearables})
            if not self._history or res.tick.t_sim_s - self._history[-1]["t_sim_s"] >= HISTORY_STEP_S:
                self._history.append(res.tick.model_dump(mode="json", include={"t_sim_s", "npcs", "modules"}))

    @staticmethod
    def _read_wearables(res: Any) -> dict[str, dict[str, float]]:
        """The crew wearables' readings of this tick (sensed values, rounded for the wire), by crew id and metric."""
        out: dict[str, dict[str, float]] = {}
        for o in res.observations:
            if o.entity_id in res.tick.npcs and o.metric in WEARABLE_METRICS:
                out.setdefault(o.entity_id, {})[o.metric] = round(float(o.value), 2)
        return out

    def warm_up(self, seconds: float, progress: Callable[[float], None] | None = None) -> None:
        """Run the simulation ahead before the first client connects: the ML detectors need hours of history before they judge,
        and the charts of the first client should not start empty. The events of these hours are dropped."""
        todo = int(seconds / self.scenario.file.dt_s)
        for done in range(0, todo, 600):
            self.advance(min(600, todo - done))
            if progress is not None:
                progress(min(1.0, (done + 600) / todo))
        self._events = []

    async def warm_up_async(self, seconds: float, emit: Callable[[str], None], *, chunk: int = 100, report_every_s: float = 0.25) -> None:
        """Like :meth:`warm_up` but served: the engine advances ``chunk`` ticks at a time and hands the loop back in between, so
        clients can connect and receive ``warming`` frames (``emit``); ends with ``history`` and ``ready``. Commands are refused meanwhile."""
        dt = self.scenario.file.dt_s
        todo = int(seconds / dt)
        self.state, self._warm = "warming", (0.0, todo * dt)
        last_report = 0.0
        for done in range(0, todo, chunk):
            self.advance(min(chunk, todo - done))
            self._warm = (min(todo, done + chunk) * dt, todo * dt)
            now = time.monotonic()
            if now - last_report >= report_every_s:
                emit(self.warming_frame())
                last_report = now
            await asyncio.sleep(0)
        self._events = []
        self.state = "live"
        emit(self.warming_frame())  # 100 %: the last report may have been skipped
        history = self.history()
        if history is not None:
            emit(history)
        emit('{"type":"ready"}')

    def warming_frame(self) -> str:
        done, total = self._warm
        return json.dumps({"type": "warming", "progress": min(1.0, done / total) if total else 1.0, "sim_s": done, "total_s": total})

    def history(self) -> str | None:
        """The ``history`` message for a new client, or None when nothing was recorded (or the warm-up is still running)."""
        if not self._history or self.state == "warming":
            return None
        return json.dumps({"type": "history", "samples": list(self._history), "vitals": list(self._vitals)})

    def frame(self) -> str | None:
        """The tick message to broadcast (latest tick + events since the last frame), or None before the first tick."""
        if self._latest is None:
            return None
        tick = self._latest.model_copy(update={"monitor_events": tuple(self._events)})
        self._events = []
        return (f'{{"type":"tick","paused":{json.dumps(self.paused)},"speed":{self.speed},'
                f'"wearables":{json.dumps(self._wearables)},"tick":{tick.model_dump_json()}}}')

    def hello(self, role: str = "operator") -> str:
        return json.dumps({"type": "hello", "scenario": self.scenario.file.name, "dt_s": self.scenario.file.dt_s,
                           "paused": self.paused, "speed": self.speed, "role": role, "state": self.state,
                           "procedures": self._catalog()})

    def _catalog(self) -> list[dict[str, Any]]:
        """Every crew procedure of the scenario (static): the UI shows the right one before the emergency is confirmed, and as a library.
        ``{subject}`` and ``{module}`` are left in the texts (the running procedures in ``tick.procedures`` have them filled in)."""
        return [{"id": p.id, "emergency": p.emergency, "cause": p.cause, "severity": p.severity, "title": p.title,
                 "steps": [{"id": st.id, "kind": st.do, "text": st.text, "role": st.role} for st in p.steps]}
                for p in self.scenario.monitor.procedures]

    async def run(self, emit: Callable[[str], None]) -> None:
        """Pace the engine to the wall clock until cancelled; ``emit`` receives each frame (at most ``max_fps`` per second)."""
        dt = self.scenario.file.dt_s
        last = last_emit = time.monotonic()
        dirty = False
        while True:
            now = time.monotonic()
            if not self.paused and not (self.pause_when_idle and self.watchers == 0):
                self._owed = min(self._owed + (now - last) * self.speed / dt, float(MAX_BATCH))
                n = int(self._owed)
                self._owed -= n
                if n:
                    self.advance(n)
                    dirty = True
            last = now
            if dirty and now - last_emit >= 1.0 / self.max_fps:
                frame = self.frame()
                if frame is not None:
                    emit(frame)
                    last_emit, dirty = now, False
            await asyncio.sleep(0.01)

    # ---- commands --------------------------------------------------------------------------------
    def handle(self, msg: Any) -> dict[str, Any]:
        """Run one client message; always returns a ``result`` reply (errors are replies, never exceptions)."""
        rid = msg.get("id") if isinstance(msg, dict) else None
        reply: dict[str, Any] = {"type": "result", "id": rid, "ok": True}
        try:
            if not isinstance(msg, dict) or msg.get("type") != "command" or not isinstance(msg.get("cmd"), str):
                raise ValueError('expected {"type": "command", "cmd": ..., "args": {...}}')
            if self.state == "warming":
                raise ValueError("the simulation is warming up: commands are accepted when it is ready")
            data = self._dispatch(msg["cmd"], msg.get("args") or {})
            if data is not None:
                reply["data"] = data
        except (ValueError, KeyError, ValidationError) as e:
            reply.update(ok=False, error=f"unknown or missing: {e}" if isinstance(e, KeyError) else str(e))
        return reply

    def _dispatch(self, cmd: str, a: dict[str, Any]) -> Any:
        e = self.engine
        by = a.get("by")
        if cmd == "inject_event":
            return e.inject(FaultSpec.model_validate({"start_s": 0, **a["fault"]})).model_dump(mode="json")
        if cmd == "stop_event":
            e.stop_event(a["fault_id"])
        elif cmd == "approve_action":
            e.approve_action(a["action_id"], by)
        elif cmd == "reject_action":
            e.reject_action(a["action_id"], by)
        elif cmd == "ack_step":
            e.ack_step(a["procedure_id"], a["step_id"], by, a.get("answer"))
        elif cmd == "declare_emergency":
            return e.declare_emergency(a["kind"], a["module_id"], by)
        elif cmd == "pause":
            self.paused = True
        elif cmd == "resume":
            self.paused = False
        elif cmd == "set_speed":
            speed = float(a["speed"])
            if not 0.0 < speed <= self.max_speed:
                raise ValueError(f"speed must be in (0, {self.max_speed:g}] simulated seconds per second")
            self.speed = speed
        elif cmd == "reset":
            self.engine = Engine(self.scenario)
            self._latest, self._events, self._owed = None, [], 0.0
            self._history.clear()  # a reset starts cold: the warm-up is only run at startup
            self._vitals.clear()
            self._wearables = {}
        else:
            raise ValueError(f"unknown command {cmd!r}")
        return None
