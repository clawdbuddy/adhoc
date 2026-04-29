#!/bin/bash
# cleanup.sh - Tear down MANET simulation

echo "Tearing down MANET simulation..."

# Stop and remove node containers
NODES=$(docker ps -aq -f name=manet-node- 2>/dev/null)
if [ -n "$NODES" ]; then
    docker stop $NODES 2>/dev/null || true
    docker rm $NODES 2>/dev/null || true
fi

# Stop controller
CONTROLLER=$(docker ps -aq -f name=ns3-controller 2>/dev/null)
if [ -n "$CONTROLLER" ]; then
    docker stop $CONTROLLER 2>/dev/null || true
    docker rm $CONTROLLER 2>/dev/null || true
fi

# Remove bridge
sudo ip link del br-ns3 2>/dev/null || true

# Remove veth and tap devices
for i in $(seq 0 29); do
    sudo ip link del "veth${i}" 2>/dev/null || true
    sudo ip link del "tap-${i}" 2>/dev/null || true
done

# Clean iptables
sudo iptables -t nat -F 2>/dev/null || true

echo "Cleanup complete."
