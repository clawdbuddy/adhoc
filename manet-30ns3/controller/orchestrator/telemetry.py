"""Telemetry: bundles SimRunner + DockerMgr snapshots into wire-format frames.

Frame schema (camelCase) matches `NodeStatus`/`FlowStats` in
app/src/types/config.ts so the React UI types are unchanged.
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
    """Compose a single node frame in wire format (matches `NodeStatus` TS interface)."""
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
    """Compose a single flow frame in wire format (matches `FlowStats` TS interface)."""
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


class Telemetry:
    """Aggregates state into JSON-serializable frames; broadcasts to WS subscribers."""

    def __init__(self, sim: SimRunner, docker: DockerMgr, specs: list[NodeSpec]):
        self.sim = sim
        self.docker = docker
        self.specs_by_id = {s.id: s for s in specs}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # ----------------------------------------------------- subscriber API
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    # ----------------------------------------------------- snapshots (REST)
    def snapshot(self) -> dict[str, Any]:
        sim_nodes = {n.id: n for n in self.sim.snapshot_nodes()}
        sim_flows = self.sim.snapshot_flows()
        nodes_out = []
        for spec in self.specs_by_id.values():
            online = self.docker.is_running(spec.id)
            nodes_out.append(_node_frame(spec, sim_nodes.get(spec.id), online))
        return {
            "t": self.sim.elapsed,
            "running": self.sim.running,
            "nodes": nodes_out,
            "flows": [_flow_frame(f) for f in sim_flows],
            "ts": time.time(),
        }

    # ----------------------------------------------------- pump (WebSocket)
    async def start(self, period: float = 1.0) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._pump(period), name="telemetry-pump")

    async def stop(self) -> None:
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
                # Drop oldest if subscriber is slow.
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
            log.exception("telemetry pump crashed")
