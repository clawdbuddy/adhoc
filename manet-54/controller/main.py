"""FastAPI 应用入口 - 电台设备控制后端。"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("manet.api")


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


app = FastAPI(title="电台控制", version="0.1.0")


@app.post("/api/radio/raw", summary="电台 UDP 帧透传", description=
"""## 二进制帧格式（api_54 协议）
7 字节头部 + N 字节内容：
- `comm_type`: 通信类型（1=静态设置, 3=动态设置）
- `cmd_id`: 信令 ID（大端序，2 字节）
- `length`: 信息长度（大端序，2 字节）
- `payload`: 参数内容

## 读写示例

### 静态参数查询（comm_type=1, 查询 ID = 设置 ID + 0x40）

| 参数 | 设置 ID | 查询 ID | Payload |
|------|--------|--------|---------|
| 网络规模 | 0x0001 | 0x0041 | 2字节 BE 整数 |
| 工作模式 | 0x0002 | 0x0042 | 1字节 整数 |
| MAC地址 | 0x0003 | 0x0043 | 2字节 BE 整数 |
| 定频频率 | 0x0004 | 0x0044 | 4字节 BCD 压缩码 |
| 跳频表号 | 0x0005 | 0x0045 | 1字节 整数 |

### 动态参数查询（comm_type=3）

| 参数 | 设置 ID | 查询 ID | Payload |
|------|--------|--------|---------|
| 传输速率 | 0x0101 | 0x0141 | 1字节 |
| 发射功率 | 0x0102 | 0x0142 | 1字节 |

### 状态查询

| 功能 | ID | comm_type | Payload |
|------|----|-----------|---------|
| 版本信息 | 0x0203 | 1 | 空 |
| 主动上报订阅 | 0x02AF | 1 | [1,1,1,0,0,0,0] |
| 自组网拓扑 | 0x0310 | 1 | 空 |

## 示例请求

**查询网络规模:**
```json
POST /api/radio/raw
{
  "host": "192.0.3.1",
  "port": 62450,
  "frame": [1, 0, 0, 0, 65, 0, 0]
}
```

**设置网络规模为 16:**
```json
POST /api/radio/raw
{
  "host": "192.0.3.1",
  "port": 62450,
  "frame": [1, 0, 0, 0, 1, 0, 2, 0, 16]
}
```

**查询工作模式:**
```json
POST /api/radio/raw
{
  "host": "192.0.3.1",
  "port": 62450,
  "frame": [1, 0, 0, 0, 66, 0, 0]
}
```

**设置定频频率 505.54MHz (BCD):**
```json
POST /api/radio/raw
{
  "host": "192.0.3.1",
  "port": 62450,
  "frame": [1, 0, 0, 0, 4, 0, 4, 5, 0, 5, 5, 4]
}
```
""")
async def radio_raw(body: dict[str, Any]) -> dict[str, Any]:
    """将 HTTP 请求中的二进制帧透传为 UDP，回复透传为 HTTP 响应。

    Body: { host: string, port: number, frame: number[] }
    Response: { reply?: number[], reason?: string }
    """
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


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


# 托管构建后的 React UI
WEB_DIR = os.environ.get("MANET_WEB_DIR", "/app/dist")
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    log.info("从 %s 提供 React UI", WEB_DIR)
    radio_dir = os.path.join(os.path.dirname(WEB_DIR), "radio")
    if os.path.isdir(radio_dir):
        app.mount("/radio", StaticFiles(directory=radio_dir, html=True), name="radio")
        log.info("从 %s 提供电台控制页面", radio_dir)
else:
    log.info("%s 处无 UI 目录；以纯 API 模式运行", WEB_DIR)


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("MANET_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)