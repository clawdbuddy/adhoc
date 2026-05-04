# MANET NS-3 仿真系统总体需求方案 v2.0

## 文档信息

| 项目 | 内容 |
|------|------|
| 文档版本 | v2.0 |
| 更新日期 | 2026-05-02 |
| 适用范围 | manet-30ns3/web-manager/ + manet-30ns3/ 全栈 |
| 状态 | 已实现并验证 |

---

## 1. 总体目标

构建一套容器化 MANET（移动自组网）仿真系统，具备：
- **多节点数据互通**：1–16 个 Docker 容器节点，所有流量强制经过 ns-3 信道模型
- **动态电磁环境模拟**：运行时调整传播模型参数、频率、功率
- **4–8 Mbps 通信带宽**：通过 802.11a/g/n/ac/ax 标准 + 数据速率配置实现
- **3–4 km 通视距离**：通过 UHF 频段（590 MHz）+ 高功率（30 dBm）+ 自由空间路径损耗实现
- **Web 可视化管理**：React 前端 + FastAPI 后端，实时拓扑、遥测、控制

---

## 2. 需求功能点总览

### R1 — 容器化节点隔离与互通
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R1.1 独立网络命名空间 | ✅ | 每个节点 `network_mode="none"`，通过 veth 注入 |
| R1.2 Linux 网桥聚合 | ✅ | `br-ns3` 连接所有 veth 宿主端 + TAP 设备 |
| R1.3 强制 ns-3 转发 | ✅ | 节点间无直接路径，所有帧必经 ns-3 PHY/MAC |
| R1.4 IP 地址分配 | ✅ | 子网 `192.168.100.0/24`，节点 i → `.10+i` |
| R1.5 节点角色定义 | ✅ | server(0)、gateway(15)、client(其余) |

### R2 — ns-3 仿真核心
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R2.1 SpectrumWifiPhy | ✅ | 默认 PHY，支持任意频率 |
| R2.2 YansWifiPhy（兼容） | ✅ | 旧路径，向后兼容 |
| R2.3 802.11s Mesh + HWMP | ✅ | `mac_mode="mesh"`，L2 多跳 |
| R2.4 AdHocWifiMac（兼容） | ✅ | `mac_mode="adhoc"`，单跳广播域 |
| R2.5 多路由协议 | ✅ | AODV、OLSR、DSDV、DSR、none |
| R2.6 多移动模型 | ✅ | random-walk、gauss-markov、grid、constant |
| R2.7 FlowMonitor 统计 | ✅ | 1 Hz 轮询，输出 throughput/delay/packet-loss |
| R2.8 PCAP/ASCII 跟踪 | ✅ | 可选每节点抓包 |

### R3 — 配置管理系统
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R3.1 SimConfig 模型 | ✅ | Pydantic v2，~85 字段，snake_case↔camelCase |
| R3.2 场景预设 | ✅ | default、urban、rural、debug、tactical |
| R3.3 .conf 文件解析 | ✅ | 兼容旧版 key=value 格式 |
| R3.4 配置优先级 | ✅ | overrides > file > preset > defaults |
| R3.5 REST 配置读写 | ✅ | GET/PUT `/api/config` |
| R3.6 前端配置面板 | ✅ | 6 子标签表单，导入/导出 |

### R4 — 动态电磁环境模拟（本次新增）
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R4.1 线程安全命令队列 | ✅ | `queue.Queue` + `_tick()` 消费 |
| R4.2 节点位置跃迁 | ✅ | `POST /api/env/position`，`MobilityModel.SetPosition()` |
| R4.3 节点功率调整 | ✅ | `POST /api/env/txpower`，`WifiPhy.SetAttribute("TxPowerStart")` |
| R4.4 节点灵敏度调整 | ✅ | `POST /api/env/rxsens`，`WifiPhy.SetAttribute("RxSensitivity")` |
| R4.5 路径损耗指数调整 | ✅ | `POST /api/env/pathloss`，`PropagationLossModel.SetAttribute("Exponent")` |
| R4.6 中心频率调整 | ✅ | `POST /api/env/frequency`，同步 PHY + 传播模型 |
| R4.7 信道宽度调整 | ✅ | `POST /api/env/channelwidth`，`WifiPhy.SetAttribute("ChannelWidth")` |
| R4.8 最大通信距离调整 | ✅ | `POST /api/env/range`，`RangePropagationLossModel.SetAttribute("MaxRange")` |
| R4.9 能力查询接口 | ✅ | `GET /api/env/capabilities` |
| R4.10 前端动态控制面板 | ✅ | `DynamicControl.tsx`，滑块 + 快速预设 |

