# 03-SECURITY-TEST-CASES.md — MANET 安全测试用例 (OWASP)

**Project**: manet-30ns3
**Category**: Security / OWASP Top 10
**Last Updated**: 2026-05-09

---

## 测试环境前置条件 (Arrange)

1. controller 容器已启动
2. 无残留仿真
3. 具备攻击者视角的网络访问权限（可访问 `:8000`）

---

## 测试用例列表

### TC-SEC-001: 命令注入 — `/api/nodes/{id}/exec`

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-001 |
| **Priority** | P0 |
| **OWASP** | A03: Injection |
| **Estimated Time** | 3 min |

**Prerequisites**: 仿真运行中 (preset=debug)

**Steps (Act)**:
1. `POST /api/nodes/0/exec {"cmd":"id; cat /etc/passwd"}`
2. `POST /api/nodes/0/exec {"cmd":"$(whoami)"}`
3. `POST /api/nodes/0/exec {"cmd":"`ls /`"}`

**Expected Results (Assert)**:
- 命令应被**拒绝执行**或**沙箱化执行**
- 不能读取 `/etc/passwd`
- 不能执行未授权命令
- 若当前无限制，记录为漏洞

---

### TC-SEC-002: 越权访问 — 访问不存在的节点

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-002 |
| **Priority** | P1 |
| **OWASP** | A01: Broken Access Control |
| **Estimated Time** | 2 min |

**Prerequisites**: 仿真运行中 (5 节点)

**Steps (Act)**:
1. `POST /api/nodes/99/exec {"cmd":"id"}`
2. `GET /api/nodes/99/logs`

**Expected Results (Assert)**:
- HTTP 404
- 不能访问超出范围的节点

---

### TC-SEC-003: CORS 配置审查

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-003 |
| **Priority** | P2 |
| **OWASP** | A05: Security Misconfiguration |
| **Estimated Time** | 2 min |

**Steps (Act)**:
1. `curl -H "Origin: https://evil.com" -I http://localhost:8000/api/health`
2. 检查响应头 `Access-Control-Allow-Origin`

**Expected Results (Assert)**:
- 不应返回 `Access-Control-Allow-Origin: *`
- 生产环境应限制为特定域名

---

### TC-SEC-004: 错误信息泄露

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-004 |
| **Priority** | P2 |
| **OWASP** | A05: Security Misconfiguration |
| **Estimated Time** | 2 min |

**Steps (Act)**:
1. `GET /api/sim/status` (异常状态)
2. `POST /api/sim/start` (携带非法 JSON)
3. 观察错误响应体

**Expected Results (Assert)**:
- 不应泄露堆栈跟踪、文件路径、内部实现细节
- 返回通用错误信息

---

### TC-SEC-005: Docker Socket 访问风险

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-005 |
| **Priority** | P0 |
| **OWASP** | A01: Broken Access Control |
| **Estimated Time** | 5 min |

**Prerequisites**: 可访问控制器容器

**Steps (Act)**:
1. 检查 `docker-compose.yml` 中的 volume 挂载
2. 验证 `/var/run/docker.sock` 是否挂载到控制器
3. 尝试通过 `POST /api/nodes/{id}/exec` 执行 `docker ps`

**Expected Results (Assert)**:
- 若 `docker ps` 成功，则存在**容器逃逸风险**
- 应限制容器对 Docker socket 的访问或启用授权

---

### TC-SEC-006: 特权模式风险

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-006 |
| **Priority** | P0 |
| **OWASP** | A05: Security Misconfiguration |
| **Estimated Time** | 3 min |

**Steps (Act)**:
1. 检查 `docker-compose.yml` 中的 `privileged: true`
2. 在节点容器中尝试访问宿主机文件系统：`cat /host/proc/1/cmdline`
3. 尝试加载内核模块：`insmod`

**Expected Results (Assert)**:
- 节点容器不应能直接访问宿主机敏感资源
- 控制器特权模式是必需的（网络操作），但需记录为已知风险

---

### TC-SEC-007: WebSocket 无认证连接

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-007 |
| **Priority** | P2 |
| **OWASP** | A07: Authentication Failures |
| **Estimated Time** | 2 min |

**Steps (Act)**:
1. 无认证直接连接 `ws://localhost:8000/ws/telemetry`
2. 接收遥测数据

**Expected Results (Assert)**:
- 当前系统无认证机制，应记录为**设计决策**
- 建议：内部网络部署时通过防火墙/VPN 限制访问

---

### TC-SEC-008: 资源耗尽 — 大量节点请求

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-008 |
| **Priority** | P2 |
| **OWASP** | A04: Insecure Design |
| **Estimated Time** | 3 min |

**Steps (Act)**:
1. `POST /api/sim/start {"config":{"nNodes":100}}`
2. 观察系统行为

**Expected Results (Assert)**:
- 应被拒绝或限制（当前配置 `nNodes` 上限为 16）
- 系统不应崩溃

---

### TC-SEC-009: 仿真停止后资源清理

| 属性 | 值 |
|------|-----|
| **ID** | TC-SEC-009 |
| **Priority** | P1 |
| **OWASP** | A09: Logging Failures |
| **Estimated Time** | 3 min |

**Steps (Act)**:
1. 启动仿真（10 节点）
2. 停止仿真
3. 检查宿主机：`ip link | grep -E 'mesh-br|mesh-tap|mesh-veth'`
4. 检查 Docker：`docker ps | grep manet-node`

**Expected Results (Assert)**:
- 所有 `mesh-br-*`, `mesh-tap-*`, `mesh-veth*` 应被清理
- 所有 `manet-node-*` 容器应被停止

---

## 安全改进建议

| 优先级 | 建议 |
|--------|------|
| P0 | `/api/nodes/{id}/exec` 增加命令白名单或沙箱 |
| P0 | 审计 Docker socket 访问权限 |
| P1 | 增加速率限制 (rate limiting) |
| P1 | 增加请求日志审计 |
| P2 | 配置 CORS 白名单 |
| P2 | 增加 API 认证（内部网络可延后）|
