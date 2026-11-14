"""WebSocket server around a :class:`Session` (needs the ``serve`` extra: ``uv sync --extra serve``)."""

from __future__ import annotations

import asyncio
import json

from .session import Session


async def serve(session: Session, host: str = "127.0.0.1", port: int = 8765, ready: asyncio.Future | None = None) -> None:
    """Serve until cancelled. Every client gets the same frames and may send commands. ``ready`` (optional) receives the port."""
    from websockets.asyncio.server import broadcast
    from websockets.asyncio.server import serve as ws_serve

    clients: set = set()

    async def handler(ws) -> None:
        clients.add(ws)
        try:
            await ws.send(session.hello())
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = None
                await ws.send(json.dumps(session.handle(msg)))
        finally:
            clients.discard(ws)

    async with ws_serve(handler, host, port) as server:
        if ready is not None:
            ready.set_result(next(iter(server.sockets)).getsockname()[1])
        runner = asyncio.create_task(session.run(lambda frame: broadcast(clients, frame)))
        try:
            await server.serve_forever()
        finally:
            runner.cancel()
