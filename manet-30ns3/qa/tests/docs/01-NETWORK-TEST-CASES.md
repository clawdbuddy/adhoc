# 01-NETWORK-TEST-CASES.md — MANET 网络连通性 / 吞吐量 / 覆盖测试用例

**Project**: manet-30ns3
**Category**: Network / WiFi / Mesh
**Last Updated**: 2026-05-08

---

## 测试环境前置条件 (Arrange)

1. 宿主机为 x86_64 Linux，已加载 `tun` / `tap` / `bridge` 内核模块
2. Docker 运行中，`controller` 容器已启动并监听 `:8000`
3. `manet-node` 镜像已构建 (`docker compose --profile build build node-image-builder`)
4. 控制器健康检查通过：`curl localhost:8000/api/health` → `{"ok":true}`
5. 测试前确保无残留仿真：`curl -X POST localhost:8000/api/sim/stop`

---

## 测试用例列表

### TC-01: 2.4GHz 频段连通性

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-001 |
| **Priority** | P1 |
| **Estimated Time** | 3 min |

**Prerequisites**: 控制器运行中，无其他仿真

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-band-test-2.4g"}`
2. 等待 5 个节点上线（`nodesOnline >= 5`，超时 60s）
3. 等待 15s 让 AODV 路由收敛
4. 从 node0 向 node1-node4 各发送 10 个 ping
5. 记录每个链路的收发数量、丢包率、平均 RTT

**Expected Results (Assert)**:
- 所有 5 个节点成功上线
- 所有 ping 100% 到达（0% 丢包）
- RTT 在合理范围（< 100ms）

---

### TC-02: 5GHz 频段连通性

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-002 |
| **Priority** | P1 |
| **Estimated Time** | 3 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-band-test-5g"}`
2. 等待 5 个节点上线
3. 等待 10s
4. 从 node0 向 node1-node4 各发送 10 个 ping

**Expected Results (Assert)**:
- 所有 ping 100% 到达
- 5GHz 下 RTT 与 2.4GHz 相近

---

### TC-03: 20MHz 带宽吞吐量

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-003 |
| **Priority** | P1 |
| **Estimated Time** | 4 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-bandwidth-test-20m"}`
2. 等待 5 个节点上线
3. 等待 10s
4. node0 启动 iperf3 server，node1-node4 作为 client 各测 15s
5. 记录每个 client 的吞吐量和重传数

**Expected Results (Assert)**:
- 各节点吞吐量为正（> 0 Mbps）
- 无明显异常重传

---

### TC-04: 40MHz 带宽吞吐量

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-004 |
| **Priority** | P1 |
| **Estimated Time** | 4 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-bandwidth-test-40m"}`
2. 等待 5 个节点上线
3. 等待 10s
4. node0 启动 iperf3 server，node1-node4 作为 client 各测 15s

**Expected Results (Assert)**:
- 40MHz 下吞吐量高于 20MHz（或至少持平）
- 各节点吞吐量为正

---

### TC-05: 通信距离衰减

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-005 |
| **Priority** | P2 |
| **Estimated Time** | 5 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-distance-test"}`
2. 等待 5 个节点上线（超时 90s）
3. 等待 15s
4. 从 node0 向不同距离的节点发送 ping（node1@500m, node2@1000m, node3@1500m, node4@2000m）
5. 对可达节点执行 iperf3 测速（5s）

**Expected Results (Assert)**:
- 所有距离节点均可达（至少部分 ping 到达）
- 吞吐量随距离增加而衰减

---

### TC-06: Adhoc 大规模拓扑

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-006 |
| **Priority** | P2 |
| **Estimated Time** | 6 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-adhoc-multihop"}`
2. 等待 10 个节点上线（超时 180s）
3. 等待 20s
4. 从 node0 向 node9（距离 2700m）发送 10 个 ping
5. 执行 traceroute
6. 执行 iperf3 测速（15s）

**Expected Results (Assert)**:
- node0 到 node9 ping 可达
- 在 4km 单跳覆盖下，traceroute 应显示 1 跳
- iperf3 吞吐量为正

---

### TC-07: 广播覆盖

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-007 |
| **Priority** | P2 |
| **Estimated Time** | 3 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 启动仿真：`POST /api/sim/start {"preset":"wifi-band-test-2.4g"}`
2. 等待 5 个节点上线
3. 等待 10s
4. node0 发送广播 ping 到 192.168.100.255
5. 检查 node1-node4 的 ARP 表中可达邻居数

**Expected Results (Assert)**:
- 广播 ping 发送成功
- 各节点 ARP 表显示有可达邻居

---

### TC-08: 2.4GHz 多信道遍历

| 属性 | 值 |
|------|-----|
| **ID** | TC-NET-008 |
| **Priority** | P2 |
| **Estimated Time** | 8 min |

**Prerequisites**: 同 TC-01

**Steps (Act)**:
1. 依次在 4 个频率启动仿真：2412, 2437, 2462, 2472 MHz
2. 每次启动后等待 5 节点上线，等待 10s
3. 从 node0 向 node1-node2 各发送 5 个 ping
4. 每次测试后停止仿真，等待 2s

**Expected Results (Assert)**:
- 所有信道下节点均可上线
- 所有 ping 100% 到达

---

## 参考实现

上述测试用例的自动化实现位于：
- `tests/wifi_test_suite.py` — 测试执行脚本
- `tests/run_all_tests.sh` — 一键执行入口
- `tests/generate_report.py` — Markdown 报告生成
