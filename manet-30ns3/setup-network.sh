#!/bin/bash
# setup-network.sh - Create isolated network infrastructure for N Docker nodes
#
# ARCHITECTURE:
#   Each Docker container has its OWN network namespace.
#   Containers CANNOT talk to each other directly.
#   All inter-node traffic MUST go through ns-3 TapBridge -> AdHoc channel.
#
# DATA PATH PER NODE:
#   Container-N -> eth0 -> veth pair -> br-ns3 -> tap-N -> ns-3 TapBridge
#                                                             |
#                                                    +--------v--------+
#                                                    |  ns-3 AdHoc     |
#                                                    |  MAC/PHY        |
#                                                    |  Channel Model  |
#                                                    +--------+--------+
#                                                             |
#   Container-M <- eth0 <- veth pair <- br-ns3 <- tap-M <----+

set -e

NODE_COUNT=${1:-30}
BRIDGE_NAME="br-ns3"
SUBNET="192.168.100"

echo "========================================"
echo "  Network Infrastructure Setup"
echo "  Nodes: ${NODE_COUNT}"
echo "========================================"

# Create Linux Bridge (the "virtual air" connecting all nodes to ns-3)
echo "[1/3] Creating bridge ${BRIDGE_NAME}..."
sudo ip link add ${BRIDGE_NAME} type bridge 2>/dev/null || true

# Critical: disable bridge STP and forward delay for instant forwarding
sudo ip link set ${BRIDGE_NAME} type bridge stp_state 0 2>/dev/null || true
sudo ip link set ${BRIDGE_NAME} type bridge forward_delay 0 2>/dev/null || true

sudo ip addr flush dev ${BRIDGE_NAME} 2>/dev/null || true
sudo ip addr add ${SUBNET}.1/24 dev ${BRIDGE_NAME}
sudo ip link set ${BRIDGE_NAME} up

# Enable IP forwarding for bridge management traffic
sudo sysctl -w net.ipv4.ip_forward=1 > /dev/null

# NAT for external access (optional)
sudo iptables -t nat -A POSTROUTING -s ${SUBNET}.0/24 ! -o ${BRIDGE_NAME} -j MASQUERADE 2>/dev/null || true

# Create veth pairs: one end stays on host (bridged), other goes to container netns
echo "[2/3] Creating ${NODE_COUNT} veth pairs..."
for i in $(seq 0 $((NODE_COUNT-1))); do
    VETH_HOST="veth${i}"
    VETH_NS="vethns${i}"
    
    # Clean up existing
    sudo ip link del ${VETH_HOST} 2>/dev/null || true
    
    # Create veth pair
    # veth${i}:  host side, connected to br-ns3
    # vethns${i}: container side, will be moved to container's netns and renamed to eth0
    sudo ip link add ${VETH_HOST} type veth peer name ${VETH_NS}
    sudo ip link set ${VETH_HOST} master ${BRIDGE_NAME}
    sudo ip link set ${VETH_HOST} up
    
    echo "  Node-${i}: ${VETH_HOST} (host) <-> ${VETH_NS} (container)"
done

# Create TAP devices for ns-3 TapBridge
echo "[3/3] Creating ${NODE_COUNT} TAP devices..."
for i in $(seq 0 $((NODE_COUNT-1))); do
    TAP="tap-${i}"
    sudo ip tuntap add dev ${TAP} mode tap 2>/dev/null || true
    sudo ip link set ${TAP} up 2>/dev/null || true
    sudo ip link set ${TAP} master ${BRIDGE_NAME} 2>/dev/null || true
    echo "  tap-${i}: ns-3 TapBridge interface for Node-${i}"
done

echo ""
echo "========================================"
echo "Network infrastructure ready:"
echo "  Bridge: ${BRIDGE_NAME} (${SUBNET}.1/24)"
echo "  veth pairs: ${NODE_COUNT} (container links)"
echo "  TAP devices: ${NODE_COUNT} (ns-3 interfaces)"
echo ""
echo "Traffic flow:"
echo "  Container -> eth0 -> veth -> br-ns3 -> tap-N -> ns-3 AdHoc"
echo "========================================"
