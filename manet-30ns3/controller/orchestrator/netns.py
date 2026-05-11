"""Network namespace and L2 plumbing for the MANET controller.

Replaces setup-network.sh / cleanup.sh / setup-taps.sh. Idempotent.

For each node `i`:
    mesh-veth{i}      (host side, master = mesh-br-{i}, up)
    mesh-vethns{i}    (peer side, moved into the container's netns and renamed eth0)
    mesh-tap-{i}      (master = mesh-br-{i}, up; attached by ns-3 TapBridge in UseBridge mode)

Each node has its own dedicated Linux bridge `mesh-br-{i}` that connects only
that node's veth and TAP.  This prevents the Linux bridge from learning
container MAC addresses and forwarding unicast frames directly between veth
interfaces, which would bypass the ns-3 PHY/MAC simulation entirely.

Cross-node traffic is forced to go through ns-3:

    Container-0 eth0 → mesh-veth0 → mesh-br-0 → mesh-tap-0
        → [ns-3 WifiNetDevice → SpectrumChannel → WifiNetDevice]
            → mesh-tap-1 → mesh-br-1 → mesh-veth1 → Container-1 eth0

Multi-host hook (Phase 2): replace the local per-node bridges with VXLAN-backed
bridges on each host so frames cross the overlay to the simulation host.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from typing import Iterator

from pyroute2 import IPRoute, NetNS

log = logging.getLogger(__name__)

DEFAULT_BRIDGE = "mesh-br"
DEFAULT_BRIDGE_IP = "192.168.100.1"
DEFAULT_BRIDGE_PREFIX = 24

# 线程本地 IPRoute 缓存：每个线程复用同一 netlink socket，减少创建/销毁开销
_ipr_local = threading.local()


def _get_ipr() -> IPRoute:
    """获取线程本地的 IPRoute 实例（首次调用时创建）。"""
    ipr = getattr(_ipr_local, "ipr", None)
    if ipr is None:
        ipr = IPRoute()
        _ipr_local.ipr = ipr
    return ipr


def _close_ipr() -> None:
    """关闭线程本地 IPRoute 实例。"""
    ipr = getattr(_ipr_local, "ipr", None)
    if ipr is not None:
        try:
            ipr.close()
        except Exception:
            pass
        _ipr_local.ipr = None


def _get_link_index(ipr: IPRoute, name: str) -> int | None:
    idx = ipr.link_lookup(ifname=name)
    return idx[0] if idx else None


def node_bridge_name(node_id: int) -> str:
    """Return the per-node bridge name, e.g. mesh-br-0."""
    return f"{DEFAULT_BRIDGE}-{node_id}"


def ensure_node_bridge(
    node_id: int,
    ip: str | None = None,
    prefixlen: int = DEFAULT_BRIDGE_PREFIX,
) -> None:
    """Create the per-node bridge mesh-br-{node_id} with STP off, idempotently."""
    name = node_bridge_name(node_id)
    ipr = _get_ipr()
    idx = _get_link_index(ipr, name)
    if idx is None:
        ipr.link("add", ifname=name, kind="bridge")
        idx = _get_link_index(ipr, name)
        log.info("created node bridge %s", name)
    # STP off, forward_delay 0
    ipr.link(
        "set", index=idx, kind="bridge",
        br_stp_state=0, br_forward_delay=0,
    )
    if ip:
        # Replace IP
        for addr in ipr.get_addr(index=idx, family=2):
            ipr.addr("del", index=idx, address=addr.get_attr("IFA_ADDRESS"),
                     prefixlen=addr["prefixlen"])
        ipr.addr("add", index=idx, address=ip, prefixlen=prefixlen)
    ipr.link("set", index=idx, state="up")


def ensure_bridge(
    name: str = DEFAULT_BRIDGE,
    ip: str = DEFAULT_BRIDGE_IP,
    prefixlen: int = DEFAULT_BRIDGE_PREFIX,
) -> None:
    """Create mesh-br with STP off and the gateway IP, idempotently.

    .. deprecated::
        Use :func:`ensure_node_bridge` for per-node isolated bridges.
        Kept for backward compatibility.
    """
    ipr = _get_ipr()
    idx = _get_link_index(ipr, name)
    if idx is None:
        ipr.link("add", ifname=name, kind="bridge")
        idx = _get_link_index(ipr, name)
        log.info("created bridge %s", name)
    ipr.link(
        "set", index=idx, kind="bridge",
        br_stp_state=0, br_forward_delay=0,
    )
    for addr in ipr.get_addr(index=idx, family=2):
        ipr.addr("del", index=idx, address=addr.get_attr("IFA_ADDRESS"),
                 prefixlen=addr["prefixlen"])
    ipr.addr("add", index=idx, address=ip, prefixlen=prefixlen)
    ipr.link("set", index=idx, state="up")


def create_veth(host_name: str, peer_name: str, node_id: int) -> None:
    """veth pair; host-side joins the per-node bridge and goes up.
    Peer-side is left in the host netns (caller moves it into the container)."""
    bridge = node_bridge_name(node_id)
    ipr = _get_ipr()
    if _get_link_index(ipr, host_name) is None:
        ipr.link("add", ifname=host_name, kind="veth", peer={"ifname": peer_name})
        log.info("created veth pair %s ↔ %s", host_name, peer_name)
    host_idx = _get_link_index(ipr, host_name)
    br_idx = _get_link_index(ipr, bridge)
    if br_idx is None:
        raise RuntimeError(f"bridge {bridge} missing; call ensure_node_bridge({node_id}) first")
    ipr.link("set", index=host_idx, master=br_idx)
    ipr.link("set", index=host_idx, state="up")


def mesh_mac(node_id: int) -> str:
    """Return the deterministic MAC address used by ns-3 MeshPointDevice.

    ns-3 allocates MACs sequentially starting from 00:00:00:00:00:01.
    The container's eth0 must use the same MAC so the 802.11s mesh
    layer treats the container as a mesh peer rather than a bridged
    client (which would break unicast forwarding).
    """
    return f"00:00:00:00:00:{node_id + 1:02x}"


def move_to_netns(
    peer_name: str,
    pid: int,
    *,
    rename_to: str = "eth0",
    ip: str | None = None,
    prefixlen: int = 24,
    mac: str | None = None,
) -> None:
    """Move `peer_name` (host-side) into the netns identified by `pid`,
    rename it to `rename_to`, optionally set MAC / assign IP, and bring it up."""
    netns_path = f"/proc/{pid}/ns/net"
    if not os.path.exists(netns_path):
        raise RuntimeError(f"container pid {pid} has no /proc/<pid>/ns/net (already exited?)")
    # 1) move
    ipr = _get_ipr()
    idx = _get_link_index(ipr, peer_name)
    if idx is None:
        raise RuntimeError(f"veth peer {peer_name} not found in host netns")
    # IPRoute.link("set", net_ns_fd=...) accepts the netns name registered
    # under /var/run/netns. We register a temporary symlink for this pid.
    ns_alias = f"node-pid-{pid}"
    netns_dir = "/var/run/netns"
    os.makedirs(netns_dir, exist_ok=True)
    alias_path = os.path.join(netns_dir, ns_alias)
    try:
        if os.path.islink(alias_path) or os.path.exists(alias_path):
            os.unlink(alias_path)
    except OSError:
        pass
    os.symlink(netns_path, alias_path)
    try:
        ipr.link("set", index=idx, net_ns_fd=ns_alias)
    finally:
        try:
            os.unlink(alias_path)
        except OSError:
            pass
    # 2) rename + configure inside the target netns
    with NetNS(netns_path) as ns:
        peer_idx = ns.link_lookup(ifname=peer_name)
        if not peer_idx:
            raise RuntimeError(f"{peer_name} did not appear inside container netns")
        peer_idx = peer_idx[0]
        ns.link("set", index=peer_idx, ifname=rename_to)
        if mac:
            ns.link("set", index=peer_idx, address=mac)
        if ip:
            # Flush any prior addresses on the iface, then assign.
            for addr in ns.get_addr(index=peer_idx, family=2):
                ns.addr("del", index=peer_idx, address=addr.get_attr("IFA_ADDRESS"),
                        prefixlen=addr["prefixlen"])
            ns.addr("add", index=peer_idx, address=ip, prefixlen=prefixlen)
        ns.link("set", index=peer_idx, state="up")


def create_tap(name: str, node_id: int) -> None:
    """ip tuntap add `name` mode tap; attach to per-node bridge; bring up."""
    bridge = node_bridge_name(node_id)
    ipr = _get_ipr()
    if _get_link_index(ipr, name) is None:
        ipr.link("add", ifname=name, kind="tuntap", mode="tap")
        log.info("created tap %s", name)
    idx = _get_link_index(ipr, name)
    br_idx = _get_link_index(ipr, bridge)
    if br_idx is None:
        raise RuntimeError(f"bridge {bridge} missing")
    ipr.link("set", index=idx, master=br_idx)
    ipr.link("set", index=idx, state="up")


def delete_link(name: str) -> None:
    """Best-effort link deletion."""
    ipr = _get_ipr()
    idx = _get_link_index(ipr, name)
    if idx is None:
        return
    try:
        ipr.link("del", index=idx)
    except Exception as e:  # noqa: BLE001
        log.warning("failed to delete %s: %s", name, e)


# 残留接口匹配模式: mesh-tap-N, mesh-tap-testN, mesh-tap-adhocN, mesh-test-tapN,
# mesh-vethN, mesh-br-N, mesh-br
_STALE_PATTERNS = [
    re.compile(r"^mesh-tap-\d+$"),
    re.compile(r"^mesh-tap-test\d+$"),
    re.compile(r"^mesh-tap-adhoc\d+$"),
    re.compile(r"^mesh-test-tap\d+$"),
    re.compile(r"^mesh-veth\d+$"),
    re.compile(r"^mesh-br-\d+$"),
    re.compile(r"^mesh-br$"),
]


def list_stale_links() -> list[str]:
    """Scan host network interfaces and return names matching simulation leftovers."""
    ipr = _get_ipr()
    stale: list[str] = []
    for msg in ipr.get_links():
        name = msg.get_attr("IFLA_IFNAME")
        if name and any(p.match(name) for p in _STALE_PATTERNS):
            stale.append(name)
    return stale


def teardown(node_count: int) -> None:
    """Remove veth, tap, and per-node bridges for nodes [0, node_count).

    Also scans for any simulation-related interfaces left behind by prior runs
    (different node counts, test matrices, adhoc experiments) and deletes them.
    """
    # 1) 按预期范围清理
    for i in range(node_count):
        delete_link(f"mesh-veth{i}")
        delete_link(f"mesh-tap-{i}")
        delete_link(node_bridge_name(i))
    # 2) 兜底:扫描并删除所有残留仿真接口
    for name in list_stale_links():
        delete_link(name)
    # 3) 清理所有线程本地 IPRoute 实例
    _close_ipr()


@contextmanager
def host_netns_context() -> Iterator[None]:
    """Context that pins the calling thread to the host netns. Useful when
    pyroute2 ops are mixed with code that itself moves netns."""
    fd = os.open("/proc/1/ns/net", os.O_RDONLY)
    try:
        # We don't actually setns() here; pyroute2 IPRoute() defaults to host.
        # This stub exists to mark intent and could be extended with libc.setns().
        yield
    finally:
        os.close(fd)
