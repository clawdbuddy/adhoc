"""可变会话状态，由 API 路由共享。

单个 Session 实例保存在 `app.state.session` 中。
/api/sim/start 会修改它。
保持小而显式（不使用 DI 框架）——同一时刻宿主机上只能运行一个仿真器。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

from controller.orchestrator import SimConfig, NodeSpec, PRESETS
from controller.orchestrator.config import load_config
from controller.orchestrator.docker_mgr import DockerMgr
from controller.orchestrator.netns import (
    DEFAULT_BRIDGE,
    ensure_bridge,
    teardown,
)
from controller.orchestrator.sim_runner import SimRunner
from controller.orchestrator.telemetry import Telemetry

log = logging.getLogger(__name__)


def default_node_specs(config: SimConfig) -> list[NodeSpec]:
    """当调用者未提供节点规格时，按节点数自动生成。

    与 start-simulation.sh 的角色分配一致：node-0 = server，node-15 = gateway，
    其余 = client。IP 从 192.168.100.10 开始。
    """
    specs: list[NodeSpec] = []
    for i in range(config.n_nodes):
        if i == 0:
            role = "server"
        elif i == 15 and config.n_nodes > 15:
            role = "gateway"
        else:
            role = "client"
        specs.append(NodeSpec(id=i, ip=f"192.168.100.{10 + i}", role=role))
    return specs


@dataclass
class Session:
    """当前仿真会话的进程级单例。"""

    config: SimConfig = field(default_factory=SimConfig)
    sim: Optional[SimRunner] = None
    docker_mgr: Optional[DockerMgr] = None
    telemetry: Optional[Telemetry] = None
    specs: list[NodeSpec] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------------------------------------------------------- 生命周期
    async def start(
        self,
        *,
        config: SimConfig | None = None,
        preset: str | None = None,
        overrides: dict | None = None,
        nodes: list[NodeSpec] | None = None,
    ) -> None:
        with self._lock:
            if self.sim and self.sim.running:
                raise RuntimeError("仿真器已在运行")

        # 解析配置：显式配置 > 预设 > 覆盖值 > 当前配置
        if config is not None:
            cfg = config
        elif preset is not None:
            cfg = PRESETS[preset].model_copy()
        else:
            cfg = self.config
        if overrides:
            cfg = cfg.merged_with(overrides)

        specs = nodes if nodes is not None else default_node_specs(cfg)

        log.info("启动仿真 (n=%d preset=%s)", cfg.n_nodes, preset)

        # 1. 创建网桥
        ensure_bridge()

        # 2. 启动容器（每次调用同时创建 veth 对 + tap，并将 veth 对端移入 netns）
        docker_mgr = DockerMgr()
        try:
            docker_mgr.start_all(specs, cfg)
        except Exception:
            docker_mgr.stop_all()
            raise

        # 3. 启动 ns-3 仿真器（驱动第 2 步创建的所有 TAP）
        sim = SimRunner(cfg)
        try:
            sim.start()
        except Exception:
            docker_mgr.stop_all()
            teardown(cfg.n_nodes)
            raise

        # 4. 启动遥测泵
        tele = Telemetry(sim, docker_mgr, specs)
        await tele.start(period=1.0)

        with self._lock:
            self.config = cfg
            self.docker_mgr = docker_mgr
            self.sim = sim
            self.telemetry = tele
            self.specs = specs

    async def stop(self) -> None:
        with self._lock:
            sim, docker_mgr, tele, specs = self.sim, self.docker_mgr, self.telemetry, self.specs
            self.sim = self.docker_mgr = self.telemetry = None
            self.specs = []

        if tele is not None:
            await tele.stop()
        if sim is not None:
            sim.stop()
        if docker_mgr is not None:
            docker_mgr.stop_all()
        teardown(len(specs))

    # ---------------------------------------------------------- 访问器
    @property
    def running(self) -> bool:
        return self.sim is not None and self.sim.running


# ----- 路由使用的单例访问函数 -----------------------------------
_session = Session()


def get_session() -> Session:
    return _session
