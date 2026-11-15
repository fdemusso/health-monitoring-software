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


def test_ack_step_closes_a_procedure_step_from_the_ui(station):
    s = Session(station, paused=True)
    s.engine.procedures.follow = False  # nobody but the UI closes steps
    s.handle(_cmd("declare_emergency", kind="medical", module_id="hab"))
    procedure = None
    for _ in range(10):
        s.advance(1)
        procs = json.loads(s.frame())["tick"]["procedures"]
        if procs:
            procedure = procs[0]
            break
    assert procedure and procedure["current"] == "s1" and procedure["steps"][0]["status"] == "active"
    tick = json.loads(s.frame())["tick"]
    assert tick["monitor_mode"] == "reaction" and tick["ml"] == {} and tick["powered_off"] == []
    assert s.handle(_cmd("ack_step", procedure_id=procedure["id"], step_id="s1", by="ui-user"))["ok"]
    s.advance(1)
    step = json.loads(s.frame())["tick"]["procedures"][0]["steps"][0]
    assert step["status"] == "done" and step["by"] == "ui-user"
    assert s.handle(_cmd("ack_step", procedure_id=procedure["id"], step_id="zzz"))["ok"] is False


def test_warm_up_fills_the_history_a_new_client_receives(station):
    s = Session(station, paused=True)
    assert s.history() is None  # nothing recorded yet: no message
    progress = []
    s.warm_up(1200, progress.append)
    msg = json.loads(s.history())
    assert msg["type"] == "history" and len(msg["samples"]) == 20  # one per simulated minute
    first = msg["samples"][0]
    assert {"t_sim_s", "npcs", "modules"} <= first.keys() and first["npcs"] and first["modules"]
    assert msg["samples"][1]["t_sim_s"] - first["t_sim_s"] == 60.0
    assert progress[-1] == 1.0
    assert json.loads(s.frame())["tick"]["tick"] == 1199 and json.loads(s.frame())["tick"]["monitor_events"] == []  # the hours before are not replayed
    s.handle(_cmd("reset"))
    assert s.history() is None  # a reset starts cold


def test_history_is_capped_at_six_hours(station):
    s = Session(station, paused=True)
    s.advance(7 * 3600)
    assert len(json.loads(s.history())["samples"]) == 360


def test_token_makes_an_operator_and_origins_are_checked(station):
    pytest.importorskip("websockets")
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    from ares3.serve.server import serve

    async def go():
        s = Session(station, speed=50.0, max_fps=20.0, max_speed=200.0)
        ready = asyncio.get_running_loop().create_future()
        server = asyncio.create_task(serve(s, "127.0.0.1", 0, ready, token="s3cret", origins=["https://ares.example"]))
        port = await ready
        try:
            async def ask(url, cmd, **kw):
                async with connect(url, **kw) as ws:
                    hello = json.loads(await ws.recv())
                    await ws.send(json.dumps(_cmd(cmd, rid=3, **({"speed": 100000} if cmd == "set_speed" else {}))))
                    while (m := json.loads(await ws.recv()))["type"] != "result":
                        pass
                    return hello["role"], m

            ok = {"origin": "https://ares.example"}
            role, reply = await ask(f"ws://127.0.0.1:{port}/?token=s3cret", "pause", **ok)
            assert role == "operator" and reply["ok"]
            role, reply = await ask(f"ws://127.0.0.1:{port}/", "pause", **ok)  # no token: watches only
            assert role == "viewer" and not reply["ok"] and "read-only" in reply["error"]
            role, reply = await ask(f"ws://127.0.0.1:{port}/?token=wrong", "pause", **ok)
            assert role == "viewer" and not reply["ok"]
            _, reply = await ask(f"ws://127.0.0.1:{port}/?token=s3cret", "set_speed", **ok)  # the server's own ceiling
            assert not reply["ok"] and "200" in reply["error"]
            with pytest.raises(InvalidStatus) as err:  # a page of another site
                await ask(f"ws://127.0.0.1:{port}/?token=s3cret", "pause", origin="https://evil.example")
            assert err.value.response.status_code == 403
            role, _ = await ask(f"ws://127.0.0.1:{port}/?token=s3cret", "pause")  # a script sends no Origin
            assert role == "operator"
        finally:
            server.cancel()
            await asyncio.wait([server], timeout=5)

    asyncio.run(go())


