"""UDP 二进制协议服务（api_54.docx）。

在控制器内启动 asyncio datagram endpoint，监听 UDP 端口 62450（可配置），
接收外部电台管理软件的二进制信令，通过 ParamStore / Telemetry 操作仿真状态。

同时维护一个周期上报任务，每 5 秒向已发现的上报地址推送拓扑 (0x0310) 和
节点状态 (0x02AF)。
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from controller.orchestrator.udp_handlers import UdpCommandHandler
from controller.orchestrator.udp_protocol import UdpFrame

log = logging.getLogger(__name__)


class UdpProtocol(asyncio.DatagramProtocol):
    """asyncio datagram endpoint 协议实现。"""

    def __init__(self, handler: UdpCommandHandler, service: "UdpService") -> None:
        self.handler = handler
        self.service = service
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # UDP 接收回调在事件循环线程中运行，但 handler 可能阻塞（ParamStore 用 RLock），
        # 因此将处理逻辑丢到线程池中，避免阻塞事件循环。
        asyncio.create_task(self._handle(data, addr))

    async def _handle(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            frame = UdpFrame.decode(data)
        except ValueError as e:
            log.warning("UDP 帧解析失败 from %s: %s", addr, e)
            return

        # 首次收到合法帧的源地址自动加入订阅列表，用于周期上报
        self.service.add_subscriber(addr)

        try:
            response = await self.handler.handle(frame)
            if response is not None and self.transport is not None:
                self.transport.sendto(response.encode(), addr)
                log.debug("UDP 响应 -> %s: %s", addr, response)
        except Exception:
            log.exception("UDP 命令处理异常 from %s", addr)


class UdpService:
    """UDP 二进制协议服务生命周期管理。"""

    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        report_period: float = 5.0,
    ) -> None:
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.report_period = report_period
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: UdpProtocol | None = None
        self._report_task: asyncio.Task[Any] | None = None
        self._handler = UdpCommandHandler()
        self._subscribers: set[tuple[str, int]] = set()

    # ------------------------------------------------------------------ 生命周期

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            lambda: UdpProtocol(self._handler, self),
            local_addr=(self.bind_host, self.bind_port),
        )
        self._report_task = asyncio.create_task(
            self._report_loop(), name="udp-report"
        )
        log.info("UDP 服务已启动 %s:%d", self.bind_host, self.bind_port)

    async def stop(self) -> None:
        if self._report_task is not None:
            self._report_task.cancel()
            try:
                await self._report_task
            except asyncio.CancelledError:
                pass
        if self._transport is not None:
            self._transport.close()
        log.info("UDP 服务已停止")

    # ------------------------------------------------------------------ 订阅管理

    def add_subscriber(self, addr: tuple[str, int]) -> None:
        """将源地址加入周期上报订阅列表。"""
        self._subscribers.add(addr)

    def remove_subscriber(self, addr: tuple[str, int]) -> None:
        self._subscribers.discard(addr)

    # ------------------------------------------------------------------ 周期上报

    async def _report_loop(self) -> None:
        """每 report_period 秒上报拓扑和节点状态。"""
        while True:
            await asyncio.sleep(self.report_period)
            if not self._subscribers:
                continue
            if self._transport is None:
                continue

            # 0x0310 拓扑上报
            try:
                topo_frame = await self._handler.handle(
                    UdpFrame(comm_type=1, cmd_id=0x0310)
                )
                if topo_frame is not None:
                    raw = topo_frame.encode()
                    for addr in list(self._subscribers):
                        try:
                            self._transport.sendto(raw, addr)
                        except Exception:
                            self._subscribers.discard(addr)
                            log.debug("移除无响应订户 %s", addr)
            except Exception:
                log.exception("拓扑上报失败")

            # 0x02AF 节点状态上报（预留）
            try:
                status_frame = self._build_status_report()
                raw = status_frame.encode()
                for addr in list(self._subscribers):
                    try:
                        self._transport.sendto(raw, addr)
                    except Exception:
                        self._subscribers.discard(addr)
            except Exception:
                log.exception("状态上报失败")

    def _build_status_report(self) -> UdpFrame:
        """构造 0x02AF 节点状态信息帧。

        格式:
            BYTE[0] = 1 (消息类别: 节点状态信息)
            BYTE[1] = 自组网状态 (0=未同步, 1=同步)
            BYTE[2] = 测控链状态 (0=未同步, 1=同步)
            BYTE[3]-BYTE[6] = 32 位无符号异常代码 (0=无异常)  → 4 bytes
        """
        from controller.api.state import get_session

        sess = get_session()
        sync = 1 if sess.running else 0
        payload = struct.pack(">BBBI", 1, sync, sync, 0)
        return UdpFrame(comm_type=1, cmd_id=0x02AF, payload=payload)
