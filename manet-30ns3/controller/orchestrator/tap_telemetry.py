"""从独立 TAP 的 IPv4 帧采集端到端统计，不依赖 ns-3 的 IP 协议栈。

所有 TAP 共用宿主时钟，以内核接收时间戳计算时延（毫秒）。仅统计已知节点
之间的单播 IPv4；丢包是发送后 10 秒仍未观察到接收的包，不把在途包算丢失。
"""
from __future__ import annotations

import hashlib
import socket
import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Flow:
    flow_id: int
    source: str
    destination: str
    tx_packets: int = 0
    rx_packets: int = 0
    lost_packets: int = 0
    rx_bytes: int = 0
    delay_sum_ms: float = 0.0
    first_tx: float = 0.0
    last_rx: float = 0.0
    pending: dict[bytes, deque[float]] = field(default_factory=lambda: defaultdict(deque))


class TapTelemetry:
    """被动读取 AF_PACKET 副本，不修改或转发用户数据。"""

    def __init__(self, prefix: str, count: int, loss_timeout: float = 10.0, ip_to_id: dict[str, int] | None = None) -> None:
        self.prefix = prefix
        self.count = count
        self.loss_timeout = loss_timeout
        self.sockets: list[tuple[int, socket.socket]] = []
        self.flows: dict[tuple[Any, ...], _Flow] = {}
        self.ip_to_id = ip_to_id if ip_to_id is not None else {f"192.168.100.{10 + i}": i for i in range(count)}
        self.capture_drops = 0

    def open(self) -> None:
        """权限或接口缺失时使启动失败，避免把缺失统计展示为零流量。"""
        try:
            for i in range(self.count):
                # ETH_P_ALL 才会接收 PACKET_OUTGOING，IPv4 过滤在解析时完成。
                sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
                self.sockets.append((i, sock))
                sock.setsockopt(socket.SOL_SOCKET, 35, 1)  # Linux SO_TIMESTAMPNS
                sock.bind((f"{self.prefix}{i}", 0))
                sock.setblocking(False)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for _, sock in self.sockets:
            sock.close()
        self.sockets.clear()

    def poll(self) -> None:
        events = []
        for node_id, sock in self.sockets:
            for _ in range(4096):
                try:
                    frame, anc, _, address = sock.recvmsg(65535, 128)
                except BlockingIOError:
                    break
                timestamp = time.time()
                for level, kind, data in anc:
                    if level == socket.SOL_SOCKET and kind == 35:
                        sec, nano = struct.unpack("@ll", data[:struct.calcsize("@ll")])
                        timestamp = sec + nano / 1e9
                events.append((timestamp, node_id, address[2] == socket.PACKET_OUTGOING, frame))
            # PACKET_STATISTICS 的读取会重置内核计数。
            _, drops = struct.unpack("II", sock.getsockopt(263, 6, 8))
            self.capture_drops += drops
        # 跨接口接收顺序不等于发送顺序，先按内核时间排序再关联。
        for timestamp, node_id, outgoing, frame in sorted(events, key=lambda e: e[0]):
            self.observe(node_id, outgoing, frame, timestamp)
        self.expire(time.time())

    def observe(self, node_id: int, outgoing: bool, frame: bytes, timestamp: float) -> None:
        """记录一条捕获事件；可离线验证重复包、丢包和时延计算。"""
        if len(frame) < 34 or frame[12:14] != b"\x08\x00":
            return
        ip = frame[14:]
        ihl = (ip[0] & 15) * 4
        length = int.from_bytes(ip[2:4], "big")
        if ip[0] >> 4 != 4 or ihl < 20 or length < ihl or len(ip) < length:
            return
        ip = ip[:length]
        source, destination = socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20])
        sid, did = self.ip_to_id.get(source), self.ip_to_id.get(destination)
        if sid is None or did is None or sid == did:
            return
        if node_id != (sid if outgoing else did):
            return
        protocol = ip[9]
        fragment = int.from_bytes(ip[6:8], "big") & 0x1fff
        ports = struct.unpack("!HH", ip[ihl:ihl + 4]) if protocol in (6, 17) and not fragment and len(ip) >= ihl + 4 else (0, 0)
        key = (source, destination, protocol, *ports)
        flow = self.flows.setdefault(key, _Flow(len(self.flows) + 1, source, destination))
        fingerprint = hashlib.blake2b(ip, digest_size=16).digest()
        if outgoing:
            if not flow.tx_packets:
                flow.first_tx = timestamp
            flow.tx_packets += 1
            flow.pending[fingerprint].append(timestamp)
        else:
            pending = flow.pending.get(fingerprint)
            if not pending:
                return  # 忽略重复接收，不能创造没有发送记录的测量值。
            sent = pending.popleft()
            if not pending:
                del flow.pending[fingerprint]
            flow.rx_packets += 1
            flow.rx_bytes += length
            flow.last_rx = timestamp
            flow.delay_sum_ms += max(0.0, timestamp - sent) * 1000.0

    def expire(self, now: float) -> None:
        for flow in self.flows.values():
            for fingerprint, pending in list(flow.pending.items()):
                while pending and now - pending[0] >= self.loss_timeout:
                    pending.popleft()
                    flow.lost_packets += 1
                if not pending:
                    del flow.pending[fingerprint]

    def snapshot(self) -> list[dict[str, Any]]:
        return [{
            "flow_id": f.flow_id, "source": f.source, "destination": f.destination,
            "tx_packets": f.tx_packets, "rx_packets": f.rx_packets,
            "lost_packets": f.lost_packets,
            "avg_delay": f.delay_sum_ms / f.rx_packets if f.rx_packets else 0.0,
            "throughput": f.rx_bytes * 8 / max(f.last_rx - f.first_tx, 0.001) / 1e6,
        } for f in self.flows.values()]
