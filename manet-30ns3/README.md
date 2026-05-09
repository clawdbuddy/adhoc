# NS-3 802.11s Mesh / AdHoc 容器化 MANET 仿真系统

**目标平台：x86_64 Ubuntu 22.04**

**802.11s Mesh (HWMP) / 802.11 AdHoc (IBSS)** 网络仿真。每个 MANET 节点是一个独立的 Docker 容器，所有节点间流量被强制经过 NS-3 的信道模型。PHY/MAC/路由/移动模型参数均可通过 **REST 接口**或 **React Web 管理面板**自由配置。

> ⚠️ **架构升级说明**：本项目已从旧的"C++ scratch + shell 脚本"流水线全面迁移到 **Python 控制器（FastAPI + ns-3 Python 绑定）**。节点容器入口也从 shell 脚本改为 Python（`node-entrypoint.py`）。详情见仓库根目录 `CLAUDE.md`。

## 核心架构：每节点一个独立容器

```
+====================================================================+
|                        宿主机 (x86_64 Ubuntu 22.04)                  |
|                                                                      |
|   +-------------+   br-ns3-0   +-------------+                       |
|   | Container-0 |<--veth0--+---+-tap-0------>|  NS-3                 |
|   |  [节点 0]    |              |            |  802.11s              |
|   |  eth0       |              |            |  Mesh MAC             |
|   +-------------+              |            |  + PHY                |
|                                |            |                       |
|   +-------------+   br-ns3-1   |            |  每帧由                |
|   | Container-1 |<--veth1--+---+-tap-1------>|  Mesh / Adhoc         |
|   |  [节点 1]    |              |            |  MAC 处理，            |
|   |  eth0       |              |            |  PHY 决定              |
|   +-------------+              |            |  转发或丢弃            |
|                                |            |                       |
|   ... (最多 30 个节点) ...       |            +---------------------+ |
|                                |                     ^               |
|   +-------------+   br-ns3-29  |                     |               |
|   |Container-29 |<--veth29-+-tap-29------------------+               |
|   | [节点 29]    |                                                     |
|   |  eth0       |                                                     |
|   +-------------+                                                     |
|                                                                       |
|  关键点：每个容器独占自己的网络命名空间 + 独占的 Linux 桥。                  |
|        容器之间无法直接相互通信（无共享 L2 广播域）。                        |
|        所有跨节点流量必须经过 ns-3 802.11s Mesh / AdHoc 信道模型。       |
+====================================================================+
```

### 数据流路径

**节点 A (Container-0) → 节点 B (Container-1)：**

```
Container-0 用户应用
  → Container-0 eth0 (192.168.100.10)
     → vethns0（容器侧）
        → veth0（宿主侧，挂在 br-ns3 上）
           → br-ns3（Linux 桥）
              → tap-0（ns-3 TapBridge 接口）
                 → [ns-3 802.11s Mesh (HWMP) / AdHocWifiMac 处理帧]
                    → [路径损耗模型：A 是否在 B 的覆盖范围内？]
                       → [衰落模型：是否因多径而丢包？]
                          → [信道模型决定：转发 或 丢弃]
                             → tap-1（若帧通过 PHY，单跳直达）
                             → tap-中间节点（若超出单跳，HWMP 自动多跳中继）
                                → br-ns3
                                   → veth1
                                      → vethns1（位于 Container-1 netns）
                                         → Container-1 eth0
                                            → Container-1 用户应用
```

### 网络隔离保证

| 特性 | 实现方式 |
|------|---------|
| 独立网络命名空间 | 每个 Docker 容器 `network_mode="none"` + veth 注入 |
| 容器之间无直接互通 | 没有共享网桥；每节点独占 br-ns3-{i} |
| 强制经过 ns-3 | veth 与 TAP 隔离在独立桥内，跨节点流量只能由 ns-3 转发 |
| 唯一 IP | 每个容器分配 `192.168.100.(10+N)` |
| 唯一 MAC | ns-3 为每个节点分配独立的 WiFi MAC |

> **重要提示**：`TapBridge` 工作在 `UseBridge` 模式（**L2**）。安装在 ns-3 IP 协议栈上的 AODV/OLSR/DSDV/DSR 路由协议**只能看到 ns-3 自己的控制面流量**，看不到用户载荷。多跳转发用户载荷必须由容器内的应用软件实现；ns-3 仅模拟相邻无线电之间的信道。

### 平台支持

仅支持 **linux/amd64** —— 部署目标是 x86 Ubuntu 20.04 主机或同等 Linux VM。

