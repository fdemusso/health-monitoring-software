import asyncio
import json

import pytest

from ares3.serve import Session

_FIRE = {"id": "dbg", "type": "fire", "targets": ["lab"], "start_s": 0, "params": {"heat_w": 1000},
         "anomaly_type": "fire", "priority": 10}


def _cmd(cmd, rid=1, **args):
    return {"type": "command", "id": rid, "cmd": cmd, "args": args}


def test_frame_carries_the_events_of_every_skipped_tick(station):
    s = Session(station, paused=True)
    s.handle(_cmd("inject_event", fault=_FIRE))
    s.advance(200)
    tick = json.loads(s.frame())["tick"]
    assert tick["tick"] == 199 and {"emergencies", "pending_actions", "monitor_events"} <= tick.keys()
    assert any(e["kind"] == "emergency_confirmed" for e in tick["monitor_events"])  # confirmed several ticks before the frame
    s.advance(1)
    assert all(e["kind"] != "emergency_confirmed" for e in json.loads(s.frame())["tick"]["monitor_events"])  # sent once


def test_commands_drive_the_engine(station):
    s = Session(station, paused=True)
    r = s.handle(_cmd("inject_event", rid="a", fault=_FIRE))
    assert r["ok"] and r["id"] == "a" and r["data"]["id"] == "dbg"
    pending = []
    for _ in range(300):  # until the monitor has confirmed the fire and proposes the extinguisher
        s.advance(1)
        pending = json.loads(s.frame())["tick"]["pending_actions"]
        if pending:
            break
    assert pending
    assert s.handle(_cmd("approve_action", action_id=pending[0]["action"]["id"], by="ui"))["ok"]
    assert s.handle(_cmd("declare_emergency", kind="fire", module_id="hab"))["data"]
    assert s.handle(_cmd("stop_event", fault_id="dbg"))["ok"]


def test_bad_messages_are_replies_not_crashes(station):
    s = Session(station, paused=True)
    for msg in (None, "x", {"type": "command"}, _cmd("nope"), _cmd("approve_action", action_id="zzz"),
                _cmd("inject_event", fault={"id": "x"}), _cmd("inject_event"), _cmd("set_speed", speed=-1)):
        r = s.handle(msg)
        assert r["ok"] is False and r["error"]


def test_pause_speed_and_reset(station):
    s = Session(station, paused=True, speed=5.0)
    s.advance(10)
    assert s.handle(_cmd("set_speed", speed=60))["ok"] and s.speed == 60.0
    s.handle(_cmd("resume"))
    assert s.paused is False
    s.handle(_cmd("reset"))
    assert s.frame() is None
    s.advance(1)
    assert json.loads(s.frame())["tick"]["tick"] == 0


def test_pacing_loop_runs_at_the_requested_speed(station):
    s = Session(station, speed=100.0, max_fps=50.0)  # dt 1 s -> 100 ticks per real second
    frames: list[str] = []

    async def go():
        task = asyncio.create_task(s.run(frames.append))
        await asyncio.sleep(0.5)
        task.cancel()

    asyncio.run(go())
    assert frames
    assert 20 <= json.loads(frames[-1])["tick"]["tick"] <= 80


def test_websocket_end_to_end(station):
    pytest.importorskip("websockets")
    from websockets.asyncio.client import connect

    from ares3.serve.server import serve

    async def go():
        s = Session(station, speed=200.0, max_fps=20.0)
        ready = asyncio.get_running_loop().create_future()
        server = asyncio.create_task(serve(s, "127.0.0.1", 0, ready))
        port = await ready
        try:
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                assert json.loads(await ws.recv())["type"] == "hello"
                await ws.send(json.dumps(_cmd("inject_event", rid=7, fault=_FIRE)))
                seen_result, tick = False, None
                while not (seen_result and tick and tick["emergencies"]):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if m["type"] == "result":
                        assert m["id"] == 7 and m["ok"]
                        seen_result = True
                    elif m["type"] == "tick":
                        tick = m["tick"]
                assert tick["emergencies"][0]["kind"] == "fire"
        finally:
            server.cancel()
            await asyncio.wait([server], timeout=5)

    asyncio.run(go())
