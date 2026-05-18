# API Routes Test Cases (TC-API-001 ~ TC-API-015)

Covers `controller/api/routes_sim.py`, `routes_config.py`, `routes_nodes.py`.

## TC-API-001: GET /api/health returns {"ok": true}

**Priority**: P0
**Type**: Integration
**Estimated Time**: 1 min

**Prerequisites**:
- Controller module imports successfully

**Test Steps**:
1. `GET /api/health`
2. Assert status 200 and body `{"ok": true}`

**Expected Result**:
✅ Health endpoint responds correctly

---

## TC-API-002: POST /api/sim/start launches simulation

**Priority**: P0
**Type**: Integration
**Estimated Time**: 2 min

**Prerequisites**:
- Mock session with `running=False`

**Test Steps**:
1. `POST /api/sim/start` with empty body
2. Assert status 200, `{"ok": true, "nNodes": 5}`

**Expected Result**:
✅ Returns ok=True immediately

---

## TC-API-003: POST /api/sim/start while running returns 409

**Priority**: P1
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. Set mock session `running=True`
2. `POST /api/sim/start`
3. Assert status 409 Conflict

**Expected Result**:
✅ Duplicate start rejected cleanly

---

## TC-API-004: POST /api/sim/start with unknown preset returns 400

**Priority**: P0
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. `POST /api/sim/start` with `{"preset": "nonexistent"}`
2. Assert status 400

**Expected Result**:
✅ KeyError from load_config caught and converted to HTTP 400

---

## TC-API-005: GET /api/sim/status returns current simulation state

**Priority**: P0
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. `GET /api/sim/status` with no simulation running
2. Assert `running=false`, `totalNodes=0`
3. With running sim: `running=true`, `elapsed>0`

**Expected Result**:
✅ Status reflects actual session state

---

## TC-API-006: GET /api/sim/presets returns all 12 presets

**Priority**: P1
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. `GET /api/sim/presets`
2. Assert keys include `debug`, `default`, `tactical`, `urban`, `rural`
3. Each preset has `nNodes`, `macMode`, `routingProtocol`, `simulationTime`

**Expected Result**:
✅ All 12 presets exposed with required fields

---

## TC-API-007: GET /api/sim/path returns BFS path between nodes

**Priority**: P2
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. Start sim with MockSim (src=0→dst=4 returns [0,2,4])
2. `GET /api/sim/path?src=0&dst=4`
3. Assert `reachable=true`, `hops=2`, `path=[0,2,4]`

**Expected Result**:
✅ Path computation and IP mapping work

---

## TC-API-008: POST /api/sim/stop stops simulation and cleans up

**Priority**: P0
**Type**: Integration
**Estimated Time**: 2 min

**Test Steps**:
1. `POST /api/sim/stop`
2. Assert status 200, `{"ok": true, "running": false}`

**Expected Result**:
✅ Stop cleans up all docker/bridge/veth/tap resources

---

## TC-API-009: GET /api/nodes returns node list

**Priority**: P0
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. With simulation running, `GET /api/nodes`
2. Assert JSON array with node id, ip, role fields

**Expected Result**:
✅ NodeSpec list returned correctly

---

## TC-API-010: POST /api/nodes/{id}/exec runs command in container

**Priority**: P1
**Type**: Integration
**Estimated Time**: 2 min

**Test Steps**:
1. `POST /api/nodes/0/exec` with `{"cmd": "ip -4 addr show eth0"}`
2. Assert status 200, output contains IP address

**Expected Result**:
✅ docker exec works, output returned

---

## TC-API-011: GET /api/logs returns node logs

**Priority**: P1
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. `GET /api/logs?node=0&tail=20`
2. Assert status 200, log text returned

**Expected Result**:
✅ Logs streamed from container

---

## TC-API-012: GET /api/flows returns FlowMonitor statistics

**Priority**: P1
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. `GET /api/flows`
2. Assert JSON with flow stats (tx_packets, rx_packets, lost_packets)

**Expected Result**:
✅ FlowMonitor stats exposed

---

## TC-API-013: WebSocket /ws/telemetry pushes 1Hz telemetry frames

**Priority**: P1
**Type**: Integration
**Estimated Time**: 3 min

**Test Steps**:
1. Connect WebSocket to `/ws/telemetry`
2. Wait 2 seconds
3. Assert at least 1 JSON frame received

**Expected Result**:
✅ Frames arrive at ~1Hz with nodes/flows/status data

---

## TC-API-014: PUT /api/config rejected while simulation running

**Priority**: P2
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. Set `running=True`
2. `PUT /api/config` with new body
3. Assert status 409 Conflict

**Expected Result**:
✅ Runtime config change prevented

---

## TC-API-015: GET /api/config returns current configuration

**Priority**: P2
**Type**: Integration
**Estimated Time**: 1 min

**Test Steps**:
1. `GET /api/config`
2. Assert JSON matches current SimConfig (camelCase)

**Expected Result**:
✅ Full config serialised as camelCase JSON

---