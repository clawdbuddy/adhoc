"""REST 代理：将浏览器 HTTP 请求转为 UDP 帧发往外接电台设备。

POST /api/radio/raw
Body: { host: string, port: number, frame: number[] }
Response: { reply?: number[], reason?: string }
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from fastapi import APIRouter

router = APIRouter()
log = logging.getLogger(__name__)


async def _send_udp_async(frame_bytes: bytes, host: str, port: int) -> tuple[bytes | None, str | None]:
    """Async wrapper over blocking socket send."""
    loop = asyncio.get_running_loop()

    def _do() -> tuple[bytes | None, str | None]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3.0)
            sock.sendto(frame_bytes, (host, port))
            reply, _ = sock.recvfrom(4096)
            sock.close()
            return reply, None
        except TimeoutError:
            return None, "UDP 接收超时"
        except Exception as e:
            return None, str(e)

    return await loop.run_in_executor(None, _do)


@router.post("/api/radio/raw")
async def radio_raw(body: dict[str, Any]) -> dict[str, Any]:
    """将 HTTP 请求中的二进制帧透传为 UDP，回复透传为 HTTP 响应。"""
    host: str = body.get("host", "192.0.3.1")
    port: int = int(body.get("port", 62450))
    frame_arr: list[int] = body.get("frame", [])

    if not frame_arr:
        return {"reason": "frame 不能为空"}

    try:
        frame_bytes = bytes(frame_arr)
    except Exception as e:
        return {"reason": f"frame 格式错误: {e}"}

    log.debug("UDP -> %s:%d  frame=%s", host, port, frame_bytes.hex())

    try:
        reply, error = await asyncio.wait_for(
            _send_udp_async(frame_bytes, host, port),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        return {"reason": "UDP 超时"}

    if error:
        return {"reason": error}

    if reply is None:
        return {"msg": "发送成功（无回复）"}

    return {"reply": list(reply)}