> ⚠️ **运行时仅支持 Linux**。控制器需要在容器中调用 `pyroute2` 直接操作宿主网络（创建桥、veth、TAP，移动 netns），需要 `tun` / `tap` / `bridge` 内核模块。**无法在 macOS 宿主上跑**——请用 x86 Ubuntu 20.04 或等价 Linux 主机/虚机。

## 快速上手

### 推荐路径：Docker Compose + Web 管理面板

```bash
cd manet-30ns3

# 1. 构建镜像（节点镜像 + 控制器镜像）
docker compose --profile build build node-image-builder
docker compose build ns3-controller

# 2. 启动控制器（FastAPI 监听 :8000，特权模式 + host 网络）
docker compose up -d ns3-controller
curl -s localhost:8000/api/health        # → {"ok": true}

# 3. 浏览器打开 http://localhost:8000/  即可使用 React 管理面板
```

### 使用 GitHub 预构建镜像（无需本地编译 NS-3）

GitHub Actions 已自动构建并推送镜像到 `ghcr.io`：

```bash
# 1. 登录 GitHub Container Registry
#   在 https://github.com/settings/tokens 生成具有 read:packages 权限的 Personal Access Token
export CR_PAT=<your-token>
echo $CR_PAT | docker login ghcr.io -u <your-github-username> --password-stdin

# 2. 拉取镜像
docker pull ghcr.io/binnary/adhoc-controller-347:latest
docker pull ghcr.io/binnary/manet-node:latest

# 3. 节点镜像必须本地 tag 为 manet-node:latest（控制器硬编码）
docker tag ghcr.io/binnary/manet-node:latest manet-node:latest

# 4. 启动控制器
#   ⚠️ --privileged 绝对不能省略，否则 pyroute2 创建网桥/TAP/veth 会报
#   NetlinkError(1, 'Operation not permitted')
docker run -d --name ns3-controller \
  --privileged \
  --network host \
  --pid host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/run/netns:/var/run/netns \
  ghcr.io/binnary/adhoc-controller-347:latest

# 5. 验证
curl -s localhost:8000/api/health
```

关键参数说明：

| 参数 | 必要性 | 说明 |
|------|--------|------|
| `--privileged` | **必须** | 创建 Linux bridge / TAP / veth、移动 netns 需要完整特权 |
| `--network host` | **必须** | 控制器直接操作宿主机网络栈 |
| `--pid host` | 推荐 | 容器内 `ps` 能看到宿主机进程，便于调试 |
| `-v /var/run/docker.sock` | **必须** | 控制器通过 Docker API 动态创建节点容器 |
| `-v /var/run/netns` | **必须** | `pyroute2` 创建的 netns 符号链接需要持久化到宿主机路径 |

Web 面板功能：

- **Dashboard**：仿真概览、关键指标、节点统计
- **Configuration**：80+ 参数表单、四种场景预设、导入/导出 `.conf`
- **Topology**：实时网络拓扑可视化（Canvas 画布）、节点列表、流统计
- **Realtime**：控制面板 + 拓扑联合视图
- **Logs**：实时滚动的系统日志

### 通过 REST 接口直接驱动

```bash
# 用预设启动一次仿真
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"debug"}'              # 5 节点，60 秒，无衰落

# 查看运行状态
curl -s localhost:8000/api/sim/status

# 取节点列表 / 流量统计
curl -s localhost:8000/api/nodes
curl -s localhost:8000/api/flows

# 在指定节点容器中执行命令
curl -X POST localhost:8000/api/nodes/0/exec \
     -H 'content-type: application/json' \
     -d '{"cmd":"ip -4 addr show eth0"}'

# 取节点日志
curl 'localhost:8000/api/logs?node=0&tail=50'

# 停止仿真（自动拆桥/拆 veth/拆 TAP/停容器）
curl -X POST localhost:8000/api/sim/stop
```

### 自定义配置

通过 REST 传入 `config` 字段即可覆盖任意参数（命名采用 camelCase，与 `manet-30ns3/web-manager/src/types/config.ts` 一致）：

```bash
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{
       "preset": "default",
       "config": {
         "nNodes": 20,
         "simulationTime": 180,
         "txPowerStart": 22,
         "pathLossExponent": 2.5,
         "routingProtocol": "olsr",
         "mobilityModel": "gauss-markov"
       },
       "nodes": [
         {"id": 0, "userAppMode": "exec"},
         {"id": 1, "userAppMode": "bind", "userAppBindPath": "/host/path/to/app"}
       ]
     }'
```

也可以通过 `PUT /api/config` 暂存"下一轮"配置：

```bash
curl -X PUT localhost:8000/api/config \
     -H 'content-type: application/json' \
     -d @my-config.json
```

