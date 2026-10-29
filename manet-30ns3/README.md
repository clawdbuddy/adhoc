# MANET NS-3 容器化仿真系统

**目标平台：x86_64 Linux**（需 Docker、`tun/tap/bridge` 内核模块）

每个 MANET 节点是一个独立 Docker 容器，所有节点间流量强制经过 NS-3 的 802.11s Mesh / AdHoc 信道模型（PHY/MAC/传播/路由）。80+ 仿真参数可通过 REST API 或 React Web 面板实时配置。

---

## 快速启动

```bash
cd manet-30ns3

# 1. 构建镜像
docker compose --profile build build node-image-builder
docker compose build controller

# 2. 启动控制器
docker compose up -d controller
curl -s localhost:8000/api/health      # {"ok":true}

# 3. 启动仿真（5 节点冒烟测试）
curl -X POST localhost:8000/api/sim/start \
  -H 'content-type: application/json' \
  -d '{"preset":"debug"}'

# 4. 打开 Web 面板
#    http://localhost:8000/

# 5. 停止仿真（自动清理容器/网桥/TAP）
curl -X POST localhost:8000/api/sim/stop
```

---

## 架构

```
每个节点独占一个 Linux bridge，桥接三个接口：

mesh-br-{id}
  ├── mesh-veth{id}  ← 容器 eth0（本地节点）
  ├── mesh-tap-{id}  → ns-3 TapBridge → MeshPointDevice → 802.11s
  └── vxlan-{id}     ← 远端 VXLAN 隧道（仅 remote/host-manet 节点）

数据流：容器 eth0 → veth → bridge → tap → ns-3 PHY/MAC → tap → bridge → veth → 目标容器 eth0
```

### 节点部署模式

| 模式 | host 值 | hostType | 说明 |
|------|---------|----------|------|
| 本地容器 | `"local"` | `"container"` | Docker 容器，eth0 → veth → tap → ns-3 |
| 远端主机节点 | `"<IP>"` | `"host-manet"` | SSH 启动容器（`--net=host`），VXLAN 隧道跨主机 |
| 远端容器 | `"<IP>"` | `"container"` | SSH 启动容器，VXLAN 隧道跨主机 |

### VXLAN 隧道（远端节点）

```
远端主机                         控制器主机
vxlan-{id}  ← UDP/4789 →  vxlan-{id}
VNI=100+id                   ↓
MTU=1400                 mesh-br-{id} → mesh-tap-{id} → ns-3
IP=MANET_IP/24

隧道端点自动选取同一 L2 子网 IP（如 192.168.50.x），避免 NAT。
静态 ARP 条目在启动时自动注入。
```

---

## 节点管理

### 注册远端主机

```bash
curl -X POST localhost:8000/api/hosts/register \
  -H 'content-type: application/json' \
  -d '{
    "ip": "100.100.100.9",
    "sshUser": "binnary",
    "sshKey": "-----BEGIN OPENSSH PRIVATE KEY-----\n...",
    "capacity": 1
  }'
```

### 配置节点规格

```bash
# 查看当前规格
curl -s localhost:8000/api/nodes/specs | jq

# 更新规格
curl -X PUT localhost:8000/api/nodes/specs \
  -H 'content-type: application/json' \
  -d '{
    "specs": [
      {"id": 0, "ip": "192.168.100.10", "role": "server", "host": "local"},
      {"id": 1, "ip": "192.168.100.11", "role": "server",
       "host": "100.100.100.9", "hostType": "host-manet"}
    ]
  }'
```

### 启动含远端节点的仿真

```bash
curl -X POST localhost:8000/api/sim/start \
  -H 'content-type: application/json' \
  -d '{
    "config": {
      "nNodes": 5, "simulationTime": 180,
      "standard": "80211n-2.4GHz",
      "macMode": "mesh",
      "mobilityModel": "grid",
      "gridDeltaX": 50, "gridWidth": 5,
      "txPowerStart": 20, "pathLossModel": "FreeSpace"
    },
    "nodes": [
      {"id": 0, "ip": "192.168.100.10", "role": "server", "host": "local"},
      {"id": 1, "ip": "192.168.100.11", "role": "server",
       "host": "100.100.100.9", "hostType": "host-manet"},
      {"id": 2, "ip": "192.168.100.12", "role": "client", "host": "local"},
      {"id": 3, "ip": "192.168.100.13", "role": "client", "host": "local"},
      {"id": 4, "ip": "192.168.100.14", "role": "client", "host": "local"}
    ]
  }'
```