def test_a_viewer_may_send_only_the_guest_commands(station):
    pytest.importorskip("websockets")
    from websockets.asyncio.client import connect

    from ares3.serve.server import serve

    async def go():
        s = Session(station, speed=50.0, max_fps=20.0)
        ready = asyncio.get_running_loop().create_future()
        server = asyncio.create_task(serve(s, "127.0.0.1", 0, ready, token="s3cret", guest_commands=frozenset({"approve_action"})))
        port = await ready
        try:
            async with connect(f"ws://127.0.0.1:{port}/") as ws:  # a visitor, no token
                assert json.loads(await ws.recv())["role"] == "viewer"

                async def reply(cmd, **args):
                    await ws.send(json.dumps(_cmd(cmd, rid=9, **args)))
                    while (m := json.loads(await ws.recv()))["type"] != "result":
                        pass
                    return m

                allowed = await reply("approve_action", action_id="nope")  # reaches the session: its own error, not the read-only one
                assert "read-only" not in allowed.get("error", "")
                refused = await reply("pause")
                assert not refused["ok"] and "'pause' needs the operator token" in refused["error"]
        finally:
            server.cancel()
            await asyncio.wait([server], timeout=5)

    asyncio.run(go())


def test_a_server_with_nobody_connected_stands_still(station):
    async def go():
        s = Session(station, speed=500.0, max_fps=50.0, pause_when_idle=True)
        task = asyncio.create_task(s.run(lambda frame: None))
        try:
            await asyncio.sleep(0.3)
            assert s._latest is None  # nobody watches: no tick was made
            s.watchers = 1
            await asyncio.sleep(0.5)
            assert s._latest is not None and s._latest.tick > 50  # the first visitor wakes it
            s.watchers = 0
            stopped = s._latest.tick
            await asyncio.sleep(0.4)
            assert s._latest.tick - stopped < 5  # and it stops again
        finally:
            task.cancel()
            await asyncio.wait([task], timeout=5)

    asyncio.run(go())


def test_a_warm_up_that_is_served_reports_progress_and_refuses_commands(station):
    s = Session(station, paused=True)
    frames, during = [], []

    def emit(frame):
        frames.append(json.loads(frame))
        if len(frames) == 1:  # a client that asks something while the engine is running ahead
            during.append((json.loads(s.hello())["state"], s.history(), s.handle(_cmd("pause"))))

    asyncio.run(s.warm_up_async(1200, emit, chunk=100, report_every_s=0))
    state, history, reply = during[0]
    assert state == "warming" and history is None and not reply["ok"] and "warming up" in reply["error"]
    kinds = [f["type"] for f in frames]
    assert kinds[-2:] == ["history", "ready"] and kinds.count("warming") >= 3
    progress = [f["progress"] for f in frames if f["type"] == "warming"]
    assert progress == sorted(progress) and progress[-1] == 1.0 and frames[0]["total_s"] == 1200.0
    assert len(frames[-2]["samples"]) == 20  # the charts of every client start full
    assert json.loads(s.hello())["state"] == "live" and s.handle(_cmd("pause"))["ok"]
    assert json.loads(s.frame())["tick"]["monitor_events"] == []  # the hours before are not replayed


def test_history_and_frames_carry_what_the_wearables_read(station):
    s = Session(station, paused=True)
    s.advance(1200)
    msg = json.loads(s.history())
    assert len(msg["vitals"]) == 120 and msg["vitals"][1]["t_sim_s"] - msg["vitals"][0]["t_sim_s"] == 10.0  # one per 10 simulated s
    crew = next(iter(json.loads(s.frame())["tick"]["npcs"]))
    assert {"hr", "spo2"} <= msg["vitals"][-1]["w"][crew].keys()
    frame = json.loads(s.frame())
    assert frame["wearables"][crew]["hr"] != frame["tick"]["npcs"][crew]["vitals"]["hr"]  # measured (noisy), not the ground truth
    s.advance(7 * 3600)
    assert len(json.loads(s.history())["vitals"]) == 2160
