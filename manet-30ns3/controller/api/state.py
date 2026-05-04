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

import docker
from docker.errors import APIError, NotFound

from controller.orchestrator import SimConfig, NodeSpec, PRESETS
from controller.orchestrator.config import load_config, load_user_config
from controller.orchestrator.docker_mgr import CONTAINER_PREFIX, DockerMgr
from controller.orchestrator.netns import (
    DEFAULT_BRIDGE,
    delete_link,
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

    config: SimConfig = field(default_factory=lambda: load_user_config() or SimConfig())
    sim: Optional[SimRunner] = None
    docker_mgr: Optional[DockerMgr] = None
    telemetry: Optional[Telemetry] = None
    specs: list[NodeSpec] = field(default_factory=list)
    preset: Optional[str] = None
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

        # 解析配置（优先级，高 → 低）：overrides > 显式 config > preset > 当前 self.config
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

        # 如果上次仿真崩溃留下了残留(docker 容器/网桥/tap/veth),先做一次 best-effort 清理
        _reap_orphans(cfg.n_nodes)

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

        # 4. 启动遥测泵 (5 Hz: 把端到端反馈从 ~1s 压到 ~200ms)
        tele = Telemetry(sim, docker_mgr, specs)
        await tele.start(period=0.2)

        with self._lock:
            self.config = cfg
            self.docker_mgr = docker_mgr
            self.sim = sim
            self.telemetry = tele
            self.specs = specs
            self.preset = preset

    async def stop(self) -> None:
        """best-effort 停止与清理。

        即使 sim 已崩溃 (sess.running == False),仍要走一遍下面的清理路径,
        把上一次仿真留下的 docker 容器/网桥/tap/veth 兜底删干净。
        """
        with self._lock:
            sim, docker_mgr, tele, specs = self.sim, self.docker_mgr, self.telemetry, self.specs
            cfg = self.config
            self.sim = self.docker_mgr = self.telemetry = None
            self.specs = []
            self.preset = None

        if tele is not None:
            try:
                await tele.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("telemetry.stop() 抛异常: %s", e)
        if sim is not None:
            try:
                sim.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("sim.stop() 抛异常: %s", e)
        if docker_mgr is not None:
            try:
                docker_mgr.stop_all()
            except Exception as e:  # noqa: BLE001
                log.warning("docker_mgr.stop_all() 抛异常: %s", e)
        # 用配置中的 n_nodes 而不是实际启动的容器数，
        # 确保 ns-3 创建的所有 tap 接口都被清理
        try:
            teardown(cfg.n_nodes)
        except Exception as e:  # noqa: BLE001
            log.warning("teardown 抛异常: %s", e)

        # 兜底:扫描 docker 中残留的 manet-node-* 容器,以及任何 tap-/veth 接口
        _reap_orphans(cfg.n_nodes)

    # ---------------------------------------------------------- 访问器
    @property
    def running(self) -> bool:
        return self.sim is not None and self.sim.running


def _reap_orphans(expected_n: int) -> None:
    """best-effort 清理 manet-node-* 容器和 tap/veth/br-ns3。

    Session 在崩溃后会丢失 docker_mgr 引用,这里通过容器名前缀重新发现并删除;
    同样用名字模式删除可能残留的 tap-*/veth*/br-ns3。
    """
    # 1. 容器
    try:
        client = docker.from_env()
        for c in client.containers.list(all=True, filters={"name": CONTAINER_PREFIX}):
            try:
                c.remove(force=True)
                log.info("orphan reap: 删除残留容器 %s", c.name)
            except (APIError, NotFound) as e:
                log.warning("orphan reap: 删除容器 %s 失败: %s", c.name, e)
    except Exception as e:  # noqa: BLE001
        log.warning("orphan reap: 列出 docker 容器失败: %s", e)

    # 2. 网络接口:扫描比 expected_n 更大的范围,以防上次跑了更多节点
    upper = max(expected_n, 16)
    for i in range(upper):
        delete_link(f"veth{i}")
        delete_link(f"tap-{i}")
    delete_link(DEFAULT_BRIDGE)


# ----- 路由使用的单例访问函数 -----------------------------------
_session = Session()


def get_session() -> Session:
    return _session
