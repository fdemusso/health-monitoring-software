"""A stand-in for the dashboard: connects to ``ares3 serve``, injects a fault of the catalog and prints what a UI would show
(mode, emergencies with their alert class and evidence, requests waiting for a confirmation, procedure steps).

    uv run ares3 serve scenarios/station/nominal.yaml --speed 60 &
    uv run python tools/demo_client.py --fault fire --module COL --seconds 90 --approve --ack
    uv run python tools/demo_client.py --fault leak --module USL            # slow leak the crew patches
    uv run python tools/demo_client.py --fault stuck --sensor nod2_ppCO2_a  # sensor fault, a substitute is proposed

Use it to check a deployment too: ``--url wss://ares-api.daado.dev --token ...`` (the token is sent as ``?token=`` when the server asks for one).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

FAULTS = {
    "fire": lambda a: {"id": "demo_fire", "type": "fire", "targets": [a.module], "params": {"heat_w": 300.0}, "anomaly_type": "fire", "priority": 9},
    "leak": lambda a: {"id": "demo_leak", "type": "leak", "targets": [a.module], "params": {"kpa_min": 0.05}, "anomaly_type": "leak", "priority": 7},
    "rapid_leak": lambda a: {"id": "demo_hole", "type": "leak", "targets": [a.module], "params": {"kpa_min": 4.0}, "duration_s": 1800,
                             "anomaly_type": "leak", "priority": 9},
    "stuck": lambda a: {"id": "demo_stuck", "type": "stuck", "targets": [a.sensor], "params": {}, "anomaly_type": "stuck", "priority": 5},
    "co_source": lambda a: {"id": "demo_co", "type": "co_source", "targets": [a.module], "params": {"mol_s": 2e-5}, "anomaly_type": "co", "priority": 8},
}


async def main(a: argparse.Namespace) -> int:
    from websockets.asyncio.client import connect

    url = a.url + (f"?token={a.token}" if a.token else "")
    async with connect(url, max_size=2**24) as ws:
        hello = json.loads(await ws.recv())
        print(f"connected: {hello.get('scenario')} dt={hello.get('dt_s')} s speed={hello.get('speed')}")
        rid = 0

        async def send(cmd: str, **args) -> None:
            nonlocal rid
            rid += 1
            await ws.send(json.dumps({"type": "command", "id": rid, "cmd": cmd, "args": args}))

        await send("set_speed", speed=a.speed)
        if a.fault != "none":
            fault = FAULTS[a.fault](a)
            fault["id"] += f"_{int(time.time())}"  # the session keeps every id: a second run of the demo needs its own
            await send("inject_event", fault=fault)
        mode, shown, acked, approved = None, set(), set(), set()
        t0 = time.monotonic()
        while time.monotonic() - t0 < a.seconds:
            m = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if m["type"] == "result":
                if not m["ok"]:
                    print(f"  command {m['id']} refused: {m.get('error')}")
                continue
            if m["type"] != "tick":
                continue
            t = m["tick"]
            if t["monitor_mode"] != mode:
                mode = t["monitor_mode"]
                print(f"[t={t['t_sim_s']:>7.0f} s] MODE -> {mode}")
            for e in t["monitor_events"]:
                if e["kind"] != "mode_changed" and e["message"] not in shown:
                    shown.add(e["message"])
                    print(f"[t={e['t_s']:>7.0f} s]   {e['kind']}: {e['message'][:140]}")
            for p in t["pending_actions"]:
                if p["action"]["id"] not in approved:
                    print(f"           request {p['action']['id']}: {p['action']['kind']} {p['action'].get('command')} on {p['action']['target']} "
                          f"(timeout {p['on_timeout']})")
                    if a.approve:
                        approved.add(p["action"]["id"])
                        await send("approve_action", action_id=p["action"]["id"], by="demo")
            for pr in t.get("procedures") or []:
                for st in pr["steps"]:
                    key = (pr["procedure_id"], pr["subject"], st["id"])
                    if st["state"] == "active" and key not in acked:
                        acked.add(key)
                        print(f"           step {pr['procedure_id']}/{st['id']}: {st['text'][:100]}")
                        if a.ack:
                            await send("ack_step", procedure_id=pr["id"], step_id=st["id"], by="demo")
        em = [(e["kind"], e["module_id"], e["state"], e.get("alert_class")) for e in t["emergencies"]]
        print(f"end: mode={mode} emergencies={em} powered_off={t.get('powered_off')} ml={ {k: round(v, 2) for k, v in (t.get('ml') or {}).items()} }")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    p.add_argument("--token")
    p.add_argument("--fault", choices=[*FAULTS, "none"], default="fire")
    p.add_argument("--module", default="COL")
    p.add_argument("--sensor", default="nod2_ppCO2_a")
    p.add_argument("--speed", type=float, default=60.0)
    p.add_argument("--seconds", type=float, default=60.0, help="real seconds to watch")
    p.add_argument("--approve", action="store_true", help="approve every request, as a crew member would")
    p.add_argument("--ack", action="store_true", help="close every procedure step")
    raise SystemExit(asyncio.run(main(p.parse_args())))
