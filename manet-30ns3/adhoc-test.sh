#!/bin/bash
# adhoc-test.sh - Configurable AdHoc Network Test Suite
#
# Usage:
#   ./adhoc-test.sh [test_name] [options]
#
# Tests: ping-flood | broadcast | iperf-mesh | udp-flood | neighbor-discovery | route-trace | all
#
# Environment overrides:
#   NODES=30       - Number of nodes
#   SUBNET=192.168.100 - Subnet prefix
#   BASE_IP=10     - Starting IP offset
#   RESULTS_DIR=./results - Output directory

set -e

# --- Configurable defaults ---
NODE_COUNT=${NODES:-30}
SUBNET=${SUBNET:-192.168.100}
BASE_IP=${BASE_IP:-10}
RESULTS_DIR=${RESULTS:-./results}
TEST_DURATION=${TEST_DURATION:-10}
IPERF_TIME=${IPERF_TIME:-10}

TEST=${1:-all}
shift || true

mkdir -p ${RESULTS_DIR}

echo "========================================"
echo "  AdHoc Test Suite"
echo "  Test: ${TEST}"
echo "  Nodes: ${NODE_COUNT}  Subnet: ${SUBNET}.0/24"
echo "========================================"

# Helper: check node is running
check_node() {
    local id=$1
    if ! docker ps --format '{{.Names}}' | grep -q "manet-node-${id}$"; then
        echo "SKIP: manet-node-${id} not running"
        return 1
    fi
}

# Helper: resolve node IP
node_ip() {
    echo "${SUBNET}.$((BASE_IP+$1))"
}

# ================================================================
# TEST 1: Ping Flood (random pairs)
# ================================================================
test_ping_flood() {
    echo ""
    echo "--- [1] Ping Flood ---"
    local pairs=("1:0" "5:10" "15:20" "25:2" "8:18")
    > "${RESULTS_DIR}/ping-flood.log"
    
    for pair in "${pairs[@]}"; do
        IFS=':' read -r src dst <<< "$pair"
        check_node $src || continue
        check_node $dst || continue
        
        local src_ip=$(node_ip $src)
        local dst_ip=$(node_ip $dst)
        echo "  Node-${src} (${src_ip}) -> Node-${dst} (${dst_ip})"
        
        docker exec "manet-node-${src}" ping -c 5 -i 0.2 "${dst_ip}" 2>&1 | tail -3 \
            | tee -a "${RESULTS_DIR}/ping-flood.log"
        echo "---" >> "${RESULTS_DIR}/ping-flood.log"
    done
}

# ================================================================
# TEST 2: Broadcast Reachability
# ================================================================
test_broadcast() {
    echo ""
    echo "--- [2] Broadcast/Multicast ---"
    local src=1
    check_node $src || return
    
    echo "  Node-${src} broadcasting to ${SUBNET}.255"
    docker exec "manet-node-${src}" ping -c 3 -b "${SUBNET}.255" 2>&1 \
        | tee -a "${RESULTS_DIR}/broadcast.log"
    
    # UDP broadcast test
    echo "  UDP broadcast test..."
    docker exec "manet-node-${src}" bash -c \
        "echo 'BROADCAST_TEST' | socat - UDP4-DATAGRAM:${SUBNET}.255:5000,broadcast" 2>/dev/null
    sleep 1
}