> **注意**：远端节点默认使用 `ghcr.io/clawdbuddy/host-manet-node:main` 镜像。
> 控制器需 `--pid host`（docker-compose 已配置 `pid: host`）以访问宿主机 PID 空间。

---

## 测试

### WiFi 自动化测试套件

```bash
cd manet-30ns3

# 运行全部 8 个测试用例
python3 tests/wifi_test_suite.py

# 运行单个测试
python3 tests/wifi_test_suite.py tc_frequency_2_4g

# 生成测试报告
python3 tests/generate_report.py
# → test-results/wifi_test_report.md
```

| 用例 | 说明 |
|------|------|
| `tc_frequency_2_4g` | 2.4GHz 频段连通性 |
| `tc_frequency_5g` | 5GHz 频段连通性 |
| `tc_bandwidth_20m` | 20MHz 带宽吞吐 |
| `tc_bandwidth_40m` | 40MHz 带宽吞吐 |
| `tc_distance_attenuation` | 距离衰减（500-2000m） |
| `tc_adhoc_multihop` | 10 节点多跳 |
| `tc_broadcast` | 广播覆盖 |
| `tc_frequency_sweep` | 多信道遍历 |

### 后端单元测试

```bash
cd manet-30ns3

# API 路由测试（Mock 模式，无需 Docker）
python3 -m pytest controller/tests/test_api_routes.py -v

# Docker 管理器测试
python3 -m pytest controller/tests/test_docker_mgr.py -v

# 网络操作测试
python3 -m pytest controller/tests/test_netns.py -v
```

### 前端检查

```bash
cd manet-30ns3/web-manager
npm run lint
npm run build    # tsc + vite build
```

### 手动端到端验证

```bash
# 1. 启动 5 节点仿真（4 本地 + 1 远程）
curl -X POST localhost:8000/api/sim/start \
  -H 'content-type: application/json' \
  -d '{"preset":"debug"}'

# 2. 检查节点状态
curl -s localhost:8000/api/nodes | jq

# 3. 连通性测试
curl -s -X POST localhost:8000/api/nodes/0/exec \
  -H 'content-type: application/json' \
  -d '{"cmd":"ping -c 4 192.168.100.11"}'

# 4. 吞吐测试
curl -s -X POST localhost:8000/api/nodes/0/exec \
  -H 'content-type: application/json' \
  -d '{"cmd":"iperf3 -c 192.168.100.11 -t 5"}'

# 5. 停止
curl -X POST localhost:8000/api/sim/stop

# 6. 验证清理
ip link | grep -E 'mesh-|vxlan-' || echo "clean"
```

---

## REST API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/sim/start` | 启动仿真（body: RunRequest） |
| POST | `/api/sim/stop` | 停止仿真 |
| GET | `/api/sim/status` | 仿真状态 |
| GET | `/api/sim/presets` | 预设列表 |
| GET | `/api/nodes` | 节点状态列表 |
| GET | `/api/flows` | 流量统计 |
| POST | `/api/nodes/{id}/exec` | 在节点中执行命令 |
| GET | `/api/logs?node={id}` | 查看节点日志 |
| GET | `/api/config` | 获取当前配置 |
| PUT | `/api/config` | 更新配置 |
| POST | `/api/hosts/register` | 注册远端主机 |
| GET | `/api/hosts` | 主机列表 |
| DELETE | `/api/hosts/{ip}` | 删除主机 |
| GET | `/api/nodes/specs` | 节点规格列表 |
| PUT | `/api/nodes/specs` | 更新节点规格 |
| WS | `/ws/telemetry` | 实时遥测（5Hz） |

### 预设

| 预设 | 场景 | 参数 |
|------|------|------|
| `debug` | 5 节点冒烟 | mesh, grid 50m, FreeSpace, Tx=20dBm |
| `default` | 用户目标 | mesh, 5000x5000, FreeSpace, Tx=30dBm |
| `urban` | 高密度城市 | mesh, LogDistance n=3.5, Nakagami, 2km |
| `rural` | 开阔野外 | mesh, FreeSpace, Grid 8km, 无衰落 |
| `tactical` | 战术通信 | 10 节点 mesh, UHF 590MHz, FreeSpace, Tx=30dBm, 6Mbps |

