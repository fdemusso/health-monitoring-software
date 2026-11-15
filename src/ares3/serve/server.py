"""WebSocket server around a :class:`Session` (needs the ``serve`` extra: ``uv sync --extra serve``)."""

from __future__ import annotations

import asyncio
import hmac
import json
from urllib.parse import parse_qs, urlsplit

from .session import Session

MAX_CLIENT_MESSAGE = 64 * 1024  # bytes: a command is a few hundred


async def serve(session: Session, host: str = "127.0.0.1", port: int = 8765, ready: asyncio.Future | None = None, *,
                token: str | None = None, origins: list[str] | None = None, max_clients: int = 100,
                guest_commands: frozenset[str] = frozenset(), warmup_s: float = 0.0) -> None:
    """Serve until cancelled. Every client gets the same frames. ``ready`` (optional) receives the port.

    Without ``token`` every client may send commands (local development). With one, a client that connects with ``?token=<token>`` is
    an OPERATOR (commands allowed); any other is a VIEWER: it gets the frames and its commands are refused with a result. ``origins``
    (e.g. ``["https://ares.daado.dev"]``) lists the pages allowed to open the socket from a browser; clients that send no Origin
    (scripts) are let in, a browser always sends one. At most ``max_clients`` connections at a time. A viewer may still send the
    commands named in ``guest_commands`` (e.g. ``approve_action``, ``ack_step``: the crew-facing ones, so a visitor can take part in
    the response without being able to inject faults, reset or change the speed). With ``warmup_s`` the port opens at once and the
    simulation runs that many seconds ahead while the clients get ``warming`` frames (see ``session.py``)."""
    from websockets.asyncio.server import broadcast
    from websockets.asyncio.server import serve as ws_serve

    clients: set = set()

    def role_of(ws) -> str:
        if token is None:
            return "operator"
        given = parse_qs(urlsplit(ws.request.path).query).get("token", [""])[0]
        return "operator" if hmac.compare_digest(given.encode(), token.encode()) else "viewer"

    async def handler(ws) -> None:
        if len(clients) >= max_clients:
            await ws.close(1013, "server busy")
            return
        role = role_of(ws)
        clients.add(ws)
        session.watchers = len(clients)
        try:
            await ws.send(session.hello(role))
            if session.state == "warming":
                await ws.send(session.warming_frame())
            history = session.history()
            if history is not None:
                await ws.send(history)
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = None
                if (role == "viewer" and isinstance(msg, dict) and msg.get("type") == "command"
                        and msg.get("cmd") not in guest_commands):
                    reply = {"type": "result", "id": msg.get("id"), "ok": False,
                             "error": f"read-only connection: {msg.get('cmd')!r} needs the operator token"}
                else:
                    reply = session.handle(msg)
                await ws.send(json.dumps(reply))
        finally:
            clients.discard(ws)
            session.watchers = len(clients)

    allowed = None if origins is None else [*origins, None]
    async with ws_serve(handler, host, port, origins=allowed, max_size=MAX_CLIENT_MESSAGE) as server:
        if ready is not None:
            ready.set_result(next(iter(server.sockets)).getsockname()[1])
        def emit(frame: str) -> None:
            broadcast(clients, frame)

        if warmup_s > 0:
            await session.warm_up_async(warmup_s, emit)
        runner = asyncio.create_task(session.run(emit))
        try:
            await server.serve_forever()
        finally:
            runner.cancel()
