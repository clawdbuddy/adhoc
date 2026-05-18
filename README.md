# MANET NS-3 容器化仿真系统

**目标平台：x86_64 Linux**（需 Docker、`tun/tap/bridge` 内核模块）

每个 MANET 节点是一个独立 Docker 容器，所有节点间流量强制经过 NS-3 的 802.11s Mesh / AdHoc 信道模型（PHY/MAC/传播/路由）。80+ 仿真参数可通过 REST API 或 React Web 面板实时配置。

---

## 控制器启动方式

### Docker — 本地构建

```bash
cd manet-30ns3

# 构建镜像
docker compose --profile build build node-image-builder
docker compose build controller

# 启动控制器（--privileged --network host --pid host）
docker compose up -d controller
curl -s localhost:8000/api/health      # {"ok":true}
```

### Docker — 从 GHCR 拉取（无需源码）

```bash
# 1. 拉取节点镜像
docker pull ghcr.io/clawdbuddy/manet-node:latest
docker tag ghcr.io/clawdbuddy/manet-node:latest manet-node:latest

# 2. 启动控制器
docker run -d --name controller \
  --privileged --network host --pid host \
  --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/run/netns:/var/run/netns \
  -v $(pwd)/results:/results \
  -v $(pwd)/config:/app/config \
  ghcr.io/clawdbuddy/manet-controller:latest

# 3. 检查健康
curl localhost:8000/api/health

# 4. 启动仿真
curl -X POST localhost:8000/api/sim/start \
  -H 'content-type: application/json' \
  -d '{"preset":"debug"}'
```

> 远端主机使用 `host-manet-node` 时，远端也需提前拉取：
> ```bash
> ssh user@remote-host
> docker pull ghcr.io/clawdbuddy/host-manet-node:main
> ```

> 如需停止并删除控制器容器：
> ```bash
> docker stop controller && docker rm controller
> ```

### Conda 物理主机

```bash
cd manet-30ns3

# 首次安装系统依赖 + conda 环境 + systemd 服务
sudo bash setup-controller.sh

# 手动启动
conda activate manet-controller
PYTHONPATH=./controller MANET_WEB_DIR=./web-manager/dist \
  python3 -m uvicorn controller.api.main:app --host 0.0.0.0 --port 8000
```

### 独立可执行程序

```bash
cd manet-30ns3
bash build-controller.sh               # 输出 dist/manet-controller/
./dist/manet-controller/manet-controller
```

---

## 快速启动

```bash
cd manet-30ns3

# 1. 构建镜像（Docker 方式启动时才需执行）
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
| `tactical` | 战术通信 | mesh, UHF 590MHz, TwoRayGround, Tx=37dBm |

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
