# Baseline Metrics - manet-30ns3

**Date**: 2026-05-09
**Purpose**: Pre-QA snapshot for comparison during testing

---

## 1. Test Coverage (Current State)

### Unit Tests
- **Backend**: 30 tests (pytest) — `controller/tests/test_config.py`
  - SimConfig validation, .conf parsing, preset loading, load_config precedence
  - All passing
- **Frontend**: 9 tests (vitest) — `web-manager/src/hooks/useSimConfig.test.ts`
  - Config update, import/export, partial updates
  - All passing
- **Coverage**: ~15% (frameworks configured, first suites written)

### Integration Tests
- **Total Tests**: 8 (WiFi 网络自动化测试套件)
- **Passing**: 8 (BUG-001 修复后)
- **Failing**: 0
- **Status**: Passing

### E2E Tests
- **Total Tests**: 0 (未配置)
- **Browsers Covered**: N/A

---

## 2. Known Issues (Pre-QA)

### Critical Issues
- [x] BUG-001: Adhoc 大规模拓扑 node0->node9 ping 100% 丢包
  - **Root Cause**: 宿主机遗留 ns-3 测试进程消耗 Mac48Address::Allocate() 计数器，导致 ns-3 MeshPointDevice MAC 与容器 eth0 MAC 不一致。802.11s mesh 将容器流量视为"桥接客户端"，不泛洪广播帧。
  - **Fix**: 清理遗留进程 + 重启控制器 + 在 `main.py` 启动时自动清理 + 在 sim_runner.py 中添加注释说明。
  - **Status**: Fixed 2026-05-09

### Technical Debt
- [x] 前后端类型需手工对齐（无自动生成机制）— 已记录，长期改进
- [x] 前端无单元测试框架 — **已配置 vitest + @testing-library/react**
- [x] 后端无 pytest 单元测试 — **已配置 pytest**
- [ ] docker-compose v1 与 Docker 28 兼容性

---

## 3. Security Status

### OWASP Top 10 Coverage
- [x] A01: Broken Access Control — TC-SEC-002, TC-SEC-005, TC-SEC-006
- [ ] A02: Cryptographic Failures
- [x] A03: Injection — TC-SEC-001 (命令白名单已落地)
- [x] A04: Insecure Design — TC-SEC-008
- [x] A05: Security Misconfiguration — TC-SEC-003, TC-SEC-004
- [ ] A06: Vulnerable Components
- [x] A07: Authentication Failures — TC-SEC-007
- [ ] A08: Data Integrity Failures
- [x] A09: Logging Failures — TC-SEC-009
- [ ] A10: SSRF

**Current Coverage**: 6/10 (60%)

**Mitigations Implemented**:
- `/api/nodes/{id}/exec` 命令白名单已生效（拒绝 shell 元字符 + 只允许网络诊断命令）
- 控制器启动时自动清理遗留 ns-3 进程

**Remaining Risks**:
- Docker socket 挂载导致的容器逃逸（架构设计决策，需网络隔离补偿）
- 特权模式下的宿主机访问（同上）

---

## 4. Performance Metrics

- **仿真启动时间**: ~15-20s (10 节点)
- **API Response Time (p95)**: < 50ms (本地)
- **iperf3 吞吐**: 16-20 Mbps (20MHz / 5 节点)
- **Ping RTT**: 1-12ms (mesh 单跳)

---

## 5. Code Quality

- **Linting Errors**: eslint clean (frontend)
- **TypeScript Strict Mode**: No (tsc -b passes)
- **Code Duplication**: N/A (未测量)
- **Cyclomatic Complexity**: N/A (未测量)

---

## 6. Predicted Issues

**CRITICAL-001**: 遗留 ns-3 进程导致 MAC 地址偏移
- **Predicted Severity**: P1
- **Root Cause**: Mac48Address::Allocate() 全局计数器被其他进程消耗
- **Test Case**: TC-NET-006 验证
- **Mitigation**: ✅ 控制器启动前 `_kill_stale_ns3_processes()` 自动清理

**CRITICAL-002**: `/api/nodes/{id}/exec` 命令注入
- **Predicted Severity**: P0
- **Root Cause**: REST 接口直接透传命令到容器 shell
- **Test Case**: TC-SEC-001 将验证
- **Mitigation**: ✅ 命令白名单 + shell 元字符过滤已落地 (`routes_nodes.py`)

---

**Next Steps**:
1. 运行完整回归测试套件验证 BUG-001 修复
2. 编写 API/安全测试用例
3. 建立 pytest + vitest 测试框架