# ================================================================
# TEST 3: iperf3 Mesh Throughput
# ================================================================
test_iperf_mesh() {
    echo ""
    echo "--- [3] iperf3 Mesh Throughput ---"
    
    # Server nodes
    local servers=(0 10 20)
    for s in "${servers[@]}"; do
        check_node $s || continue
        docker exec "manet-node-${s}" pkill iperf3 2>/dev/null || true
        docker exec -d "manet-node-${s}" iperf3 -s -p 5201
        echo "  Server on Node-${s} ($(node_ip $s):5201)"
        sleep 1
    done
    
    # Client flows
    local flows=("1:0" "11:10" "21:20" "5:20" "15:0" "3:10" "7:20")
    for flow in "${flows[@]}"; do
        IFS=':' read -r client server <<< "$flow"
        check_node $client || continue
        check_node $server || continue
        
        local srv_ip=$(node_ip $server)
        echo "  Node-${client} -> Node-${server} (${srv_ip}) TCP ${IPERF_TIME}s"
        
        docker exec "manet-node-${client}" \
            timeout $((IPERF_TIME+5)) \
            iperf3 -c "${srv_ip}" -p 5201 -t "${IPERF_TIME}" -J \
            > "${RESULTS_DIR}/iperf-node${client}-to-node${server}.json" 2>/dev/null || true
        
        # Extract summary
        if [ -f "${RESULTS_DIR}/iperf-node${client}-to-node${server}.json" ]; then
            local bw=$(python3 -c "
import json,sys
try:
    d=json.load(open('${RESULTS_DIR}/iperf-node${client}-to-node${server}.json'))
    print(f'{d[\"end\"][\"sum_received\"][\"bits_per_second\"]/1e6:.2f}')
except: print('N/A')
" 2>/dev/null)
            echo "    Result: ${bw} Mbps"
        fi
    done
    
    # Cleanup servers
    for s in "${servers[@]}"; do
        docker exec "manet-node-${s}" pkill iperf3 2>/dev/null || true
    done
}

# ================================================================
# TEST 4: UDP Flood
# ================================================================
test_udp_flood() {
    echo ""
    echo "--- [4] UDP Broadcast Flood ---"
    local src=2
    check_node $src || return
    
    echo "  Node-${src} flooding UDP broadcast ${SUBNET}.255:5000"
    docker exec "manet-node-${src}" bash -c \
        "for i in \$(seq 1 50); do echo \"FLOOD_\$i\" | socat - UDP4-DATAGRAM:${SUBNET}.255:5000,broadcast; sleep 0.05; done" &
    local pid=$!
    
    # Capture on random nodes
    local targets=(0 1 3 5 10 15 20 25)
    for nid in "${targets[@]}"; do
        check_node $nid || continue
        timeout 5 docker exec "manet-node-${nid}" tcpdump -i eth0 -nn -l -c 10 udp port 5000 2>/dev/null \
            | tee "${RESULTS_DIR}/udp-flood-node${nid}.log" &
    done
    
    wait $pid 2>/dev/null || true
    sleep 2
    
    # Count received packets per node
    echo "  Reception summary:"
    for nid in "${targets[@]}"; do
        local count=$(wc -l < "${RESULTS_DIR}/udp-flood-node${nid}.log" 2>/dev/null || echo 0)
        echo "    Node-${nid}: ~${count} packets"
    done
}

# ================================================================
# TEST 5: Neighbor Discovery (ARP + ping sweep)
# ================================================================
test_neighbor_discovery() {
    echo ""
    echo "--- [5] Neighbor Discovery ---"
    local src=3
    check_node $src || return
    
    echo "  Node-${src} scanning ${SUBNET}.${BASE_IP} - ${SUBNET}.$((BASE_IP+NODE_COUNT-1))"
    docker exec "manet-node-${src}" bash -c \
        "for i in \$(seq ${BASE_IP} $((BASE_IP+NODE_COUNT-1))); do 
            ping -c 1 -W 0.5 ${SUBNET}.\$i >/dev/null 2>&1 && echo \"REACHABLE ${SUBNET}.\$i\" 
        done" | tee "${RESULTS_DIR}/neighbors-node${src}.log"
    
    local reachable=$(grep -c "REACHABLE" "${RESULTS_DIR}/neighbors-node${src}.log" 2>/dev/null || echo 0)
    echo "  ${reachable}/${NODE_COUNT} nodes reachable from Node-${src}"
    
    echo "  ARP table:"
    docker exec "manet-node-${src}" ip neigh | tee -a "${RESULTS_DIR}/neighbors-node${src}.log"
}

# ================================================================
# TEST 6: Route Trace (multi-hop)
# ================================================================
test_route_trace() {
    echo ""
    echo "--- [6] Route Trace (multi-hop path) ---"
    
    # Test from far nodes to see if multi-hop routing works
    local paths=("29:0" "25:5" "20:10")
    for p in "${paths[@]}"; do
        IFS=':' read -r src dst <<< "$p"
        check_node $src || continue
        check_node $dst || continue
        
        local dst_ip=$(node_ip $dst)
        echo "  Node-${src} -> Node-${dst} (${dst_ip})"
        
        # Traceroute
        docker exec "manet-node-${src}" traceroute -n -m 10 "${dst_ip}" 2>&1 | head -5 \
            | tee -a "${RESULTS_DIR}/route-trace.log"
        
        # MTR (if available)
        docker exec "manet-node-${src}" mtr -n -r -c 5 "${dst_ip}" 2>/dev/null \
            | tee -a "${RESULTS_DIR}/route-mtr.log" || true
        echo "---" >> "${RESULTS_DIR}/route-trace.log"
    done
}

# ================================================================
# TEST 7: Concurrent Load Test
# ================================================================
test_concurrent_load() {
    echo ""
    echo "--- [7] Concurrent Load Test ---"
    
    # Start multiple servers
    local servers=(0 5 10 15 20 25)
    for s in "${servers[@]}"; do
        check_node $s || continue
        docker exec "manet-node-${s}" pkill iperf3 2>/dev/null || true
        docker exec -d "manet-node-${s}" iperf3 -s -p 5201
    done
    sleep 1
    
    # Many concurrent clients
    echo "  Starting ${#servers[@]} concurrent iperf3 clients..."
    local pids=()
    for s in "${servers[@]}"; do
        local client=$(( (s + 1) % NODE_COUNT ))
        check_node $client || continue
        local srv_ip=$(node_ip $s)
        docker exec "manet-node-${client}" \
            iperf3 -c "${srv_ip}" -p 5201 -t "${TEST_DURATION}" -J \
            > "${RESULTS_DIR}/load-node${client}-to-node${s}.json" 2>/dev/null &
        pids+=($!)
    done
    
    # Wait for all
    for pid in "${pids[@]}"; do
        wait $pid 2>/dev/null || true
    done
    
    # Aggregate results
    echo "  Aggregate throughput:"
    local total_bw=0
    for s in "${servers[@]}"; do
        local client=$(( (s + 1) % NODE_COUNT ))
        local f="${RESULTS_DIR}/load-node${client}-to-node${s}.json"
        if [ -f "$f" ]; then
            local bw=$(python3 -c "
import json
try:
    d=json.load(open('$f'))
    print(d['end']['sum_received']['bits_per_second']/1e6)
except: print(0)
" 2>/dev/null)
            total_bw=$(python3 -c "print(${total_bw} + ${bw})" 2>/dev/null)
        fi
    done
    echo "    Total: ${total_bw} Mbps across ${#servers[@]} flows"
    
    for s in "${servers[@]}"; do
        docker exec "manet-node-${s}" pkill iperf3 2>/dev/null || true
    done
}

# ================================================================
# Run requested test(s)
# ================================================================
case ${TEST} in
    ping-flood)         test_ping_flood ;;
    broadcast)          test_broadcast ;;
    iperf-mesh)         test_iperf_mesh ;;
    udp-flood)          test_udp_flood ;;
    neighbor-discovery) test_neighbor_discovery ;;
    route-trace)        test_route_trace ;;
    concurrent-load)    test_concurrent_load ;;
    all)
        test_ping_flood
        test_broadcast
        test_iperf_mesh
        test_udp_flood
        test_neighbor_discovery
        test_route_trace
        test_concurrent_load
        echo ""
        echo "========================================"
        echo "All tests complete. Results: ${RESULTS_DIR}/"
        echo "========================================"
        ;;
    *)
        echo "Unknown test: ${TEST}"
        echo "Usage: $0 [ping-flood|broadcast|iperf-mesh|udp-flood|neighbor-discovery|route-trace|concurrent-load|all]"
        exit 1
        ;;
esac
