"""WebSocket 遥测路由：GET /ws/telemetry — 双向通信。

支持：
- 服务端 → 客户端：原有 5 Hz 遥测帧（t, running, nodes, flows, env...）
- 服务端 → 客户端：参数变更广播（param_changed）
- 客户端 → 服务端：参数读写（param_get / param_set / param_batch_set / param_get_all）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from controller.api.state import get_session

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket) -> None:
    """双向 WebSocket：推送遥测帧 + 接收参数读写请求 + 广播参数变更。"""
    await ws.accept()
    sess = get_session()

    # 参数变更订阅队列
    param_queue: asyncio.Queue | None = None
    if sess.param_store is not None:
        param_queue = sess.param_store.subscribe()

    # 遥测帧订阅队列（仅在仿真运行时有效）
    tele_owner = sess.telemetry
    tele_queue = tele_owner.subscribe() if tele_owner else None

    # 如果既没有 param_store 也没有 telemetry，直接关闭
    if param_queue is None and tele_queue is None:
        await ws.send_json({"running": False, "nodes": [], "flows": [], "t": 0.0})
        await ws.close()
        return

    tasks: list[asyncio.Task] = []

    async def _recv_loop() -> None:
        """处理客户端发来的消息。"""
        while True:
            raw = await ws.receive_text()
            try:
                msg = _parse_json(raw)
            except Exception:
                await _send_safe(ws, {"type": "error", "reason": "invalid JSON"})
                continue

            msg_type = msg.get("type", "")
            req_id = msg.get("reqId", "")

            if msg_type == "param_get":
                await _handle_param_get(ws, msg, req_id)
            elif msg_type == "param_set":
                await _handle_param_set(ws, msg, req_id)
            elif msg_type == "param_batch_set":
                await _handle_param_batch_set(ws, msg, req_id)
            elif msg_type == "param_get_all":
                await _handle_param_get_all(ws, req_id)
            else:
                await _send_safe(ws, {"type": "error", "reqId": req_id, "reason": f"unknown type: {msg_type}"})

    async def _tele_loop() -> None:
        """跨启停重新订阅，已连接的页面无需刷新或重连。"""
        nonlocal tele_owner, tele_queue
        sent_idle = False
        while True:
            if sess.telemetry is not tele_owner:
                if tele_owner is not None and tele_queue is not None:
                    tele_owner.unsubscribe(tele_queue)
                tele_owner = sess.telemetry
                tele_queue = tele_owner.subscribe() if tele_owner else None
                sent_idle = False
            if tele_queue is None:
                if not sent_idle:
                    await _send_safe(ws, {"running": False, "nodes": [], "flows": [], "t": 0.0})
                    sent_idle = True
                await asyncio.sleep(0.2)
                continue
            try:
                frame = await asyncio.wait_for(tele_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await _send_safe(ws, frame)

    async def _param_broadcast_loop() -> None:
        """从 ParamStore 接收变更事件并广播给客户端。"""
        if param_queue is None:
            return
        while True:
            event = await param_queue.get()
            await _send_safe(ws, {
                "type": "param_changed",
                "key": event.key,
                "value": event.value,
                "scope": event.scope,
                "source": event.source,
            })

    try:
        tasks = [
            asyncio.create_task(_recv_loop(), name="ws-recv"),
            asyncio.create_task(_tele_loop(), name="ws-tele"),
        ]
        if param_queue is not None:
            tasks.append(asyncio.create_task(_param_broadcast_loop(), name="ws-param"))

        # 任一 task 完成（异常或正常结束）则全部取消
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                log.warning("WebSocket task ended with %s", task.exception())

    except WebSocketDisconnect:
        log.info("WebSocket 客户端断开")
    except Exception:
        log.exception("WebSocket 异常")
    finally:
        for task in tasks:
            task.cancel()
        if param_queue is not None and sess.param_store is not None:
            sess.param_store.unsubscribe(param_queue)
        if tele_queue is not None and tele_owner is not None:
            tele_owner.unsubscribe(tele_queue)
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

async def _handle_param_get(ws: WebSocket, msg: dict[str, Any], req_id: str) -> None:
    key = msg.get("key", "")
    store = get_session().param_store
    if store is None:
        await _send_safe(ws, {"type": "param_response", "reqId": req_id, "ok": False, "reason": "param_store not ready"})
        return
    result = store.get(key)
    await _send_safe(ws, {
        "type": "param_response",
        "reqId": req_id,
        **result,
    })


async def _handle_param_set(ws: WebSocket, msg: dict[str, Any], req_id: str) -> None:
    key = msg.get("key", "")
    value = msg.get("value")
    store = get_session().param_store
    if store is None:
        await _send_safe(ws, {"type": "param_response", "reqId": req_id, "ok": False, "reason": "param_store not ready"})
        return
    result = await asyncio.to_thread(store.set, key, value, source="ws")
    await _send_safe(ws, {
        "type": "param_response",
        "reqId": req_id,
        **result,
    })


async def _handle_param_batch_set(ws: WebSocket, msg: dict[str, Any], req_id: str) -> None:
    params = msg.get("params", {})
    store = get_session().param_store
    if store is None:
        await _send_safe(ws, {"type": "param_batch_response", "reqId": req_id, "ok": False, "reason": "param_store not ready"})
        return
    results = await asyncio.to_thread(store.batch_set, params, source="ws")
    ok = all(r.get("ok") for r in results)
    await _send_safe(ws, {
        "type": "param_batch_response",
        "reqId": req_id,
        "ok": ok,
        "results": results,
    })


async def _handle_param_get_all(ws: WebSocket, req_id: str) -> None:
    store = get_session().param_store
    if store is None:
        await _send_safe(ws, {"type": "param_response", "reqId": req_id, "ok": False, "reason": "param_store not ready"})
        return
    values = store.get_all()
    await _send_safe(ws, {
        "type": "param_response",
        "reqId": req_id,
        "ok": True,
        "params": values,
    })


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> dict[str, Any]:
    import json
    return json.loads(raw)


async def _send_safe(ws: WebSocket, data: dict[str, Any]) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        pass
