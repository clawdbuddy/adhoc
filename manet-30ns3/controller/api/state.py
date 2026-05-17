"""可变会话状态，由 API 路由共享。

单个 Session 实例保存在 `app.state.session` 中。
/api/sim/start 会修改它。
保持小而显式（不使用 DI 框架）——同一时刻宿主机上只能运行一个仿真器。
"""
from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional

import docker
from docker.errors import APIError, NotFound

import json
from pathlib import Path

from controller.orchestrator import SimConfig, NodeSpec, PRESETS
from controller.orchestrator.config import load_user_config, save_config_to_file
from controller.orchestrator.docker_mgr import CONTAINER_PREFIX, DockerMgr
from controller.orchestrator.netns import (
    create_vxlan_on_controller,
    delete_link,
    list_stale_links,
    node_bridge_name,
    teardown,
)
from controller.orchestrator.param_store import ParamStore
from controller.orchestrator.host_node_mgr import HostNodeMgr
from controller.orchestrator.remote_docker import RemoteDockerMgr
from controller.orchestrator.sim_runner import SimRunner
from controller.orchestrator.telemetry import Telemetry

SNAPSHOT_PATH: Path = Path("/app/config/sim_snapshot.json")

log = logging.getLogger(__name__)


def _remote_lan_ip(host_ip: str) -> str:
    """SSH to *host_ip* and detect its LAN IP (src IP of default route).

    Looks up SSH credentials from the host registry.
    """
    from controller.api.routes_hosts import get_host_registry
    reg = get_host_registry()
    entry = reg.get(host_ip)
    ssh_user = entry.ssh_user if entry else "root"
    ssh_key = entry.ssh_key if entry else None
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs: dict = {
        "hostname": host_ip,
        "username": ssh_user,
        "timeout": 15,
        "banner_timeout": 15,
    }
    if ssh_key:
        try:
            from controller.orchestrator.host_node_mgr import _load_pkey
            pkey = _load_pkey(ssh_key)
            if pkey is not None:
                connect_kwargs["pkey"] = pkey
            else:
                connect_kwargs["key_filename"] = ssh_key
        except Exception:
            connect_kwargs["key_filename"] = ssh_key
    try:
        client.connect(**connect_kwargs)
        _, stdout, _ = client.exec_command(
            "ip route get 8.8.8.8", timeout=15
        )
        out = stdout.read().decode()
        parts = out.strip().split()
        for i, p in enumerate(parts):
            if p == "src" and i + 1 < len(parts):
                return parts[i + 1]
        raise RuntimeError(f"Could not detect LAN IP on {host_ip}")
    finally:
        client.close()


