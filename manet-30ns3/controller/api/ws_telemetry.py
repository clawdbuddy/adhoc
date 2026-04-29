"""WS /ws/telemetry — 1 Hz JSON frames matching the React UI's NodeStatus/FlowStats."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from controller.api.state import get_session

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket) -> None:
    await ws.accept()
    sess = get_session()
    if not sess.telemetry:
        # Send a single empty frame and close — UI can reconnect once a sim starts.
        await ws.send_json({"running": False, "nodes": [], "flows": [], "t": 0.0})
        await ws.close()
        return

    queue = sess.telemetry.subscribe()
    try:
        while True:
            frame = await queue.get()
            await ws.send_json(frame)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ws send failed")
    finally:
        if sess.telemetry:
            sess.telemetry.unsubscribe(queue)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
