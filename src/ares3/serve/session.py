"""A running simulation paced against the wall clock, driven by JSON messages.

Transport-free on purpose: ``Session.handle`` takes a decoded client message and returns the reply, ``Session.run`` yields
the frames to broadcast, so the protocol is testable without a socket (``server.py`` only moves the text around).
Everything runs on one asyncio loop, so the engine is never touched from two places at once.

Server -> client (JSON text frames):
  {"type": "hello", "scenario": str, "dt_s": float, "paused": bool, "speed": float, "role": "operator" | "viewer"}
      a viewer (connected without the server's token) gets the frames but every command is refused.
  {"type": "history", "samples": [{"t_sim_s", "npcs", "modules"}, ...]}
      sent once to a new client right after ``hello``: the last 6 simulated hours, one sample per simulated minute, so the charts are
      full at once instead of starting empty at the moment of connection (nothing is sent when there is no history yet).
  {"type": "tick", "tick": <SimulationTick>, "paused": bool, "speed": float}
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

    # ---- stepping --------------------------------------------------------------------------------
    def advance(self, n: int) -> None:
        """Step the engine ``n`` ticks now (the pacing loop and the tests use this)."""
        for _ in range(n):
            res = self.engine.step()
            self._latest = res.tick
            self._events.extend(res.tick.monitor_events)
            if not self._history or res.tick.t_sim_s - self._history[-1]["t_sim_s"] >= HISTORY_STEP_S:
                self._history.append(res.tick.model_dump(mode="json", include={"t_sim_s", "npcs", "modules"}))

    def warm_up(self, seconds: float, progress: Callable[[float], None] | None = None) -> None:
        """Run the simulation ahead before the first client connects: the ML detectors need hours of history before they judge,
        and the charts of the first client should not start empty. The events of these hours are dropped."""
        todo = int(seconds / self.scenario.file.dt_s)
        for done in range(0, todo, 600):
            self.advance(min(600, todo - done))
            if progress is not None:
                progress(min(1.0, (done + 600) / todo))
        self._events = []

    def history(self) -> str | None:
        """The ``history`` message for a new client, or None when nothing was recorded."""
        if not self._history:
            return None
        return json.dumps({"type": "history", "samples": list(self._history)})

    def frame(self) -> str | None:
        """The tick message to broadcast (latest tick + events since the last frame), or None before the first tick."""
        if self._latest is None:
            return None
        tick = self._latest.model_copy(update={"monitor_events": tuple(self._events)})
        self._events = []
        return (f'{{"type":"tick","paused":{json.dumps(self.paused)},"speed":{self.speed},'
                f'"tick":{tick.model_dump_json()}}}')

    def hello(self, role: str = "operator") -> str:
        return json.dumps({"type": "hello", "scenario": self.scenario.file.name, "dt_s": self.scenario.file.dt_s,
                           "paused": self.paused, "speed": self.speed, "role": role})

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
        else:
            raise ValueError(f"unknown command {cmd!r}")
        return None
