#!/bin/bash
# start-simulation.sh - Fully Configurable AdHoc 30-Node Simulation Launcher
#
# Usage:
#   ./start-simulation.sh                    # Use defaults
#   ./start-simulation.sh config-urban.conf  # Use config file
#   CONFIG_FILE=config.conf TX_POWER=15 ./start-simulation.sh  # Mixed
#
# All parameters can be set via:
#   1. Config file (.conf)  -- highest precedence via ns-3
#   2. Environment variables
#   3. Built-in defaults

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ================================================================
# ARCHITECTURE DETECTION
# ================================================================
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    BUILD_ARCH="arm64"
    # ARM64 devices often have limited RAM; cap parallelism if < 6GB
    TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)
    TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))
    if [ "$TOTAL_MEM_GB" -lt 6 ]; then
        BUILD_JOBS=2
        echo "[INFO] ARM64 detected with ${TOTAL_MEM_GB}GB RAM, using -j2 for safe compilation"
    else
        BUILD_JOBS=$(nproc)
        echo "[INFO] ARM64 detected with ${TOTAL_MEM_GB}GB RAM, using -j${BUILD_JOBS}"
    fi
else
    BUILD_ARCH="x86_64"
    BUILD_JOBS=$(nproc)
    echo "[INFO] x86_64 detected, using -j${BUILD_JOBS}"
fi

# Optionally force platform via env
if [ -n "${FORCE_PLATFORM}" ]; then
    DOCKER_PLATFORM="--platform=${FORCE_PLATFORM}"
    echo "[INFO] Forcing Docker platform: ${FORCE_PLATFORM}"
else
    DOCKER_PLATFORM=""
fi

# --- General ---
: ${N_NODES:=30}
: ${SIM_TIME:=300}
: ${SEED:=1}
: ${RUN_NUM:=1}
: ${LOG_COMPONENTS:=""}

# --- PHY ---
: ${STANDARD:=80211g}
: ${DATARATE:=ErpOfdmRate54Mbps}
: ${TX_POWER_START:=20.0}
: ${TX_POWER_END:=20.0}
: ${TX_POWER_LEVELS:=1}
: ${RX_SENSITIVITY:=-85.0}
: ${CCA_THRESHOLD:=-62.0}
: ${ANTENNA_GAIN:=0.0}

# --- Propagation ---
: ${PROP_DELAY:=ConstantSpeed}
: ${PATH_LOSS:=LogDistance}
: ${PATH_LOSS_EXP:=3.0}
: ${PATH_LOSS_REF_LOSS:=46.6777}
: ${PATH_LOSS_REF_DIST:=1.0}
: ${ENABLE_FADING:=true}
: ${FADING_MODEL:=Nakagami}
: ${NAKAGAMI_M0:=1.5}
: ${NAKAGAMI_M1:=1.0}
: ${NAKAGAMI_M2:=0.75}
: ${NAKAGAMI_D1:=50.0}
: ${NAKAGAMI_D2:=100.0}

# --- MAC ---
: ${SSID:=adhoc-30ns3}
: ${BSSID:=00:00:00:00:AD:H0}
: ${RATE_CONTROL:=Arf}
: ${RTS_CTS_THRESHOLD:=2200}
: ${FRAG_THRESHOLD:=2200}
: ${NON_UNICAST_MODE:=false}
: ${BEACON_INTERVAL:=100}
: ${CW_MIN:=15}
: ${CW_MAX:=1023}

# --- Routing ---
: ${ROUTING:=aodv}
: ${AODV_HELLO_INTERVAL:=1.0}
: ${AODV_RREQ_RETRIES:=2}
: ${AODV_ROUTE_TIMEOUT:=3.0}
: ${AODV_DELETE_PERIOD:=5.0}
: ${AODV_NET_DIAMETER:=35}
: ${AODV_ENABLE_HELLO:=true}
: ${OLSR_HELLO_INTERVAL:=2.0}
: ${OLSR_TC_INTERVAL:=5.0}
: ${OLSR_WILLINGNESS:=7}
: ${DSDV_UPDATE_INTERVAL:=15.0}
: ${DSDV_SETTLING_TIME:=6}