> 仿真运行中 `PUT /api/config` 会被拒绝；先 stop 再下发。

## 配置预设

预设定义在 `controller/orchestrator/config.py:PRESETS`，并通过 `GET /api/sim/presets` 暴露：

| Preset | 适用场景 | 关键设置 |
|--------|----------|----------|
| `default` | 用户目标场景（adhoc） | AdhocWifiMac + SpectrumWifiPhy + Friis @ 2412 MHz WiFi + 6 节点 + 5 km × 5 km + 4 km LOS + AODV |
| `urban` | 高密度城市（mesh） | LogDistance n=3.5、Nakagami 强衰落、Aarf、始终 RTS/CTS、2 km × 2 km |
| `rural` | 开阔野外（mesh） | FreeSpace、关闭衰落、Grid 8 km × 8 km、关闭 RTS/CTS |
| `debug` | 5 节点冒烟测试（adhoc） | adhoc 模式、routing=none、Grid 5×5 / 50 m 间距、200 m 视距、ASCII trace |

## 完整参数参考

> 参数权威源在 `controller/orchestrator/config.py:SimConfig`（Pydantic v2 模型，camelCase 别名）；`manet-30ns3/web-manager/src/types/config.ts` 与之对齐。

### 通用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `nNodes` | 6 | AdHoc 节点数（2–100） |
| `simulationTime` | 300 | 仿真时长（秒） |
| `seed` | 1 | 随机种子 |
| `run` | 1 | run 编号 |
| `logComponents` | "" | 逗号分隔的 `NS_LOG` 组件 |

### PHY（物理层）

| 参数 | 默认值 | 取值 |
|------|--------|------|
| `standard` | `80211g` | `80211b`、`80211a`、`80211g`、`80211n-2.4GHz`、`80211n-5GHz`、`80211ac`、`80211ax-2.4GHz`、`80211ax-5GHz` |
| `phyModel` | `spectrum` | `yans` 或 `spectrum`（默认走 `SpectrumWifiPhy + MultiModelSpectrumChannel`） |
| `frequencyMhz` | 2412 | 中心频率（MHz）；默认 2.4 GHz WiFi Channel 1 (2412 MHz)，路径损耗按此频率算 |
| `channelWidthMhz` | 20 | 信道带宽（MHz） |
| `rangeTargetM` | 4000 | 期望视距覆盖半径（m），用于显示与冒烟检查 |
| `dataRate` | `ErpOfdmRate24Mbps` | 任意 ns-3 wifi mode 字符串 |
| `txPowerStart` / `txPowerEnd` | 30.0 | 发射功率（dBm） |
| `txPowerLevels` | 1 | 功率级数 |
| `rxSensitivity` | -92.0 | 接收灵敏度（dBm） |
| `ccaThreshold` | -82.0 | CCA 能量检测门限（dBm） |
| `antennaGain` | 3.0 | 天线增益（dBi） |

### 传播模型

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `propagationDelay` | `ConstantSpeed` | `ConstantSpeed` 或 `Random` |
| `pathLossModel` | `FreeSpace` | `LogDistance`、`FreeSpace`、`TwoRayGround`、`ThreeLogDistance`、`Cost231`、`Range`（`spectrum` PHY 默认 Friis @ 2412 MHz） |
| `pathLossExponent` | 2.0 | 路径损耗指数 n（2 = 自由空间，3 = 城市，4 = 高密度城市） |
| `pathLossRefLoss` | 46.6777 | 1m 处参考损耗（dB） |
| `pathLossRefDistance` | 1.0 | 参考距离（m） |
| `enableFading` | false | 是否启用衰落（mesh 默认关闭，让 4 km 视距预算稳定） |
| `fadingModel` | `Nakagami` | `Nakagami` 或 `Jakes` |
| `nakagamiM0` | 1.5 | d < d1 段的 m 因子（m<1 严重，m=1 Rayleigh，m>2 轻） |
| `nakagamiM1` | 1.0 | d1 < d < d2 段的 m 因子 |
| `nakagamiM2` | 0.75 | d > d2 段的 m 因子 |
| `nakagamiD1` | 50.0 | 距离边界 1（m） |
| `nakagamiD2` | 100.0 | 距离边界 2（m） |