def _get_controller_ip(remote_lan_ip: str | None = None) -> str:
    """Return the controller IP to use as VXLAN tunnel endpoint.

    If *remote_lan_ip* is given, finds the controller IP on the same
    /24 subnet (so VXLAN traffic stays on one L2 segment and avoids NAT).
    Falls back to the default-route source IP, then ``MANET_CONTROLLER_IP``,
    then 127.0.0.1.
    """
    ip = __import__("os").environ.get("MANET_CONTROLLER_IP")
    if ip:
        return ip
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", "scope", "global"],
            text=True,
        )
        if remote_lan_ip:
            remote_prefix = ".".join(remote_lan_ip.split(".")[:2]) + "."
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    parts = line.split()
                    addr = parts[1].split("/")[0]
                    if addr.startswith(remote_prefix):
                        return addr
        # Fallback: default-route source IP
        out = subprocess.check_output(
            ["ip", "route", "get", "1.1.1.1"],
            text=True,
        )
        parts = out.strip().split()
        for i, p in enumerate(parts):
            if p == "src" and i + 1 < len(parts):
                return parts[i + 1]
    except Exception:
        log.debug("fallback IP detection failed (ip route)", exc_info=True)
    return "127.0.0.1"


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
    remote_mgrs: dict[str, RemoteDockerMgr] = field(default_factory=dict)
    host_mgrs: dict[str, HostNodeMgr] = field(default_factory=dict)
    telemetry: Optional[Telemetry] = None
    param_store: Optional[ParamStore] = None
    specs: list[NodeSpec] = field(default_factory=list)
    preset: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        # ParamStore 始终存活，支持无仿真时的参数读写
        if self.param_store is None:
            self.param_store = ParamStore(self)

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

        # 按 host 分组节点
        local_specs = [s for s in specs if s.host == "local"]
        remote_specs = [s for s in specs if s.host != "local"]

        log.info(
            "启动仿真 (n=%d local=%d remote=%d preset=%s)",
            cfg.n_nodes, len(local_specs), len(remote_specs), preset,
        )

        # 如果上次仿真崩溃留下了残留(docker 容器/网桥/tap/veth),先做一次 best-effort 清理
        _reap_orphans(cfg.n_nodes)

        # 1. 启动本地节点容器
        docker_mgr = DockerMgr()
        try:
            if local_specs:
                await asyncio.to_thread(docker_mgr.start_all, local_specs, cfg)
        except Exception:
            await asyncio.to_thread(docker_mgr.stop_all)
            raise

        # 2. First pass: detect remote LAN IPs and compute per-remote controller IPs
        #    (before starting containers, so we can pass the correct controller IP)
        remote_controller_ips: dict[int, str] = {}
        for spec in remote_specs:
            remote_host = spec.host
            if spec.host_type == "host-manet":
                # SSH to detect the remote's LAN IP (e.g. 192.168.50.199)
                try:
                    remote_lan = _remote_lan_ip(spec.host)
                except Exception:
                    log.warning("LAN IP detection failed for %s, using host IP", spec.host)
                    remote_lan = spec.host
            else:
                remote_lan = spec.host
            # Find a controller IP on the same /24 as the remote to avoid NAT
            local_ip = _get_controller_ip(remote_lan)
            remote_controller_ips[spec.id] = local_ip

        # 3. 启动远端节点容器（分两类：host-manet-node 和 常规远端容器）
        remote_mgrs: dict[str, RemoteDockerMgr] = {}
        host_mgrs: dict[str, HostNodeMgr] = {}
        try:
            for spec in remote_specs:
                if spec.host_type == "host-manet":
                    # host-manet-node: SSH 启动容器 + 创建 controller 侧 bridge/tap
                    mgr = host_mgrs.get(spec.host)
                    if mgr is None:
                        from controller.api.routes_hosts import get_host_registry
                        reg = get_host_registry()
                        entry = reg.get(spec.host)
                        if entry is not None:
                            mgr = HostNodeMgr(
                                spec.host,
                                ssh_user=entry.ssh_user,
                                ssh_key=entry.ssh_key,
                            )
                        else:
                            mgr = HostNodeMgr(spec.host)
                        host_mgrs[spec.host] = mgr
                    await asyncio.to_thread(
                        mgr.start_one, spec, cfg,
                        remote_controller_ips.get(spec.id, spec.host),
                    )
                else:
                    mgr = remote_mgrs.get(spec.host)
                    if mgr is None:
                        mgr = RemoteDockerMgr(spec.host)
                        remote_mgrs[spec.host] = mgr
                    await asyncio.to_thread(
                        mgr.start_one, spec, cfg,
                        remote_controller_ips.get(spec.id, spec.host),
                    )
        except Exception:
            for mgr in host_mgrs.values():
                try:
                    mgr.stop_all()
                except Exception:
                    pass
                try:
                    mgr.close()
                except Exception:
                    pass
            for mgr in remote_mgrs.values():
                try:
                    mgr.stop_all()
                except Exception:
                    pass
                try:
                    mgr.close()
                except Exception:
                    pass
            docker_mgr.stop_all()
            raise

        # 4. 控制器主机为每个远端节点创建 VXLAN 接口
        for spec in remote_specs:
            remote_lan = spec.host
            if spec.host_type == "host-manet":
                try:
                    remote_lan = _remote_lan_ip(spec.host)
                except Exception:
                    log.warning("LAN IP detection failed for %s, using %s", spec.host, spec.host)
            local_ip = _get_controller_ip(remote_lan)
            try:
                create_vxlan_on_controller(
                    spec.id,
                    remote_ip=remote_lan,
                    local_ip=local_ip,
                )
            except Exception:
                log.warning(
                    "为远端节点 %d (host=%s) 创建 VXLAN 失败",
                    spec.id, spec.host,
                )

        # 4. 启动 ns-3 仿真器（驱动所有 TAP）
        sim = SimRunner(cfg)
        try:
            await asyncio.to_thread(sim.start)
        except Exception:
            docker_mgr.stop_all()
            for mgr in remote_mgrs.values():
                mgr.stop_all()
            for mgr in host_mgrs.values():
                mgr.stop_all()
            teardown(cfg.n_nodes)
            raise

        # 4.5 如果存在上次仿真快照，恢复节点位置和动态参数
        if SNAPSHOT_PATH.exists():
            try:
                snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
                snapshot_preset = snapshot.get("preset")
                if snapshot_preset == preset:
                    positions = snapshot.get("positions", [])
                    for i, pos in enumerate(positions):
                        if i < cfg.n_nodes and isinstance(pos, dict):
                            sim.set_node_position(i, pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))
                    log.info("已从快照恢复 %d 个节点位置 (preset=%s)", len(positions), preset)
                else:
                    log.info(
                        "跳过快照位置恢复: 快照 preset=%s, 当前 preset=%s",
                        snapshot_preset, preset,
                    )
            except Exception as e:  # noqa: BLE001
                log.warning("恢复快照失败: %s", e)

        # 5. 启动容器状态缓存刷新（本地节点）
        docker_mgr.start_status_refresh(interval=1.0)

        # 6. 启动遥测泵 (5 Hz)
        # 统一的状态检查函数，覆盖本地、host、远端节点
        specs_by_id = {s.id: s for s in specs}

        def _is_running(node_id: int) -> bool:
            spec = specs_by_id.get(node_id)
            if spec is None:
                return False
            if spec.host == "local":
                return docker_mgr.is_running(node_id)
            if spec.host_type == "host-manet":
                mgr = host_mgrs.get(spec.host)
                return mgr.is_running(node_id) if mgr else False
            mgr = remote_mgrs.get(spec.host)
            return mgr.is_running(node_id) if mgr else False

        tele = Telemetry(sim, docker_mgr, specs, is_running_fn=_is_running)
        await tele.start(period=0.2)

        with self._lock:
            self.config = cfg
            self.docker_mgr = docker_mgr
            self.remote_mgrs = remote_mgrs
            self.host_mgrs = host_mgrs
            self.sim = sim
            self.telemetry = tele
            self.specs = specs
            self.preset = preset

    async def stop(self) -> None:
        """best-effort 停止与清理。

        即使 sim 已崩溃 (sess.running == False),仍要走一遍下面的清理路径,
        把上一次仿真留下的 docker 容器/mesh-br/mesh-tap/mesh-veth 兜底删干净。
        """
        with self._lock:
            sim, docker_mgr, remote_mgrs, host_mgrs, tele, specs = (
                self.sim, self.docker_mgr, self.remote_mgrs, self.host_mgrs, self.telemetry, self.specs
            )
            cfg = self.config
            last_preset = self.preset
            self.sim = self.docker_mgr = self.telemetry = None
            self.remote_mgrs = {}
            self.host_mgrs = {}
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
            docker_mgr.stop_status_refresh()
            try:
                await asyncio.to_thread(docker_mgr.stop_all)
            except Exception as e:  # noqa: BLE001
                log.warning("docker_mgr.stop_all() 抛异常: %s", e)
        # 停止所有远端 container 节点
        for host_ip, mgr in remote_mgrs.items():
            try:
                await asyncio.to_thread(mgr.stop_all)
            except Exception as e:  # noqa: BLE001
                log.warning("remote_mgr %s stop_all() 抛异常: %s", host_ip, e)
            try:
                mgr.close()
            except Exception as e:  # noqa: BLE001
                log.warning("remote_mgr %s close() 抛异常: %s", host_ip, e)
        # 停止所有 host-manet-node 节点
        for host_ip, mgr in host_mgrs.items():
            try:
                await asyncio.to_thread(mgr.stop_all)
            except Exception as e:  # noqa: BLE001
                log.warning("host_mgr %s stop_all() 抛异常: %s", host_ip, e)
            try:
                mgr.close()
            except Exception as e:  # noqa: BLE001
                log.warning("host_mgr %s close() 抛异常: %s", host_ip, e)
        # 用配置中的 n_nodes 而不是实际启动的容器数，
        # 确保 ns-3 创建的所有 tap 接口都被清理
        try:
            await asyncio.to_thread(teardown, cfg.n_nodes)
        except Exception as e:  # noqa: BLE001
            log.warning("teardown 抛异常: %s", e)

        # 兜底:扫描 docker 中残留的 manet-node-* 容器,以及任何 mesh-tap/mesh-veth 接口
        await asyncio.to_thread(_reap_orphans, cfg.n_nodes)

        # 仿真停止后保存动态参数快照到文件，供下次启动恢复
        if sim is not None:
            try:
                env = sim.snapshot_env()
                snapshot = {
                    "preset": last_preset,
                    "positions": env.positions,
                    "txPower": env.tx_power,
                    "rxSensitivity": env.rx_sensitivity,
                    "pathLossExponent": env.path_loss_exponent,
                    "frequencyMhz": env.frequency_mhz,
                    "channelWidthMhz": env.channel_width_mhz,
                    "rangeTargetM": env.range_target_m,
                    "pathLossModel": env.path_loss_model,
                }
                SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
                SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
                log.info("仿真快照已保存到 %s (preset=%s)", SNAPSHOT_PATH, last_preset)
            except Exception as e:  # noqa: BLE001
                log.warning("保存仿真快照失败: %s", e)

    # ---------------------------------------------------------- 访问器
    @property
    def running(self) -> bool:
        return self.sim is not None and self.sim.running


def _reap_orphans(expected_n: int) -> None:
    """best-effort 清理 manet-node-* 容器和 mesh-tap/mesh-veth/mesh-br。

    Session 在崩溃后会丢失 docker_mgr 引用,这里通过容器名前缀重新发现并删除;
    同样用名字模式删除可能残留的 mesh-tap-*/mesh-veth*/mesh-br-*。
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

    # 2. 网络接口:扫描所有实际存在的仿真残留接口(mesh-tap-*/mesh-veth*/mesh-br-* 等)
    for name in list_stale_links():
        delete_link(name)


# ----- 路由使用的单例访问函数 -----------------------------------
_session = Session()


def get_session() -> Session:
    return _session
