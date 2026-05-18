"""Host Node Manager — manages physical hosts as MANET nodes.

Each physical host runs a `host-manet-node` container (--net=host) that
creates a VXLAN tunnel back to the controller.  The controller side
creates a matching VXLAN + bridge + TAP for each host node.

Data path:

  Host App → vxlan-{id} ── UDP/4789 ──► Controller vxlan-{id}
                                          |
                                     mesh-br-{id}
                                          ├── mesh-tap-{id} → ns-3 PHY/MAC

Unlike RemoteDockerMgr (which creates `--net=none` containers + veth
pairs), the host-manet-node container runs in the *host* network
namespace and manages its own VXLAN interface — HostNodeMgr only needs
to SSH-start the container and create the controller-side bridge + TAP.
"""
from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from typing import Optional

from .config import NodeSpec, SimConfig
from . import netns

try:
    import paramiko
    from paramiko import RSAKey, Ed25519Key, ECDSAKey
except ImportError as _e:
    paramiko = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

HOST_CONTAINER_PREFIX = "manet-host-node-"


def _load_pkey(key_data: str) -> Optional["paramiko.PKey"]:
    """Try loading a private key from its PEM/OpenSSH content string."""
    for cls in (RSAKey, Ed25519Key, ECDSAKey):
        try:
            return cls.from_private_key(io.StringIO(key_data))
        except Exception:
            continue
    return None


@dataclass
class _HostNode:
    spec: NodeSpec
    container_id: str