# --- Mobility ---
: ${MOBILITY:=random-walk}
: ${MOB_MIN_X:=0.0}
: ${MOB_MAX_X:=500.0}
: ${MOB_MIN_Y:=0.0}
: ${MOB_MAX_Y:=500.0}
: ${RW_MIN_SPEED:=0.5}
: ${RW_MAX_SPEED:=3.0}
: ${RW_DISTANCE:=20.0}
: ${RW_MODE:=Time}
: ${RW_TIME:=1.0}
: ${GRID_MIN_X:=10.0}
: ${GRID_MIN_Y:=10.0}
: ${GRID_DELTA_X:=80.0}
: ${GRID_DELTA_Y:=80.0}
: ${GRID_WIDTH:=6}
: ${GRID_LAYOUT:=RowFirst}
: ${GM_ALPHA:=0.85}

# --- Tracing ---
: ${PCAP:=true}
: ${ASCII:=false}
: ${FLOW_MONITOR:=true}
: ${PCAP_PREFIX:=manet-30nodes-adhoc}
: ${MOBILITY_TRACE:=false}

# --- TapBridge ---
: ${TAP_MODE:=UseBridge}
: ${TAP_PREFIX:=tap-}

# --- Config file ---
: ${CONFIG_FILE:=""}

# ================================================================
# CONFIG FILE HANDLING
# ================================================================