### MAC

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `macMode` | `adhoc` | `mesh`（802.11s + HWMP，L2 多跳）或 `adhoc`（IBSS，单跳广播域，多跳由上层路由完成） |
| `ssid` | `adhoc-30ns3` | IBSS / mesh 网络名 |
| `bssid` | `00:00:00:00:AD:H0` | IBSS BSSID（hex，仅 `adhoc` 模式） |
| `rateControl` | `Arf` | `Arf`、`Aarf`、`Onoe`、`Constant`、`Minstrel` |
| `rtsCtsThreshold` | 2200 | RTS/CTS 阈值（字节，**65535 = 关闭**） |
| `fragmentationThreshold` | 2200 | 最大分片字节 |
| `nonUnicastMode` | false | 广播/组播是否走固定速率 |
| `beaconInterval` | 100 | Beacon 间隔（TU，1 TU = 1024 µs） |
| `cwMin` | 15 | 最小竞争窗口 |
| `cwMax` | 1023 | 最大竞争窗口 |

### 路由协议

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `routingProtocol` | `aodv` | `aodv`、`olsr`、`dsdv`、`dsr`、`none` |
| **AODV** | | |
| `aodvHelloInterval` | 1.0 | Hello 间隔（秒） |
| `aodvRreqRetries` | 2 | RREQ 重试次数 |
| `aodvActiveRouteTimeout` | 3.0 | 路由过期时间（秒） |
| `aodvDeletePeriod` | 5.0 | 路由删除周期（秒） |
| `aodvNetDiameter` | 35 | 期望网络直径（跳数） |
| `aodvEnableHello` | true | 是否启用 hello |
| **OLSR** | | |
| `olsrHelloInterval` | 2.0 | Hello 间隔（秒） |
| `olsrTcInterval` | 5.0 | TC 间隔（秒） |
| `olsrWillingness` | 7 | MPR willingness（0–7） |
| **DSDV** | | |
| `dsdvPeriodicUpdateInterval` | 15.0 | 周期更新间隔（秒） |
| `dsdvSettlingTime` | 6 | settling 时间倍数 |

### 移动模型

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mobilityModel` | `random-walk` | `random-walk`、`gauss-markov`、`grid`、`constant` |
| `mobilityMinX/MaxX` | 0.0/5000.0 | X 方向边界（m） |
| `mobilityMinY/MaxY` | 0.0/5000.0 | Y 方向边界（m） |
| **RandomWalk** | | |
| `rwMinSpeed` / `rwMaxSpeed` | 0.5/3.0 | 速度区间（m/s） |
| `rwDistance` | 200.0 | 转向前的距离（m） |
| `rwMode` | `Time` | `Time` 或 `Distance` |
| `rwTime` | 1.0 | 时间步长（s） |
| **Grid** | | |
| `gridDeltaX/Y` | 800.0/800.0 | 网格间距（m） |
| `gridWidth` | 6 | 每行节点数 |
| **GaussMarkov** | | |
| `gmAlpha` | 0.85 | 记忆因子（0–1，越大相关性越强） |

### 跟踪 / 输出

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `pcap` | true | 每节点 PCAP 抓包 |
| `ascii` | false | ASCII 跟踪 |
| `flowMonitor` | true | FlowMonitor 统计 |
| `pcapPrefix` | `manet-30nodes-adhoc` | PCAP 文件名前缀 |
| `enableMobilityTrace` | false | 移动 ASCII trace |

> **历史命名注意**：`pcap` / `ascii` 在旧版 `.conf` 中曾叫 `pcapTracing` / `asciiTracing`，旧 C++ 解析器会把它们静默丢弃。现在的 Python 解析器（`parse_conf_file`）显式接受这两个旧别名并自动转换。

## 用户软件加载模式（R7）

每个节点容器通过环境变量 `USER_APP_MODE` 选择加载方式（在 `nodes` 数组中按节点指定）：

| 模式 | 机制 | 适用 |
|------|------|------|
| `bind` | bind 挂载用户目录到 `/opt/userapp`，运行 `${USER_APP_CMD:-/opt/userapp/run.sh}` | 迭代开发，宿主侧改代码即可 |
| `image` | 以用户镜像启动；入口脚本检测 `/opt/userapp/run.sh` 已存在 | 可复现的打包软件 |
| `exec`/`ssh` | 容器空转（sshd 或 `tail -f`）；后端通过 `docker exec` / `ssh` 推送二进制 | 演示 / 运行时下发 |

示例：

```bash
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{
       "preset":"debug",
       "nodes":[
         {"id":0,"userAppMode":"bind","userAppBindPath":"/opt/myapp"},
         {"id":1,"userAppMode":"image","image":"my/app:latest"},
         {"id":2,"userAppMode":"exec","sshEnable":false}
       ]
     }'
