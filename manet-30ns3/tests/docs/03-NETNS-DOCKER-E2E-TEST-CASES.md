# Netns / DockerMgr / E2E Test Cases (TC-NET, TC-DCK, TC-E2E)

Covers `controller/orchestrator/netns.py`, `docker_mgr.py`, and integration tests.

---

## TC-NET-001: node_bridge_name returns correct format mesh-br-{id}

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. Call `node_bridge_name(0)`, `node_bridge_name(5)`, `node_bridge_name(15)`
2. Assert `"mesh-br-0"`, `"mesh-br-5"`, `"mesh-br-15"`

**Expected Result**:
✅ Format matches Linux bridge naming convention

---

## TC-NET-002: ensure_node_bridge creates bridge idempotently

**Priority**: P1
**Type**: Integration* (requires --privileged Linux)
**Estimated Time**: 3 min

**Test Steps**:
1. `ensure_node_bridge(0, ip="192.168.100.1", prefixlen=24)`
2. Repeat same call
3. `ip link show mesh-br-0` — verify bridge exists

**Expected Result**:
✅ Second call is no-op (idempotent), no error

---

## TC-NET-007: _normalize_keys converts snake_case to camelCase

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. `_normalize_keys({"hello_world": 1})` → `{"helloWorld": 1}`
2. `_normalize_keys({"foo_bar_baz": 2})` → `{"fooBarBaz": 2}`
3. `_normalize_keys({"camelKey": 1})` → passthrough

**Expected Result**:
✅ Consistent key normalization for MAC lookup compatibility

---

## TC-DCK-001: start_one creates --net=none container

**Priority**: P0
**Type**: Integration* (requires Docker daemon)
**Estimated Time**: 5 min

**Test Steps**:
1. Call `docker_mgr.start_one(NodeSpec(id=0, ip="192.168.100.10"), SimConfig())`
2. `docker ps` shows `manet-node-0` with `--network none`
3. `docker inspect manet-node-0` shows `NetworkMode: none`

**Expected Result**:
✅ Container isolated with no Docker bridge networking

---

## TC-DCK-002: stop_all removes all containers

**Priority**: P0
**Type**: Integration* (requires Docker daemon)
**Estimated Time**: 5 min

**Test Steps**:
1. Start 5-node simulation
2. `POST /api/sim/stop`
3. `docker ps | grep manet-node` → empty

**Expected Result**:
✅ All containers cleaned up

---

## TC-DCK-003: is_running returns correct status from cache

**Priority**: P1
**Type**: Unit (mocked)
**Estimated Time**: 1 min

**Test Steps**:
1. Pre-populate `docker_mgr._status_cache[0] = True`
2. Call `is_running(0)` without Docker API
3. Assert `True`, no `containers.get` call

**Expected Result**:
✅ Cache hit avoids Docker API round-trip

---

## TC-E2E-001: debug preset — 5 node / 60s simulation smoke test

**Priority**: P0
**Type**: E2E
**Estimated Time**: 10 min

**Prerequisites**:
- Linux host with Docker, 5+ GB RAM
- Controller running: `docker compose up -d controller`
- Can access `localhost:8000`

**Test Steps**:
1. `POST /api/sim/start` with `{"preset": "debug"}`
2. Wait 5s, verify `mesh-br-*`, `mesh-tap-*`, `mesh-veth*` exist via `ip link`
3. Verify 5 containers via `docker ps`
4. `docker exec manet-node-0 ping -c 3 192.168.100.11`
5. `POST /api/sim/stop`
6. `ip link | grep mesh-br` → empty (clean)

**Expected Result**:
✅ Full lifecycle works end-to-end, no resource leak

---

## TC-E2E-002: default preset — 6 node ping across topology

**Priority**: P0
**Type**: E2E
**Estimated Time**: 10 min

**Test Steps**:
1. `POST /api/sim/start` with `{"preset": "default"}`
2. Wait 10s for routing to converge
3. `docker exec manet-node-0 ping -c 3 192.168.100.15` (node 5)
4. Verify ping success or proper path loss

**Expected Result**:
✅ Multi-hop mesh routing functional

---

## TC-E2E-008: br-ns3/tap-*/veth* cleaned after stop

**Priority**: P0
**Type**: E2E
**Estimated Time**: 5 min

**Test Steps**:
1. `POST /api/sim/start` with `{"preset": "debug"}`
2. Verify resources present
3. `POST /api/sim/stop`
4. `ip link | grep -E 'mesh-br|mesh-tap|mesh-veth' || echo "clean"`

**Expected Result**:
✅ Output is "clean" — no stale interfaces

---

## TC-E2E-009: bind mode user software load works

**Priority**: P2
**Type**: E2E
**Estimated Time**: 5 min

**Test Steps**:
1. Host: `mkdir -p /tmp/uatest && echo 'echo hello' > /tmp/uatest/run.sh`
2. `POST /api/sim/start` with:
   ```json
   {"preset": "debug", "nodes": [{"id": 0, "userAppMode": "bind", "userAppBindPath": "/tmp/uatest"}]}
   ```
3. `docker exec manet-node-0 /opt/userapp/run.sh` → "hello"

**Expected Result**:
✅ Bind mount makes host directory available in container

---

## TC-E2E-010: exec mode — docker exec delivers commands

**Priority**: P2
**Type**: E2E
**Estimated Time**: 3 min

**Test Steps**:
1. `POST /api/sim/start` with `{"preset": "debug"}`
2. `POST /api/nodes/0/exec` with `{"cmd": "echo hi"}`
3. Assert `"hi"` in response

**Expected Result**:
✅ Command execution API works

---

*Integration tests marked (*) require a privileged Linux environment with Docker daemon.
Unit tests run in any environment with mocks.