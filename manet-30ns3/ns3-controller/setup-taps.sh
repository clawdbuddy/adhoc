#!/bin/bash
# setup-taps.sh - Create TAP devices inside NS-3 controller container

NODE_COUNT=${1:-30}
BRIDGE_NAME="br-ns3"

for i in $(seq 0 $((NODE_COUNT-1))); do
    TAP_NAME="tap-${i}"
    
    ip tuntap add dev ${TAP_NAME} mode tap 2>/dev/null || true
    ip link set ${TAP_NAME} up 2>/dev/null || true
    
    # Bridge tap to host bridge (requires --net=host)
    brctl addif ${BRIDGE_NAME} ${TAP_NAME} 2>/dev/null || true || echo "Note: brctl may need bridge-utils"
    
    echo "TAP ${TAP_NAME} -> ${BRIDGE_NAME}"
done

echo "${NODE_COUNT} TAP devices ready."
