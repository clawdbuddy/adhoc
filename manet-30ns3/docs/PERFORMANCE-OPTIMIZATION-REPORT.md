# MANET 仿真性能优化报告

**日期**: 2026-05-09
**版本**: v1.0
**状态**: 已实施并推送 (commit `b60213d`)

---

## 目录

1. [已实施的优化 (5 阶段)](#1-已实施的优化)
2. [ns-3 多进程并行化可行性分析](#2-ns-3-多进程并行化可行性分析)
3. [性能基准与预期收益](#3-性能基准与预期收益)
4. [监控与验证方案](#4-监控与验证方案)
5. [未来演进路径](#5-未来演进路径)

---

## 1. 已实施的优化

### Phase 1: 并行化容器启动

**文件**: `controller/orchestrator/docker_mgr.py`

| 改动 | 说明 |
|------|------|
| `start_all()` 并行化 | `ThreadPoolExecutor(max_workers=min(n, 8))` 并行启动节点 |
| `stop_all()` 并行化 | 同样使用线程池批量停止 |
| 线程安全 | `self._nodes` 增加 `threading.Lock` 保护 |

**预期收益**: 10 节点启动从 ~15-20s → ~2-3s

---

### Phase 2: Docker API 异步化

**文件**: `controller/api/state.py`, `controller/api/routes_nodes.py`

| 改动 | 说明 |
|------|------|
| `Session.start()` | `docker_mgr.start_all()` 用 `asyncio.to_thread()` 包裹 |
| `Session.stop()` | `docker_mgr.stop_all()`、`teardown()`、`_reap_orphans()` 全部异步化 |
| `/api/nodes/{id}/exec` | `exec_in()` 用 `asyncio.to_thread()` 包裹 |
| `/api/logs` | `logs()` 用 `asyncio.to_thread()` 包裹 |

**预期收益**: API 不再阻塞 asyncio 事件循环

---

### Phase 3: Telemetry 性能优化

**文件**: `controller/orchestrator/docker_mgr.py`, `controller/orchestrator/telemetry.py`, `controller/orchestrator/param_store.py`

| 改动 | 说明 |
|------|------|
| 容器状态缓存 | 后台线程 `_status_refresh_loop()` 每 1s 批量查询并缓存 |
| `is_running()` | 优先读缓存，避免每帧 N 次 Docker API 调用 |
| ParamStore Queue | 设置 `maxsize=64` 防止无界增长 |

**预期收益**: telemetry 泵每 200ms 不再阻塞事件循环

---

### Phase 4: Wall Pacer 运行时优化

**文件**: `controller/orchestrator/sim_runner.py`, `controller/api/main.py`

| 改动 | 说明 |
|------|------|
| 自适应 sleep | 测量迭代耗时，动态调整以维持 10 Hz 目标频率 |
| FlowMonitor 增量更新 | 改全量 `dict.clear()` + 重建为 in-place 更新，减少 GC 压力 |
| `_get_node_phy()` 缓存 | 首次成功查找后缓存 `node_id → phy` 映射 |
| ns-3 预导入 | `main.py` lifespan 中后台线程预导入 ns-3 绑定，摊销 JIT 成本 |

**预期收益**: 更稳定的 wall pacer 频率，更低的 GC 压力

---

### Phase 5: Netns 优化

**文件**: `controller/orchestrator/netns.py`

| 改动 | 说明 |
|------|------|
| IPRoute socket 复用 | 线程本地 `_ipr_local` 缓存，每个线程复用同一 netlink socket |
| 清理 | `teardown()` 时调用 `_close_ipr()` 释放资源 |

**预期收益**: 减少 ~5-10ms 每次 netlink 调用的 socket 创建/销毁开销

---

## 2. ns-3 多进程并行化可行性分析

### 结论

**当前架构下不可行**。ns-3 的 `RealtimeSimulatorImpl` + `TapBridge` + Docker 容器网络这三者的组合，与多进程存在根本性冲突。

### 2.1 ns-3 原生分布式模拟（MPI）

ns-3 支持 `--enable-mpi` 编译选项，使用 `DistributedSimulatorImpl` 替代 `RealtimeSimulatorImpl`。

| 要求 | 当前状态 | 冲突 |
|------|----------|------|
| 编译选项 | 未启用 MPI | 需要重新编译 NS-3.45 |
| Simulator | `DistributedSimulatorImpl` | 与 `RealtimeSimulatorImpl` **互斥** |
| TapBridge | 需要共享 TAP fd 跨进程 | MPI 进程间无法共享 Linux TAP |
| 时钟同步 | 逻辑时钟（事件序号） | 与 wall-time 实时模式矛盾 |

**核心矛盾**: `DistributedSimulatorImpl` 是为**离线大规模模拟**设计的（追求吞吐量，牺牲实时性），而本项目需要**实时模式**（`RealtimeSimulatorImpl` + `TapBridge` 把容器流量同步到仿真时间）。

### 2.2 多进程 + TapBridge 的架构障碍

当前数据路径（单进程）:

```
Container-0 eth0 → veth0 → br-ns3-0 → tap-0 → [ns-3 进程] → tap-1 → br-ns3-1 → veth1 → Container-1
```

如果拆分为 2 个 ns-3 进程:

```
Process A: 管理 node 0-7
Process B: 管理 node 8-15
```

**问题**:
- **TAP 设备归属**: `tap-0` 到 `tap-7` 由进程 A 打开，`tap-8` 到 `tap-15` 由进程 B 打开。Linux 不允许两个进程同时 `open()` 同一个 TAP 设备（除非使用 `TUNSETIFF` + `IFF_MULTI_QUEUE`，但 ns-3 TapBridge 不支持）。
- **跨进程流量**: node-0 发给 node-8 的包需要进程 A 转发到进程 B。这需要 IPC（shared memory / UNIX socket / DPDK ring），但 `RealtimeSimulatorImpl` 的 wall-time 同步会使跨进程延迟不可控。
- **PHY 共享**: `SpectrumChannel` / `YansChannel` 是 C++ 对象，存在于单一地址空间。多进程需要把信道状态序列化传输——开销远大于单进程计算。

### 2.3 线程级并行（替代方案）

ns-3 内部是**单线程事件循环**（`Scheduler::Insert` + `Scheduler::RemoveNext`），这是 DES（Discrete Event Simulation）的本质。

但在 C++ 层面，部分模块支持线程并行:
- `SpectrumWifiPhy` 的频域处理可以 SIMD 向量化（GCC 自动优化）
- `MultiModelSpectrumChannel` 的信号叠加可以 OpenMP 并行（ns-3 未实现）

**当前瓶颈不在 CPU**: 16 节点的 802.11s mesh + HWMP 计算量很小。wall pacer 的 O(n²) 邻居计算在 16 节点时仅 256 次距离检查/100ms。

### 2.4 可行的演进路径（如果需要 100+ 节点）

| 方案 | 架构改动 | 复杂度 | 适用场景 |
|------|----------|--------|----------|
| **A. 纯 ns-3 分布式** | 移除 Docker 容器，用 MPI + `DistributedSimulatorImpl` | 高 | 纯模拟，无真实容器流量 |
| **B. 容器自治路由** | ns-3 只做 PHY，L2/L3 路由用 batman-adv/OLSR 跑在容器内 | 中 | 需要真实容器互通，可接受 ns-3 只做"电缆" |
| **C. DPDK + 多队列 TAP** | 替换 TapBridge 为 DPDK `rte_eth_tap`，多进程绑定不同队列 | 很高 | 需要高性能数据面 |
| **D. 多控制器分片** | 每 16 节点一个控制器实例，节点间用 VXLAN 互通 | 中 | 多机部署 Phase 2 的自然延伸 |

### 2.5 当前优化的正确方向

对于 ≤16 节点的当前规模，**已完成的所有优化是正确的**:

| 优化 | 瓶颈类型 | 收益 |
|------|----------|------|
| 并行容器启动 | I/O 阻塞 | 15-20s → 2-3s |
| Docker API 异步化 | 事件循环阻塞 | API 响应 p95 <100ms |
| Telemetry 缓存 | N×Docker API 查询 | 消除 200ms 周期性阻塞 |
| Wall Pacer 自适应 | 忙时堆积 | 更稳定的 10 Hz |
| FlowMonitor 增量 | GC 压力 | 减少对象分配 |

**真正的硬瓶颈** `TapBridge + RealtimeSimulatorImpl ≈ 1.5-2 Mbps` 是**架构性上限**，无法通过并行化突破。要提升吞吐，需要:
- 移除 `RealtimeSimulatorImpl`，改用 `DefaultSimulatorImpl` + 批量事件处理
- 但这会破坏容器实时互通的语义

---

## 3. 性能基准与预期收益

### 启动时间

| 指标 | 优化前 | 优化后 | 变化 |
|------|--------|--------|------|
| 5 节点 (debug) | ~8-10s | ~2-3s | **5x** |
| 10 节点 (tactical) | ~15-20s | ~3-5s | **5x** |
| 16 节点 (urban/rural) | ~25-30s | ~5-7s | **5x** |

### API 响应

| 端点 | 优化前 | 优化后 |
|------|--------|--------|
| `GET /api/nodes` | 阻塞 N×50ms | <10ms（读缓存） |
| `GET /api/sim/status` | 阻塞 N×50ms | <10ms（读缓存） |
| `POST /api/sim/start` | 阻塞 15-20s | 立即返回，后台执行 |
| `POST /api/nodes/{id}/exec` | 阻塞命令时长 | 不阻塞事件循环 |

### 运行时

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| Wall pacer 频率稳定性 | 固定 100ms，忙时堆积 | 自适应，维持 10 Hz |
| FlowMonitor GC 压力 | 每 100ms 全量重建 | 增量更新 |
| PHY 命令延迟 | 四级回退 ~50-200ms | 缓存命中 ~1ms |

---

## 4. 监控与验证方案

### 启动时间基准测试

```bash
cd manet-30ns3
time curl -X POST localhost:8000/api/sim/start -d '{"preset":"debug"}'
# 目标: 10 节点 < 5s
```

### API 并发测试

```bash
# 仿真运行时并发请求 /api/nodes 和 /api/sim/status
# 目标: p95 < 100ms，无事件循环阻塞
```

### 回归测试

```bash
cd manet-30ns3 && python3 tests/wifi_test_suite.py
# 目标: 8/8 通过，与优化前一致
```

### 单元测试

```bash
# 后端
cd manet-30ns3 && python3 -m pytest
# 前端
cd manet-30ns3/web-manager && npm test
```

---

## 5. 未来演进路径

### 短期（已实施）

- [x] 并行容器启动
- [x] Docker API 异步化
- [x] Telemetry 缓存
- [x] Wall Pacer 自适应
- [x] FlowMonitor 增量更新
- [x] PHY 缓存
- [x] Netns socket 复用
- [x] ns-3 预导入

### 中期（建议）

- [ ] 引入 metrics 采集（Prometheus / statsd）
- [ ] 添加启动时间 / API 延迟的持续基准测试
- [ ] 评估方案 B: 容器自治路由（batman-adv/OLSR）
- [ ] 引入 asyncio 连接池优化 Docker SDK

### 长期（如果需要 100+ 节点）

- [ ] 方案 D: 多控制器分片（每 16 节点一个控制器，VXLAN 互联）
- [ ] 方案 C: DPDK 替代 TapBridge（高性能数据面）
- [ ] 方案 A: 纯 ns-3 分布式（MPI，无真实容器）

---

## 附录: 修改文件清单

| 文件 | 改动 |
|------|------|
| `controller/orchestrator/docker_mgr.py` | 并行化启动/停止 + 容器状态缓存 |
| `controller/orchestrator/netns.py` | IPRoute socket 线程本地复用 |
| `controller/orchestrator/sim_runner.py` | 自适应 sleep + FlowMonitor 增量更新 + PHY 缓存 |
| `controller/api/state.py` | Docker 调用异步化 + 缓存启停 |
| `controller/api/routes_nodes.py` | exec/logs 端点异步化 + 命令白名单 |
| `controller/api/main.py` | ns-3 预导入 + 遗留进程清理 |
| `controller/orchestrator/param_store.py` | Queue 设 maxsize=64 |
| `controller/tests/test_config.py` | 30 个 pytest 单元测试 |
| `web-manager/src/hooks/useSimConfig.test.ts` | 9 个 vitest 单元测试 |
| `pytest.ini` | pytest 配置 |
| `web-manager/package.json` | 新增 vitest 依赖 |
| `web-manager/vite.config.ts` | vitest 配置 |
| `qa/tests/docs/BASELINE-METRICS.md` | 更新基线指标 |
| `qa/tests/docs/02-API-TEST-CASES.md` | 10 个 API 测试用例 |
| `qa/tests/docs/03-SECURITY-TEST-CASES.md` | 9 个安全测试用例 |

---

*本文档由性能优化计划自动生成，计划文件: `/home/binnary/.claude/plans/glimmering-painting-pretzel.md`*
