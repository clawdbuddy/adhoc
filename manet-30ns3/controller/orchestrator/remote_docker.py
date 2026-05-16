"""Remote Docker manager — controls node containers on a remote host via SSH.

Each remote host runs Docker daemon locally.  The controller opens an SSH
connection to the host and executes docker / iproute2 commands remotely.

Per-node network on the remote host (mirrors the local setup but uses VXLAN
instead of TAP to reach the controller):

    mesh-br-{i} (per-node bridge, STP off)
    ├── mesh-veth{i}   (host side, up)
    └── vxlan-{i}      (VXLAN tunnel to controller, VNI=100+i)

    Container netns:
    └── eth0 (renamed from mesh-vethns{i}, MAC=00:00:00:00:00:{i+1})

Frames from the container traverse: eth0 → veth → bridge → vxlan → UDP/4789
→ controller host → bridge → tap → ns-3.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

from .config import NodeSpec, SimConfig
from . import netns

try:
    import paramiko
except ImportError as _e:  # pragma: no cover
    paramiko = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

CONTAINER_PREFIX = "manet-node-"


@dataclass
class _RemoteNode:
    spec: NodeSpec
    container_id: str
    pid: int


class RemoteDockerMgr:
    """Manages Docker containers and L2 plumbing on a single remote host."""

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
        self._client: "paramiko.SSHClient | None" = None
        self._client_lock = threading.Lock()
        self._nodes: dict[int, _RemoteNode] = {}
        self._nodes_lock = threading.Lock()

    # ------------------------------------------------------------------ SSH
    def _ssh(self) -> "paramiko.SSHClient":
        """Lazy-connect (and cache) a Paramiko SSHClient."""
        if paramiko is None:
            raise RuntimeError("paramiko is not installed; remote hosts are unsupported")
        with self._client_lock:
            if self._client is not None:
                # Verify the transport is still alive
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
                connect_kwargs["key_filename"] = self.ssh_key
            elif self.ssh_password:
                connect_kwargs["password"] = self.ssh_password
            client.connect(**connect_kwargs)
            self._client = client
            log.info("SSH connected to %s@%s", self.ssh_user, self.host_ip)
            return client

    def _exec(self, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
        """Execute a command on the remote host via SSH.

        Returns (exit_code, stdout, stderr).
        """
        client = self._ssh()
        log.debug("[remote %s] %s", self.host_ip, cmd)
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

    # ------------------------------------------------------------------ local IP discovery
    def _get_local_ip(self) -> str:
        """Return the IP address on the remote host used to reach the controller.

        We ask the remote host for its default route's source IP, which is
        the IP it will use to send VXLAN packets to the controller.
        """
        # Try to infer from the SSH connection's local address
        client = self._ssh()
        transport = client.get_transport()
        if transport is not None:
            sock = transport.sock
            if hasattr(sock, "getsockname"):
                local_addr = sock.getsockname()[0]
                # This is the *controller* side IP; we need the remote side.
                # Fallback: ask the remote host directly.
        # Ask the remote host which IP it uses for the default route
        cmd = (
            "ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++)"
            " if($i==\"src\"){print $(i+1); exit}}' || hostname -I | awk '{print $1}'"
        )
        rc, out, _ = self._exec(cmd)
        ip = out.strip().split()[0] if out.strip() else ""
        if not ip:
            raise RuntimeError(f"Cannot determine local IP on remote host {self.host_ip}")
        return ip

    # ------------------------------------------------------------------ container lifecycle
    def start_one(self, spec: NodeSpec, config: SimConfig,
                  controller_ip: str) -> dict:
        """Start a node container on the remote host and set up its VXLAN plumbing.

        Returns a dict with {container_id, pid, host_ip}.
        """
        if paramiko is None:
            raise RuntimeError("paramiko is not installed")

        name = f"{CONTAINER_PREFIX}{spec.id}"
        # 1) Kill stale container
        self._exec(f"docker rm -f {name} 2>/dev/null || true")

        # 2) Build env and volumes
        env_list = [
            f"-e NODE_ID={spec.id}",
            f"-e NODE_IP={spec.ip}",
            f"-e NODE_ROLE={spec.role}",
            f"-e BRIDGE_IP={netns.DEFAULT_BRIDGE_IP}",
            f"-e USER_APP_MODE={spec.user_app_mode}",
            f"-e BSSID={config.bssid}",
            f"-e SSH_ENABLE={'1' if spec.ssh_enable else '0'}",
        ]
        if spec.user_app_cmd:
            env_list.append(f"-e USER_APP_CMD='{spec.user_app_cmd}'")
        if spec.ssh_authorized_keys:
            env_list.append(f"-e SSH_AUTHORIZED_KEYS='{spec.ssh_authorized_keys}'")

        vol_list: list[str] = []
        if spec.user_app_mode == "bind" and spec.user_app_bind_path:
            vol_list.append(f"-v {spec.user_app_bind_path}:/opt/userapp:rw")

        env_str = " ".join(env_list)
        vol_str = " ".join(vol_list)

        log.info("Remote start %s on %s (image=%s IP=%s)",
                 name, self.host_ip, spec.image, spec.ip)

        # 3) docker run
        run_cmd = (
            f"docker run -d --name {name} --hostname adhoc-node-{spec.id} "
            f"--network none --privileged --cap-add NET_ADMIN --cap-add SYS_ADMIN "
            f"{env_str} {vol_str} {spec.image}"
        )
        out = self._exec_ok(run_cmd)
        container_id = out.strip()

        # 4) Get container PID
        pid_out = self._exec_ok(f"docker inspect -f '{{{{.State.Pid}}}}' {container_id}")
        pid = int(pid_out.strip())
        if not pid:
            raise RuntimeError(f"Remote container {name} has no PID")

        # 5) L2 plumbing on the remote host
        veth_host = f"mesh-veth{spec.id}"
        veth_peer = f"mesh-vethns{spec.id}"
        bridge = netns.node_bridge_name(spec.id)
        tap = f"mesh-tap-{spec.id}"
        vxlan = f"vxlan-{spec.id}"
        vni = 100 + spec.id
        mac = netns.mesh_mac(spec.id)
        local_ip = self._get_local_ip()

        # Ensure the remote host has the netns symlink dir available
        self._exec_ok("mkdir -p /var/run/netns")

        # Create veth pair
        self._exec_ok(f"ip link add {veth_host} type veth peer {veth_peer}")

        # Move peer into container netns, rename to eth0, set MAC/IP
        self._exec_ok(f"ip link set {veth_peer} netns {pid}")
        self._exec_ok(
            f"ip netns exec {pid} ip link set {veth_peer} name eth0"
        )
        self._exec_ok(
            f"ip netns exec {pid} ip link set eth0 address {mac}"
        )
        self._exec_ok(
            f"ip netns exec {pid} ip addr add {spec.ip}/24 dev eth0"
        )
        self._exec_ok(
            f"ip netns exec {pid} ip link set eth0 up"
        )
        self._exec_ok(
            f"ip netns exec {pid} ip link set lo up"
        )

        # Create per-node bridge on remote host
        self._exec_ok(f"ip link add {bridge} type bridge")
        self._exec_ok(
            f"ip link set {bridge} type bridge stp_state 0 forward_delay 0"
        )
        self._exec_ok(f"ip link set {bridge} up")

        # Attach veth host side to bridge
        self._exec_ok(f"ip link set {veth_host} master {bridge}")
        self._exec_ok(f"ip link set {veth_host} up")

        # Create VXLAN tunnel
        self._exec_ok(
            f"ip link add {vxlan} type vxlan id {vni} "
            f"remote {controller_ip} local {local_ip} dstport 4789"
        )
        self._exec_ok(f"ip link set {vxlan} up")
        self._exec_ok(f"ip link set {vxlan} master {bridge}")

        log.info(
            "Remote node %s ready on %s: pid=%d veth=%s vxlan=%s(vni=%d)",
            name, self.host_ip, pid, veth_host, vxlan, vni,
        )

        with self._nodes_lock:
            self._nodes[spec.id] = _RemoteNode(spec=spec, container_id=container_id, pid=pid)

        return {
            "container_id": container_id,
            "pid": pid,
            "host_ip": self.host_ip,
        }

    def stop_one(self, node_id: int) -> None:
        """Stop the remote container and clean up veth / bridge / vxlan."""
        with self._nodes_lock:
            rn = self._nodes.pop(node_id, None)
        name = f"{CONTAINER_PREFIX}{node_id}"
        # Best-effort cleanup; ignore errors on disconnected hosts
        try:
            self._exec_ok(f"docker rm -f {name} 2>/dev/null || true")
        except Exception as e:
            log.warning("remote stop: failed to remove container %s on %s: %s", name, self.host_ip, e)

        for link in (f"mesh-veth{node_id}", f"mesh-tap-{node_id}",
                     f"vxlan-{node_id}", netns.node_bridge_name(node_id)):
            try:
                self._exec_ok(f"ip link del {link} 2>/dev/null || true")
            except Exception as e:
                log.warning("remote stop: failed to delete %s on %s: %s", link, self.host_ip, e)

    def stop_all(self) -> None:
        """Stop all remote nodes managed by this manager."""
        with self._nodes_lock:
            nids = list(self._nodes)
        for nid in nids:
            self.stop_one(nid)

    # ------------------------------------------------------------------ exec / logs / status
    def exec_in(self, node_id: int, cmd: str | list[str]) -> tuple[int, str]:
        """Execute a command inside the remote container."""
        rn = self._nodes.get(node_id)
        if rn is None:
            raise KeyError(f"Remote node {node_id} not found on {self.host_ip}")
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = cmd
        docker_cmd = f"docker exec {rn.container_id} sh -c '{cmd_str}'"
        rc, out, err = self._exec(docker_cmd)
        return rc, out + err

    def logs(self, node_id: int, *, tail: int | str = 200) -> str:
        """Fetch container logs from the remote host."""
        rn = self._nodes.get(node_id)
        if rn is None:
            raise KeyError(f"Remote node {node_id} not found on {self.host_ip}")
        rc, out, _ = self._exec(f"docker logs --tail {tail} {rn.container_id}")
        return out

    def is_running(self, node_id: int) -> bool:
        """Check whether the remote container is still running."""
        rn = self._nodes.get(node_id)
        if rn is None:
            return False
        try:
            rc, out, _ = self._exec(
                f"docker inspect -f '{{{{.State.Running}}}}' {rn.container_id}"
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
