# 02-API-TEST-CASES.md — MANET FastAPI 控制平面测试用例

**Project**: manet-30ns3
**Category**: API / REST / WebSocket
**Last Updated**: 2026-05-09

---

## 测试环境前置条件 (Arrange)

1. ns3-controller 容器已启动并监听 `:8000`
2. `manet-node` 镜像已构建
3. 无残留仿真：`POST /api/sim/stop`

---

## 测试用例列表

### TC-API-001: Health Check

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-001 |
| **Priority** | P0 |
| **Estimated Time** | 1 min |

**Steps (Act)**:
1. `GET /api/health`

**Expected Results (Assert)**:
- HTTP 200
- JSON: `{"ok": true}`

---

### TC-API-002: 仿真生命周期 — 启动/停止/状态

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-002 |
| **Priority** | P0 |
| **Estimated Time** | 3 min |

**Steps (Act)**:
1. `POST /api/sim/start {"preset":"debug"}`
2. 轮询 `GET /api/sim/status` 直到 `running=true`
3. `POST /api/sim/stop`
4. 轮询 `GET /api/sim/status` 直到 `running=false`

**Expected Results (Assert)**:
- 启动返回 `{"ok": true, "running": true}`
- 状态最终显示 `running=true, nodesOnline=5`
- 停止返回 `{"ok": true, "running": false}`
- 状态最终显示 `running=false`

---

### TC-API-003: 预设列表

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-003 |
| **Priority** | P1 |
| **Estimated Time** | 1 min |

**Steps (Act)**:
1. `GET /api/sim/presets`

**Expected Results (Assert)**:
- HTTP 200
- 返回包含 `default`, `urban`, `rural`, `debug`, `tactical` 等预设

---

### TC-API-004: 节点列表与流统计

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-004 |
| **Priority** | P1 |
| **Estimated Time** | 2 min |

**Prerequisites**: 仿真运行中 (preset=debug)

**Steps (Act)**:
1. `GET /api/nodes`
2. `GET /api/flows`

**Expected Results (Assert)**:
- `/api/nodes` 返回 5 个节点，每个节点有 `id`, `ip`, `role`, `status`
- `/api/flows` 返回数组（可能为空，取决于是否有流量）

---

### TC-API-005: 节点命令执行

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-005 |
| **Priority** | P1 |
| **Estimated Time** | 2 min |

**Prerequisites**: 仿真运行中 (preset=debug)

**Steps (Act)**:
1. `POST /api/nodes/0/exec {"cmd":"echo hello"}`
2. `POST /api/nodes/0/exec {"cmd":"ip addr show eth0"}`

**Expected Results (Assert)**:
- 返回 `{"output": "hello\n"}`
- 返回包含 `192.168.100.10`

---

### TC-API-006: 节点日志读取

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-006 |
| **Priority** | P2 |
| **Estimated Time** | 2 min |

**Prerequisites**: 仿真运行中，已在节点上执行过命令

**Steps (Act)**:
1. `GET /api/logs?node=0&tail=10`

**Expected Results (Assert)**:
- HTTP 200
- 返回最近 10 行日志

---

### TC-API-007: WebSocket 遥测

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-007 |
| **Priority** | P1 |
| **Estimated Time** | 3 min |

**Prerequisites**: 仿真运行中

**Steps (Act)**:
1. 连接 `ws://localhost:8000/ws/telemetry`
2. 等待 3 秒接收帧
3. 关闭连接

**Expected Results (Assert)**:
- WebSocket 连接成功
- 收到 JSON 帧，包含 `nodes`, `flows`, `status`
- 帧中 `nodes` 数组长度等于当前节点数

---

### TC-API-008: 非法预设拒绝

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-008 |
| **Priority** | P2 |
| **Estimated Time** | 1 min |

**Steps (Act)**:
1. `POST /api/sim/start {"preset":"nonexistent"}`

**Expected Results (Assert)**:
- HTTP 422 或 400
- 返回错误信息包含 "unknown preset"

---

### TC-API-009: 并发启动拒绝

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-009 |
| **Priority** | P2 |
| **Estimated Time** | 2 min |

**Prerequisites**: 仿真运行中

**Steps (Act)**:
1. `POST /api/sim/start {"preset":"debug"}`

**Expected Results (Assert)**:
- HTTP 400 或 409
- 返回错误信息包含 "already running"

---

### TC-API-010: 配置读取与修改

| 属性 | 值 |
|------|-----|
| **ID** | TC-API-010 |
| **Priority** | P2 |
| **Estimated Time** | 2 min |

**Prerequisites**: 仿真未运行

**Steps (Act)**:
1. `GET /api/config`
2. `PUT /api/config {"nNodes":8}`
3. `GET /api/config`

**Expected Results (Assert)**:
- 初始 `GET` 返回当前配置
- `PUT` 返回成功
- 再次 `GET` 显示 `nNodes=8`

---

## 参考实现

上述测试用例的自动化实现建议放在：
- `tests/api_test_suite.py` — 使用 `urllib.request` 或 `httpx`
- 可复用 `tests/wifi_test_suite.py` 中的 `TestRunner._api/_get/_post` 模式
