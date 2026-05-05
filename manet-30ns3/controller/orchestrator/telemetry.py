"""遥测：将 SimRunner + DockerMgr 快照打包为线格式帧。

帧格式（camelCase）与 manet-30ns3/web-manager/src/types/config.ts 中的 NodeStatus / FlowStats 对齐，
因此 React 前端类型无需改动。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import NodeSpec
from .docker_mgr import DockerMgr
from .sim_runner import SimRunner

log = logging.getLogger(__name__)


def _node_frame(spec: NodeSpec, sim_node, online: bool) -> dict[str, Any]:
    """组装单个节点帧（线格式，与 NodeStatus TS 接口匹配）。"""
    return {
        "id": spec.id,
        "ip": spec.ip,
        "status": "online" if online else "offline",
        "role": spec.role,
        "rxPackets": int(sim_node.rx_packets) if sim_node else 0,
        "txPackets": int(sim_node.tx_packets) if sim_node else 0,
        "latency": 0.0,
        "neighbors": list(sim_node.neighbors) if sim_node else [],
        "x": float(sim_node.x) if sim_node else 0.0,
        "y": float(sim_node.y) if sim_node else 0.0,
    }


def _flow_frame(flow) -> dict[str, Any]:
    """组装单个流量帧（线格式，与 FlowStats TS 接口匹配）。"""
    return {
        "flowId": int(flow.flow_id),
        "source": str(flow.source),
        "destination": str(flow.destination),
        "txPackets": int(flow.tx_packets),
        "rxPackets": int(flow.rx_packets),
        "lostPackets": int(flow.lost_packets),
        "avgDelay": float(flow.avg_delay),
        "throughput": float(flow.throughput),
    }


def _aggregate_pairs(
    flows: list, ip_to_id: dict[str, int]
) -> list[dict[str, Any]]:
    """把 FlowMonitor 的 5-tuple 流按 (srcId, dstId) 聚合,丢掉无法映射到节点的流。

    NxN 矩阵 UI 需要的是 "节点 i 给节点 j 发了多少",一对节点之间可能有多个 5-tuple
    (TCP+UDP+ICMP 各 1 条),这里把它们求和;avgDelay 取按收到包数加权平均,
    throughput / 各 packet 计数求和。
    """
    buckets: dict[tuple[int, int], dict[str, float]] = {}
    for f in flows:
        sid = ip_to_id.get(str(f.source))
        did = ip_to_id.get(str(f.destination))
        if sid is None or did is None or sid == did:
            continue
        key = (sid, did)
        b = buckets.setdefault(key, {
            "txPackets": 0, "rxPackets": 0, "lostPackets": 0,
            "throughput": 0.0, "delaySumWeighted": 0.0, "delayWeight": 0,
        })
        b["txPackets"] += int(f.tx_packets)
        b["rxPackets"] += int(f.rx_packets)
        b["lostPackets"] += int(f.lost_packets)
        b["throughput"] += float(f.throughput)
        rx = int(f.rx_packets)
        if rx > 0:
            b["delaySumWeighted"] += float(f.avg_delay) * rx
            b["delayWeight"] += rx
    out: list[dict[str, Any]] = []
    for (sid, did), b in buckets.items():
        avg_delay = b["delaySumWeighted"] / b["delayWeight"] if b["delayWeight"] else 0.0
        out.append({
            "srcId": sid,
            "dstId": did,
            "txPackets": int(b["txPackets"]),
            "rxPackets": int(b["rxPackets"]),
            "lostPackets": int(b["lostPackets"]),
            "throughput": float(b["throughput"]),
            "avgDelay": float(avg_delay),
        })
    return out


class Telemetry:
    """聚合状态为 JSON 可序列化帧；向 WebSocket 订阅者广播。"""

    def __init__(self, sim: SimRunner, docker: DockerMgr, specs: list[NodeSpec]):
        self.sim = sim
        self.docker = docker
        self.specs_by_id = {s.id: s for s in specs}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # ----------------------------------------------------- 订阅者 API
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """订阅遥测帧；返回一个 asyncio.Queue。"""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """取消订阅。"""
        self._subscribers.discard(q)

    # ----------------------------------------------------- 快照（REST）
    def snapshot(self) -> dict[str, Any]:
        """生成当前完整快照（供 REST 和 WebSocket 使用）。"""
        sim_nodes = {n.id: n for n in self.sim.snapshot_nodes()}
        sim_flows = self.sim.snapshot_flows()
        nodes_out = []
        for spec in self.specs_by_id.values():
            online = self.docker.is_running(spec.id)
            nodes_out.append(_node_frame(spec, sim_nodes.get(spec.id), online))
        # 节点对聚合：把 5-tuple flow 折叠成 (srcId, dstId) 维度
        ip_to_id = {spec.ip: spec.id for spec in self.specs_by_id.values()}
        pairs_out = _aggregate_pairs(sim_flows, ip_to_id)
        env = self.sim.snapshot_env()
        return {
            "t": self.sim.elapsed,
            "running": self.sim.running,
            "nodes": nodes_out,
            "flows": [_flow_frame(f) for f in sim_flows],
            "pairs": pairs_out,
            "env": {
                "txPower": env.tx_power,
                "rxSensitivity": env.rx_sensitivity,
                "positions": env.positions,
                "pathLossExponent": env.path_loss_exponent,
                "frequencyMhz": env.frequency_mhz,
                "channelWidthMhz": env.channel_width_mhz,
                "rangeTargetM": env.range_target_m,
            },
            "ts": time.time(),
        }

    # ----------------------------------------------------- 泵（WebSocket）
    async def start(self, period: float = 1.0) -> None:
        """启动周期性广播任务。"""
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._pump(period), name="telemetry-pump")

    async def stop(self) -> None:
        """停止广播任务。"""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _pump(self, period: float) -> None:
        try:
            while not self._stop.is_set():
                frame = self.snapshot()
                # 如果订阅者处理慢，丢弃最旧的帧
                for q in list(self._subscribers):
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        q.put_nowait(frame)
                    except asyncio.QueueFull:
                        pass
                await asyncio.sleep(period)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("遥测泵崩溃")
