"""WebSocket 遥测路由：GET /ws/telemetry — 1 Hz JSON 帧。

帧格式与 React 前端的 NodeStatus / FlowStats 类型对齐。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from controller.api.state import get_session

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket) -> None:
    """向所有连接的 WebSocket 客户端广播 1 Hz 遥测帧。"""
    await ws.accept()
    sess = get_session()
    if not sess.telemetry:
        # 仿真未运行：发送一帧空数据后关闭，UI 可在仿真启动后自动重连
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
        log.exception("WebSocket 发送失败")
    finally:
        if sess.telemetry:
            sess.telemetry.unsubscribe(queue)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
