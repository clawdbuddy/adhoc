"""Unit tests for controller/orchestrator/netns.py (pure-function subset).

Real netlink/bridge operations require a privileged Linux environment
and are covered by E2E tests (TC-E2E-*).
"""
from __future__ import annotations

import pytest

from controller.orchestrator.netns import (
    node_bridge_name,
    mesh_mac,
    DEFAULT_BRIDGE,
    DEFAULT_BRIDGE_IP,
    DEFAULT_BRIDGE_PREFIX,
)


class TestNodeBridgeName:
    def test_format(self):
        assert node_bridge_name(0) == "mesh-br-0"
        assert node_bridge_name(5) == "mesh-br-5"
        assert node_bridge_name(15) == "mesh-br-15"

    def test_prefix_uses_default_constant(self):
        assert DEFAULT_BRIDGE == "mesh-br"


class TestMeshMac:
    def test_format_valid(self):
        mac = mesh_mac(0)
        assert isinstance(mac, str)
        parts = mac.split(":")
        assert len(parts) == 6
        assert all(len(p) == 2 for p in parts)
        # All hex
        assert all(int(p, 16) < 256 for p in parts)

    def test_deterministic(self):
        assert mesh_mac(0) == mesh_mac(0)
        assert mesh_mac(5) == mesh_mac(5)

    def test_unique_per_node(self):
        macs = {mesh_mac(i) for i in range(16)}
        assert len(macs) == 16

    def test_node_15_last_octet_sixteen(self):
        # node_id=15 → last octet = 0x10 = 16
        assert mesh_mac(15).endswith(":10")

    def test_first_octet_zero(self):
        # First octet must be 00 to avoid ns-3 special-address confusion
        assert mesh_mac(0).startswith("00:")


class TestDefaultConstants:
    def test_bridge_ip_format(self):
        parts = DEFAULT_BRIDGE_IP.split(".")
        assert len(parts) == 4
        assert all(0 <= int(p) <= 255 for p in parts)

    def test_bridge_prefixlen(self):
        assert DEFAULT_BRIDGE_PREFIX == 24