# If first argument is a .conf file, use it
if [ $# -ge 1 ] && [ -f "$1" ]; then
    CONFIG_FILE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
    echo "Using config file: ${CONFIG_FILE}"
    shift
fi

# ================================================================
# BUILD NS-3 COMMAND LINE ARGUMENTS
# ================================================================

NS3_ARGS=""

# Helper to add arg if not using config file
add_arg() {
    local key="$1"
    local val="$2"
    NS3_ARGS="${NS3_ARGS} --${key}=${val}"
}

# If config file is specified, pass it and skip individual args
if [ -n "${CONFIG_FILE}" ] && [ -f "${CONFIG_FILE}" ]; then
    # Mount config file into container
    CONFIG_BASENAME=$(basename "${CONFIG_FILE}")
    NS3_ARGS="--configFile=/opt/ns3/configs/${CONFIG_BASENAME}"
    USE_CONFIG_FILE=1
else
    USE_CONFIG_FILE=0
    # Build arguments from environment variables
    add_arg "nNodes" "${N_NODES}"
    add_arg "simulationTime" "${SIM_TIME}"
    add_arg "seed" "${SEED}"
    add_arg "run" "${RUN_NUM}"
    [ -n "${LOG_COMPONENTS}" ] && add_arg "logComponents" "${LOG_COMPONENTS}"
    
    add_arg "standard" "${STANDARD}"
    add_arg "dataRate" "${DATARATE}"
    add_arg "txPowerStart" "${TX_POWER_START}"
    add_arg "txPowerEnd" "${TX_POWER_END}"
    add_arg "txPowerLevels" "${TX_POWER_LEVELS}"
    add_arg "rxSensitivity" "${RX_SENSITIVITY}"
    add_arg "ccaThreshold" "${CCA_THRESHOLD}"
    add_arg "antennaGain" "${ANTENNA_GAIN}"
    
    add_arg "propagationDelay" "${PROP_DELAY}"
    add_arg "pathLossModel" "${PATH_LOSS}"
    add_arg "pathLossExponent" "${PATH_LOSS_EXP}"
    add_arg "pathLossRefLoss" "${PATH_LOSS_REF_LOSS}"
    add_arg "pathLossRefDistance" "${PATH_LOSS_REF_DIST}"
    add_arg "enableFading" "${ENABLE_FADING}"
    add_arg "fadingModel" "${FADING_MODEL}"
    add_arg "nakagamiM0" "${NAKAGAMI_M0}"
    add_arg "nakagamiM1" "${NAKAGAMI_M1}"
    add_arg "nakagamiM2" "${NAKAGAMI_M2}"
    add_arg "nakagamiD1" "${NAKAGAMI_D1}"
    add_arg "nakagamiD2" "${NAKAGAMI_D2}"
    
    add_arg "ssid" "${SSID}"
    add_arg "bssid" "${BSSID}"
    add_arg "rateControl" "${RATE_CONTROL}"
    add_arg "rtsCtsThreshold" "${RTS_CTS_THRESHOLD}"
    add_arg "fragmentationThreshold" "${FRAG_THRESHOLD}"
    add_arg "nonUnicastMode" "${NON_UNICAST_MODE}"
    add_arg "beaconInterval" "${BEACON_INTERVAL}"
    add_arg "cwMin" "${CW_MIN}"
    add_arg "cwMax" "${CW_MAX}"
    
    add_arg "routingProtocol" "${ROUTING}"
    add_arg "aodvHelloInterval" "${AODV_HELLO_INTERVAL}"
    add_arg "aodvRreqRetries" "${AODV_RREQ_RETRIES}"
    add_arg "aodvActiveRouteTimeout" "${AODV_ROUTE_TIMEOUT}"
    add_arg "aodvDeletePeriod" "${AODV_DELETE_PERIOD}"
    add_arg "aodvNetDiameter" "${AODV_NET_DIAMETER}"
    add_arg "aodvEnableHello" "${AODV_ENABLE_HELLO}"
    add_arg "olsrHelloInterval" "${OLSR_HELLO_INTERVAL}"
    add_arg "olsrTcInterval" "${OLSR_TC_INTERVAL}"
    add_arg "olsrWillingness" "${OLSR_WILLINGNESS}"
    add_arg "dsdvPeriodicUpdateInterval" "${DSDV_UPDATE_INTERVAL}"
    add_arg "dsdvSettlingTime" "${DSDV_SETTLING_TIME}"
    
    add_arg "mobilityModel" "${MOBILITY}"
    add_arg "mobilityMinX" "${MOB_MIN_X}"
    add_arg "mobilityMaxX" "${MOB_MAX_X}"
    add_arg "mobilityMinY" "${MOB_MIN_Y}"
    add_arg "mobilityMaxY" "${MOB_MAX_Y}"
    add_arg "rwMinSpeed" "${RW_MIN_SPEED}"
    add_arg "rwMaxSpeed" "${RW_MAX_SPEED}"
    add_arg "rwDistance" "${RW_DISTANCE}"
    add_arg "rwMode" "${RW_MODE}"
    add_arg "rwTime" "${RW_TIME}"
    add_arg "gridMinX" "${GRID_MIN_X}"
    add_arg "gridMinY" "${GRID_MIN_Y}"
    add_arg "gridDeltaX" "${GRID_DELTA_X}"
    add_arg "gridDeltaY" "${GRID_DELTA_Y}"
    add_arg "gridWidth" "${GRID_WIDTH}"
    add_arg "gridLayout" "${GRID_LAYOUT}"
    add_arg "gmAlpha" "${GM_ALPHA}"
    
    add_arg "pcap" "${PCAP}"
    add_arg "ascii" "${ASCII}"
    add_arg "flowMonitor" "${FLOW_MONITOR}"
    add_arg "pcapPrefix" "${PCAP_PREFIX}"
    add_arg "enableMobilityTrace" "${MOBILITY_TRACE}"
    
    add_arg "tapMode" "${TAP_MODE}"
    add_arg "tapPrefix" "${TAP_PREFIX}"
fi

NODE_COUNT=${N_NODES}
SUBNET="192.168.100"

echo "========================================"
echo "  NS-3 AdHoc ${NODE_COUNT}-Node Launcher"
echo "  Architecture: ${BUILD_ARCH}"
echo "========================================"
echo "  Routing:    ${ROUTING}"
echo "  Mobility:   ${MOBILITY}"
echo "  PHY:        ${STANDARD} @ ${DATARATE}"
echo "  Tx Power:   ${TX_POWER_START} dBm"
echo "  Path Loss:  ${PATH_LOSS}(n=${PATH_LOSS_EXP})"
echo "  Fading:     ${FADING_MODEL}(M0=${NAKAGAMI_M0})"
echo "  Rate Ctrl:  ${RATE_CONTROL}"
echo "  RTS/CTS:    ${RTS_CTS_THRESHOLD} bytes"
echo "  Sim Time:   ${SIM_TIME} s"
echo "  Build Jobs: ${BUILD_JOBS}"
[ -n "${CONFIG_FILE}" ] && echo "  Config:     ${CONFIG_FILE}"
echo "========================================"

# ================================================================
# STEP 1: Network Infrastructure
# ================================================================
echo "[1/5] Setting up host network..."
sudo "${SCRIPT_DIR}/setup-network.sh"

# ================================================================
# STEP 2: Build Images
# ================================================================
echo "[2/5] Building Docker images..."
docker build ${DOCKER_PLATFORM} -t manet-node:latest -f "${SCRIPT_DIR}/node/Dockerfile.node" "${SCRIPT_DIR}/node/"
docker build ${DOCKER_PLATFORM} -t ns3-controller:latest -f "${SCRIPT_DIR}/ns3-controller/Dockerfile.controller" "${SCRIPT_DIR}/ns3-controller/"

# ================================================================
# STEP 3: Launch Node Containers
# ================================================================
echo "[3/5] Launching ${NODE_COUNT} node containers..."
mkdir -p "${SCRIPT_DIR}/results"

for i in $(seq 0 $((NODE_COUNT-1))); do
    NODE_IP="${SUBNET}.$((10+i))"
    VETH="vethns${i}"
    ROLE="client"
    [ "$i" -eq 0 ] && ROLE="server"
    [ "$i" -eq 15 ] && ROLE="gateway"

    docker run -d \
        --name "manet-node-${i}" \
        --hostname "adhoc-node-${i}" \
        --privileged \
        --cap-add NET_ADMIN \
        --cap-add SYS_ADMIN \
        -e NODE_ID="${i}" \
        -e NODE_IP="${NODE_IP}" \
        -e NODE_ROLE="${ROLE}" \
        -e VETH_PEER="${VETH}" \
        -e BRIDGE_IP="${SUBNET}.1" \
        -e BSSID="${BSSID}" \
        -v "${SCRIPT_DIR}/results:/results" \
        manet-node:latest 2>/dev/null || {
            echo "ERROR: Failed to start manet-node-${i}"
            continue
        }

    PID=$(docker inspect -f '{{.State.Pid}}' "manet-node-${i}" 2>/dev/null)
    if [ -z "$PID" ] || [ "$PID" = "0" ]; then
        echo "WARN: Cannot get PID for node-${i}"
        continue
    fi

    sudo ip link set "${VETH}" netns "${PID}" 2>/dev/null || true
    sudo nsenter -t "${PID}" -n ip link set "${VETH}" name eth0 2>/dev/null || true
    sudo nsenter -t "${PID}" -n ip addr add "${NODE_IP}/24" dev eth0 2>/dev/null || true
    sudo nsenter -t "${PID}" -n ip link set eth0 up 2>/dev/null || true
    sudo nsenter -t "${PID}" -n ip route add default via "${SUBNET}.1" 2>/dev/null || true

    echo "  Node-${i} ${NODE_IP} (${ROLE}) ready"
done

# ================================================================
# STEP 4: Setup TAP Devices
# ================================================================
echo "[4/5] Creating TAP devices..."
for i in $(seq 0 $((NODE_COUNT-1))); do
    TAP="tap-${i}"
    sudo ip tuntap add dev "${TAP}" mode tap 2>/dev/null || true
    sudo ip link set "${TAP}" up 2>/dev/null || true
    sudo brctl addif br-ns3 "${TAP}" 2>/dev/null || true
done

# ================================================================
# STEP 5: Launch NS-3 Controller with Full Configuration
# ================================================================
echo "[5/5] Starting NS-3 AdHoc controller..."
echo "NS-3 args: ${NS3_ARGS}"

# Build volume mounts
VOL_ARGS="-v ${SCRIPT_DIR}/ns3-code:/opt/ns3/ns-3/scratch:ro"
VOL_ARGS="${VOL_ARGS} -v ${SCRIPT_DIR}/results:/opt/ns3/results"

# If using config file, mount its directory
if [ -n "${CONFIG_FILE}" ] && [ -f "${CONFIG_FILE}" ]; then
    mkdir -p "${SCRIPT_DIR}/configs"
    cp "${CONFIG_FILE}" "${SCRIPT_DIR}/configs/"
    VOL_ARGS="${VOL_ARGS} -v ${SCRIPT_DIR}/configs:/opt/ns3/configs:ro"
fi

docker run -it --rm \
    --name ns3-controller \
    --privileged \
    --net=host \
    -e NS3_TAP_MODE=UseBridge \
    -e NODE_COUNT="${NODE_COUNT}" \
    ${VOL_ARGS} \
    ns3-controller:latest \
    bash -c "
        set -e
        cd /opt/ns3/ns-3
        cp /opt/ns3/ns-3/scratch/manet-30nodes.cc scratch/manet-30nodes.cc 2>/dev/null || true
        ./ns3 configure --build-profile=optimized --enable-examples --enable-tests
        ./ns3 build -j${BUILD_JOBS}
        echo ''
        echo 'TAP devices:'
        ip link show | grep -E '^[0-9]+: tap-' || true
        echo ''
        echo '========================================'
        echo 'Starting configurable AdHoc simulation'
        echo '========================================'
        sudo ./ns3 run 'scratch/manet-30nodes ${NS3_ARGS}'
        echo ''
        cp -r build/*.pcap /opt/ns3/results/ 2>/dev/null || true
        cp -r build/*.tr /opt/ns3/results/ 2>/dev/null || true
    "

echo ""
echo "========================================"
echo "Simulation complete."
echo "Results: ${SCRIPT_DIR}/results/"
echo ""
echo "Run tests:   ./adhoc-test.sh all"
echo "Cleanup:     ./cleanup.sh"
echo "========================================"