### R5 — 遥测与可视化
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R5.1 WebSocket 遥测 | ✅ | `/ws/telemetry`，1 Hz 广播 |
| R5.2 节点位置实时显示 | ✅ | TopologyView Canvas 渲染 |
| R5.3 流量统计实时显示 | ✅ | FlowStats 表格 |
| R5.4 日志实时滚动 | ✅ | LogView，WebSocket + API 日志 |
| R5.5 仪表盘指标 | ✅ | Dashboard，在线节点/吞吐/延迟/丢包 |

### R6 — 用户软件加载
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R6.1 bind 模式 | ✅ | 挂载宿主目录到 `/opt/userapp` |
| R6.2 image 模式 | ✅ | 自定义镜像启动 |
| R6.3 exec/ssh 模式 | ✅ | 容器空转，`docker exec` 推送 |
| R6.4 容器内命令执行 | ✅ | `POST /api/nodes/{id}/exec` |
| R6.5 容器日志获取 | ✅ | `GET /api/logs?node={id}&tail={n}` |

### R7 — 战术通信场景（本次新增）
| 子功能 | 状态 | 说明 |
|--------|------|------|
| R7.1 10 节点网格部署 | ✅ | tactical 预设，grid 布局 |
| R7.2 UHF 590 MHz 频段 | ✅ | 覆盖 500–680 MHz |
| R7.3 6 Mbps 数据速率 | ✅ | `OfdmRate6Mbps`，20 MHz 信道 |
| R7.4 4 km 通视距离 | ✅ | 30 dBm + 3 dBi + (-92 dBm) + FreeSpace |
| R7.5 5×5 km 活动区域 | ✅ | grid 布局，1000 m 间距 |

---

## 3. 设计实现：按功能点展开

### R1 — 容器化节点隔离与互通

**R1.1–R1.5 设计：**
- 网络层：`controller/orchestrator/netns.py`（pyroute2）
- 容器层：`controller/orchestrator/docker_mgr.py`（docker SDK）
- 生命周期：`controller/api/state.py:Session.start/stop`

**实现要点：**
```python
# netns.py: create_veth → move_to_netns → create_tap
# docker_mgr.py: start_one(network_mode="none") → exec_in → logs
# state.py: start() 顺序：bridge → containers → veth → tap → sim → telemetry
```

**关键代码路径：**
- `netns.py:ensure_bridge()` — 创建 `br-ns3`，IP `192.168.100.1/24`
- `netns.py:create_veth(i)` — `veth{i}` 接 bridge，`vethns{i}` 移入容器 netns
- `netns.py:move_to_netns()` — 容器内改名为 `eth0`，分配 `192.168.100.(10+i)/24`
- `netns.py:create_tap(i)` — `tap-{i}` 接 bridge，ns-3 TapBridge 绑定

---

### R2 — ns-3 仿真核心

**R2.1–R2.8 设计：**
- 核心引擎：`controller/orchestrator/sim_runner.py:SimRunner`
- 双路线 Python 绑定兼容：`sim_runner.py:_import_ns()`

**实现要点：**
```python
# sim_runner.py:_build_and_run() 执行顺序：
# 1. RealtimeSimulatorImpl + RNG 种子
# 2. NodeContainer.Create(n_nodes)
# 3. PHY: spectrum → _build_spectrum_phy() / yans → _build_yans_phy()
# 4. WifiHelper.SetStandard() + SetRemoteStationManager()
# 5. MAC: mesh → MeshHelper.Install() / adhoc → WifiMacHelper.Install()
# 6. MobilityHelper.Install()
# 7. InternetStackHelper.Install() + RoutingHelper
# 8. Ipv4AddressHelper.Assign()
# 9. TapBridgeHelper.Install()
# 10. FlowMonitorHelper.InstallAll()
# 11. Tracing (pcap/ascii)
# 12. _schedule_periodic() — 1 Hz 快照
# 13. Simulator.Run()
```

**关键技术决策：**
- `phy_model="spectrum"` 时，`frequency_mhz=590` 不合法（802.11a 频道表），但通过 Friis 传播模型把 `Frequency` 属性钉到 590 MHz，实现 UHF 物理预算
- `mac_mode="mesh"` 时，ns-3 802.11s HWMP 在 L2 完成多跳，容器视角为单一广播域
- `mac_mode="adhoc"` 时，多跳需容器内软件（如 batman-adv）自行处理

