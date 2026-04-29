"""Docker SDK wrapper for MANET node containers.

The orchestrator creates one container per MANET node with --net=none, then
calls into `netns.move_to_netns` to inject the veth peer as eth0. This module
owns the container lifecycle; it does NOT perform any L2/bridge work.
"""
from __future__ import annotations

import logging
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
    spec: NodeSpec
    container_id: str
    pid: int
    name: str


class DockerMgr:
    def __init__(self, client: docker.DockerClient | None = None):
        self.client = client or docker.from_env()
        self._nodes: dict[int, RuntimeNode] = {}

    # ------------------------------------------------------------------ start
    def start_all(self, specs: Iterable[NodeSpec], config: SimConfig) -> list[RuntimeNode]:
        out: list[RuntimeNode] = []
        for spec in specs:
            out.append(self.start_one(spec, config))
        return out

    def start_one(self, spec: NodeSpec, config: SimConfig) -> RuntimeNode:
        name = f"{CONTAINER_PREFIX}{spec.id}"
        # Drop any stale container with the same name.
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

        log.info("starting %s (image=%s mode=%s ip=%s)",
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

        # Refresh attrs to read PID.
        container.reload()
        pid = container.attrs["State"]["Pid"]
        if not pid:
            raise RuntimeError(f"container {name} has no PID after start")

        # Now plumb networking: create veth, move peer into netns, create tap.
        veth_host = f"veth{spec.id}"
        veth_peer = f"vethns{spec.id}"
        tap = f"tap-{spec.id}"

        netns.create_veth(veth_host, veth_peer)
        netns.move_to_netns(
            veth_peer, pid,
            rename_to="eth0", ip=spec.ip, prefixlen=24,
        )
        netns.create_tap(tap)

        runtime = RuntimeNode(spec=spec, container_id=container.id, pid=pid, name=name)
        self._nodes[spec.id] = runtime
        return runtime

    # ------------------------------------------------------------------ stop
    def stop_all(self) -> None:
        for nid in list(self._nodes):
            self.stop_one(nid)

    def stop_one(self, node_id: int) -> None:
        rn = self._nodes.pop(node_id, None)
        if rn is None:
            return
        self._kill_stale(rn.name)
        # Bring down veth/tap on host; controller-level teardown also runs at sim_stop.
        netns.delete_link(f"veth{node_id}")
        netns.delete_link(f"tap-{node_id}")

    def _kill_stale(self, name: str) -> None:
        try:
            c = self.client.containers.get(name)
            try:
                c.kill()
            except APIError:
                pass
            c.remove(force=True)
        except NotFound:
            pass

    # ------------------------------------------------------------------ exec
    def exec_in(self, node_id: int, cmd: str | list[str], *, tty: bool = False) -> tuple[int, str]:
        rn = self._nodes.get(node_id)
        if rn is None:
            raise KeyError(f"node {node_id} not running")
        c = self.client.containers.get(rn.container_id)
        if isinstance(cmd, str):
            cmd_list = ["sh", "-c", cmd]
        else:
            cmd_list = cmd
        result = c.exec_run(cmd_list, tty=tty, demux=False)
        out = result.output.decode("utf-8", errors="replace") if result.output else ""
        return result.exit_code, out

    # ------------------------------------------------------------------ logs
    def logs(self, node_id: int, *, tail: int | str = 200) -> str:
        rn = self._nodes.get(node_id)
        if rn is None:
            raise KeyError(f"node {node_id} not running")
        c = self.client.containers.get(rn.container_id)
        return c.logs(tail=tail, stdout=True, stderr=True).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ accessors
    @property
    def nodes(self) -> dict[int, RuntimeNode]:
        return dict(self._nodes)

    def is_running(self, node_id: int) -> bool:
        rn = self._nodes.get(node_id)
        if rn is None:
            return False
        try:
            c = self.client.containers.get(rn.container_id)
            return c.status == "running"
        except NotFound:
            return False