class HostNodeMgr:
    """Manages host-manet-node containers on a single remote physical host.

    For each node:
      1. SSH to the remote host and run the host-manet-node container
         (which creates the remote-side VXLAN tunnel).
      2. On the *controller* host: create per-node bridge + TAP interface.
      3. The VXLAN tunnel on the controller side is created later by
         ``Session.start()`` (calling ``create_vxlan_on_controller``)
         which also attaches it to the bridge created in step 2.
    """

    def __init__(
        self,
        host_ip: str,
        ssh_user: str = "root",
        ssh_key: str | None = None,
        ssh_password: str | None = None,
    ):
        self.host_ip = host_ip
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.ssh_password = ssh_password
        self._client: paramiko.SSHClient | None = None
        self._client_lock = threading.Lock()
        self._nodes: dict[int, _HostNode] = {}
        self._nodes_lock = threading.Lock()

    # ------------------------------------------------------------------ SSH
    def _ssh(self) -> paramiko.SSHClient:
        """Lazy-connect (and cache) a Paramiko SSHClient."""
        if paramiko is None:
            raise RuntimeError("paramiko is not installed")
        with self._client_lock:
            if self._client is not None:
                transport = self._client.get_transport()
                if transport is not None and transport.is_active():
                    return self._client
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs: dict = {
                "hostname": self.host_ip,
                "username": self.ssh_user,
                "timeout": 30,
                "banner_timeout": 30,
            }
            if self.ssh_key:
                pkey = _load_pkey(self.ssh_key)
                if pkey is not None:
                    connect_kwargs["pkey"] = pkey
                else:
                    raise ValueError(f"无法解析 SSH 私钥 (host={self.host_ip})")
            elif self.ssh_password:
                connect_kwargs["password"] = self.ssh_password
            client.connect(**connect_kwargs)
            self._client = client
            log.info("SSH connected to %s@%s", self.ssh_user, self.host_ip)
            return client

    def _exec(self, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
        """Execute a command on the remote host via SSH."""
        client = self._ssh()
        log.debug("[host %s] %s", self.host_ip, cmd)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_code, out, err

    def _exec_ok(self, cmd: str, timeout: int = 60) -> str:
        """Execute a command and raise on non-zero exit."""
        rc, out, err = self._exec(cmd, timeout)
        if rc != 0:
            raise RuntimeError(
                f"Remote command failed on {self.host_ip} (rc={rc}): {cmd}\n"
                f"stdout: {out}\nstderr: {err}"
            )
        return out

    # ------------------------------------------------------------------ container lifecycle
    def _detect_lan_ip(self) -> str:
        """Detect the remote host's LAN IP by checking the default route."""
        rc, out, _ = self._exec("ip route get 8.8.8.8 2>/dev/null || ip route get 1.1.1.1 2>/dev/null")
        parts = out.strip().split()
        for i, p in enumerate(parts):
            if p == "src" and i + 1 < len(parts):
                return parts[i + 1]
        raise RuntimeError(f"Could not detect LAN IP on {self.host_ip}")

    def _create_remote_vxlan(self, node_id: int, node_ip: str,
                              controller_ip: str, remote_mac: str) -> None:
        """Create VXLAN on the remote host for a host-manet-node.

        The VXLAN MAC is set to mesh peer MAC so the 802.11s mesh can
        route frames to/from this remote endpoint.
        MTU is reduced to 1400 to accommodate VXLAN encapsulation overhead.
        """
        vni = 100 + node_id
        remote_lan = self._detect_lan_ip()
        # Delete stale VXLAN if exists
        self._exec(f"sudo ip link delete vxlan-{node_id} 2>/dev/null || true")
        # Create VXLAN with correct parameters
        cmd = (
            f"sudo ip link add vxlan-{node_id} type vxlan "
            f"id {vni} local {remote_lan} remote {controller_ip} dstport 4789 && "
            f"sudo ip link set vxlan-{node_id} address {remote_mac} && "
            f"sudo ip link set vxlan-{node_id} mtu 1400 && "
            f"sudo ip addr add {node_ip}/24 dev vxlan-{node_id} && "
            f"sudo ip link set vxlan-{node_id} up"
        )
        self._exec_ok(cmd)
        log.info("Remote VXLAN vxlan-%d created (mac=%s ip=%s local=%s remote=%s)",
                 node_id, remote_mac, node_ip, remote_lan, controller_ip)

    def start_one(self, spec: NodeSpec, config: SimConfig,
                  controller_ip: str) -> dict:
        """Start a host-manet-node container on the remote host.

        Steps:
          1. SSH to the remote host and pull + run host-manet-node.
          2. Create remote VXLAN tunnel with correct MAC/IP/MTU.
          3. On the controller host: create the per-node bridge and TAP.
             (Local VXLAN will be created by Session.start() later.)

        Returns a dict with {container_id, host_ip, remote_lan_ip}.
        """
        if paramiko is None:
            raise RuntimeError("paramiko is not installed")

        name = f"{HOST_CONTAINER_PREFIX}{spec.id}"

        # 1) Kill stale container
        self._exec(f"docker rm -f {name} 2>/dev/null || true")

        # 2) Build env vars
        env_list = [
            f"-e NODE_ID={spec.id}",
            f"-e NODE_IP={spec.ip}",
            f"-e CONTROLLER_IP={controller_ip}",
            f"-e NODE_ROLE={spec.role}",
            f"-e SSH_ENABLE={'1' if spec.ssh_enable else '0'}",
            f"-e USER_APP_MODE={spec.user_app_mode}",
        ]
        if spec.user_app_cmd:
            env_list.append(f"-e USER_APP_CMD='{spec.user_app_cmd}'")
        if spec.ssh_authorized_keys:
            env_list.append(f"-e SSH_AUTHORIZED_KEYS='{spec.ssh_authorized_keys}'")

        # Pass the controller's view of the remote host IP as LOCAL_IP
        env_list.append(f"-e LOCAL_IP={self.host_ip}")

        env_str = " ".join(env_list)

        log.info("Host start %s on %s (image=%s IP=%s)",
                 name, self.host_ip, spec.image, spec.ip)

        # 3) docker run (--net=host, --privileged)
        #    Map local image names to GHCR host-manet-node images.
        #    If the caller specifies a custom image (e.g. GHCR path), use it as-is.
        image = spec.image or "manet-node:latest"
        if image in ("manet-node:latest", "host-manet-node:latest"):
            image = "ghcr.io/clawdbuddy/host-manet-node:main"
        # v1.1.4+ tagged images
        if image == "host-manet-node:1.1.4":
            image = "ghcr.io/clawdbuddy/host-manet-node:1.1.4"
        # Auto-pull if not present
        self._exec(f"docker images -q {image} 2>/dev/null | grep -q . || docker pull {image}")
        run_cmd = (
            f"docker run -d --name {name} --hostname host-manet-{spec.id} "
            f"--net=host --privileged --cap-add NET_ADMIN --cap-add SYS_ADMIN "
            f"{env_str} {image}"
        )
        out = self._exec_ok(run_cmd)
        container_id = out.strip()
        log.info("Host container %s started: %s", name, container_id)

        # 4) Create remote VXLAN tunnel
        remote_mac = netns.mesh_mac(spec.id)
        self._create_remote_vxlan(spec.id, spec.ip, controller_ip, remote_mac)

        # 5) Create controller-side bridge + TAP for this node
        #    (Local VXLAN will be added by Session.start() -> create_vxlan_on_controller)
        netns.ensure_node_bridge(spec.id)
        tap_name = f"mesh-tap-{spec.id}"
        netns.create_tap(tap_name, spec.id)
        log.info("Controller-side bridge+tap ready for host node %s", spec.id)

        with self._nodes_lock:
            self._nodes[spec.id] = _HostNode(spec=spec, container_id=container_id)

        remote_lan_ip = self._detect_lan_ip()
        return {
            "container_id": container_id,
            "host_ip": self.host_ip,
            "remote_lan_ip": remote_lan_ip,
        }

    def stop_one(self, node_id: int) -> None:
        """Stop the host-manet-node container and clean up controller-side links."""
        with self._nodes_lock:
            hn = self._nodes.pop(node_id, None)
        name = f"{HOST_CONTAINER_PREFIX}{node_id}"

        # Best-effort remote cleanup
        try:
            self._exec_ok(f"docker rm -f {name} 2>/dev/null || true")
        except Exception as e:
            log.warning("host stop: failed to remove %s on %s: %s", name, self.host_ip, e)

        # Clean up remote VXLAN
        try:
            self._exec_ok(f"sudo ip link delete vxlan-{node_id} 2>/dev/null || true")
        except Exception as e:
            log.warning("host stop: failed to remove vxlan-%d on %s: %s", node_id, self.host_ip, e)

        # Clean up controller-side bridge + tap
        netns.delete_link(f"mesh-tap-{node_id}")
        netns.delete_link(netns.node_bridge_name(node_id))
        log.info("Host node %d cleaned up on controller", node_id)

    def stop_all(self) -> None:
        """Stop all host-manet-node containers managed by this manager."""
        with self._nodes_lock:
            nids = list(self._nodes)
        for nid in nids:
            self.stop_one(nid)

    # ------------------------------------------------------------------ exec / logs / status
    def exec_on_host(self, cmd: str, timeout: int = 30) -> tuple[int, str]:
        """Execute a command directly on the remote host (not inside a container)."""
        return self._exec(cmd, timeout)

    def exec_in(self, node_id: int, cmd: str | list[str]) -> tuple[int, str]:
        """Execute a command inside the host-manet-node container."""
        hn = self._nodes.get(node_id)
        if hn is None:
            raise KeyError(f"Host node {node_id} not found on {self.host_ip}")
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = cmd
        docker_cmd = f"docker exec {hn.container_id} sh -c '{cmd_str}'"
        rc, out, err = self._exec(docker_cmd)
        return rc, out + err

    def logs(self, node_id: int, *, tail: int | str = 200) -> str:
        """Fetch container logs from the remote host."""
        hn = self._nodes.get(node_id)
        if hn is None:
            raise KeyError(f"Host node {node_id} not found on {self.host_ip}")
        rc, out, _ = self._exec(f"docker logs --tail {tail} {hn.container_id}")
        return out

    def is_running(self, node_id: int) -> bool:
        """Check whether the host-manet-node container is still running."""
        hn = self._nodes.get(node_id)
        if hn is None:
            return False
        try:
            rc, out, _ = self._exec(
                f"docker inspect -f '{{{{.State.Running}}}}' {hn.container_id}"
            )
            return out.strip().lower() == "true"
        except Exception:
            return False

    def close(self) -> None:
        """Close the SSH connection."""
        with self._client_lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