---

### R3 — 配置管理系统

**R3.1–R3.6 设计：**
- 后端模型：`controller/orchestrator/config.py:SimConfig`
- 加载器：`controller/orchestrator/config.py:load_config()`
- 前端模型：`manet-30ns3/web-manager/src/types/config.ts:SimConfig`
- 前端状态：`manet-30ns3/web-manager/src/hooks/useSimConfig.ts`

**实现要点：**
```python
# config.py:SimConfig
class SimConfig(_CamelModel):
    # alias_generator=to_camel, populate_by_name=True
    # 约 85 个字段，覆盖 PHY/传播/MAC/路由/移动/跟踪/TapBridge

# config.py:load_config()
# 优先级：overrides > file_path > preset > defaults

def load_config(*, file_path=None, overrides=None, preset=None):
    if preset: cfg = PRESETS[preset]
    else: cfg = SimConfig()
    if file_path: cfg = cfg.merged_with(parse_conf_file(file_path))
    if overrides: cfg = cfg.merged_with(overrides)
    return cfg
```

**预设定义（前后端对齐）：**
| 预设 | 关键差异 |
|------|----------|
| default | 16 节点、random-walk、FreeSpace、AODV、4 km |
| urban | 16 节点、LogDistance n=3.5、Nakagami 衰落、2 km、AARF |
| rural | 16 节点、FreeSpace、Grid 8×8 km、33 dBm、OLSR |
| debug | 5 节点、adhoc、无路由、Grid 300×300 m、ASCII trace |
| tactical | 8 节点、Grid 5×5 km、UHF 590 MHz、6 Mbps、4 km |

---

### R4 — 动态电磁环境模拟（本次核心新增）

**R4.1–R4.10 设计：**
- 线程安全机制：`SimRunner._command_queue` + `_tick()` 消费
- REST 路由：`controller/api/routes_dynamic.py`
- 前端面板：`manet-30ns3/web-manager/src/sections/DynamicControl.tsx`

#### R4.1 线程安全命令队列
```python
# sim_runner.py
self._command_queue: queue.Queue = queue.Queue()

def _inject_command(self, fn: Callable[[], None]):
    self._command_queue.put(fn)

# _tick() 中消费：
while not runner._command_queue.empty():
    cmd = runner._command_queue.get_nowait()
    cmd()  # 在 ns-3 线程中执行
```

#### R4.2 节点位置跃迁
```python
def set_node_position(self, node_id, x, y, z=0):
    def _do():
        node = self._nodes_container.Get(node_id)
        mm = node.GetObject(ns.mobility.MobilityModel.GetTypeId())
        mm.SetPosition(ns.core.Vector(x, y, z))
    self._inject_command(_do)
```
- REST: `POST /api/env/position` `{nodeId, x, y, z}`
- 前端：X/Y 输入框 + 应用按钮

#### R4.3 节点功率调整
```python
def set_tx_power(self, node_id, dbm):
    def _do():
        device = self._wifi_devices.Get(node_id)
        phy = device.GetPhy()
        phy.SetAttribute("TxPowerStart", ns.core.DoubleValue(dbm))
        phy.SetAttribute("TxPowerEnd", ns.core.DoubleValue(dbm))
    self._inject_command(_do)
```
- REST: `POST /api/env/txpower` `{nodeId, dbm}`
- 前端：0–40 dBm 滑块

#### R4.4 节点灵敏度调整
```python
def set_rx_sensitivity(self, node_id, dbm):
    def _do():
        device = self._wifi_devices.Get(node_id)
        phy = device.GetPhy()
        phy.SetAttribute("RxSensitivity", ns.core.DoubleValue(dbm))
    self._inject_command(_do)
```
- REST: `POST /api/env/rxsens` `{nodeId, dbm}`
- 前端：-110 ~ -60 dBm 滑块

#### R4.5 路径损耗指数调整
```python
def set_path_loss_exponent(self, exponent):
    def _do():
        self._propagation_loss_model.SetAttribute(
            "Exponent", self._ns.core.DoubleValue(exponent)
        )
    self._inject_command(_do)
```
- REST: `POST /api/env/pathloss` `{exponent}`
- 前端：1.0–6.0 滑块
- 限制：仅 LogDistance 模型生效

