"""Docker SDK 包装器：MANET 节点容器管理。

编排器为每个 MANET 节点创建一个 --net=none 的容器，
然后调用 `netns.move_to_netns` 将 veth 对端作为 eth0 注入容器。
本模块负责容器生命周期，不执行任何 L2/网桥操作。
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading
from dataclasses import dataclass
from typing import Iterable

import docker
from docker.errors import NotFound, APIError

from .config import NodeSpec, SimConfig
from . import netns

log = logging.getLogger(__name__)

CONTAINER_PREFIX = "manet-node-"


@dataclass
class RuntimeNode:
    """运行时节点记录。"""
    spec: NodeSpec
    container_id: str
    pid: int
    name: str


class DockerMgr:
    def __init__(self, client: docker.DockerClient | None = None):
        self.client = client or docker.from_env()
        self._nodes: dict[int, RuntimeNode] = {}
        self._nodes_lock = threading.Lock()
        # 容器状态缓存，减少 telemetry 每帧都查 Docker API 的开销
        self._status_cache: dict[int, bool] = {}
        self._status_lock = threading.Lock()
        self._status_thread: threading.Thread | None = None
        self._status_stop = threading.Event()

    # ------------------------------------------------------------------ 启动
    def start_all(self, specs: Iterable[NodeSpec], config: SimConfig) -> list[RuntimeNode]:
        """批量启动所有节点容器（并行化）。"""
        spec_list = list(specs)
        n = len(spec_list)
        if n == 0:
            return []

        # 小批量时顺序执行避免线程开销；大批量时并行化
        if n <= 2:
            out: list[RuntimeNode] = []
            for spec in spec_list:
                out.append(self.start_one(spec, config))
            return out

        # 并行启动：每节点独立（容器创建 + netns 配置互不干扰）
        # Docker daemon 有内部锁，但 I/O 并行仍有显著收益
        out = [None] * n  # type: ignore[list-item]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 8)) as pool:
            futures = {
                pool.submit(self.start_one, spec, config): i
                for i, spec in enumerate(spec_list)
            }
            for future in concurrent.futures.as_completed(futures):
                i = futures[future]
                try:
                    out[i] = future.result()
                except Exception:
                    # 任一节点失败时取消剩余任务并清理
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise
        return out  # type: ignore[return-value]

    def start_one(self, spec: NodeSpec, config: SimConfig) -> RuntimeNode:
        """启动单个节点容器并配置网络。"""
        name = f"{CONTAINER_PREFIX}{spec.id}"
        # 清理同名残留容器
        self._kill_stale(name)

        env = {
            "NODE_ID": str(spec.id),
            "NODE_IP": spec.ip,
            "NODE_ROLE": spec.role,
            "BRIDGE_IP": netns.DEFAULT_BRIDGE_IP,
            "USER_APP_MODE": spec.user_app_mode,
            "BSSID": config.bssid,
            "SSH_ENABLE": "1" if spec.ssh_enable else "0",
        }
        if spec.user_app_cmd:
            env["USER_APP_CMD"] = spec.user_app_cmd
        if spec.ssh_authorized_keys:
            env["SSH_AUTHORIZED_KEYS"] = spec.ssh_authorized_keys

        volumes: dict[str, dict[str, str]] = {}
        if spec.user_app_mode == "bind" and spec.user_app_bind_path:
            volumes[spec.user_app_bind_path] = {"bind": "/opt/userapp", "mode": "rw"}

        log.info("启动 %s (镜像=%s 模式=%s IP=%s)",
                 name, spec.image, spec.user_app_mode, spec.ip)

        container = self.client.containers.run(
            image=spec.image,
            name=name,
            hostname=f"adhoc-node-{spec.id}",
            detach=True,
            network_mode="none",
            privileged=True,
            cap_add=["NET_ADMIN", "SYS_ADMIN"],
            environment=env,
            volumes=volumes,
        )

        # 刷新属性以读取 PID
        container.reload()
        pid = container.attrs["State"]["Pid"]
        if not pid:
            raise RuntimeError(f"容器 {name} 启动后没有 PID")

        # 配置网络：创建每节点独立桥、veth，将 peer 移入 netns，创建 tap
        veth_host = f"veth{spec.id}"
        veth_peer = f"vethns{spec.id}"
        tap = f"tap-{spec.id}"

        netns.ensure_node_bridge(spec.id)
        netns.create_veth(veth_host, veth_peer, spec.id)
        netns.move_to_netns(
            veth_peer, pid,
            rename_to="eth0", ip=spec.ip, prefixlen=24,
            mac=netns.mesh_mac(spec.id),
        )
        netns.create_tap(tap, spec.id)

        runtime = RuntimeNode(spec=spec, container_id=container.id, pid=pid, name=name)
        with self._nodes_lock:
            self._nodes[spec.id] = runtime
        return runtime

    # ------------------------------------------------------------------ 停止
    def stop_all(self) -> None:
        """停止所有节点容器（并行化）。"""
        with self._nodes_lock:
            nids = list(self._nodes)
        if not nids:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(nids), 8)) as pool:
            list(pool.map(self.stop_one, nids))

    def stop_one(self, node_id: int) -> None:
        """停止指定节点并清理其网络接口与独立桥。"""
        with self._nodes_lock:
            rn = self._nodes.pop(node_id, None)
        if rn is None:
            return
        self._kill_stale(rn.name)
        # 在宿主侧清理 veth/tap/桥；控制器级别的 teardown 也会在 sim_stop 时运行
        netns.delete_link(f"veth{node_id}")
        netns.delete_link(f"tap-{node_id}")
        netns.delete_link(netns.node_bridge_name(node_id))

    def _kill_stale(self, name: str) -> None:
        """强制终止并删除同名残留容器。"""
        try:
            c = self.client.containers.get(name)
            try:
                c.kill()
            except APIError:
                pass
            c.remove(force=True)
        except NotFound:
            pass

    # ------------------------------------------------------------------ 执行
    def exec_in(self, node_id: int, cmd: str | list[str], *, tty: bool = False) -> tuple[int, str]:
        """在节点容器内执行命令。"""
        rn = self._nodes.get(node_id)
        if rn is None:
            raise KeyError(f"节点 {node_id} 未运行")
        c = self.client.containers.get(rn.container_id)
        if isinstance(cmd, str):
            cmd_list = ["sh", "-c", cmd]
        else:
            cmd_list = cmd
        result = c.exec_run(cmd_list, tty=tty, demux=False)
        out = result.output.decode("utf-8", errors="replace") if result.output else ""
        return result.exit_code, out

    # ------------------------------------------------------------------ 日志
    def logs(self, node_id: int, *, tail: int | str = 200) -> str:
        """获取节点容器日志。"""
        rn = self._nodes.get(node_id)
        if rn is None:
            raise KeyError(f"节点 {node_id} 未运行")
        c = self.client.containers.get(rn.container_id)
        return c.logs(tail=tail, stdout=True, stderr=True).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ 访问器
    @property
    def nodes(self) -> dict[int, RuntimeNode]:
        return dict(self._nodes)

    # ------------------------------------------------------------------ 状态缓存
    def start_status_refresh(self, interval: float = 1.0) -> None:
        """启动后台线程，定期刷新容器运行状态缓存。"""
        self.stop_status_refresh()
        self._status_stop.clear()
        self._status_thread = threading.Thread(
            target=self._status_refresh_loop, args=(interval,), daemon=True,
            name="docker-status-refresh"
        )
        self._status_thread.start()

    def stop_status_refresh(self) -> None:
        """停止状态刷新后台线程。"""
        if self._status_thread is not None:
            self._status_stop.set()
            self._status_thread.join(timeout=2.0)
            self._status_thread = None

    def _status_refresh_loop(self, interval: float) -> None:
        while not self._status_stop.is_set():
            self._refresh_status_cache()
            self._status_stop.wait(interval)

    def _refresh_status_cache(self) -> None:
        """批量查询所有节点的容器状态并写入缓存。"""
        with self._nodes_lock:
            nodes = list(self._nodes.values())
        new_cache: dict[int, bool] = {}
        for rn in nodes:
            try:
                c = self.client.containers.get(rn.container_id)
                new_cache[rn.spec.id] = c.status == "running"
            except NotFound:
                new_cache[rn.spec.id] = False
            except Exception:
                new_cache[rn.spec.id] = False
        with self._status_lock:
            self._status_cache = new_cache

    def is_running(self, node_id: int) -> bool:
        """检查节点容器是否仍在运行（优先读缓存）。"""
        with self._status_lock:
            if node_id in self._status_cache:
                return self._status_cache[node_id]
        # 缓存未命中时回退到实时查询
        rn = self._nodes.get(node_id)
        if rn is None:
            return False
        try:
            c = self.client.containers.get(rn.container_id)
            return c.status == "running"
        except NotFound:
            return False