```

## 文件结构

```
manet-30ns3/
├─ controller/                 # Python 控制器（主路径）
│  ├─ orchestrator/            #   config / netns / docker_mgr / sim_runner / telemetry
│  └─ api/                     #   FastAPI 应用 + REST 路由 + /ws/telemetry
├─ ns3-controller/             # 控制器 Dockerfile（含 NS-3.45 + Python 绑定）
├─ node/                       # 节点 Dockerfile + node-entrypoint.py
├─ web-manager/                # React 19 + Vite + TS 源码 + 由 `npm run build` 产出的 dist/
├─ docker-compose.yml          # 控制器 + 节点镜像构建目标
│
└─ ns3-code/                   # ⚠ 旧版 C++ scratch 程序（仅作历史参考）
```

## 多机部署（Phase 2，已设计未实现）

单机 MVP 是当前已落地形态。多机方案：

- 选定一台主机跑 ns-3 控制器，独占 `br-ns3` 与所有 TAP。
- 其它主机仅跑节点容器；它们的 `veth*-h` 不接本地桥，而是接到 VXLAN 网卡，把 L2 平面延伸到控制器主机的 `br-ns3`。
- 控制器主机：对每个远端 peer 执行 `bridge fdb append … dst <peer-ip> via vxlan100`；`netns.py` 与 `docker_mgr.py` 增加 `host` 参数，`POST /api/hosts/register` 用于远端注册。
- 仍只有一个 ns-3 进程，仿真时间与 PHY 模型一致。

详见 `/Users/binnary/.claude/plans/melodic-puzzling-pebble.md` §9。

## 端到端验证（仅 Linux）

```bash
cd manet-30ns3

# 1. 构建
docker compose --profile build build node-image-builder
docker compose build ns3-controller
# 预期：ns3-controller 镜像内 `python3 -c "from ns import ns"` 成功导入

# 2. 起服
docker compose up -d ns3-controller
curl -s localhost:8000/api/health     # {"ok": true}

# 3. 启动 5 节点冒烟
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"debug"}'
ip link | grep -E 'br-ns3|tap-|veth'  # 应能看到 br-ns3、5 个 tap-{i}、5 个 veth{i}
docker ps | grep manet-node           # 5 个节点容器

# 4. 连通性
docker exec manet-node-0 ping -c 3 192.168.100.11
docker exec manet-node-0 iperf3 -c 192.168.100.14 -t 5

# 5. 遥测
#    打开 http://localhost:8000/  → React UI 加载
#    Topology 页显示 5 个节点；iperf3 起来约 10 秒后 FlowStats 更新

# 6. 拆除
curl -X POST localhost:8000/api/sim/stop
ip link | grep -E 'br-ns3|tap-|veth' || echo "clean"
```

## 构建缓存

两个 Dockerfile（`node/Dockerfile.node`、`ns3-controller/Dockerfile.controller`）都使用 `ccache`（挂载到 `/ccache`，10 GB 上限），第二次起的构建会快很多。

## 系统要求

- Docker ≥ 20.10
- Linux 内核加载 `tun`、`tap`、`bridge`
- **x86_64**（linux/amd64）宿主

| 资源 | 推荐 | 备注 |
|------|------|------|
| CPU | 4 核+ | `pip install ns3` 期间可能编译少量扩展 |
| 内存 | 4 GB+ | 镜像构建峰值会用到 ~3 GB |
| 编译耗时 | ~5–10 min | ccache 命中后通常 < 1 min |

## 故障排查

| 现象 | 排查 |
|------|------|
| `/api/health` 返回错误 | `docker logs ns3-controller` 看是否绑定 socket / 启动成功 |
| 容器之间不通 | 仿真未启动；ns-3 不跑时桥本身不会转发——属于设计内行为 |
| `ip link` 看不到 `br-ns3` | 仿真未启动，或控制器创建桥失败（缺权限/缺内核模块） |
| ns-3 build 出错 `unknown module` | 重建控制器镜像：`docker compose build --no-cache ns3-controller` |
| 吞吐 0 | 试试 `rtsCtsThreshold=65535`、检查 `pathLossExponent` 是否过大 |
| 仿真很慢 | 减小 `nNodes`、用 `mobilityModel=grid`、关掉 `ascii` |
| `exec format error` | 镜像是为 amd64 构建的；确认主机也是 x86_64 |
| `NetlinkError(1, 'Operation not permitted')` | 容器缺少 `--privileged`。删除容器后重新用 `--privileged` 启动 |
| ccache 不生效 | 检查 `CCACHE_DIR` 卷挂载（`-v /ccache:/ccache`） |

## 许可证

NS-3 部分代码遵循 GPLv2。本项目作为配置/参考实现提供。