#### R4.6 中心频率调整
```python
def set_frequency(self, mhz):
    def _do():
        freq_hz = float(mhz) * 1e6
        # 修改所有节点 PHY
        for i in range(self.config.n_nodes):
            device = self._wifi_devices.Get(i)
            phy = device.GetPhy()
            phy.SetAttribute("Frequency", ns.core.DoubleValue(freq_hz))
        # 同步传播模型频率
        if self._propagation_loss_model is not None:
            model_name = str(self._propagation_loss_model.GetInstanceTypeId().GetName())
            if "Friis" in model_name or "TwoRay" in model_name:
                self._propagation_loss_model.SetAttribute(
                    "Frequency", ns.core.DoubleValue(freq_hz)
                )
    self._inject_command(_do)
```
- REST: `POST /api/env/frequency` `{mhz}`
- 前端：300–5800 MHz 滑块

#### R4.7 信道宽度调整
```python
def set_channel_width(self, mhz):
    def _do():
        for i in range(self.config.n_nodes):
            device = self._wifi_devices.Get(i)
            phy = device.GetPhy()
            phy.SetAttribute("ChannelWidth", ns.core.UintegerValue(mhz))
    self._inject_command(_do)
```
- REST: `POST /api/env/channelwidth` `{mhz}`
- 前端：5–80 MHz 滑块（步长 5）

#### R4.8 最大通信距离调整
```python
def set_range_target(self, meters):
    def _do():
        model_name = str(self._propagation_loss_model.GetInstanceTypeId().GetName())
        if "Range" not in model_name:
            log.warning("current model is %s, not Range", model_name)
            return
        self._propagation_loss_model.SetAttribute(
            "MaxRange", self._ns.core.DoubleValue(meters)
        )
    self._inject_command(_do)
```
- REST: `POST /api/env/range` `{meters}`
- 前端：100–10000 m 滑块
- 限制：仅 Range 模型生效

#### R4.9 能力查询
```python
@router.get("/api/env/capabilities")
async def get_capabilities():
    return {"capabilities": [
        {"id": "txpower", "name": "发射功率", "unit": "dBm", "scope": "per-node"},
        {"id": "position", "name": "节点位置", "unit": "m", "scope": "per-node"},
        {"id": "rxsens", "name": "接收灵敏度", "unit": "dBm", "scope": "per-node"},
        {"id": "pathloss", "name": "路径损耗指数", "unit": "", "scope": "global"},
        {"id": "frequency", "name": "中心频率", "unit": "MHz", "scope": "global"},
        {"id": "channelwidth", "name": "信道宽度", "unit": "MHz", "scope": "global"},
        {"id": "range", "name": "最大通信距离", "unit": "m", "scope": "global"},
    ]}
```

#### R4.10 前端动态控制面板
- 文件：`manet-30ns3/web-manager/src/sections/DynamicControl.tsx`
- Hook：`manet-30ns3/web-manager/src/hooks/useDynamicControl.ts`
- 集成：`App.tsx` 新增 "动态控制" Tab
- 控件：
  - 节点选择器（显示当前所有节点 ID + 坐标）
  - 位置跃迁：X/Y 输入 + 应用按钮
  - 发射功率：0–40 dBm 滑块
  - 接收灵敏度：-110 ~ -60 dBm 滑块
  - 路径损耗指数：1.0–6.0 滑块
  - 中心频率：300–5800 MHz 滑块
  - 信道宽度：5–80 MHz 滑块
  - 最大通信距离：100–10000 m 滑块
  - 快速预设：自由空间/UHF、城市/2.4GHz、开阔地/5GHz、高密度城市/UHF

---

### R5 — 遥测与可视化

**R5.1–R5.5 设计：**
- 后端：`controller/orchestrator/telemetry.py`
- WebSocket：`controller/api/ws_telemetry.py`
- 前端：`manet-30ns3/web-manager/src/hooks/useSimulation.ts` + `TopologyView.tsx` + `Dashboard.tsx`

**实现要点：**
```python
# telemetry.py: 1 Hz asyncio pump
# - 读取 SimRunner.snapshot_nodes() → 位置、包计数
# - 读取 SimRunner.snapshot_flows() → FlowMonitor 统计
# - 广播到所有 WebSocket 订阅者

# ws_telemetry.py: /ws/telemetry
# - 接收连接 → 加入 subscribers
# - 每帧到达 → 序列化 JSON → 发送
# - 仿真未运行 → 发送空帧后关闭
```