---

## 目录结构

```
manet-30ns3/
├── controller/
│   ├── api/            # FastAPI 路由（sim/nodes/config/hosts）
│   ├── orchestrator/   # 核心：config/netns/docker_mgr/host_node_mgr/sim_runner
│   └── tests/          # 后端单元测试
├── node/               # 节点 Dockerfile + node-entrypoint.py
├── web-manager/        # React 19 + Vite + TypeScript 前端
├── tests/              # WiFi 自动化测试套件 + 报告生成器
│   ├── wifi_test_suite.py
│   ├── generate_report.py
│   └── docs/           # 测试用例文档
├── config/             # 运行时持久化（host_registry.json, node_specs.json）
├── docker-compose.yml
└── results/            # PCAP / ASCII trace 输出
```

---

## 故障排查

| 现象 | 排查 |
|------|------|
| 远端容器未启动 | 检查 `node_specs.json` 中节点 `host` 和 `hostType` 是否正确配置 |
| docker pull 403 | daocloud 镜像代理限制 → 使用 GHCR 全路径镜像名 |
| VXLAN 不通 | 检查两端 LAN IP 是否在同一子网（`ip route get 8.8.8.8`） |
| ping 丢包 | 检查 ARP 表（`arp -n`），静态 ARP 是否注入 |
| `--privileged` 缺失 | pyroute2 创建网桥/TAP 时报 `NetlinkError(1, 'Operation not permitted')` |
| 容器残留 | `docker rm -f $(docker ps -aq --filter name=manet-node)` |

---

## 系统要求

- Docker ≥ 20.10, Linux x86_64
- 内核模块：`tun`, `tap`, `bridge`
- CPU ≥ 4 核, 内存 ≥ 4 GB
- 控制器需 `--privileged --network host --pid host`


## 无线配置与统计的实现边界

- 标准、速率控制、RTS/CTS、分片阈值、竞争窗口和带宽作用于实际 WiFi 接口。MeshHelper 安装阶段使用合法的 5 GHz 代理频道，安装完成后设置目标频段与带宽。
- `simulationTime` 按仿真时间自动结束；会话随后清理节点容器与网络设备。实时模式使用 BestEffort，主机过载或 cppyy 首次编译时可能落后于墙钟。
- 动态命令与 ns-3 状态采样都在仿真线程执行；API 读取快照，不跨线程操作模型对象。队列满或等待超时会报告失败。
- `PUT /api/config` 原子保存下次启动的配置；运行中的修改使用 `/api/env/*` 或 WebSocket 参数接口。前端读取初始配置成功后才允许自动保存。
- 当前 cppyy 路线对 AdHoc + TAP 组合显式拒绝启动，以避免已知崩溃；AdHoc + onoff 与 Mesh 模式保留。完整容器 AdHoc 支持仍需后续绑定修复，不能视作已验收。
- WiFi 动态频点须与当前标准、带宽匹配。UHF 仍是传播损耗预算模拟，实际调制使用 WiFi 代理载波；遥测 `env.phyFrequencyMhz` 返回实际载波，`env.frequencyMhz` 返回预算频率。
- TAP 业务流量通过独立接口上的 AF_PACKET 被动采集，当前覆盖已知节点之间的单播 IPv4。延迟单位为毫秒，吞吐单位为 Mbps（自首次发送起累计平均），丢包为发送 10 秒后仍未观察到接收的包。`measurement.captureDrops` 标记采集器自身丢帧，出现丢帧时统计不完整。IPv6、广播端到端统计未实现。
- 拓扑邻居来自实际已建立的 Mesh peer；`/api/sim/path` 是该 peer 图上的 BFS 路径，不代表 HWMP 实际选路或业务成功交付。

内部流量冒烟验证（不需要 Docker，不创建宿主网络接口）：

```bash
PYTHONPATH=. python3 tests/smoke_sim_runner.py
```

此冒烟覆盖真实 ns-3 启动、位置/功率调整、20→40 MHz 切换、源目的流量统计和自然停止。容器 TAP/VXLAN 的端到端效果及目标平台 ns-3.47 仍需在部署环境运行集成测试。
