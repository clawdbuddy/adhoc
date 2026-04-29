#!/bin/bash
# node-entrypoint.sh - MANET node container entrypoint
#
# EACH CONTAINER = ONE INDEPENDENT NETWORK NODE
#
# Network isolation:
#   - Container runs in its own network namespace (--net=none at docker run).
#   - The controller injects a veth pair after start: vethns<ID> is moved into
#     this netns and renamed to eth0.
#   - The host-side veth is bridged into br-ns3 alongside tap-<ID>, which is
#     bound to ns-3 TapBridge (UseBridge mode). All traffic therefore traverses
#     the ns-3 AdHoc PHY/MAC channel model.
#
# Data path:
#   Container -> eth0 -> vethns<ID> (host) -> br-ns3 -> tap-<ID> -> ns-3
#                                                                  -> AdHoc MAC (CSMA/CA)
#                                                                  -> WiFi PHY + path loss + fading
#                                                                  -> peer node's tap -> peer eth0
#
# User-software loading (USER_APP_MODE):
#   bind  - host bind-mounts /opt/userapp ; entrypoint runs ${USER_APP_CMD:-/opt/userapp/run.sh}
#   image - container is launched from a derived image with /opt/userapp/run.sh baked in
#   exec  - container stays idle (optional sshd); backend pushes binaries via docker exec / ssh
#
# Required env: NODE_ID, NODE_IP
# Optional env: NODE_ROLE (client|server|gateway), BRIDGE_IP, USER_APP_MODE,
#               USER_APP_CMD, SSH_AUTHORIZED_KEYS, SSH_ENABLE (1|0)

set -u

NODE_ID=${NODE_ID:-0}
NODE_IP=${NODE_IP:-192.168.100.10}
BRIDGE_IP=${BRIDGE_IP:-192.168.100.1}
SUBNET_MASK=${SUBNET_MASK:-24}
NODE_ROLE=${NODE_ROLE:-client}
USER_APP_MODE=${USER_APP_MODE:-exec}
USER_APP_CMD=${USER_APP_CMD:-}
SSH_ENABLE=${SSH_ENABLE:-0}

log() { echo "[node-${NODE_ID}] $*"; }

log "starting (role=${NODE_ROLE} mode=${USER_APP_MODE} ip=${NODE_IP}/${SUBNET_MASK})"

# Wait for the controller to inject eth0 (renamed from vethns<ID>).
# Up to ~30 s; the orchestrator typically attaches within a few hundred ms of `docker start`.
for _ in $(seq 1 60); do
    if ip link show eth0 >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! ip link show eth0 >/dev/null 2>&1; then
    log "ERROR: eth0 was not injected by the controller after 30s"
    exit 1
fi

# Strict isolation: bring down anything that isn't lo or eth0.
# Parse the device name in `<idx>: <name>: ...` lines without trailing colon.
ip -o link show | awk -F': ' '{print $2}' | while read -r iface; do
    iface=${iface%%@*}   # strip @parent suffix on veth peers
    case "$iface" in
        lo|eth0|"") ;;
        *) ip link set "$iface" down 2>/dev/null || true ;;
    esac
done

ip link set lo up
ip addr add 127.0.0.1/8 dev lo 2>/dev/null || true

ip link set eth0 down 2>/dev/null || true
ip addr flush dev eth0 2>/dev/null || true
ip addr add "${NODE_IP}/${SUBNET_MASK}" dev eth0
ip link set eth0 up

# Default route via the host bridge (used as the conventional gateway IP for
# the simulated AdHoc subnet; ns-3 routing decides actual forwarding).
ip route add default via "${BRIDGE_IP}" 2>/dev/null || true

sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=0 >/dev/null 2>&1 || true

# Role services
case "${NODE_ROLE}" in
    server)
        log "role=server: starting iperf3 (5201) + UDP echo (5000)"
        iperf3 -s -p 5201 -D >/dev/null 2>&1 || true
        socat UDP4-LISTEN:5000,fork EXEC:'cat' >/dev/null 2>&1 &
        sysctl -w net.ipv4.ip_forward=0 >/dev/null 2>&1 || true
        ;;
    gateway)
        log "role=gateway: enabling ip_forward"
        sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
        ;;
    client|*)
        sysctl -w net.ipv4.ip_forward=0 >/dev/null 2>&1 || true
        ;;
esac

# Optional sshd (only used in `exec` mode when the operator wants to push code via ssh).
if [ "${SSH_ENABLE}" = "1" ]; then
    log "starting sshd"
    if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
        ssh-keygen -A >/dev/null 2>&1 || true
    fi
    if [ -n "${SSH_AUTHORIZED_KEYS:-}" ]; then
        mkdir -p /root/.ssh
        printf '%s\n' "${SSH_AUTHORIZED_KEYS}" > /root/.ssh/authorized_keys
        chmod 700 /root/.ssh
        chmod 600 /root/.ssh/authorized_keys
    fi
    /usr/sbin/sshd
fi

log "online: $(ip -4 addr show eth0 | awk '/inet /{print $2}')"

# User-app dispatch
case "${USER_APP_MODE}" in
    bind)
        cmd="${USER_APP_CMD:-/opt/userapp/run.sh}"
        if [ ! -x "${cmd}" ] && [ -f "${cmd}" ]; then
            chmod +x "${cmd}" 2>/dev/null || true
        fi
        if [ ! -e "${cmd}" ]; then
            log "USER_APP_MODE=bind but ${cmd} not found; sleeping idle"
            exec tail -f /dev/null
        fi
        log "exec bind app: ${cmd}"
        exec "${cmd}"
        ;;
    image)
        cmd="${USER_APP_CMD:-/opt/userapp/run.sh}"
        if [ ! -e "${cmd}" ]; then
            log "USER_APP_MODE=image but ${cmd} missing in image; sleeping idle"
            exec tail -f /dev/null
        fi
        log "exec image app: ${cmd}"
        exec "${cmd}"
        ;;
    exec|*)
        log "USER_APP_MODE=exec: idling for backend-driven docker exec / ssh"
        exec tail -f /dev/null
        ;;
esac