**TopologyView.tsx：**
- Canvas 2D 渲染
- 网格背景、节点圆点（绿/黄/红）、邻居连线（蓝）
- 节点列表侧边栏：IP、状态、包数

---

### R6 — 用户软件加载

**R6.1–R6.5 设计：**
- 入口：`node/node-entrypoint.py`（容器内）
- 控制：`controller/orchestrator/docker_mgr.py`

**实现要点：**
```python
# node-entrypoint.py 根据 USER_APP_MODE 选择行为：
# bind:   检测 /opt/userapp/run.sh → 执行
# image:  同上（镜像已打包）
# exec:   tail -f /dev/null（空转，等 docker exec）
# ssh:    启动 sshd

# docker_mgr.py:
# start_one() → docker run --net=none -e USER_APP_MODE=...
# exec_in()   → docker exec <container> <cmd>
# logs()      → docker logs --tail <n>
```

---

### R7 — 战术通信场景

**R7.1–R7.5 设计：**
- 预设：`controller/orchestrator/config.py:PRESETS["tactical"]`
- 前端同步：`manet-30ns3/web-manager/src/types/config.ts:PRESETS.tactical`

**配置参数：**
```python
"tactical": _preset(
    nNodes=10, simulationTime=300,
    standard="80211a", phyModel="spectrum",
    frequencyMhz=590, channelWidthMhz=20,
    dataRate="OfdmRate6Mbps",
    txPowerStart=30.0, txPowerEnd=30.0,
    rxSensitivity=-92.0, ccaThreshold=-82.0,
    antennaGain=3.0,
    pathLossModel="FreeSpace", pathLossExponent=2.0,
    enableFading=False,
    macMode="mesh", rateControl="Constant",
    rtsCtsThreshold=2200,
    mobilityModel="grid",
    mobilityMaxX=5000.0, mobilityMaxY=5000.0,
    gridMinX=100.0, gridMinY=100.0,
    gridDeltaX=1000.0, gridDeltaY=1000.0,
    gridWidth=5,
    rangeTargetM=4000.0,
    pcapPrefix="manet-tactical",
)
```

**4 km 视距预算验证：**
- 发射端：30 dBm Tx + 3 dBi 天线增益 = 33 dBm EIRP
- 路径损耗（Friis @ 590 MHz，4 km）：
  - `PL = 20*log10(4πd/λ) = 20*log10(4π*4000/(3e8/590e6)) ≈ 99.9 dB`
- 接收端：33 dBm EIRP - 99.9 dB PL + 3 dBi Rx = -63.9 dBm
- 接收灵敏度：-92 dBm
- 链路余量：-63.9 - (-92) = **28.1 dB** ✓（满足 3–4 km 要求）

**4–8 Mbps 带宽实现：**
- 802.11a @ 20 MHz 信道：
  - 6 Mbps：`OfdmRate6Mbps`（保守，实际可用）
  - 9 Mbps：`OfdmRate9Mbps`
  - 12 Mbps：`OfdmRate12Mbps`
- 用户可通过 `dataRate` 字段在 6/9/12/18/24/36/48/54 Mbps 间切换

---

## 4. 关键文件清单

### 后端（Python）

| 文件 | 职责 | 涉及需求 |
|------|------|----------|
| `controller/orchestrator/config.py` | SimConfig / PRESETS / 加载器 | R3, R7 |
| `controller/orchestrator/sim_runner.py` | ns-3 仿真引擎 + 动态控制 | R2, R4 |
| `controller/orchestrator/netns.py` | Linux 网络命名空间操作 | R1 |
| `controller/orchestrator/docker_mgr.py` | Docker 容器管理 | R1, R6 |
| `controller/orchestrator/telemetry.py` | 遥测数据聚合 | R5 |
| `controller/api/state.py` | Session 生命周期 | R1–R7 |
| `controller/api/main.py` | FastAPI 应用入口 | R1–R7 |
| `controller/api/routes_sim.py` | 仿真启停/状态/预设 | R2, R3 |
| `controller/api/routes_config.py` | 配置读写 | R3 |
| `controller/api/routes_nodes.py` | 节点操作/执行/日志 | R5, R6 |
| `controller/api/routes_dynamic.py` | 动态环境控制（新增） | R4 |
| `controller/api/ws_telemetry.py` | WebSocket 遥测 | R5 |

### 前端（TypeScript/React）

| 文件 | 职责 | 涉及需求 |
|------|------|----------|
| `manet-30ns3/web-manager/src/types/config.ts` | 类型定义 + PRESETS | R3, R7 |
| `manet-30ns3/web-manager/src/hooks/useSimConfig.ts` | 配置状态管理 | R3 |
| `manet-30ns3/web-manager/src/hooks/useSimulation.ts` | 仿真生命周期 + WebSocket | R5 |
| `manet-30ns3/web-manager/src/hooks/useDynamicControl.ts` | 动态控制 API 封装（新增） | R4 |
| `manet-30ns3/web-manager/src/App.tsx` | 主布局 + Tab 路由 | R1–R7 |
| `manet-30ns3/web-manager/src/sections/Dashboard.tsx` | 仪表盘 | R5 |
| `manet-30ns3/web-manager/src/sections/ConfigPanel.tsx` | 配置面板 | R3 |
| `manet-30ns3/web-manager/src/sections/TopologyView.tsx` | 拓扑可视化 | R5 |
| `manet-30ns3/web-manager/src/sections/ControlPanel.tsx` | 控制面板 | R2, R5 |
| `manet-30ns3/web-manager/src/sections/DynamicControl.tsx` | 动态控制面板（新增） | R4 |
| `manet-30ns3/web-manager/src/sections/LogView.tsx` | 日志视图 | R5 |

### 基础设施

| 文件 | 职责 |
|------|------|
| `manet-30ns3/docker-compose.yml` | 控制器/节点镜像编排 |
| `manet-30ns3/ns3-controller/Dockerfile.controller` | NS-3.45 + Python 绑定镜像 |
| `manet-30ns3/node/Dockerfile.node` | 节点容器镜像 |
| `manet-30ns3/node/node-entrypoint.py` | 节点容器入口 |

---

## 5. 验证清单

### 冒烟测试（Linux 宿主上执行）

```bash
cd manet-30ns3

# 1. 构建
docker compose --profile build build node-image-builder
docker compose build ns3-controller

# 2. 起服
docker compose up -d ns3-controller
curl -s localhost:8000/api/health  # → {"ok": true}

# 3. 启动 tactical 预设
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"tactical"}'

# 4. 验证网络接口
ip link | grep -E 'br-ns3|tap-|veth'  # 10 个 tap + 10 个 veth + br-ns3
docker ps | grep manet-node            # 10 个节点容器

# 5. 连通性测试
docker exec manet-node-0 ping -c 3 192.168.100.11
docker exec manet-node-0 iperf3 -c 192.168.100.14 -t 5

# 6. 动态控制测试
curl -X POST localhost:8000/api/env/position \
     -d '{"nodeId":0,"x":1000,"y":1000}'
curl -X POST localhost:8000/api/env/txpower \
     -d '{"nodeId":0,"dbm":10}'
curl -X POST localhost:8000/api/env/pathloss \
     -d '{"exponent":4.0}'
curl -X POST localhost:8000/api/env/frequency \
     -d '{"mhz":2400}'

# 7. 遥测验证
# 打开 http://localhost:8000/ → 动态控制 Tab 应能正常操作
# Topology Tab 应显示 10 个节点位置实时更新

# 8. 拆除
curl -X POST localhost:8000/api/sim/stop
ip link | grep -E 'br-ns3|tap-|veth' || echo "clean"
```

---

## 6. 已知限制与未来扩展

### 当前限制
1. **仅支持 Linux/x86_64**：macOS/Windows 无法运行（ns-3 + pyroute2 依赖）
2. **ns-3 非线程安全**：动态控制命令必须通过队列注入，延迟 < 1 s
3. **频率合法性**：590 MHz 不在 802.11a 频道表中，SpectrumWifiPhy 内部仍按 5 GHz 频道工作，真实物理由 Friis Frequency 决定
4. **Yans PHY 频率调整受限**：YansWifiPhy 频率从 channel 获取，运行时调整可能不生效

### 未来扩展
1. **多机部署**：VXLAN 扩展 `br-ns3` 到多台物理机
2. **OpenAPI 自动生成 TS 类型**：消除前后端类型手工同步
3. **功率遥测**：在遥测帧中增加 `txPower` 字段
4. **3D 位置支持**：当前 z 坐标恒为 0，可扩展三维移动模型
5. **衰落模型动态调整**：运行时启用/禁用 Nakagami 衰落
